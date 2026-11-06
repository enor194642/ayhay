import math

from rw_transit_data import RAIL_LINES

CENTER_LAT, CENTER_LNG = 14.5955, 121.0500
TZ_UTC_OFFSET_HOURS = 8

PLACES = {
    "Marikina City Hall": {"lat": 14.6335, "lng": 121.0965},
    "Quezon City Hall":   {"lat": 14.6488, "lng": 121.0509},
    "Ortigas Center":     {"lat": 14.5852, "lng": 121.0569},
    "Pasig Mega Market":  {"lat": 14.5583, "lng": 121.0825},
    "Manila City Hall":   {"lat": 14.5896, "lng": 120.9817},
    "Makati CBD":         {"lat": 14.5547, "lng": 121.0244},
    "BGC Taguig":         {"lat": 14.5507, "lng": 121.0510},
    "Cubao Araneta Center": {"lat": 14.6205, "lng": 121.0535},
    "SM North EDSA":      {"lat": 14.6564, "lng": 121.0287},
    "Ninoy Aquino Airport": {"lat": 14.5086, "lng": 121.0194},
    "Manila Cathedral":   {"lat": 14.5912, "lng": 120.9814},
    "Ayala Center":       {"lat": 14.5545, "lng": 121.0235},
    "TriNoma":            {"lat": 14.6537, "lng": 121.0331},
    "Antipolo Cathedral": {"lat": 14.5872, "lng": 121.1758},
    "SM Masinag":         {"lat": 14.6258, "lng": 121.1715},
    "Quiapo Church":      {"lat": 14.5994, "lng": 120.9838},
    "Baclaran Church":    {"lat": 14.5330, "lng": 120.9985},
    "PITX":               {"lat": 14.5095, "lng": 120.9913},
    "My Current Location": {"lat": CENTER_LAT, "lng": CENTER_LNG, "is_current": True},
}

PROVIDERS = {
    "angkas": {"kind": "road", "label": "Angkas", "icon": "🏍️",
               "desc": "Safer and more affordable motorcycle transportation.",
               "url": "https://www.angkas.com", "base": 50, "per_km": 10.0, "free_km": 2.0},
    "moveit": {"kind": "road", "label": "Move It", "icon": "🏍️",
               "desc": "Fast motorcycle transportation.",
               "url": "https://www.moveit.com.ph/home", "base": 50, "per_km": 9.5, "free_km": 2.0},
    "joyride": {"kind": "road", "label": "JoyRide", "icon": "🛵",
                "desc": "Fast motorcycle transportation, but more expensive.",
                "url": "https://joyride.com.ph", "base": 60, "per_km": 12.0, "free_km": 2.0},
    "grab": {"kind": "road", "label": "Grab Car", "icon": "🚗",
             "desc": "Comfortable car transportation.",
             "url": "https://www.grab.com/sg/transport/", "base": 90, "per_km": 18.0, "free_km": 0.0},
    "jeepney": {"kind": "jeepney", "label": "Jeepney", "icon": "🚌", "url": "",
                "desc": "Public transportation with designated routes and stops.",
                "base": 13, "per_km": 1.8, "free_km": 4.0},
    "bus": {"kind": "bus", "label": "Bus", "icon": "🚍", "url": "",
            "desc": "Public transportation with designated routes and stops.",
            "base": 15, "per_km": 2.2, "free_km": 5.0},
    "lrt1": {"kind": "rail", "line": "lrt1", "label": "LRT-1", "icon": "🚇", "url": "",
             "desc": "Railway transportation with its own fixed route and stations.",
             "base": 16, "per_km": 0.8, "free_km": 0.0, "floor": 16, "cap": 35},
    "lrt2": {"kind": "rail", "line": "lrt2", "label": "LRT-2", "icon": "🚇", "url": "",
             "desc": "Railway transportation with its own fixed route and stations.",
             "base": 13, "per_km": 1.8, "free_km": 0.0, "floor": 13, "cap": 35},
    "mrt3": {"kind": "rail", "line": "mrt3", "label": "MRT-3", "icon": "🚇", "url": "",
             "desc": "Railway transportation with its own fixed route and stations.",
             "base": 13, "per_km": 1.25, "free_km": 0.0, "floor": 13, "cap": 28},
}

MODES = [PROVIDERS[k]["label"] for k in PROVIDERS]
MODE_BY_LABEL = {PROVIDERS[k]["label"]: k for k in PROVIDERS}

