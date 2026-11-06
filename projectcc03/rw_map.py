import math
import tkinter as tk
import tkinter.font as tkfont

from PIL import ImageTk

import rw_data as RWD
import rw_traffic as RT
import rw_tiles as T
import rw_transit as TR

BG = "#0b0d19"
CARD = "#0f172a"
BORDER = "#2b3a5e"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
INDIGO = "#6366f1"
WHITE = "#ffffff"
ROUTE_CASING = "#0f172a"
BAD_PURPLE = "#9333ea"
HAZARD_RED = "#dc2626"
USER_BLUE = "#3b82f6"

MIN_ZOOM, MAX_ZOOM = 9, 17
BOARD_GREEN = "#16a34a"
ALIGHT_RED = "#dc2626"
TRANSFER_AMBER = "#f59e0b"
WALK_WHITE = "#f8fafc"


def _font(size, weight="normal"):
    key = ("Segoe UI", size, weight)
    f = _FONTS.get(key)
    if f is None:
        f = _FONTS[key] = tkfont.Font(family="Segoe UI", size=size, weight=weight)
    return f


_FONTS = {}


class TrafficPanel(tk.Frame):
    """The floating card from the web build: clock, city line, time slider,
    presets, rain switch, legend and basemap styles."""

    PRESETS = (("Live", None), ("AM Rush", 480), ("Midday", 750),
               ("PM Rush", 1080), ("Night", 1410))

    def __init__(self, parent, on_time=None, on_rain=None, on_style=None, on_collapse=None):
        super().__init__(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        self.on_time = on_time
        self.on_rain = on_rain
        self.on_style = on_style
        self._buttons = {}
        self._styles = {}
        self._open = True
        self._lock = False

        self.head = tk.Label(self, text="🚦 Live Traffic    ▾", bg=CARD, fg=TEXT,
                             font=_font(11, "bold"), anchor="w", cursor="hand2")
        self.head.pack(fill="x", padx=10, pady=(8, 2))
        self.head.bind("<Button-1>", self._toggle)

        self.body = tk.Frame(self, bg=CARD)
        self.body.pack(fill="x", padx=10, pady=(0, 10))

        row = tk.Frame(self.body, bg=CARD)
        row.pack(fill="x")
        self.dot = tk.Canvas(row, width=10, height=10, bg=CARD, highlightthickness=0)
        self.dot.pack(side="left", pady=4)
        self.city = tk.Label(row, text="Metro Manila: —", bg=CARD, fg=TEXT,
                             font=_font(9, "bold"))
        self.city.pack(side="left", padx=6)

        clock = tk.Frame(self.body, bg=CARD)
        clock.pack(fill="x", pady=(6, 0))
        self.time_lbl = tk.Label(clock, text="--:--", bg=CARD, fg=TEXT,
                                 font=_font(17, "bold"))
        self.time_lbl.pack(side="left")
        self.period_lbl = tk.Label(clock, text="", bg=CARD, fg=MUTED, font=_font(8),
                                   justify="right")
        self.period_lbl.pack(side="right")

        self.slider = tk.Scale(self.body, from_=0, to=1425, resolution=15, orient="horizontal",
                               bg=CARD, fg="#6366f1", troughcolor="#334155",
                               highlightthickness=0, activebackground=WHITE,
                               bd=0, showvalue=0, sliderrelief="flat", length=210,
                               command=self._slide)
        self.slider.pack(fill="x", pady=(4, 6))

        btns = tk.Frame(self.body, bg=CARD)
        btns.pack(fill="x")
        for label, minutes in self.PRESETS:
            b = self._chip(btns, label, lambda m=minutes: self._preset(m))
            self._buttons[label] = b

        self.rain = tk.BooleanVar(value=False)
        tk.Checkbutton(self.body, text="☔ Heavy rain & floods", variable=self.rain,
                       bg=CARD, fg=TEXT, selectcolor=CARD, activebackground=CARD,
                       activeforeground=TEXT, font=_font(9, "bold"), highlightthickness=0,
                       bd=0, anchor="w", command=self._rain).pack(fill="x", pady=(4, 2))

        leg = tk.Frame(self.body, bg=CARD)
        leg.pack(fill="x", pady=(2, 4))
        rows = [(lv["label"], lv["color"], False) for lv in RT.LEVELS]
        rows.append(("Bad road", BAD_PURPLE, True))
        for text, color, dashed in rows:
            cell = tk.Frame(leg, bg=CARD)
            cell.pack(fill="x", pady=0)
            sw = tk.Canvas(cell, width=16, height=6, bg=CARD, highlightthickness=0)
            sw.pack(side="left")
            if dashed:
                for x in range(0, 16, 5):
                    sw.create_rectangle(x, 1, min(x + 3, 16), 5, fill=color, outline="")
            else:
                sw.create_rectangle(0, 1, 16, 5, fill=color, outline="")
            tk.Label(cell, text=text, bg=CARD, fg="#cbd5e1",
                     font=_font(8)).pack(side="left", padx=5)

        styles = tk.Frame(self.body, bg=CARD)
        styles.pack(fill="x", pady=(2, 0))
        for key, label in (("streets", "Streets"), ("dark", "Dark"), ("satellite", "Satellite")):
            b = self._chip(styles, label, lambda k=key: self._style(k))
            self._styles[key] = b

    def _chip(self, parent, text, cmd):
        b = tk.Label(parent, text=text, bg="#1e293b", fg="#e2e8f0", font=_font(8, "bold"),
                     padx=7, pady=3, cursor="hand2")
        b.pack(side="left", expand=True, fill="x", padx=1)
        b.bind("<Button-1>", lambda e: cmd())
        return b

    @staticmethod
    def _active(b, on):
        b.configure(bg=INDIGO if on else "#1e293b", fg=WHITE if on else "#e2e8f0")

    def _toggle(self, _e=None):
        self._open = not self._open
        if self._open:
            self.body.pack(fill="x", padx=10, pady=(0, 10))
            self.head.configure(text="🚦 Live Traffic    ▾")
        else:
            self.body.forget()
            self.head.configure(text="🚦 Live Traffic    ▸")

    def _slide(self, value):
        if self._lock:
            return
        if self.on_time:
            self.on_time(int(float(value)), "manual")

    def set_minutes(self, minutes):
        """Follow the live clock without triggering the manual-scrub callback."""
        self._lock = True
        self.slider.set(int(minutes))
        self._lock = False

    def _preset(self, minutes):
        if minutes is None:
            if self.on_time:
                self.on_time(None, "live")
        else:
            self.set_minutes(minutes)
            if self.on_time:
                self.on_time(minutes, "manual")

    def _rain(self):
        if self.on_rain:
            self.on_rain(bool(self.rain.get()))

    def _style(self, key):
        if self.on_style:
            self.on_style(key)

    def update_state(self, minutes, live, rain, level, speed, style):
        self.time_lbl.configure(text=fmt_clock(minutes))
        tag = "Live · " if live else ""
        self.period_lbl.configure(text=tag + period_label(minutes) + (" · Rain" if rain else ""))
        self.city.configure(text="Metro Manila: %s (~%d km/h)" % (level["label"], round(speed)))
        self.dot.delete("all")
        self.dot.create_oval(0, 0, 10, 10, fill=level["color"], outline="")
        for label, minutes_p in self.PRESETS:
            on = (live and minutes_p is None) or (not live and minutes_p == int(minutes))
            self._active(self._buttons[label], on)
        for key, b in self._styles.items():
            self._active(b, key == style)


def fmt_clock(minutes):
    h = int(minutes) // 60 % 24
    m = int(minutes) % 60
    return "%d:%02d %s" % (((h + 11) % 12) + 1, m, "AM" if h < 12 else "PM")


def period_label(minutes):
    h = (minutes or 0) / 60.0 % 24
    if 6 <= h < 10:
        return "Morning rush hour"
    if 10 <= h < 16:
        return "Daytime"
    if 16 <= h < 20.5:
        return "Evening rush hour"
    if 20.5 <= h < 24:
        return "Night"
    return "Late night"


class LiveMap(tk.Frame):
    def __init__(self, parent, on_place=None, on_hazard=None, on_pick=None,
                 on_bad=None, on_train=None):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg="#090a0f", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.on_place = on_place
        self.on_hazard = on_hazard
        self.on_bad = on_bad
        self.on_train = on_train
        self.on_pick = on_pick

        self.lat0, self.lng0 = RWD.CENTER_LAT, RWD.CENTER_LNG
        self.zoom = 12
        self.style = "streets"
        self.tiles = T.Tiles(style=self.style)

        self.network = []
        self.hazards = []
        self.bad_spots = []
        self.train_lines = RWD.TRAIN_LINES
        self.route = None
        self.display = "traffic"
        self.transit = None
        self.preview = None
        self.rail_filter = None
        self.route_labels = None
        self.user_pos = None
        self.minutes = 480.0
        self.live = True
        self.rain = False
        self.pick_mode = False

        self._photos = {}
        self._pin_map = {}
        self._cam_sig = None
        self._traffic_sig = None
        self._pins_sig = None
        self._drag = None
        self._pending = 0

        c = self.canvas
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._drag_move)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<MouseWheel>", self._wheel)
        c.bind("<ButtonPress-3>", self._right_press)
        c.bind("<Configure>", lambda e: self._redraw_all())

        self._build_buttons()

    def _size(self):
        return max(self.canvas.winfo_width(), 40), max(self.canvas.winfo_height(), 40)

    def _origin(self, w, h):
        return (T.lng_to_x(self.lng0, self.zoom) - w / 2.0,
                T.lat_to_y(self.lat0, self.zoom) - h / 2.0)

    def _px(self, lat, lng, ox, oy):
        return T.lng_to_x(lng, self.zoom) - ox, T.lat_to_y(lat, self.zoom) - oy

    def center_on(self, lat, lng, zoom=None):
        self.lat0, self.lng0 = lat, lng
        if zoom is not None:
            self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, int(round(zoom))))
        self._redraw_all()

    def zoom_by(self, step):
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom + int(step)))
        self._redraw_all()

    def fit(self, points, pad=70):
        if not points:
            return
        ref = MAX_ZOOM
        xs = [T.lng_to_x(p[1], ref) for p in points]
        ys = [T.lat_to_y(p[0], ref) for p in points]
        w, h = self._size()
        sx = max(max(xs) - min(xs), 1.0)
        sy = max(max(ys) - min(ys), 1.0)
        span_zoom = ref + min(math.log2(max(w - 2 * pad, 1.0) / sx),
                              math.log2(max(h - 2 * pad, 1.0) / sy))
        self.zoom = int(max(MIN_ZOOM, min(MAX_ZOOM, span_zoom)))
        self.lng0 = T.x_to_lng((min(xs) + max(xs)) / 2.0, ref)
        self.lat0 = T.y_to_lat((min(ys) + max(ys)) / 2.0, ref)
        self._redraw_all()

    def set_style(self, style):
        if style == self.style:
            return
        self.style = style
        self.tiles.set_style(style)
        self._photos.clear()
        self._redraw_all()

    def _press(self, e):
        self._drag = (e.x, e.y, self.lng0, self.lat0, e.num)

    def _drag_move(self, e):
        if not self._drag:
            return
        x0, y0, lng0, lat0, _ = self._drag
        w, h = self._size()
        ox = T.lng_to_x(lng0, self.zoom) - w / 2.0 - (e.x - x0)
        oy = T.lat_to_y(lat0, self.zoom) - h / 2.0 - (e.y - y0)
        self.lng0 = T.x_to_lng(ox + w / 2.0, self.zoom)
        self.lat0 = T.y_to_lat(oy + h / 2.0, self.zoom)
        self._redraw_all()

    def _release(self, e):
        moved = self._drag and (abs(e.x - self._drag[0]) > 3 or abs(e.y - self._drag[1]) > 3)
        self._drag = None
        if moved:
            return
        item = self.canvas.find_withtag("current")
        if item:
            hit = self._pin_map.get(item[0])
            if hit:
                kind, payload = hit
                cb = {"place": self.on_place, "hazard": self.on_hazard,
                      "bad": self.on_bad, "train": self.on_train}.get(kind)
                if cb:
                    cb(payload)
                return
        if self.pick_mode and self.on_pick:
            w, h = self._size()
            ox, oy = self._origin(w, h)
            self.on_pick(T.y_to_lat(oy + e.y, self.zoom), T.x_to_lng(ox + e.x, self.zoom))

    def _wheel(self, e):
        w, h = self._size()
        ox, oy = self._origin(w, h)
        anchor = (T.x_to_lng(ox + e.x, self.zoom), T.y_to_lat(oy + e.y, self.zoom))
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom + (1 if e.delta > 0 else -1)))
        w, h = self._size()
        self.lng0 = T.x_to_lng(T.lng_to_x(anchor[0], self.zoom) - e.x + w / 2.0, self.zoom)
        self.lat0 = T.y_to_lat(T.lat_to_y(anchor[1], self.zoom) - e.y + h / 2.0, self.zoom)
        self._redraw_all()
        self._redraw_all()

    def _right_press(self, e):
        if self.on_pick:
            w, h = self._size()
            ox, oy = self._origin(w, h)
            self.on_pick(T.y_to_lat(oy + e.y, self.zoom), T.x_to_lng(ox + e.x, self.zoom))

    def render(self, now_ms=None):
        self._pending += self.tiles.poll()
        w, h = self._size()
        ox, oy = self._origin(w, h)
        cam = (self.zoom, int(ox), int(oy), self.style)
        if cam != self._cam_sig or self._pending:
            self._cam_sig = cam
            self._pending = 0
            self._draw_tiles(w, h, ox, oy)
        demand = RT.demand_at(self.minutes)
        traffic_sig = (self.display, int(self.minutes // 5), self.rain,
                       tuple(int(RT.corridor_jam(c, self.minutes, demand,
                                                 RT.hazard_near(c, self.hazards)
                                                 if self.hazards else []) * 100)
                             for c in self.network))
        if traffic_sig != self._traffic_sig:
            self._traffic_sig = traffic_sig
            self._draw_traffic(w, h, ox, oy)
        pins_sig = (self.display, self.rail_filter, id(self.transit), id(self.preview),
                    len(self.hazards), len(self.bad_spots), id(self.route),
                    self.user_pos is not None, tuple(h["id"] for h in self.hazards))
        if pins_sig != self._pins_sig:
            self._pins_sig = pins_sig
            self._draw_pins(w, h, ox, oy)

    def _redraw_all(self):
        self._cam_sig = None
        self._traffic_sig = None
        self._pins_sig = None
        self.render()

    def _draw_tiles(self, w, h, ox, oy):
        c = self.canvas
        c.delete("tile")
        z = self.zoom
        x0 = int(math.floor(ox / T.TILE_PX))
        x1 = int(math.floor((ox + w) / T.TILE_PX))
        y0 = int(math.floor(oy / T.TILE_PX))
        y1 = int(math.floor((oy + h) / T.TILE_PX))
        max_xy = (1 << z) - 1
        seen = set()
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                if not (0 <= tx <= max_xy and 0 <= ty <= max_xy):
                    continue
                key = (z, tx % (max_xy + 1), ty)
                seen.add(key)
                sx = tx * T.TILE_PX - ox
                sy = ty * T.TILE_PX - oy
                im = self.tiles.get(*key)
                if im is None:
                    c.create_rectangle(sx, sy, sx + T.TILE_PX, sy + T.TILE_PX,
                                       fill="#111827", outline="", tags=("tile",))
                    continue
                photo = self._photos.get(key)
                if photo is None or photo.width() != im.size[0]:
                    photo = ImageTk.PhotoImage(im)
                    self._photos[key] = photo
                c.create_image(sx, sy, image=photo, anchor="nw", tags=("tile",))
        if len(self._photos) > 96:
            self._photos = {k: v for k, v in self._photos.items() if k in seen}
        c.create_text(w - 6, h - 6, text=T.ATTRIBUTION[self.style], anchor="se",
                      fill="#dbe3f0", font=_font(7), tags=("tile",))
        c.tag_raise("traffic")
        c.tag_raise("route")
        c.tag_raise("pin")

    def _draw_traffic(self, w, h, ox, oy):
        c = self.canvas
        c.delete("rail")
        c.delete("traffic")
        if self.display == "rail":
            return
        width = {9: 1.6, 10: 2.0, 11: 2.6, 12: 3.2, 13: 4.2, 14: 5.4}.get(
            self.zoom, 7.0 if self.zoom >= 15 else 3.2)
        for line in self.train_lines:
            flat = []
            for st in line["stations"]:
                x, y = self._px(st["lat"], st["lng"], ox, oy)
                flat += [x, y]
            if len(flat) >= 4:
                c.create_line(flat, fill=line["color"], width=max(1.5, width * 0.55),
                              dash=(4, 3), capstyle="round", tags=("rail",))
        demand = RT.demand_at(self.minutes)
        chunk_m = 900.0 / (2 ** (self.zoom - 12))
        for coro in self.network:
            pts = coro.get("draw") or coro["coords"]
            if len(pts) < 2:
                continue
            near = RT.hazard_near(coro, self.hazards) if self.hazards else []
            base_jam = RT.corridor_jam(coro, self.minutes, demand, near)
            cum = [0.0]
            for i in range(1, len(pts)):
                cum.append(cum[-1] + RT.haversine_m(pts[i - 1], pts[i]))
            total = max(cum[-1], 1.0)
            screen = [self._px(p[0], p[1], ox, oy) for p in pts]
            seg, step, visible = [], 0.0, False
            for i in range(1, len(pts)):
                x, y = screen[i]
                on = -80.0 < x < w + 80.0 and -80.0 < y < h + 80.0
                if not seg:
                    seg = [x, y]
                    step = cum[i - 1] / total
                    visible = on
                else:
                    seg += [x, y]
                    visible = visible or on
                last = i == len(pts) - 1
                if visible and (cum[i] - step * total >= chunk_m or last):
                    if len(seg) >= 4:
                        jam = RT.chunk_jam(coro, base_jam, step, self.minutes, self.rain)
                        lv = RT.level_for(jam)
                        c.create_line(seg, fill=ROUTE_CASING, width=width + 2.4,
                                      capstyle="round", joinstyle="round", tags=("traffic",))
                        c.create_line(seg, fill=lv["color"], width=width,
                                      capstyle="round", joinstyle="round", tags=("traffic",))
                    seg, visible = [], False
        c.tag_raise("traffic")

    def _draw_pins(self, w, h, ox, oy):
        c = self.canvas
        c.delete("pin")
        c.delete("route")
        self._pin_map = {}
        rail = self.display == "rail"
        planned = self.transit is not None
        if planned:
            self._draw_plan(w, h, ox, oy)
        elif rail:
            self._draw_rail_network(w, h, ox, oy)
        elif self.preview:
            self._draw_preview(w, h, ox, oy)
        if self.route:
            flat = []
            for p in self.route:
                x, y = self._px(p[0], p[1], ox, oy)
                flat += [x, y]
            if len(flat) >= 4:
                c.create_line(flat, fill=ROUTE_CASING, width=11, capstyle="round",
                              joinstyle="round", tags=("route",))
                c.create_line(flat, fill=INDIGO, width=6.5, capstyle="round",
                              joinstyle="round", tags=("route",))
        if rail:
            self._draw_user_and_ab(w, h, ox, oy)
            c.tag_raise("pin")
            return
        for line in ([] if planned else self.train_lines):
            for st in line["stations"]:
                x, y = self._px(st["lat"], st["lng"], ox, oy)
                if not (-20 < x < w + 20 and -20 < y < h + 20):
                    continue
                cid = c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=line["color"],
                                    outline=WHITE, width=2, tags=("pin",))
                self._pin_map[cid] = ("train", {"line": line, "station": st})
        for spot in self.bad_spots:
            x, y = self._px(spot["lat"], spot["lng"], ox, oy)
            if not (-20 < x < w + 20 and -20 < y < h + 20):
                continue
            if spot.get("rain_only") and not self.rain:
                continue
            cid = c.create_oval(x - 11, y - 11, x + 11, y + 11, fill=BAD_PURPLE,
                                outline=WHITE, width=2, tags=("pin",))
            c.create_text(x, y, text=spot["icon"], font=_font(9), tags=("pin",))
            self._pin_map[cid] = ("bad", spot)
        for hz in self.hazards:
            x, y = self._px(hz["lat"], hz["lng"], ox, oy)
            if not (-20 < x < w + 20 and -20 < y < h + 20):
                continue
            cid = c.create_oval(x - 10, y - 10, x + 10, y + 10, fill=HAZARD_RED,
                                outline=WHITE, width=2, tags=("pin",))
            c.create_text(x, y, text="⚠", fill=WHITE, font=_font(9, "bold"), tags=("pin",))
            self._pin_map[cid] = ("hazard", hz)
        for name, place in ([] if planned else RWD.PLACES.items()):
            if place.get("is_current") or "lat" not in place:
                continue
            x, y = self._px(place["lat"], place["lng"], ox, oy)
            if not (-20 < x < w + 20 and -20 < y < h + 20):
                continue
            cid = c.create_oval(x - 5, y - 5, x + 5, y + 5, fill=INDIGO, outline=WHITE,
                                width=2, tags=("pin",))
            c.create_text(x + 9, y, text=name, anchor="w", fill="#e6ebf5",
                          font=_font(8, "bold"), tags=("pin",))
            self._pin_map[cid] = ("place", name)
        self._draw_user_and_ab(w, h, ox, oy)
        c.tag_raise("pin")

    def _draw_user_and_ab(self, w, h, ox, oy):
        c = self.canvas
        if self.user_pos and not self.transit:
            x, y = self._px(self.user_pos[0], self.user_pos[1], ox, oy)
            c.create_oval(x - 9, y - 9, x + 9, y + 9, fill=USER_BLUE, outline=WHITE,
                          width=3, tags=("pin",))
        ends = None
        if self.transit and self.transit.get("kind") == "rail":
            return
        if self.transit:
            pts = self.transit["points"]
            ends = (pts[0], pts[-1])
        elif self.route:
            ends = (self.route[0], self.route[-1])
        if ends:
            for p, mark in ((ends[0], "A"), (ends[1], "B")):
                x, y = self._px(p[0], p[1], ox, oy)
                c.create_oval(x - 8, y - 8, x + 8, y + 8, fill=CARD, outline=WHITE,
                              width=2, tags=("pin",))
                c.create_text(x, y, text=mark, fill=WHITE, font=_font(8, "bold"),
                              tags=("pin",))
        if self.route and not self.transit and self.route_labels:
            for p, word, color, name in (
                    (ends[0], "PICKUP", BOARD_GREEN, self.route_labels[0]),
                    (ends[1], "DROP-OFF", ALIGHT_RED, self.route_labels[1])):
                x, y = self._px(p[0], p[1], ox, oy)
                self._label(x, y, "%s · %s" % (word, name), color, dy=-12)

    def _label(self, x, y, text, bg, fg=WHITE, dy=-16):
        """A small pill label whose bottom edge sits `dy` pixels above (x, y)."""
        c = self.canvas
        f = _font(8, "bold")
        tw = f.measure(text) + 14
        y1 = y + dy
        y0 = y1 - 18
        c.create_rectangle(x - tw / 2, y0, x + tw / 2, y1, fill=bg, outline=WHITE,
                           width=1, tags=("pin",))
        c.create_text(x, (y0 + y1) / 2, text=text, fill=fg, font=f, tags=("pin",))

    def _station_dot(self, st, line_name, color, ox, oy, w, h, r=4.5, name=True,
                     ring=WHITE):
        c = self.canvas
        x, y = self._px(st["lat"], st["lng"], ox, oy)
        if not (-30 < x < w + 30 and -30 < y < h + 30):
            return None
        cid = c.create_oval(x - r, y - r, x + r, y + r, fill=WHITE, outline=color,
                            width=2.2, tags=("pin",))
        self._pin_map[cid] = ("train", {"line": {"name": line_name}, "station": st})
        if name:
            ink = "#0f172a" if self.style == "streets" else "#f8fafc"
            c.create_text(x + r + 4, y, text=st["name"], anchor="w", fill=ink,
                          font=_font(8, "bold"), tags=("pin",))
        return x, y

    def _line_width(self):
        return {9: 2.5, 10: 3.0, 11: 3.5, 12: 4.5, 13: 5.5, 14: 6.5}.get(
            self.zoom, 8.0 if self.zoom >= 15 else 3.0)

    def _flat(self, pts, ox, oy):
        flat = []
        for p in pts:
            x, y = self._px(p[0], p[1], ox, oy)
            flat += [x, y]
        return flat

    def _draw_rail_network(self, w, h, ox, oy):
        """Whole LRT/MRT network: fixed tracks and every station."""
        c = self.canvas
        lw = self._line_width()
        lines = self._rail_lines()
        for ln in lines:
            flat = self._flat(ln["track"], ox, oy)
            c.create_line(flat, fill=ROUTE_CASING, width=lw + 3, capstyle="round",
                          joinstyle="round", tags=("route",))
            c.create_line(flat, fill=ln["color"], width=lw, capstyle="round",
                          joinstyle="round", tags=("route",))
        for ln in lines:
            last = len(ln["stations"]) - 1
            for st in ln["stations"]:
                key = st["id"]
                special = st["idx"] in (0, last) or key in TR.RAIL.interchanges
                if self.rail_filter:
                    show_name = self.zoom >= 12
                else:
                    show_name = self.zoom >= 13 or (special and self.zoom >= 11)
                r = 6.0 if key in TR.RAIL.interchanges else 4.5
                self._station_dot(st, ln["name"], ln["color"], ox, oy, w, h, r=r,
                                  name=show_name)
        self._rail_legend()

    def _rail_lines(self):
        if self.rail_filter and self.rail_filter in TR.RAIL.lines:
            return [TR.RAIL.lines[self.rail_filter]]
        return list(TR.RAIL.lines.values())

    def _rail_legend(self):
        c = self.canvas
        y = 12
        for ln in self._rail_lines():
            a, b = ln["stations"][0]["name"], ln["stations"][-1]["name"]
            text = "%s   %s ⇄ %s" % (ln["short"], a, b)
            f = _font(8, "bold")
            tw = f.measure(text) + 30
            c.create_rectangle(12, y, 12 + tw, y + 22, fill=CARD, outline=BORDER,
                               tags=("pin",))
            c.create_rectangle(16, y + 6, 24, y + 16, fill=ln["color"], outline="",
                               tags=("pin",))
            c.create_text(32, y + 11, text=text, anchor="w", fill=TEXT, font=f,
                          tags=("pin",))
            y += 26

    def _draw_preview(self, w, h, ox, oy):
        """All designated routes of the selected road-transit mode, with stops."""
        c = self.canvas
        lw = self._line_width() * 0.85
        for r in self.preview:
            flat = self._flat(r["coords"], ox, oy)
            if len(flat) < 4:
                continue
            c.create_line(flat, fill=ROUTE_CASING, width=lw + 3, capstyle="round",
                          joinstyle="round", tags=("route",))
            c.create_line(flat, fill=r["color"], width=lw, capstyle="round",
                          joinstyle="round", tags=("route",))
        for r in self.preview:
            for k, st in enumerate(r["stops"]):
                end = k in (0, len(r["stops"]) - 1)
                self._station_dot(st, r["name"], r["color"], ox, oy, w, h, r=4.5,
                                  name=self.zoom >= 14 or (end and self.zoom >= 12))

    def _draw_plan(self, w, h, ox, oy):
        """A planned trip: walk legs dashed, ride legs in the route's colour,
        every stop on the ride, plus clear BOARD / GET OFF / TRANSFER markers."""
        c = self.canvas
        plan = self.transit
        lw = self._line_width() + 2
        for leg in plan["legs"]:
            flat = self._flat(leg["coords"], ox, oy)
            if len(flat) < 4:
                continue
            if leg["type"] == "ride":
                c.create_line(flat, fill=ROUTE_CASING, width=lw + 4, capstyle="round",
                              joinstyle="round", tags=("route",))
                c.create_line(flat, fill=leg["color"], width=lw, capstyle="round",
                              joinstyle="round", tags=("route",))
            else:
                c.create_line(flat, fill=ROUTE_CASING, width=6, capstyle="round",
                              tags=("route",))
                c.create_line(flat, fill=WALK_WHITE, width=3, dash=(6, 4),
                              capstyle="round", tags=("route",))
        for leg in plan["legs"]:
            if leg["type"] == "ride":
                for st in leg["stops"][1:-1]:
                    self._station_dot(st, leg["name"], leg["color"], ox, oy, w, h,
                                      r=4.5, name=self.zoom >= (12 if plan["kind"] == "rail"
                                                                else 14))
        for leg in plan["legs"]:
            if leg["type"] == "ride":
                self._marker(leg["board"], leg["name"], leg["color"], "BOARD",
                             BOARD_GREEN, ox, oy, w, h)
                self._marker(leg["alight"], leg["name"], leg["color"], "GET OFF",
                             ALIGHT_RED, ox, oy, w, h)
            elif leg["type"] == "transfer":
                x, y = self._px(leg["at"]["lat"], leg["at"]["lng"], ox, oy)
                if -30 < x < w + 30 and -30 < y < h + 30:
                    c.create_oval(x - 11, y - 11, x + 11, y + 11, fill=TRANSFER_AMBER,
                                  outline=WHITE, width=3, tags=("pin",))
                    c.create_text(x, y, text="⇄", fill=WHITE, font=_font(9, "bold"),
                                  tags=("pin",))

    def _marker(self, st, line_name, line_color, word, color, ox, oy, w, h):
        c = self.canvas
        x, y = self._px(st["lat"], st["lng"], ox, oy)
        if not (-60 < x < w + 60 and -40 < y < h + 40):
            return
        cid = c.create_oval(x - 9, y - 9, x + 9, y + 9, fill=color, outline=WHITE,
                            width=3, tags=("pin",))
        self._pin_map[cid] = ("train", {"line": {"name": line_name}, "station": st})
        self._label(x, y, "%s · %s" % (word, st["name"]), color, dy=-14)

    def set_display(self, display):
        if display != self.display:
            self.display = display
            self._redraw_all()

    def show_rail_network(self, line_id=None):
        """Rail view. With a line id, only that line's track and stations."""
        self.route = None
        self.transit = None
        self.preview = None
        self.rail_filter = line_id
        self.display = "rail"
        self.fit([p for ln in self._rail_lines() for p in ln["track"]], pad=50)

    def show_preview(self, routes):
        self.route = None
        self.transit = None
        self.display = "traffic"
        self.preview = routes
        pts = [p for r in routes for p in r["coords"]]
        if pts:
            self.fit(pts, pad=50)
        else:
            self._redraw_all()

    def clear_transit(self):
        self.transit = None
        self.preview = None
        self.route = None
        self.rail_filter = None
        self.route_labels = None
        self.display = "traffic"
        self._redraw_all()

    def _build_buttons(self):
        stack = tk.Frame(self, bg=BG)
        stack.place(relx=0.985, rely=0.03, anchor="ne")
        self._btn(stack, "◎", lambda: self.center_on(RWD.CENTER_LAT, RWD.CENTER_LNG, 12), 46)
        self._btn(stack, "📌", self.arm_pick, 46)

        zooms = tk.Frame(self, bg=BG)
        zooms.place(relx=0.985, rely=0.80, anchor="ne")
        self._btn(zooms, "+", lambda: self.zoom_by(1), 38)
        self._btn(zooms, "−", lambda: self.zoom_by(-1), 38)

        self._view_lbl = tk.Label(self, text="", bg=CARD, fg=MUTED, font=_font(8),
                                  padx=8, pady=3)
        self._view_lbl.place(relx=0.985, rely=0.94, anchor="ne")

    @staticmethod
    def _btn(parent, text, cmd, size):
        b = tk.Label(parent, text=text, bg=CARD, fg=TEXT, font=_font(11, "bold"),
                     width=0, height=0, cursor="hand2",
                     highlightbackground=BORDER, highlightthickness=1)
        b.pack(pady=3, ipadx=10, ipady=8)
        b.bind("<Button-1>", lambda e: cmd())
        return b

    def arm_pick(self):
        self.pick_mode = not self.pick_mode
        self.canvas.configure(cursor="crosshair" if self.pick_mode else "")
        if not self.pick_mode:
            self.set_status("")

    def set_status(self, text):
        self._view_lbl.configure(text=text)
