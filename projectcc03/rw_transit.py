import heapq
import json
import math
import os
import ssl
import threading
import urllib.request

from rw_transit_data import RAIL_LINES, RAIL_TRANSFERS, ROAD_ROUTES

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _CTX = ssl.create_default_context()

WALK_M_PER_MIN = 80.0
WALK_DETOUR = 1.25
RAIL_DWELL_MIN = 0.6
RAIL_BOARD_WAIT = 3.0
RAIL_TRANSFER_WAIT = 3.0
MIN_TRANSIT_WALK_M = 700

_EARTH = 6371000.0


def hav_m(a, b):
    dlat = math.radians(b[0] - a[0])
    dlng = math.radians(b[1] - a[1])
    s = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0]))
         * math.cos(math.radians(b[0])) * math.sin(dlng / 2) ** 2)
    return 2 * _EARTH * math.asin(math.sqrt(s))


def walk_min(meters):
    return meters * WALK_DETOUR / WALK_M_PER_MIN


def _walk_m(meters):
    """Straight-line metres -> realistic street metres, rounded for display."""
    return int(round(meters * WALK_DETOUR / 10.0) * 10)


def _slug(text):
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")


def _fail(reason):
    return {"ok": False, "reason": reason}


def _dist_label(m):
    return "%d m" % m if m < 1000 else "%.1f km" % (m / 1000.0)


def _walk_step(meters, target, arriving=False):
    """One 'walk' instruction; says so plainly when no walking is needed."""
    if meters < 50:
        title = "Your destination is right at the stop" if arriving else \
            "You're already at %s" % target
        return {"kind": "walk", "color": "#94a3b8", "title": title,
                "detail": "No walking needed"}
    return {"kind": "walk", "color": "#94a3b8",
            "title": "Walk to %s" % target,
            "detail": "%s · about %d min" % (_dist_label(meters),
                                             max(1, round(meters / WALK_M_PER_MIN)))}