TRAFFIC_PRESETS = {
    "Auto – Live Traffic": None,
    "Clear / Smooth": 1.00,
    "Moderate": 1.35,
    "Heavy Gridlock": 2.10,
}

SEED_HAZARDS = [
    ("Heavy Jam near EDSA Ortigas", "Slow traffic southbound.", 14.5855, 121.0565),
    ("Construction on Marikina Bridge", "Outer lane blocked for repairs.", 14.6330, 121.0960),
]

TRAIN_LINES = [
    {"id": ln["id"], "name": ln["name"], "color": ln["color"],
     "stations": [{"name": n, "lat": la, "lng": lo} for n, la, lo in ln["stations"]]}
    for ln in RAIL_LINES
]

BAD_ROADS = [
    {"corridor": "edsa", "a": 0.58, "b": 0.62, "kind": "Pothole", "icon": "🕳"},
    {"corridor": "marcos", "a": 0.35, "b": 0.50, "kind": "Roadworks", "icon": "🚧"},
    {"corridor": "aurora", "a": 0.40, "b": 0.46, "kind": "Rough surface", "icon": "⚠"},
    {"corridor": "commonwealth", "a": 0.30, "b": 0.36, "kind": "Pothole", "icon": "🕳"},
    {"corridor": "taft", "a": 0.50, "b": 0.58, "kind": "Roadworks", "icon": "🚧"},
    {"corridor": "marikina-road", "a": 0.40, "b": 0.65, "kind": "Roadworks", "icon": "🚧"},
    {"corridor": "c5", "a": 0.50, "b": 0.58, "kind": "Flood-prone", "icon": "🌊",
     "rain_only": True},
    {"corridor": "ortigas-ave", "a": 0.45, "b": 0.55, "kind": "Flood-prone", "icon": "🌊",
     "rain_only": True},
    {"corridor": "roxas", "a": 0.40, "b": 0.55, "kind": "Flood-prone", "icon": "🌊",
     "rain_only": True},
]

CORRIDORS = [
    {"id": "edsa", "name": "EDSA", "waypoints": [
        (14.6450, 120.9882), (14.6478, 121.0120), (14.6462, 121.0360),
        (14.6228, 121.0429), (14.5995, 121.0466), (14.5850, 121.0570),
        (14.5712, 121.0375), (14.5626, 121.0184), (14.5547, 121.0244)]},
    {"id": "c5", "name": "C-5 South", "waypoints": [
        (14.6240, 121.0870), (14.5895, 121.0830), (14.5610, 121.0660),
        (14.5488, 121.0515), (14.5330, 121.0350)]},
    {"id": "commonwealth", "name": "Commonwealth Ave", "waypoints": [
        (14.6300, 121.0580), (14.6465, 121.0470), (14.6650, 121.0440), (14.7030, 121.0430)]},
    {"id": "katipunan", "name": "Katipunan Ave", "waypoints": [
        (14.6300, 121.0560), (14.6360, 121.0770), (14.6335, 121.1050), (14.6280, 121.1150)]},
    {"id": "marcos", "name": "Marcos Highway", "waypoints": [
        (14.6150, 121.1080), (14.6210, 121.0850), (14.6310, 121.0580)]},
    {"id": "ortigas-ave", "name": "Ortigas Ave", "waypoints": [
        (14.5885, 121.0940), (14.5860, 121.0750), (14.5850, 121.0620), (14.5845, 121.0575)]},
    {"id": "shaw", "name": "Shaw Blvd", "waypoints": [
        (14.5848, 121.0572), (14.5838, 121.0520), (14.5825, 121.0470)]},
    {"id": "aurora", "name": "Aurora Blvd", "waypoints": [
        (14.6245, 121.0680), (14.6215, 121.0490), (14.6195, 121.0430)]},
    {"id": "nsamoranto", "name": "N.S. Amoranto / Banawe", "waypoints": [
        (14.6340, 121.0420), (14.6255, 121.0385), (14.6200, 121.0400)]},
    {"id": "espana", "name": "Espana Ave", "waypoints": [
        (14.6060, 120.9930), (14.6205, 120.9905), (14.6300, 120.9890)]},
    {"id": "quezon-blvd", "name": "Quezon Blvd", "waypoints": [
        (14.5895, 120.9895), (14.6010, 120.9885), (14.6140, 120.9880)]},
    {"id": "taft", "name": "Taft Ave", "waypoints": [
        (14.5560, 120.9985), (14.5670, 120.9930), (14.5835, 120.9885)]},
    {"id": "roxas", "name": "Roxas Blvd", "waypoints": [
        (14.6010, 120.9830), (14.5880, 120.9800), (14.5720, 120.9770), (14.5560, 120.9820)]},
    {"id": "ayala", "name": "Ayala Ave, Makati", "waypoints": [
        (14.5550, 121.0180), (14.5605, 121.0175), (14.5660, 121.0165)]},
    {"id": "r6", "name": "R-6 / Bonifacio Drive", "waypoints": [
        (14.5965, 120.9765), (14.5835, 120.9775), (14.5700, 120.9820)]},
    {"id": "c6", "name": "Harbor Road / C-6", "waypoints": [
        (14.6050, 120.9785), (14.6260, 120.9820), (14.6430, 120.9860)]},
    {"id": "marikina-road", "name": "Marikina-Infanta Hwy", "waypoints": [
        (14.6335, 121.0965), (14.6200, 121.0990), (14.6060, 121.1030)]},
    {"id": "buendia", "name": "South Taft / Ayala connector", "waypoints": [
        (14.5547, 121.0244), (14.5540, 121.0120), (14.5535, 120.9985)]},
]

