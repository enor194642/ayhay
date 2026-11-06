import io
import math
import os
import queue
import ssl
import threading
import urllib.request

from PIL import Image, ImageOps

TILE_PX = 256
MIN_ZOOM = 4
MAX_ZOOM = 19

_UA = "RoadWisePH/2.0 (desktop traffic map; student project)"
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/"

STYLES = {
    "streets": [(_ESRI + "World_Street_Map/MapServer/tile/{z}/{y}/{x}", "rgb")],
    "dark": [(_ESRI + "World_Street_Map/MapServer/tile/{z}/{y}/{x}", "dark")],
    "satellite": [
        (_ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", "rgb"),
        (_ESRI + "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}", "over"),
        (_ESRI + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", "over"),
    ],
}

ATTRIBUTION = {
    "streets": "Tiles © Esri — OpenStreetMap contributors",
    "dark": "Tiles © Esri — OpenStreetMap contributors",
    "satellite": "Imagery © Esri, Maxar, Earthstar Geographics",
}


def _to_dark(im):
    """Invert the paper-and-ink street tile into a slate dark theme: land goes
    deep, roads and labels stay the bright parts of the picture."""
    v = ImageOps.invert(im.convert("L"))
    v = v.point([int(255 * (i / 255.0) ** 0.80) for i in range(256)])
    chans = [v.point([int(i * k) for i in range(256)]) for k in (0.40, 0.52, 0.80)]
    return Image.merge("RGB", chans)


def lng_to_x(lng, zoom):
    return (lng + 180.0) / 360.0 * TILE_PX * (1 << zoom)


def lat_to_y(lat, zoom):
    lat = max(-85.05112878, min(85.05112878, lat))
    r = math.radians(lat)
    return (1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * TILE_PX * (1 << zoom)


def world_px(lat, lng, zoom):
    return lng_to_x(lng, zoom), lat_to_y(lat, zoom)


def x_to_lng(x, zoom):
    return x / (TILE_PX * (1 << zoom)) * 360.0 - 180.0


def y_to_lat(y, zoom):
    n = math.pi - 2.0 * math.pi * y / (TILE_PX * (1 << zoom))
    return math.degrees(math.atan(math.sinh(n)))


class Tiles:
    """Tile cache + background downloader.

    The worker threads only touch urllib and PIL; Tk images are built in the
    main thread by whoever polls ready(), because tkinter is not thread-safe.
    """

    def __init__(self, style="streets", cache_dir=None, workers=6, keep=900):
        self.style = style
        self.keep = keep
        self._lock = threading.Lock()
        self._imgs = {}
        self._failed = set()
        self._want = set()
        self._q = queue.Queue()
        self._ready = queue.Queue()
        self._stop = threading.Event()
        self.dir = cache_dir or os.path.join(
            os.environ.get("TEMP", os.path.expanduser("~")), "roadwise_tiles")
        self._threads = [threading.Thread(target=self._work, daemon=True)
                         for _ in range(workers)]
        for t in self._threads:
            t.start()

    def set_style(self, style):
        if style == self.style:
            return
        self.style = style
        with self._lock:
            self._imgs.clear()
            self._failed.clear()
            self._want.clear()

    def get(self, z, x, y):
        key = (z, x, y)
        with self._lock:
            im = self._imgs.get(key)
            if im is not None or key in self._failed:
                return im
            if key not in self._want:
                self._want.add(key)
                self._q.put(key)
        return None

    def poll(self):
        """Drain finished tiles; returns how many arrived."""
        n = 0
        while True:
            try:
                key = self._ready.get_nowait()
            except queue.Empty:
                break
            n += 1
            with self._lock:
                self._want.discard(key)
        return n

    def preload(self, keys):
        for k in keys:
            self.get(*k)

    def close(self):
        self._stop.set()

    def _path(self, z, x, y):
        d = os.path.join(self.dir, self.style)
        return os.path.join(d, "%d_%d_%d.png" % (z, x, y))

    def _work(self):
        while not self._stop.is_set():
            try:
                z, x, y = self._q.get(timeout=0.25)
            except queue.Empty:
                continue
            key = (z, x, y)
            with self._lock:
                if key in self._imgs:
                    continue
            path = self._path(z, x, y)
            im = None
            try:
                im = self._read_disk(path)
                if im is None:
                    im = self._build(z, x, y, path)
            except Exception:
                im = None
            with self._lock:
                if im is None:
                    self._failed.add(key)
                else:
                    self._imgs[key] = im
                    if len(self._imgs) > self.keep:
                        for old in list(self._imgs)[:len(self._imgs) - self.keep]:
                            if old != key:
                                self._imgs.pop(old, None)
            self._ready.put(key)

    def _read_disk(self, path):
        try:
            if os.path.getsize(path) > 0:
                return Image.open(path)
        except OSError:
            pass
        return None

    def _build(self, z, x, y, path):
        layers = STYLES[self.style]
        base = None
        for i, (tpl, kind) in enumerate(layers):
            url = tpl.format(z=z, x=x, y=y)
            raw = self._fetch(url)
            if raw is None:
                return None if i == 0 else base
            im = Image.open(io.BytesIO(raw))
            if kind == "over":
                ov = im.convert("RGBA")
                base = Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")
            else:
                base = im.convert("RGB")
        if base is None:
            return None
        if base.size != (TILE_PX, TILE_PX):
            base = base.resize((TILE_PX, TILE_PX), Image.BILINEAR)
        if STYLES[self.style][0][1] == "dark":
            base = _to_dark(base)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            base.save(path, "PNG", optimize=True)
        except OSError:
            pass
        return base

    def _fetch(self, url, timeout=8):
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            data = r.read()
        if len(data) < 64:
            return None
        try:
            Image.open(io.BytesIO(data)).load()
        except Exception:
            return None
        return data