class RailNetwork:
    def __init__(self, lines=RAIL_LINES, transfers=RAIL_TRANSFERS):
        self.lines = {}
        self.stations = {}
        self.adj = {}
        self.interchanges = set()
        for ln in lines:
            sts = []
            for i, (name, lat, lng) in enumerate(ln["stations"]):
                s = {"id": "%s:%s" % (ln["id"], _slug(name)), "name": name,
                     "lat": lat, "lng": lng, "line": ln["id"], "idx": i}
                sts.append(s)
                self.stations[s["id"]] = s
                self.adj[s["id"]] = []
            line = dict(ln)
            line["stations"] = sts
            line["track"] = [(s["lat"], s["lng"]) for s in sts]
            self.lines[ln["id"]] = line
            for a, b in zip(sts, sts[1:]):
                km = hav_m((a["lat"], a["lng"]), (b["lat"], b["lng"])) / 1000.0
                mins = km / ln["speed_kph"] * 60.0 + RAIL_DWELL_MIN
                self._link(a["id"], b["id"], mins, {"type": "ride", "line": ln["id"]})
        for la, na, lb, nb, walk, note in transfers:
            a = "%s:%s" % (la, _slug(na))
            b = "%s:%s" % (lb, _slug(nb))
            meta = {"type": "transfer", "walk_min": walk, "note": note}
            self._link(a, b, walk + RAIL_TRANSFER_WAIT, meta)
            self.interchanges.update((a, b))

    def _link(self, a, b, mins, meta):
        self.adj[a].append((b, mins, meta))
        self.adj[b].append((a, mins, meta))

    def nearest(self, p, limit_m, k=4):
        ranked = sorted((hav_m(p, (s["lat"], s["lng"])), sid)
                        for sid, s in self.stations.items())
        return [(d, sid) for d, sid in ranked[:k] if d <= limit_m]

    def _dijkstra(self, sources):
        dist = dict(sources)
        prev = {sid: None for sid in sources}
        heap = [(c, sid) for sid, c in sources.items()]
        heapq.heapify(heap)
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, float("inf")):
                continue
            for v, w, meta in self.adj[u]:
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = (u, meta)
                    heapq.heappush(heap, (nd, v))
        return dist, prev

    def all_points(self):
        return [p for ln in self.lines.values() for p in ln["track"]]

    def _track_slice(self, line_id, i, j):
        tr = self.lines[line_id]["track"]
        return tr[i:j + 1] if i <= j else tr[j:i + 1][::-1]

    def plan(self, a, b, max_walk_m=2500):
        """a, b are (lat, lng). Returns a plan dict (see module docstring)."""
        if hav_m(a, b) < MIN_TRANSIT_WALK_M:
            return _fail("These two points are only %s apart - quicker to walk "
                         "than to take the train." % _dist_label(int(hav_m(a, b))))
        near_a = self.nearest(a, max_walk_m)
        near_b = self.nearest(b, max_walk_m)
        if not near_a:
            return _fail("No LRT/MRT station within %.1f km of your starting point. "
                         "Try a road-based mode." % (max_walk_m / 1000.0))
        if not near_b:
            return _fail("No LRT/MRT station within %.1f km of your destination. "
                         "Try a road-based mode." % (max_walk_m / 1000.0))

        sources = {sid: walk_min(d) + RAIL_BOARD_WAIT for d, sid in near_a}
        start_walk = {sid: d for d, sid in near_a}
        dist, prev = self._dijkstra(sources)

        best = None
        for d, sid in near_b:
            if sid not in dist:
                continue
            total = dist[sid] + walk_min(d)
            if best is None or total < best[0]:
                best = (total, sid, d)
        if best is None:
            return _fail("No train connection found between those stations.")
        total_min, end_sid, end_walk = best

        chain = []
        cur = end_sid
        while cur is not None:
            link = prev.get(cur)
            chain.append((cur, link[1] if link else None))
            cur = link[0] if link else None
        chain.reverse()
        board_sid = chain[0][0]
        if len(chain) == 1:
            return _fail("Your start and destination are both closest to %s station - "
                         "walk instead." % self.stations[board_sid]["name"])

        segments, transfers = [], []
        seg = [self.stations[chain[0][0]]]
        for sid, meta in chain[1:]:
            st = self.stations[sid]
            if meta["type"] == "ride":
                seg.append(st)
            else:
                segments.append(seg)
                transfers.append((seg[-1], st, meta))
                seg = [st]
        segments.append(seg)

        return self._assemble(a, b, segments, transfers,
                              start_walk[board_sid], end_walk, total_min)

    def line_station_names(self, line_id):
        """Station names of one line in running order - feeds the station pickers."""
        return [s["name"] for s in self.lines[line_id]["stations"]]

    def plan_line(self, line_id, board_name, alight_name):
        """Ride one line from a chosen boarding station to a chosen drop-off station.

        Only that line's own track and stations are used; nothing here touches
        OSRM or any road data. Returns the same plan shape as plan()."""
        line = self.lines.get(line_id)
        if line is None:
            return _fail("Unknown railway line.")
        names = [s["name"] for s in line["stations"]]
        if board_name not in names or alight_name not in names:
            return _fail("Pick a boarding station and a drop-off station on %s." % line["short"])
        i, j = names.index(board_name), names.index(alight_name)
        if i == j:
            return _fail("Boarding and drop-off are the same station. "
                         "Pick two different %s stations." % line["short"])
        sts = line["stations"]
        seg = sts[i:j + 1] if i < j else sts[j:i + 1][::-1]
        mins = RAIL_BOARD_WAIT
        for p, q in zip(seg, seg[1:]):
            km = hav_m((p["lat"], p["lng"]), (q["lat"], q["lng"])) / 1000.0
            mins += km / line["speed_kph"] * 60.0 + RAIL_DWELL_MIN
        a = (seg[0]["lat"], seg[0]["lng"])
        b = (seg[-1]["lat"], seg[-1]["lng"])
        plan = self._assemble(a, b, [seg], [], 0, 0, mins)
        plan["legs"] = [l for l in plan["legs"] if l["type"] != "walk"]
        plan["steps"] = [s for s in plan["steps"] if s["kind"] != "walk"]
        plan["points"] = list(plan["legs"][0]["coords"])
        plan["walk_m"] = 0
        plan["line_id"] = line_id
        return plan

    def _assemble(self, a, b, segments, transfers, start_walk_m, end_walk_m, total_min):
        legs, steps, points = [], [], [a]
        first, last = segments[0][0], segments[-1][-1]

        legs.append({"type": "walk", "coords": [a, (first["lat"], first["lng"])],
                     "m": _walk_m(start_walk_m), "to": first["name"] + " Station"})
        steps.append(_walk_step(_walk_m(start_walk_m), "%s Station" % first["name"]))
        fare = 0
        ride_km = 0.0
        for n, seg in enumerate(segments):
            line = self.lines[seg[0]["line"]]
            i, j = seg[0]["idx"], seg[-1]["idx"]
            coords = self._track_slice(line["id"], i, j)
            km = sum(hav_m(p, q) for p, q in zip(coords, coords[1:])) / 1000.0
            ride_km += km
            n_stops = len(seg) - 1
            toward = line["stations"][-1]["name"] if j > i else line["stations"][0]["name"]
            fare += min(line["fare"]["max"],
                        int(round(line["fare"]["base"] + line["fare"]["per_stop"] * n_stops)))
            legs.append({"type": "ride", "mode": "rail", "line": line["id"],
                         "name": line["short"], "color": line["color"], "toward": toward,
                         "board": seg[0], "alight": seg[-1], "stops": seg,
                         "coords": coords, "km": km})
            mid = [s["name"] for s in seg[1:-1]]
            via = ""
            if mid:
                via = " · via " + ", ".join(mid if len(mid) <= 4 else mid[:2] + ["…"] + mid[-1:])
            steps.append({"kind": "board", "color": line["color"],
                          "title": "Board %s at %s" % (line["short"], seg[0]["name"]),
                          "detail": "Toward %s · ride %d stop%s%s" % (
                              toward, n_stops, "" if n_stops == 1 else "s", via)})
            steps.append({"kind": "alight", "color": "#ef4444",
                          "title": "Get off at %s" % seg[-1]["name"],
                          "detail": "%s station" % line["short"]})
            points += coords
            if n < len(transfers):
                f, t, meta = transfers[n]
                nxt = self.lines[t["line"]]
                legs.append({"type": "transfer",
                             "coords": [(f["lat"], f["lng"]), (t["lat"], t["lng"])],
                             "at": f, "to": t, "note": meta["note"],
                             "mins": meta["walk_min"]})
                steps.append({"kind": "transfer", "color": "#f59e0b",
                              "title": "Transfer to %s" % nxt["short"],
                              "detail": "%s (~%d min walk)" % (meta["note"], meta["walk_min"])})

        legs.append({"type": "walk", "coords": [(last["lat"], last["lng"]), b],
                     "m": _walk_m(end_walk_m), "to": "your destination"})
        steps.append(_walk_step(_walk_m(end_walk_m), "your destination", True))
        points.append(b)
        walk_total = (_walk_m(start_walk_m) + _walk_m(end_walk_m)
                      + sum(int(t[2]["walk_min"] * WALK_M_PER_MIN) for t in transfers))
        return {"ok": True, "kind": "rail", "legs": legs, "steps": steps,
                "mins": total_min, "km": ride_km, "fare": fare, "walk_m": walk_total,
                "points": points, "transfers": len(transfers),
                "lines": [self.lines[s[0]["line"]]["short"] for s in segments]}