CORRIDOR_PROFILE = {
    "edsa":          {"base": 0.62, "peak": 1.00, "lanes": 3},
    "c5":            {"base": 0.55, "peak": 0.92, "lanes": 3},
    "commonwealth":  {"base": 0.58, "peak": 0.90, "lanes": 2},
    "katipunan":     {"base": 0.60, "peak": 0.95, "lanes": 2},
    "marcos":        {"base": 0.64, "peak": 1.00, "lanes": 2},
    "ortigas-ave":   {"base": 0.66, "peak": 0.98, "lanes": 2},
    "shaw":          {"base": 0.63, "peak": 0.94, "lanes": 2},
    "aurora":        {"base": 0.52, "peak": 0.85, "lanes": 2},
    "nsamoranto":    {"base": 0.50, "peak": 0.80, "lanes": 1},
    "espana":        {"base": 0.48, "peak": 0.78, "lanes": 1},
    "quezon-blvd":   {"base": 0.50, "peak": 0.80, "lanes": 1},
    "taft":          {"base": 0.56, "peak": 0.88, "lanes": 2},
    "roxas":         {"base": 0.54, "peak": 0.86, "lanes": 2},
    "ayala":         {"base": 0.68, "peak": 0.96, "lanes": 2},
    "r6":            {"base": 0.44, "peak": 0.72, "lanes": 1},
    "c6":            {"base": 0.42, "peak": 0.70, "lanes": 1},
    "marikina-road": {"base": 0.58, "peak": 0.90, "lanes": 2},
    "buendia":       {"base": 0.46, "peak": 0.75, "lanes": 1},
}

