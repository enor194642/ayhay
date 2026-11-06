import json
import math
import random
import ssl
import urllib.request
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor

from rw_data import CORRIDORS, CORRIDOR_PROFILE, BAD_ROADS

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()

EARTH_R = 6371000.0
M_PER_DEG_LAT = 111320.0

def clamp(v, a, b):
    return max(a, min(b, v))

def lerp(a, b, t):
    return a + (b - a) * t

def haversine_m(a, b):
    dlat = math.radians(b[0] - a[0])
    dlng = math.radians(b[1] - a[1])
    s = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0]))
         * math.sin(dlng / 2) ** 2)
    return 2 * EARTH_R * math.asin(math.sqrt(s))

def bearing_deg(a, b):
    y = math.sin(math.radians(b[1] - a[1])) * math.cos(math.radians(b[0]))
    x = (math.cos(math.radians(a[0])) * math.sin(math.radians(b[0]))
         - math.sin(math.radians(a[0])) * math.cos(math.radians(b[0]))
         * math.cos(math.radians(b[1] - a[1])))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

def destination_point(p, brg, dist_m):
    d = dist_m / EARTH_R
    t = math.radians(brg)
    lat1, lng1 = math.radians(p[0]), math.radians(p[1])
    lat2 = math.asin(math.sin(lat1) * math.cos(d)
                     + math.cos(lat1) * math.sin(d) * math.cos(t))
    lng2 = lng1 + math.atan2(math.sin(t) * math.sin(d) * math.cos(lat1),
                              math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return (math.degrees(lat2), math.degrees(lng2))

def _hash_seed(text):
    h = 2166136261
    for ch in text:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return (h % 1000) / 1000.0

HOUR = [0.10, 0.06, 0.05, 0.04, 0.08, 0.20, 0.44, 0.80, 0.95, 0.80, 0.60, 0.58,
        0.62, 0.60, 0.60, 0.66, 0.78, 0.92, 0.98, 0.82, 0.60, 0.42, 0.28, 0.16]

def demand_at(minutes_of_day):
    h = (minutes_of_day % 1440.0) / 60.0
    i0 = int(h) % 24
    i1 = (i0 + 1) % 24
    return lerp(HOUR[i0], HOUR[i1], h - int(h))

COLOR_STOPS = [
    (0.00, (34, 197, 94)),
    (0.40, (234, 179, 8)),
    (0.70, (249, 115, 22)),
    (1.00, (239, 68, 68)),
]

def jam_rgb(jam):
    jam = clamp(jam, 0.0, 1.0)
    for i in range(1, len(COLOR_STOPS)):
        if jam <= COLOR_STOPS[i][0]:
            (a, ca), (b, cb) = COLOR_STOPS[i - 1], COLOR_STOPS[i]
            t = (jam - a) / (b - a)
            return tuple(int(round(lerp(ca[k], cb[k], t))) for k in range(3))
    return (239, 68, 68)

def hexc(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)

def mix_rgb(c1, c2, t):
    return tuple(lerp(c1[k], c2[k], t) for k in range(3))

def freeflow_kph(lanes):
    return 50 if lanes >= 3 else (40 if lanes == 2 else 32)

def _seg_sq_m(p, a, b):
    """Squared distance (m) from p to segment a-b in a local equirectangular frame."""
    kx = M_PER_DEG_LAT * math.cos(math.radians(p[0]))
    ax = (a[1] - p[1]) * kx; ay = (a[0] - p[0]) * M_PER_DEG_LAT
    bx = (b[1] - p[1]) * kx; by = (b[0] - p[0]) * M_PER_DEG_LAT
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = clamp((-ax * dx - ay * dy) / L2, 0.0, 1.0) if L2 else 0.0
    px, py = ax + t * dx, ay + t * dy
    return px * px + py * py

def simplify(coords, tol_m=26.0):
    """Douglas-Peucker (iterative) so far-off road shapes cost less to draw."""
    n = len(coords)
    if n < 3:
        return list(coords)
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    tol2 = tol_m * tol_m
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 - i0 < 2:
            continue
        a, b = coords[i0], coords[i1]
        best, bi = -1.0, -1
        for k in range(i0 + 1, i1):
            d = _seg_sq_m(coords[k], a, b)
            if d > best:
                best, bi = d, k
        if bi >= 0 and best > tol2:
            keep[bi] = True
            stack.append((i0, bi)); stack.append((bi, i1))
    return [c for c, k in zip(coords, keep) if k]

def corridor_jam(coro, minutes, demand, nearby_hazards):
    seed = coro["seed"]
    wobble = (0.10 * math.sin(minutes / 19.0 + seed * 6.28)
              + 0.06 * math.sin(minutes / 61.0 + seed * 11.0))
    boost = 0.0
    for dist in nearby_hazards:
        if dist < 900.0:
            boost += (1.0 - dist / 900.0) * 0.22
    soak = 1.25 - 0.25 * coro["lanes"]
    j = (coro["base"] * demand * 0.80
         + coro["peak"] * max(0.0, demand - 0.55) * 0.85 * soak
         + 0.05 + wobble + boost)
    return clamp(j, 0.06, 1.0)

LEVELS = [
    {"label": "Clear", "color": "#22c55e", "max": 0.25},
    {"label": "Light traffic", "color": "#a3e635", "max": 0.45},
    {"label": "Moderate", "color": "#f59e0b", "max": 0.65},
    {"label": "Heavy", "color": "#ef4444", "max": 0.82},
    {"label": "Standstill", "color": "#991b1b", "max": 1.01},
]

def level_for(jam):
    for lv in LEVELS:
        if jam < lv["max"]:
            return lv
    return LEVELS[-1]

def speed_for(jam):
    return 6.0 + 52.0 * (1.0 - clamp(jam, 0.0, 1.0))

def hazard_near(coro, hazards):
    return [h["near"][coro["id"]] for h in hazards
            if h.get("near") and coro["id"] in h["near"]]

def bad_road_at(coro_id, frac, rain=False):
    """+0.25 when this point on the corridor sits inside a known rough stretch."""
    for spot in BAD_ROADS:
        if spot["corridor"] != coro_id:
            continue
        if spot.get("rain_only") and not rain:
            continue
        if spot["a"] <= frac <= spot["b"]:
            return True
    return False

def chunk_jam(coro, base_jam, frac, minutes, rain=False):
    seed = coro.get("seed", 0.0)
    ripple = (0.07 * math.sin(frac * 18.0 + seed * 6.28)
              + 0.05 * math.sin(frac * 47.0 - minutes / 37.0 + seed * 3.1))
    j = base_jam + ripple
    j += 0.28 if bad_road_at(coro["id"], frac, rain) else 0.0
    return clamp(j, 0.04, 1.0)

def point_at_fraction(c, frac):
    coords, cum = c["coords"], c["cum"]
    target = clamp(frac, 0.0, 1.0) * cum[-1]
    i = bisect_left(cum, target)
    if i < 1:
        i = 1
    elif i > len(cum) - 1:
        i = len(cum) - 1
    seg = cum[i] - cum[i - 1] or 1.0
    t = (target - cum[i - 1]) / seg
    a, b = coords[i - 1], coords[i]
    return (lerp(a[0], b[0], t), lerp(a[1], b[1], t))

def derive_bad_spots(network):
    """Pin each rough stretch at the middle of its span so it lands on the road."""
    by_id = {c["id"]: c for c in network}
    out = []
    for spot in BAD_ROADS:
        c = by_id.get(spot["corridor"])
        if c is None:
            continue
        lat, lng = point_at_fraction(c, (spot["a"] + spot["b"]) / 2.0)
        out.append({"lat": lat, "lng": lng, "icon": spot["icon"],
                    "kind": spot["kind"], "corridor": c["name"],
                    "rain_only": bool(spot.get("rain_only")),
                    "label": "%s — %s" % (c["name"], spot["kind"])})
    return out

def densify(waypoints, steps=14):
    out = []
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        for s in range(steps):
            t = s / steps
            out.append((lerp(a[0], b[0], t), lerp(a[1], b[1], t)))
    out.append(waypoints[-1])
    return out

def snap_via_osrm(coords, timeout=6):
    q = ";".join("%.5f,%.5f" % (c[1], c[0]) for c in coords)
    url = ("https://router.project-osrm.org/route/v1/driving/"
           + q + "?overview=full&geometries=geojson")
    req = urllib.request.Request(url, headers={"User-Agent": "RoadWisePH/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    routes = data.get("routes") or []
    if not routes:
        raise RuntimeError("no route")
    return [(p[1], p[0]) for p in routes[0]["geometry"]["coordinates"]]

def build_network(max_workers=6):
    """Snap every corridor onto real roads; fall back to smooth curves offline."""
    def job(c):
        try:
            coords = snap_via_osrm(c["waypoints"])
        except Exception:
            coords = densify(c["waypoints"])
        if len(coords) < 2:
            coords = densify(c["waypoints"])
        cum, total = [0.0], 0.0
        for i in range(1, len(coords)):
            total += haversine_m(coords[i - 1], coords[i])
            cum.append(total)
        prof = CORRIDOR_PROFILE.get(c["id"], {"base": 0.5, "peak": 0.8, "lanes": 2})
        lats = [p[0] for p in coords]
        lngs = [p[1] for p in coords]
        return {
            "id": c["id"], "name": c["name"], "coords": coords, "cum": cum,
            "draw": simplify(coords, 26.0),
            "segb": [bearing_deg(coords[i], coords[i + 1]) for i in range(len(coords) - 1)],
            "bbox": (min(lats), max(lats), min(lngs), max(lngs)),
            "lengthKm": total / 1000.0,
            "lanes": prof["lanes"], "base": prof["base"], "peak": prof["peak"],
            "seed": _hash_seed(c["id"]), "freeflow": freeflow_kph(prof["lanes"]),
            "jam": 0.3,
        }

    corridors = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for coro in pool.map(job, CORRIDORS):
            corridors.append(coro)
    return corridors

def bind_hazards(hazards, network):
    """Attach each hazard to its nearby corridors with point-to-segment distance."""
    def seg_m(p, a, b):
        ax = (a[1] - p[1]) * M_PER_DEG_LAT * math.cos(math.radians(p[0]))
        ay = (a[0] - p[0]) * M_PER_DEG_LAT
        bx = (b[1] - p[1]) * M_PER_DEG_LAT * math.cos(math.radians(p[0]))
        by = (b[0] - p[0]) * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = clamp((-ax * dx - ay * dy) / L2, 0.0, 1.0) if L2 else 0.0
        px, py = ax + t * dx, ay + t * dy
        return math.hypot(px, py)

    for h in hazards:
        h["near"] = {}
        for c in network:
            pts = c["coords"]
            best = float("inf")
            for i in range(1, len(pts)):
                best = min(best, seg_m((h["lat"], h["lng"]), pts[i - 1], pts[i]))
            if best < 1200.0:
                h["near"][c["id"]] = best
    return hazards

class Engine:
    def __init__(self, network):
        self.network = network
        self.vehicles = []
        self._uid = 0
        self._by_id = {c["id"]: c for c in network}

    def _point_at(self, c, s):
        cum, coords = c["cum"], c["coords"]
        total = cum[-1]
        s = clamp(s, 0.0, total)
        i = bisect_left(cum, s)
        if i < 1:
            i = 1
        elif i > len(cum) - 1:
            i = len(cum) - 1
        seg = cum[i] - cum[i - 1] or 1.0
        t = (s - cum[i - 1]) / seg
        a, b = coords[i - 1], coords[i]
        brg = c["segb"][i - 1] if c.get("segb") else bearing_deg(a, b)
        return (lerp(a[0], b[0], t), lerp(a[1], b[1], t)), brg

    def _targets_for(self, c, demand):
        per_km = c["lanes"] * (0.3 + 1.35 * demand)
        return clamp(int(round(c["lengthKm"] * per_km)), 2, c["lanes"] * 16)

    def _spawn(self, c, jam, s=None):
        self._uid += 1
        direction = 1 if random.random() < 0.5 else -1
        lane = random.randrange(c["lanes"])
        offset = (lane - (c["lanes"] - 1) / 2.0) * 6.0 * direction
        self.vehicles.append({
            "id": self._uid, "cid": c["id"], "dir": direction, "lane": lane,
            "s": random.random() * c["cum"][-1] if s is None else s,
            "offset": offset, "jam": jam,
            "clat": math.cos(math.radians(c["coords"][0][0])),
        })

    def step(self, minutes, dt, hazards, demand):
        for c in self.network:
            near = [h["near"][c["id"]] for h in hazards
                    if h.get("near") and c["id"] in h["near"]]
            c["jam"] = corridor_jam(c, minutes, demand, near)

        counts = {}
        for v in self.vehicles:
            counts[v["cid"]] = counts.get(v["cid"], 0) + 1
        targets = {c["id"]: self._targets_for(c, demand) for c in self.network}
        for c in self.network:
            have = counts.get(c["id"], 0)
            target = targets[c["id"]]
            while have < target:
                self._spawn(c, c["jam"])
                have += 1
        if any(counts.get(c["id"], 0) > targets[c["id"]] for c in self.network):
            keep, seen = [], {}
            for v in self.vehicles:
                n = seen.get(v["cid"], 0)
                if n < targets[v["cid"]]:
                    keep.append(v)
                    seen[v["cid"]] = n + 1
            self.vehicles = keep

        out = []
        append = out.append
        for v in self.vehicles:
            c = self._by_id[v["cid"]]
            v["jam"] = c["jam"]
            eff = (c["freeflow"] * (1.0 - 0.78 * c["jam"]) + 6.0) / 3.6
            v["s"] += eff * dt * 60.0 * v["dir"]
            total = c["cum"][-1]
            if v["s"] > total:
                v["s"] = 0.0
            elif v["s"] < 0:
                v["s"] = total
            p, brg = self._point_at(c, v["s"])
            hdg = (brg if v["dir"] > 0 else brg + 180.0) * 0.017453292519943295
            off = v["offset"]
            append((p[0] - off * math.sin(hdg) / M_PER_DEG_LAT,
                    p[1] + off * math.cos(hdg) / (M_PER_DEG_LAT * v["clat"]),
                    v["jam"], int(round(eff * 3.6))))
        return out

def auto_factor(network, minutes, hazards, rain=False):
    demand = demand_at(minutes)
    if not network:
        return 1.3
    total = 0.0
    for c in network:
        total += corridor_jam(c, minutes, demand, hazard_near(c, hazards))
    avg = total / len(network)
    delay = 1.0 + avg * 1.3
    if rain:
        delay += 0.18 * (0.4 + avg)
    return round(delay, 2)

def route_between(a, b, timeout=7):
    """OSRM path between two points; straight-line fallback when offline."""
    try:
        return snap_via_osrm([(a["lat"], a["lng"]), (b["lat"], b["lng"])], timeout)
    except Exception:
        coords, steps = [], 24
        for i in range(steps + 1):
            t = i / steps
            coords.append((lerp(a["lat"], b["lat"], t), lerp(a["lng"], b["lng"], t)))
        return coords

def route_info(a, b, timeout=7):
    """(coords, km, free-flow minutes) for a car trip; straight line when offline."""
    pa, pb = (a["lat"], a["lng"]), (b["lat"], b["lng"])
    try:
        q = "%.5f,%.5f;%.5f,%.5f" % (pa[1], pa[0], pb[1], pb[0])
        url = ("https://router.project-osrm.org/route/v1/driving/"
               + q + "?overview=full&geometries=geojson")
        req = urllib.request.Request(url, headers={"User-Agent": "RoadWisePH/2.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        r = (data.get("routes") or [])[0]
        coords = [(p[1], p[0]) for p in r["geometry"]["coordinates"]]
        return coords, r["distance"] / 1000.0, r["duration"] / 60.0
    except Exception:
        km = haversine_m(pa, pb) / 1000.0
        return densify([pa, pb], 24), km, km / 26.0 * 60.0

def sun_state(dt_local, lat=14.6):
    """Solar altitude drives the day/night look. Returns (alt_deg, night, warm)."""
    doy = dt_local.timetuple().tm_yday
    hour = dt_local.hour + dt_local.minute / 60.0 + dt_local.second / 3600.0
    decl = -23.44 * math.cos(math.radians(360.0 / 365.25 * (doy + 10)))
    ha = (hour - 12.0) * 15.0
    cos_alt = (math.sin(math.radians(lat)) * math.sin(math.radians(decl))
               + math.cos(math.radians(lat)) * math.cos(math.radians(decl))
               * math.cos(math.radians(ha)))
    alt = math.degrees(math.asin(clamp(cos_alt, -1.0, 1.0)))
    night = clamp((7.0 - alt) / 13.0, 0.0, 1.0)
    warm = clamp(1.0 - abs(alt - 6.0) / 12.0, 0.0, 1.0)
    return alt, night, warm