KIND_RULES = {
    "jeepney": {"max_walk_m": 1000, "wait_min": 4.0, "label": "jeepney"},
    "bus":     {"max_walk_m": 1500, "wait_min": 7.0, "label": "bus"},
}
STOP_DWELL_MIN = 0.35


class RoadRoutes:
    def __init__(self, routes=ROAD_ROUTES, cache_file=None):
        self.routes = {}
        for r in routes:
            r = dict(r)
            r["stops"] = [{"name": n, "lat": la, "lng": ln} for n, la, ln in r["stops"]]
            self.routes[r["id"]] = r
        self.cache_file = cache_file
        self.online = True
        self._built = {}
        self._lock = threading.Lock()
        self._disk = self._load_disk()

    def _load_disk(self):
        try:
            with open(self.cache_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, TypeError, ValueError):
            return {}

    def _save_disk(self):
        if not self.cache_file:
            return
        try:
            with open(self.cache_file, "w", encoding="utf-8") as fh:
                json.dump(self._disk, fh)
        except OSError:
            pass

    @staticmethod
    def _sig(route):
        return ";".join("%.5f,%.5f" % (s["lat"], s["lng"]) for s in route["stops"])

    def _snap(self, route, timeout=9):
        q = ";".join("%.5f,%.5f" % (s["lng"], s["lat"]) for s in route["stops"])
        url = ("https://router.project-osrm.org/route/v1/driving/" + q
               + "?overview=full&geometries=geojson&continue_straight=false")
        req = urllib.request.Request(url, headers={"User-Agent": "RoadWisePH/2.1"})
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [(p[1], p[0]) for p in data["routes"][0]["geometry"]["coordinates"]]

    def build(self, rid):
        """Road geometry for one route, snapped to real streets when online."""
        with self._lock:
            if rid in self._built:
                return self._built[rid]
        route = self.routes[rid]
        sig = self._sig(route)
        path, snapped = None, False
        cached = self._disk.get(rid)
        if cached and cached.get("sig") == sig:
            path, snapped = [tuple(p) for p in cached["path"]], True
        elif self.online:
            try:
                path, snapped = self._snap(route), True
                self._disk[rid] = {"sig": sig, "path": path}
                self._save_disk()
            except Exception:
                path = None
        if not path:
            path = [(s["lat"], s["lng"]) for s in route["stops"]]
        cum = [0.0]
        for i in range(1, len(path)):
            cum.append(cum[-1] + hav_m(path[i - 1], path[i]))
        idx = self._stop_indices(path, route["stops"])
        built = {"path": path, "cum": cum, "idx": idx, "snapped": snapped}
        with self._lock:
            self._built[rid] = built
        return built

    @staticmethod
    def _stop_indices(path, stops):
        """Place each stop on the path, never moving backwards along it."""
        out, start = [], 0
        for s in stops:
            kx = math.cos(math.radians(s["lat"]))
            best, bd = start, float("inf")
            for i in range(start, len(path)):
                d = (path[i][0] - s["lat"]) ** 2 + ((path[i][1] - s["lng"]) * kx) ** 2
                if d < bd:
                    bd, best = d, i
            out.append(best)
            start = best
        return out

    def of_kind(self, kind):
        return [r for r in self.routes.values() if r["kind"] == kind]

    def preview(self, kind):
        """Everything the map needs to show a mode's designated routes."""
        out = []
        for r in self.of_kind(kind):
            b = self.build(r["id"])
            out.append({"name": r["name"], "color": r["color"], "coords": b["path"],
                        "stops": r["stops"], "sample": r.get("sample", False)})
        return out

    def plan(self, kind, a, b, factor=1.0):
        rules = KIND_RULES[kind]
        label = rules["label"]
        routes = self.of_kind(kind)
        if not routes:
            return _fail("No %s routes are loaded yet." % label)
        if hav_m(a, b) < MIN_TRANSIT_WALK_M:
            return _fail("These two points are only %s apart - quicker to walk."
                         % _dist_label(int(hav_m(a, b))))

        options = []
        for r in routes:
            built = self.build(r["id"])
            stops = r["stops"]
            near_a = [(hav_m(a, (s["lat"], s["lng"])), i) for i, s in enumerate(stops)]
            near_b = [(hav_m(b, (s["lat"], s["lng"])), i) for i, s in enumerate(stops)]
            near_a = [x for x in near_a if x[0] <= rules["max_walk_m"]]
            near_b = [x for x in near_b if x[0] <= rules["max_walk_m"]]
            busway = r.get("busway", False)
            exp = 0.35 if busway else 1.0
            for da, i in near_a:
                for db, j in near_b:
                    if i == j:
                        continue
                    ride_m = abs(built["cum"][built["idx"][j]] - built["cum"][built["idx"][i]])
                    if ride_m < 400:
                        continue
                    ff = ride_m / 1000.0 / r["speed_kph"] * 60.0
                    ride_min = ff * (max(factor, 1.0) ** exp) + abs(j - i) * STOP_DWELL_MIN
                    total = walk_min(da) + walk_min(db) + rules["wait_min"] + ride_min
                    options.append((total, r, i, j, da, db, ride_m, ride_min))
        if not options:
            return _fail(self._no_route_reason(kind, a, b, rules))
        options.sort(key=lambda o: o[0])
        total, r, i, j, da, db, ride_m, ride_min = options[0]
        plan = self._assemble(kind, r, i, j, a, b, da, db, ride_m, ride_min, total)
        seen, alts = {r["id"]}, []
        for o in options[1:]:
            if o[1]["id"] not in seen:
                seen.add(o[1]["id"])
                alts.append({"name": o[1]["name"], "mins": o[0]})
        plan["alts"] = alts[:3]
        return plan

    def _no_route_reason(self, kind, a, b, rules):
        label = rules["label"]
        stops = [(s, r) for r in self.of_kind(kind) for s in r["stops"]]
        sa = min(stops, key=lambda x: hav_m(a, (x[0]["lat"], x[0]["lng"])))
        sb = min(stops, key=lambda x: hav_m(b, (x[0]["lat"], x[0]["lng"])))
        da = int(hav_m(a, (sa[0]["lat"], sa[0]["lng"])))
        db = int(hav_m(b, (sb[0]["lat"], sb[0]["lng"])))
        return ("No %s route in the route book serves both ends of this trip "
                "(max walk to a stop: %s).\nNearest stop to start: %s, %s away.\n"
                "Nearest stop to destination: %s, %s away.\n"
                "Add the route you need in rw_transit_data.py, or try another mode."
                % (label, _dist_label(rules["max_walk_m"]), sa[0]["name"], _dist_label(da),
                   sb[0]["name"], _dist_label(db)))

    def _assemble(self, kind, r, i, j, a, b, da, db, ride_m, ride_min, total):
        built = self.build(r["id"])
        stops = r["stops"]
        pi, pj = built["idx"][i], built["idx"][j]
        path = built["path"]
        coords = path[pi:pj + 1] if pi <= pj else path[pj:pi + 1][::-1]
        order = range(i, j + 1) if i <= j else range(i, j - 1, -1)
        run = [stops[k] for k in order]
        board, alight = run[0], run[-1]
        toward = stops[-1]["name"] if j > i else stops[0]["name"]
        icon = "🚍" if kind == "bus" else "🚌"
        ps = lambda s: (s["lat"], s["lng"])
        legs = [
            {"type": "walk", "coords": [a, ps(board)], "m": _walk_m(da),
             "to": board["name"] + " stop"},
            {"type": "ride", "mode": kind, "name": r["name"], "color": r["color"],
             "toward": toward, "board": board, "alight": alight, "stops": run,
             "coords": coords, "km": ride_m / 1000.0, "signboard": r["signboard"]},
            {"type": "walk", "coords": [ps(alight), b], "m": _walk_m(db),
             "to": "your destination"},
        ]
        n = len(run) - 1
        mid = [s["name"] for s in run[1:-1]]
        via = ""
        if mid:
            via = " · via " + ", ".join(mid if len(mid) <= 4 else mid[:2] + ["…"] + mid[-1:])
        sample = " (sample route)" if r.get("sample") else ""
        steps = [
            _walk_step(_walk_m(da), "%s stop" % board["name"]),
            {"kind": "board", "color": r["color"],
             "title": "Board the %s %s" % (KIND_RULES[kind]["label"], icon),
             "detail": "Signboard “%s” toward %s%s. Ride %d stop%s%s" % (
                 r["signboard"], toward, sample, n, "" if n == 1 else "s", via)},
            {"kind": "alight", "color": "#ef4444",
             "title": "Get off at %s" % alight["name"],
             "detail": "Tell the driver “para po” before the stop" if kind == "jeepney"
                       else "Press the bell one stop ahead"},
            _walk_step(_walk_m(db), "your destination", True),
        ]
        return {"ok": True, "kind": kind, "legs": legs, "steps": steps, "mins": total,
                "km": ride_m / 1000.0, "fare": None, "walk_m": _walk_m(da) + _walk_m(db),
                "points": [a] + coords + [b], "route": r["name"], "color": r["color"],
                "snapped": built["snapped"]}


RAIL = RailNetwork()
ROUTES = RoadRoutes(cache_file=os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "roadwise_routes_cache.json"))