BLOCK_DENSITY = 1.9
DISTRICTS = [
    {"lat": 14.5547, "lng": 121.0244, "rx": 0.0075, "ry": 0.0085, "n": 18, "hmin": 70, "hmax": 250, "seed": 11},
    {"lat": 14.5507, "lng": 121.0510, "rx": 0.0080, "ry": 0.0075, "n": 18, "hmin": 90, "hmax": 320, "seed": 23},
    {"lat": 14.5852, "lng": 121.0569, "rx": 0.0070, "ry": 0.0070, "n": 15, "hmin": 70, "hmax": 290, "seed": 37},
    {"lat": 14.5896, "lng": 120.9817, "rx": 0.0090, "ry": 0.0090, "n": 13, "hmin": 40, "hmax": 160, "seed": 53},
    {"lat": 14.6488, "lng": 121.0509, "rx": 0.0080, "ry": 0.0080, "n": 12, "hmin": 40, "hmax": 150, "seed": 71},
    {"lat": 14.5760, "lng": 121.0360, "rx": 0.0065, "ry": 0.0065, "n": 11, "hmin": 45, "hmax": 175, "seed": 97},
    {"lat": 14.5740, "lng": 121.0840, "rx": 0.0070, "ry": 0.0060, "n": 10, "hmin": 35, "hmax": 140, "seed": 113},
    {"lat": 14.6335, "lng": 121.0965, "rx": 0.0065, "ry": 0.0060, "n": 9, "hmin": 30, "hmax": 120, "seed": 131},
    {"lat": 14.5420, "lng": 121.0140, "rx": 0.0070, "ry": 0.0060, "n": 9, "hmin": 30, "hmax": 120, "seed": 149},
    {"lat": 14.6120, "lng": 120.9990, "rx": 0.0075, "ry": 0.0065, "n": 10, "hmin": 30, "hmax": 130, "seed": 167},
    {"lat": 14.6010, "lng": 121.0400, "rx": 0.0055, "ry": 0.0050, "n": 8, "hmin": 35, "hmax": 130, "seed": 181},
    {"lat": 14.6400, "lng": 121.0350, "rx": 0.0070, "ry": 0.0060, "n": 9, "hmin": 30, "hmax": 125, "seed": 199},
    {"lat": 14.7000, "lng": 121.0600, "rx": 0.0060, "ry": 0.0050, "n": 10, "hmin": 25, "hmax": 100, "seed": 223},
    {"lat": 14.5980, "lng": 120.9710, "rx": 0.0040, "ry": 0.0035, "n": 12, "hmin": 40, "hmax": 180, "seed": 227},
    {"lat": 14.5720, "lng": 120.9990, "rx": 0.0060, "ry": 0.0050, "n": 12, "hmin": 35, "hmax": 160, "seed": 229},
    {"lat": 14.5640, "lng": 120.9870, "rx": 0.0050, "ry": 0.0045, "n": 8, "hmin": 30, "hmax": 140, "seed": 233},
    {"lat": 14.6400, "lng": 120.9600, "rx": 0.0050, "ry": 0.0045, "n": 8, "hmin": 25, "hmax": 110, "seed": 239},
]

BAY_POLYGON = [
    (120.8000, 14.7400), (120.9000, 14.7350), (120.9500, 14.6900),
    (120.9720, 14.6300), (120.9790, 14.5850), (120.9760, 14.5400),
    (120.9850, 14.5000), (120.9600, 14.4400), (120.8000, 14.4400),
]
RIVER = [
    (14.7000, 121.1150), (14.6600, 121.1050), (14.6300, 121.0970),
    (14.5950, 121.0860), (14.5600, 121.0740), (14.5300, 121.0620),
]
RIVER_TRIB = [
    (14.7100, 121.0600), (14.6800, 121.0450), (14.6500, 121.0400),
    (14.6200, 121.0500), (14.6000, 121.0700), (14.5850, 121.0850),
]

URBAN_AREAS = [
    ("Manila",        14.5900, 120.9820, 1.7, 1.3, 25, 0.30),
    ("Ermita",        14.5780, 120.9850, 1.0, 0.9, 20, 0.26),
    ("Santa Mesa",    14.6080, 121.0020, 1.0, 0.8, 32, 0.28),
    ("San Miguel",    14.6110, 121.0180, 1.0, 0.9, 30, 0.30),
    ("Sampaloc",      14.6120, 120.9990, 1.2, 1.0, 35, 0.26),
    ("Tondo",         14.6040, 120.9800, 1.1, 1.0, 28, 0.24),
    ("Caloocan",      14.6400, 121.0350, 1.4, 1.2, 45, 0.30),
    ("Quezon City",   14.6520, 121.0480, 1.5, 1.4, 45, 0.32),
    ("Project 7",     14.6320, 121.0600, 1.0, 0.9, 45, 0.28),
    ("Makati",        14.5560, 121.0220, 1.5, 1.5, 22, 0.26),
    ("Guadalupe",     14.5570, 121.0040, 0.9, 0.8, 25, 0.30),
    ("Mandaluyong",   14.5770, 121.0370, 1.2, 1.0, 30, 0.28),
    ("Ortigas",       14.5870, 121.0580, 1.0, 0.8, 30, 0.26),
    ("San Juan",      14.6010, 121.0410, 0.9, 0.8, 45, 0.30),
    ("BGC",           14.5510, 121.0500, 1.1, 0.9, 15, 0.22),
    ("Pateros",       14.5590, 121.0670, 0.8, 0.7, 20, 0.32),
    ("Pasig",         14.5750, 121.0800, 1.4, 1.0, 30, 0.28),
    ("Marikina",      14.6360, 121.0970, 1.3, 1.0, 62, 0.28),
    ("Paranaque",     14.5420, 121.0140, 1.2, 1.0, 45, 0.30),
    ("Valenzuela",    14.6750, 121.0000, 1.1, 0.9, 45, 0.32),
    ("Navotas",       14.6400, 120.9600, 0.9, 0.8, 40, 0.30),
    ("Meycauayan",    14.7100, 120.9850, 0.8, 0.7, 35, 0.32),
    ("Pasay",         14.5650, 120.9920, 1.0, 0.8, 25, 0.28),
    ("Montalban",     14.6670, 121.1300, 0.7, 0.6, 40, 0.34),
    ("Tondo North",   14.6180, 120.9740, 0.9, 0.7, 30, 0.26),
]

SPRAWL = 1.42

M_PER_DEG_LAT = 111320.0
DEG_LAT_PER_KM = 1000.0 / M_PER_DEG_LAT


def _deg_lng_per_km(lat):
    return 1000.0 / (M_PER_DEG_LAT * math.cos(math.radians(lat)))


def _lattice(area):
    """Two families of parallel streets clipped to an ellipse -> reads as a city grid.

    Returns [(n-s streets), (e-w streets)] where each family is a list of
    ((lat1, lng1), (lat2, lng2)) segments paired by row.
    """
    label, lat, lng, ax, ay, gdir, sp = area
    ax *= SPRAWL
    ay *= SPRAWL
    kx = _deg_lng_per_km(lat)
    ky = DEG_LAT_PER_KM
    fams = []
    for along, across, theta in ((ay, ax, gdir), (ax, ay, gdir + 90.0)):
        t = math.radians(theta)
        east, north = math.sin(t), math.cos(t)
        pe, pn = math.cos(t), -math.sin(t)
        fam = []
        n = max(3, int(2 * across / sp))
        for k in range(n):
            off = (k + 0.5) / n * 2 * across - across
            frac = 1.0 - (off / across) ** 2
            if frac <= 0.03:
                fam.append(None)
                continue
            half = along * math.sqrt(frac) * 0.95
            cx = lng + off * pe * kx
            cy = lat + off * pn * ky
            fam.append(((cy - half * north * ky, cx - half * east * kx),
                        (cy + half * north * ky, cx + half * east * kx)))
        fams.append(fam)
    return fams


STREETS = [_lattice(a) for a in URBAN_AREAS]

def _patch(area, scale=1.20, steps=16):
    label, lat, lng, ax, ay, gdir, sp = area
    scale *= SPRAWL
    th = math.radians(gdir)
    kx = _deg_lng_per_km(lat)
    pts = []
    for i in range(steps):
        a = math.tau * i / steps
        ex = math.cos(a) * ax * scale * math.cos(th) - math.sin(a) * ay * scale * math.sin(th)
        ny = math.cos(a) * ax * scale * math.sin(th) + math.sin(a) * ay * scale * math.cos(th)
        pts.append((lng + ex * kx, lat + ny * DEG_LAT_PER_KM))
    return pts


URBAN_PATCHES = [_patch(a) for a in URBAN_AREAS]

CITY_LABELS = [
    ("MANILA BAY", 14.5600, 120.9050, 13),
    ("QUEZON CITY", 14.6520, 121.0480, 11),
    ("CALOOCAN", 14.6400, 121.0320, 9),
    ("MARIKINA", 14.6400, 121.1000, 10),
    ("SAN JUAN", 14.6050, 121.0430, 9),
    ("Mandaluyong", 14.5700, 121.0380, 9),
    ("ORTIGAS", 14.5860, 121.0600, 10),
    ("PASIG", 14.5760, 121.0820, 10),
    ("MAKATI", 14.5560, 121.0190, 11),
    ("BGC", 14.5490, 121.0530, 10),
    ("PARANAQUE", 14.5380, 121.0130, 9),
    ("MANILA", 14.5930, 120.9840, 11),
    ("Marikina River", 14.6480, 121.1010, 8),
    ("BULACAN", 14.7300, 121.0300, 9),
    ("PAMPANGA", 14.7600, 120.9000, 9),
    ("CAVITE", 14.4000, 120.9000, 9),
    ("LAGUNA DE BAY", 14.3800, 121.1500, 9),
    ("RIZAL", 14.6600, 121.1700, 9),
]
