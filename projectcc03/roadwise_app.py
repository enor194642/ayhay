import datetime
import email.utils
import hashlib
import os
import queue
import sqlite3
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import font as tkfont

import rw_data as RWD
import rw_traffic as RT
import rw_map as M
import rw_transit as TR
from rw_map import LiveMap, TrafficPanel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "roadwise.db")

BG = "#0b0d19"
CARD = "#0f172a"
INPUT = "#1e293b"
BORDER = "#243044"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
SOFT = "#cbd5e1"
PRIMARY = "#6366f1"
HOVER = "#4f46e5"
GREEN = "#34d399"
RED = "#ef4444"

_FONTS = {}


def F(size, weight="normal", family="Segoe UI"):
    if weight == "italic":
        family, weight = "Segoe UI Italic", "normal"
    key = (family, size, weight)
    f = _FONTS.get(key)
    if f is None:
        f = _FONTS[key] = tkfont.Font(family=family, size=size, weight=weight)
    return f


def _pw(p):
    return hashlib.sha256((p or "").encode()).hexdigest()


def _ensure_columns(conn, table, cols):
    existing = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
    for name, decl in cols.items():
        if name not in existing:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, decl))


def _hazard_coords(title):
    t = (title or "").lower()
    if "ortigas" in t:
        return 14.5855, 121.0565
    if "marikina" in t:
        return 14.6330, 121.0960
    if "monumento" in t:
        return 14.6450, 120.9882
    if "edsa" in t:
        return 14.6000, 121.0460
    return 14.5950, 121.0480


def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL, role TEXT DEFAULT 'user', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS hazards (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, desc TEXT NOT NULL,
        lat REAL, lng REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trips (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, start TEXT NOT NULL, end TEXT NOT NULL,
        mode TEXT NOT NULL, traffic TEXT NOT NULL, fare REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    _ensure_columns(conn, "hazards", {"lat": "REAL", "lng": "REAL", "type": "TEXT"})
    _ensure_columns(conn, "trips", {"traffic": "TEXT"})
    for hid, title in c.execute("SELECT id,title FROM hazards WHERE lat IS NULL").fetchall():
        lat, lng = _hazard_coords(title)
        c.execute("UPDATE hazards SET lat=?, lng=? WHERE id=?", (lat, lng, hid))
    c.execute("SELECT * FROM users WHERE role = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (name,email,password,role) VALUES (?,?,?,?)",
                  ("Admin User", "admin@roadwise.ph", _pw("admin123"), "admin"))
    c.execute("SELECT COUNT(*) FROM hazards")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT INTO hazards (title,desc,lat,lng) VALUES (?,?,?,?)", RWD.SEED_HAZARDS)
    conn.commit()
    conn.close()


def fare_for(mode, km):
    pid = RWD.MODE_BY_LABEL.get(mode, mode)
    p = RWD.PROVIDERS[pid]
    v = p["base"] + max(0.0, km - p["free_km"]) * p["per_km"]
    if "cap" in p:
        v = min(p["cap"], max(p["floor"], v))
    return round(v)


CLOCK_OFFSET = datetime.timedelta(0)


def manila_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + \
        CLOCK_OFFSET + datetime.timedelta(hours=RWD.TZ_UTC_OFFSET_HOURS)


def sync_clock():
    global CLOCK_OFFSET
    for url in ("https://www.google.com", "https://www.microsoft.com",
                "https://www.cloudflare.com"):
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "RoadWisePH/2.2"})
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=6) as resp:
                stamp = resp.headers["Date"]
            t1 = time.time()
            server = email.utils.parsedate_to_datetime(stamp).astimezone(
                datetime.timezone.utc) + datetime.timedelta(seconds=0.5)
            local = datetime.datetime.fromtimestamp((t0 + t1) / 2.0, datetime.timezone.utc)
            CLOCK_OFFSET = server - local
            return True
        except Exception:
            continue
    return False


class RoadWiseApp:
    def __init__(self, root):
        self.root = root
        root.title("RoadWise PH — Metro Manila Live Traffic")
        root.geometry("1320x860")
        root.minsize(1080, 720)
        root.configure(bg=BG)

        self.user = None
        self.sim = manila_now()
        self.mult = 1.0
        self.live = True
        self.scrub_minutes = float(self.sim.hour * 60 + self.sim.minute)
        self.rain = False
        self.network = []
        self.hazards = []
        self.picked = None
        self.pick_mode = False
        self.trip = None
        self._preview_token = 0
        self.current_view = "planner"
        self._last = time.monotonic() * 1000.0
        self._prev_tick = 0.0
        self._last_minute = -1
        self._q = queue.Queue()

        self._style_widgets()
        init_db()
        self._build_ui()
        threading.Thread(target=self._load_network, daemon=True).start()
        threading.Thread(target=self._sync_time, daemon=True).start()
        self.root.after(32, self._loop)

    def _style_widgets(self):
        st = ttk.Style()
        st.theme_use("clam")
        st.configure("Rw.TCombobox", fieldbackground=INPUT, background=INPUT, foreground=TEXT,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, arrowsize=13,
                     padding=6, font=F(10, "bold"))
        st.map("Rw.TCombobox", fieldbackground=[("readonly", INPUT)],
               foreground=[("readonly", TEXT)], bordercolor=[("focus", PRIMARY)])
        st.configure("Treeview", background=INPUT, fieldbackground=INPUT, foreground=SOFT,
                     rowheight=26, borderwidth=0, relief="flat", highlightthickness=0,
                     bordercolor=INPUT, lightcolor=INPUT, darkcolor=INPUT, font=F(9))
        st.configure("Treeview.Heading", background=CARD, foreground=MUTED, font=F(8, "bold"),
                     relief="flat", bordercolor=CARD, lightcolor=CARD, darkcolor=CARD)
        st.map("Treeview", background=[("selected", PRIMARY)], foreground=[("selected", "#ffffff")])
        st.configure("Rw.Vertical.TScrollbar", background=INPUT, troughcolor=CARD,
                     bordercolor=BORDER, lightcolor=INPUT, darkcolor=INPUT,
                     arrowcolor=MUTED, relief="flat", width=10)
        st.map("Rw.Vertical.TScrollbar", background=[("active", PRIMARY)])
        self.root.option_add("*TCombobox*Listbox*Background", INPUT)
        self.root.option_add("*TCombobox*Listbox*Foreground", SOFT)
        self.root.option_add("*TCombobox*Listbox*selectBackground", PRIMARY)
        self.root.option_add("*TCombobox*Listbox*selectForeground", "#ffffff")

    def _card(self, parent, pad=18):
        c = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        inner = tk.Frame(c, bg=CARD, padx=pad, pady=pad)
        inner.pack(fill="both", expand=True)
        c.inner = inner
        return c

    def _eyebrow(self, parent, text):
        lbl = tk.Label(parent, text=text.upper(), bg=CARD, fg=MUTED, font=F(8, "bold"))
        lbl.pack(anchor="w")
        return lbl

    def _entry(self, parent, width=30):
        return tk.Entry(parent, width=width, bg=INPUT, fg=TEXT, insertbackground=TEXT,
                        relief="flat", font=F(10, "bold"), highlightbackground=BORDER,
                        highlightthickness=1)

    def _combo(self, parent, label, values, current):
        cb_label = self._eyebrow(parent, label)
        cb = ttk.Combobox(parent, values=values, state="readonly", style="Rw.TCombobox")
        cb.set(current)
        cb.pack(fill="x", pady=(4, 12))
        cb.eyebrow = cb_label
        return cb

    def _btn(self, parent, text, cmd, kind="primary", side=None):
        colors = {"primary": (PRIMARY, "#ffffff"), "ghost": (INPUT, SOFT),
                  "danger": (RED, "#ffffff")}
        bg, fg = colors[kind]
        b = tk.Label(parent, text=text, bg=bg, fg=fg, font=F(10, "bold"),
                     padx=16, pady=9, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(
            bg=HOVER if kind == "primary" else ("#2b3a55" if kind == "ghost" else "#dc2626")))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        if side:
            b.pack(side=side, padx=(0, 6), pady=(4, 4))
        else:
            b.pack(fill="x", pady=(4, 4))
        return b

    def _build_ui(self):
        nav = tk.Frame(self.root, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        nav.pack(fill="x")
        left = tk.Frame(nav, bg=CARD)
        left.pack(side="left", padx=18, pady=10)
        tk.Label(left, text="🛣  RoadWise PH", bg=CARD, fg=TEXT, font=F(15, "bold")).pack(side="left")
        tk.Label(left, text="  Metro Manila · live traffic", bg=CARD, fg=MUTED,
                 font=F(9)).pack(side="left")

        right_nav = tk.Frame(nav, bg=CARD)
        right_nav.pack(side="right", padx=18)
        self.clock_lbl = tk.Label(right_nav, text="--:--", bg=CARD, fg=TEXT, font=F(12, "bold"))
        self.clock_lbl.pack(side="right", padx=(14, 0))
        self.phase_lbl = tk.Label(right_nav, text="", bg=CARD, fg=MUTED, font=F(9))
        self.phase_lbl.pack(side="right", padx=(6, 0))
        self.nav_btns = {}
        for key, text in (("account", "👤  Account"), ("admin", "🗄  Admin"),
                          ("hazards", "⚠  Road hazards"), ("planner", "🧭  Plan a trip")):
            b = tk.Label(right_nav, text=text, bg=CARD, fg=SOFT, font=F(10, "bold"),
                         padx=12, pady=8, cursor="hand2")
            b.pack(side="right", padx=2)
            b.bind("<Button-1>", lambda e, k=key: self._show(k))
            self.nav_btns[key] = b

        self.content = tk.Frame(self.root, bg=BG)
        self.content.pack(fill="both", expand=True)
        self.views = {}
        self._build_planner()
        self._build_hazards()
        self._build_admin()
        self._build_account()
        self._build_gate()
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        self.refresh_hazards()
        self._enter_gate()

    def _show(self, key):
        for v in self.views.values():
            v.pack_forget()
        self.views[key].pack(fill="both", expand=True)
        for name, b in self.nav_btns.items():
            on = name == key
            fg = "#ffffff" if on else (GREEN if (name == "account" and self.user) else SOFT)
            b.configure(bg=PRIMARY if on else CARD, fg=fg)
        self.current_view = key

    def _scroll_column(self, parent, width):
        """A fixed-width column that scrolls when the window is too short."""
        wrap = tk.Frame(parent, bg=BG)
        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0, width=width)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview,
                            style="Rw.Vertical.TScrollbar")
        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=inner, anchor="nw", width=width)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        self.planner_inner = inner
        return wrap, canvas

    def _on_wheel(self, event):
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self.planner_inner:
                self.planner_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
                return
            widget = getattr(widget, "master", None)

    def _build_planner(self):
        view = tk.Frame(self.content, bg=BG)
        self.views["planner"] = view
        hero = tk.Frame(view, bg=BG)
        hero.pack(fill="x", padx=22, pady=(18, 8))
        tk.Label(hero, text="LRT/MRT & RIDE-HAILING COMPARATOR", bg=BG, fg=MUTED,
                 font=F(9, "bold")).pack(anchor="w")
        tk.Label(hero, text="Plan Commute & Compare Fares", bg=BG, fg=TEXT,
                 font=F(26, "bold")).pack(anchor="w", pady=(2, 0))
        tk.Label(hero, text="Real road network, live congestion and honest fares for Metro Manila.",
                 bg=BG, fg=MUTED, font=F(10)).pack(anchor="w")

        body = tk.Frame(view, bg=BG)
        body.pack(fill="both", expand=True, padx=22, pady=(6, 18))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        col, self.planner_canvas = self._scroll_column(body, 344)
        col.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        form = self._card(self.planner_inner, 18)
        form.pack(fill="x")
        inner = form.inner
        self.place_names = list(RWD.PLACES.keys())
        mode_vals = ["%s  %s" % (RWD.PROVIDERS[k]["icon"], RWD.PROVIDERS[k]["label"])
                     for k in RWD.PROVIDERS]
        self.mode_combo = self._combo(inner, "Mode of Transport", mode_vals, mode_vals[0])
        self.mode_combo.bind("<<ComboboxSelected>>", self._mode_changed)
        self.mode_desc = tk.Label(inner, text="", bg=CARD, fg=SOFT, font=F(9, "italic"),
                                  wraplength=300, justify="left")
        self.mode_desc.pack(anchor="w", pady=(0, 12))
        self.start_combo = self._combo(inner, "Pickup Point", self.place_names, "Ayala Center")
        self.end_combo = self._combo(inner, "Drop-off Point", self.place_names, "BGC Taguig")
        self.traffic_combo = self._combo(inner, "Traffic-Crowd",
                                         list(RWD.TRAFFIC_PRESETS.keys()), "Auto – Live Traffic")
        btns = tk.Frame(inner, bg=CARD)
        btns.pack(fill="x", pady=(4, 2))
        self._btn(btns, "Calculate Route & Fare", self.calculate_trip, "primary", side="left")
        self._btn(btns, "Save Destination", self.save_destination, "ghost", side="left")
        tk.Label(inner, text="Tip: right-click the map to drop your own pin.",
                 bg=CARD, fg=MUTED, font=F(8, "italic")).pack(anchor="w", pady=(6, 0))

        self.summary = self._card(self.planner_inner, 18)
        self.summary.pack(fill="both", expand=True, pady=(14, 0))
        self._summary_placeholder()
        self._apply_mode_pickers(self._current_pid(), reset=True)

        map_card = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        map_card.grid(row=0, column=1, sticky="nsew")
        head = tk.Frame(map_card, bg=CARD)
        head.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(head, text="LIVE TRAFFIC MAP", bg=CARD, fg=MUTED, font=F(8, "bold")).pack(side="left")
        chips = tk.Frame(head, bg=CARD)
        chips.pack(side="right")
        self.speed_btns = {}
        for text, mm in (("1×", 1.0), ("10×", 10.0), ("60×", 60.0), ("Now", None)):
            b = tk.Label(chips, text=text, bg=INPUT, fg=SOFT, font=F(8, "bold"),
                         padx=9, pady=4, cursor="hand2")
            b.pack(side="left", padx=2)
            if mm is None:
                b.bind("<Button-1>", lambda e: self._go_live())
            else:
                b.bind("<Button-1>", lambda e, v=mm: self._set_mult(v))
            self.speed_btns[text] = b
        self._set_speed_buttons()

        holder = tk.Frame(map_card, bg="#090a0f")
        holder.pack(fill="both", expand=True, padx=1, pady=(6, 1))
        self.map = LiveMap(holder, on_place=self._on_place, on_hazard=self._on_hazard,
                           on_pick=self._on_pick, on_bad=self._on_bad, on_train=self._on_train)
        self.map.pack(fill="both", expand=True)
        self.panel = TrafficPanel(holder, on_time=self._on_time, on_rain=self._on_rain,
                                  on_style=self.map.set_style)
        self.panel.place(relx=0.012, rely=0.985, anchor="sw", width=252)

    def _clear(self, inner):
        for w in inner.winfo_children():
            w.destroy()

    MODE_HINTS = {
        "rail": "Showing this line's fixed railway route and stations. Pick your boarding "
                "station and your drop-off station from the lists, then press Calculate.",
        "jeepney": "Showing the designated jeepney routes and their stops. Pick a start "
                   "and a destination to see where to ride and where to get off.",
        "bus": "Showing the designated bus routes and their stops. Pick a start and a "
               "destination to see where to board and where to get off.",
    }

    def _summary_placeholder(self, kind="road"):
        inner = self.summary.inner
        self._clear(inner)
        self._eyebrow(inner, "Route Summary")
        tk.Label(inner, text=self.MODE_HINTS.get(kind, "Pick a start, a destination and a "
                                                       "ride, then press “Calculate Route & Fare”."),
                 bg=CARD, fg=MUTED, font=F(10), wraplength=330,
                 justify="left").pack(anchor="w", pady=(6, 0))

    def _render_summary(self):
        t = self.trip
        inner = self.summary.inner
        self._clear(inner)
        self._eyebrow(inner, "Route Summary")
        tk.Label(inner, text=t["badge"], bg=PRIMARY, fg="#ffffff",
                 font=F(9, "bold"), padx=10, pady=5).pack(anchor="w", pady=(4, 8))
        tk.Label(inner, text=t["title"], bg=CARD, fg=TEXT, font=F(15, "bold"),
                 wraplength=350, justify="left").pack(anchor="w")
        tk.Label(inner, text="₱%d" % t["fare"], bg=CARD, fg=GREEN,
                 font=F(34, "bold")).pack(anchor="w", pady=(4, 2))

        tiles = tk.Frame(inner, bg=CARD)
        tiles.pack(fill="x", pady=(2, 6))
        for label, value in (("Distance", "%.1f km" % t["km"]),
                             ("Time" if t["kind"] == "rail" else "Time (+traffic)",
                              "%d mins" % t["mins"]),
                             ("Arrival", t["eta"])):
            cell = tk.Frame(tiles, bg=INPUT, highlightbackground=BORDER, highlightthickness=1)
            cell.pack(side="left", expand=True, fill="x", padx=2)
            tk.Label(cell, text=label.upper(), bg=INPUT, fg=MUTED,
                     font=F(7, "bold")).pack(pady=(7, 0))
            tk.Label(cell, text=value, bg=INPUT, fg=TEXT, font=F(12, "bold")).pack(pady=(0, 7))

        if t.get("steps"):
            self._eyebrow(inner, "Your journey")
            for st in t["steps"]:
                row = tk.Frame(inner, bg=CARD)
                row.pack(fill="x", pady=(6, 0))
                tk.Frame(row, bg=st["color"], width=4).pack(side="left", fill="y", padx=(0, 8))
                col = tk.Frame(row, bg=CARD)
                col.pack(side="left", fill="x", expand=True)
                tk.Label(col, text=st["title"], bg=CARD, fg=TEXT, font=F(10, "bold"),
                         wraplength=320, justify="left").pack(anchor="w")
                tk.Label(col, text=st["detail"], bg=CARD, fg=MUTED, font=F(9),
                         wraplength=320, justify="left").pack(anchor="w")
            if t.get("alts"):
                tk.Label(inner, text="Other options: " + " · ".join(
                    "%s (~%d min)" % (a["name"], round(a["mins"])) for a in t["alts"]),
                    bg=CARD, fg=MUTED, font=F(8), wraplength=330,
                    justify="left").pack(anchor="w", pady=(8, 0))
        tk.Label(inner, text=t["note"], bg=CARD, fg=MUTED, font=F(9),
                 wraplength=350, justify="left").pack(anchor="w", pady=(8, 0))
        if t["url"]:
            link = tk.Label(inner, text="Open %s ↗" % t["provider"], bg=CARD, fg=PRIMARY,
                            font=F(10, "bold"), cursor="hand2")
            link.pack(anchor="w", pady=(8, 0))
            link.bind("<Button-1>", lambda e, u=t["url"]: webbrowser.open(u))

    def _build_hazards(self):
        view = tk.Frame(self.content, bg=BG)
        self.views["hazards"] = view
        hero = tk.Frame(view, bg=BG)
        hero.pack(fill="x", padx=22, pady=(18, 8))
        tk.Label(hero, text="COMMUNITY REPORTS", bg=BG, fg=MUTED, font=F(9, "bold")).pack(anchor="w")
        tk.Label(hero, text="Road Hazards & Bad Spots", bg=BG, fg=TEXT,
                 font=F(22, "bold")).pack(anchor="w")

        body = tk.Frame(view, bg=BG)
        body.pack(fill="both", expand=True, padx=22, pady=(6, 18))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        lst = self._card(body, 14)
        lst.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self._eyebrow(lst.inner, "Reported hazards")
        self.hazard_tree = ttk.Treeview(lst.inner, columns=("title", "desc", "where"),
                                        show="headings", height=12)
        for c, text, w in (("title", "Title", 220), ("desc", "Details", 320),
                           ("where", "Coordinates", 150)):
            self.hazard_tree.heading(c, text=text)
            self.hazard_tree.column(c, width=w, anchor="w")
        self.hazard_tree.pack(fill="both", expand=True, pady=(4, 8))
        self.hazard_tree.bind("<<TreeviewSelect>>", self._hazard_selected)
        self._btn(lst.inner, "Show on map", self._jump_to_hazard, "ghost", side="left")
        self._btn(lst.inner, "Reload list", self.refresh_hazards, "ghost", side="left")

        rep = self._card(body, 16)
        rep.grid(row=0, column=1, sticky="nsew")
        inner = rep.inner
        self._eyebrow(inner, "Report a hazard")
        tk.Label(inner, text="Title", bg=CARD, fg=SOFT, font=F(9, "bold")).pack(anchor="w", pady=(6, 0))
        self.ent_h_title = self._entry(inner, 30)
        self.ent_h_title.pack(fill="x", pady=(2, 8))
        tk.Label(inner, text="Description", bg=CARD, fg=SOFT, font=F(9, "bold")).pack(anchor="w")
        self.ent_h_desc = self._entry(inner, 30)
        self.ent_h_desc.pack(fill="x", pady=(2, 8))
        self.btn_pick = self._btn(inner, "Pick spot on the map", self._toggle_pick, "ghost")
        self.pick_lbl = tk.Label(inner, text="No spot pinned yet.", bg=CARD, fg=MUTED,
                                 font=F(8, "italic"), wraplength=300, justify="left")
        self.pick_lbl.pack(anchor="w", pady=(4, 8))
        self._btn(inner, "Submit Hazard Report", self.add_hazard, "danger")

    def _build_admin(self):
        view = tk.Frame(self.content, bg=BG)
        self.views["admin"] = view
        hero = tk.Frame(view, bg=BG)
        hero.pack(fill="x", padx=22, pady=(18, 8))
        tk.Label(hero, text="RESTRICTED", bg=BG, fg=MUTED, font=F(9, "bold")).pack(anchor="w")
        tk.Label(hero, text="Admin Database Viewer", bg=BG, fg=TEXT,
                 font=F(22, "bold")).pack(anchor="w")
        card = self._card(view, 14)
        card.pack(fill="both", expand=True, padx=22, pady=(6, 18))
        self.lbl_admin_status = tk.Label(card.inner, text="Status: log in with an admin account",
                                         bg=CARD, fg="#f87171", font=F(10, "bold"))
        self.lbl_admin_status.pack(anchor="w")
        bar = tk.Frame(card.inner, bg=CARD)
        bar.pack(fill="x", pady=(6, 0))
        self._btn(bar, "Refresh Database Records", self.load_admin_data, "ghost", side="left")
        self.admin_text = tk.Text(card.inner, bg=INPUT, fg=SOFT, font=("Consolas", 9),
                                  relief="flat", wrap="none")
        self.admin_text.pack(fill="both", expand=True, pady=(8, 0))

    def _build_account(self):
        view = tk.Frame(self.content, bg=BG)
        self.views["account"] = view
        hero = tk.Frame(view, bg=BG)
        hero.pack(fill="x", padx=22, pady=(18, 8))
        tk.Label(hero, text="YOUR COMMUTES ARE SAVED HERE", bg=BG, fg=MUTED,
                 font=F(9, "bold")).pack(anchor="w")
        tk.Label(hero, text="My Account", bg=BG, fg=TEXT, font=F(22, "bold")).pack(anchor="w")

        card = self._card(view, 22)
        card.pack(fill="x", padx=22, pady=(6, 12))
        inner = card.inner
        self.lbl_user_status = tk.Label(inner, text="", bg=CARD, fg=GREEN, font=F(11, "bold"))
        self.lbl_user_status.pack(anchor="w", pady=(0, 10))
        row = tk.Frame(inner, bg=CARD)
        row.pack(anchor="w")
        self._btn(row, "Logout", self.logout_user, "danger", side="left")

        recent = self._card(view, 18)
        recent.pack(fill="both", expand=True, padx=22, pady=(6, 18))
        self._eyebrow(recent.inner, "Saved commutes")
        self.recent_list = tk.Listbox(recent.inner, bg=INPUT, fg=SOFT, font=F(9), relief="flat",
                                      highlightthickness=0, selectbackground=PRIMARY)
        self.recent_list.pack(fill="both", expand=True)

    def _on_place(self, name):
        p = RWD.PLACES[name]
        if p.get("is_current") and self.map.user_pos:
            self.map.center_on(self.map.user_pos[0], self.map.user_pos[1], 15)
        else:
            self.map.center_on(p["lat"], p["lng"], 15)
        self.map.set_status(name)

    def _on_hazard(self, h):
        self.map.center_on(h["lat"], h["lng"], 15)
        self.map.set_status("⚠ %s" % h["title"])

    def _on_bad(self, spot):
        self.map.center_on(spot["lat"], spot["lng"], 15)
        self.map.set_status("%s %s" % (spot["icon"], spot["label"]))

    def _on_train(self, t):
        st = t["station"]
        self.map.center_on(st["lat"], st["lng"], 15)
        self.map.set_status("%s — %s" % (t["line"]["name"], st["name"]))

    def _on_pick(self, lat, lng):
        self.picked = (lat, lng)
        self.map.user_pos = (lat, lng)
        self.map.set_status("Pinned %.4f, %.4f" % (lat, lng))
        self.pick_lbl.configure(text="Pinned at %.4f, %.4f — submit to log it." % (lat, lng),
                                fg=GREEN)

    def _toggle_pick(self):
        self.pick_mode = not self.pick_mode
        self.map.pick_mode = self.pick_mode
        self.map.canvas.configure(cursor="crosshair" if self.pick_mode else "")
        self.btn_pick.configure(bg=PRIMARY if self.pick_mode else INPUT,
                                fg="#ffffff" if self.pick_mode else SOFT)
        if self.pick_mode:
            self._show("planner")

    def _on_time(self, minutes, kind):
        if kind == "live":
            self._go_live()
        else:
            self.live = False
            self.scrub_minutes = float(minutes)
            self._set_speed_buttons()

    def _go_live(self):
        self.live = True
        self.mult = 1.0
        self.sim = manila_now()
        self.scrub_minutes = float(self.sim.hour * 60 + self.sim.minute)
        self._set_speed_buttons()

    def _set_mult(self, m):
        self.mult = float(m)
        self._set_speed_buttons()

    def _set_speed_buttons(self):
        for text, b in self.speed_btns.items():
            on = (text == "Now" and self.live) or \
                 (text != "Now" and self.live and self.mult == float(text.rstrip("×")))
            b.configure(bg=PRIMARY if on else INPUT, fg="#ffffff" if on else SOFT)

    def _on_rain(self, on):
        self.rain = on

    @property
    def minutes(self):
        if self.live:
            return self.sim.hour * 60 + self.sim.minute + self.sim.second / 60.0
        return self.scrub_minutes

    def _resolve(self, label):
        p = RWD.PLACES[label]
        if p.get("is_current") and self.map.user_pos:
            return {"lat": self.map.user_pos[0], "lng": self.map.user_pos[1]}
        return {"lat": p["lat"], "lng": p["lng"]}

    def calculate_trip(self):
        start, end = self.start_combo.get(), self.end_combo.get()
        if start == end:
            messagebox.showwarning("Warning", "Boarding/start and drop-off/destination "
                                   "cannot be the same.")
            return
        pid = self._current_pid()
        mode_label = RWD.PROVIDERS[pid]["label"]
        if RWD.PROVIDERS[pid]["kind"] == "rail":
            p1 = p2 = None
        else:
            p1, p2 = self._resolve(start), self._resolve(end)
        self._summary_busy(start, end)
        threading.Thread(target=self._route_worker,
                         args=(p1, p2, pid, mode_label, self.traffic_combo.get(), start, end),
                         daemon=True).start()

    def _summary_busy(self, start, end):
        inner = self.summary.inner
        self._clear(inner)
        self._eyebrow(inner, "Route Summary")
        word = "railway" if RWD.PROVIDERS[self._current_pid()]["kind"] == "rail" else "road"
        tk.Label(inner, text="Finding the best %s between\n%s → %s …" % (word, start, end),
                 bg=CARD, fg=MUTED, font=F(10), justify="left").pack(anchor="w", pady=(6, 0))

    def _route_worker(self, p1, p2, pid, mode_label, preset, start, end):
        prov = RWD.PROVIDERS[pid]
        kind = prov.get("kind", "road")
        minutes = self.minutes
        factor = RWD.TRAFFIC_PRESETS[preset]
        live_reading = factor is None
        if live_reading:
            factor = RT.auto_factor(self.network, minutes, self.hazards, self.rain)
        a = b = None
        if p1 is not None:
            a, b = (p1["lat"], p1["lng"]), (p2["lat"], p2["lng"])

        plan = None
        if kind == "rail":
            plan = TR.RAIL.plan_line(prov["line"], start, end)
        elif kind in ("jeepney", "bus"):
            plan = TR.ROUTES.plan(kind, a, b, factor)
        if plan is not None and not plan["ok"]:
            self._post(self._trip_failed, plan["reason"])
            return

        if plan is None:
            coords, km, ff_min = RT.route_info(p1, p2)
            mins = max(1, int(round(ff_min * factor)))
            fare = fare_for(pid, km)
        else:
            coords, km = None, plan["km"]
            mins = max(1, int(round(plan["mins"])))
            fare = plan["fare"] if plan["fare"] is not None else fare_for(pid, km)

        if self.network:
            demand = RT.demand_at(minutes)
            avg = sum(RT.corridor_jam(c, minutes, demand, RT.hazard_near(c, self.hazards))
                      for c in self.network) / len(self.network)
        else:
            avg = 0.35
        lv = RT.level_for(avg)
        eta = datetime.datetime(2000, 1, 1) + datetime.timedelta(minutes=minutes + mins)
        traffic_note = "Traffic delay ×%.2f · %s%s" % (
            factor, "Auto – Live Traffic" if live_reading else preset,
            " · heavy rain" if self.rain else "")
        if kind == "rail":
            badge = "%s  %s  •  %d stops" % (prov["icon"], prov["label"],
                                              len(plan["legs"][0]["stops"]) - 1)
            note = ("Trains run on fixed tracks, so road traffic doesn't change this route. "
                    "Time includes about 3 min waiting for the train. Fare is an estimate.")
        elif plan is not None:
            badge = "%s  %s  •  %s (~%d km/h)" % (prov["icon"], plan["route"], lv["label"],
                                                  round(RT.speed_for(avg)))
            note = traffic_note + ("" if plan["snapped"] else
                                   " · offline: route drawn as straight lines")
        else:
            badge = "%s  %s  •  %s (~%d km/h)" % (prov["icon"], prov["label"], lv["label"],
                                                  round(RT.speed_for(avg)))
            note = traffic_note
        trip = {
            "coords": coords, "km": km, "mins": mins, "fare": fare,
            "start": start, "end": end, "mode_label": mode_label, "pid": pid,
            "kind": kind, "plan": plan,
            "steps": plan["steps"] if plan else None,
            "alts": plan.get("alts") if plan else None,
            "preset": preset, "factor": factor,
            "eta": M.fmt_clock(eta.hour * 60 + eta.minute),
            "badge": badge, "title": "%s → %s" % (start, end),
            "provider": prov["label"], "url": prov["url"], "note": note,
        }
        self._post(self._trip_ready, trip)

    def _trip_failed(self, reason):
        self.trip = None
        self.map.transit = None
        self.map.route = None
        inner = self.summary.inner
        self._clear(inner)
        self._eyebrow(inner, "Route Summary")
        tk.Label(inner, text="No route found", bg=CARD, fg=RED,
                 font=F(14, "bold")).pack(anchor="w", pady=(8, 4))
        tk.Label(inner, text=reason, bg=CARD, fg=SOFT, font=F(10), wraplength=330,
                 justify="left").pack(anchor="w")

    def _current_pid(self):
        label = self.mode_combo.get().split("  ", 1)[-1]
        return RWD.MODE_BY_LABEL[label]

    def _apply_mode_pickers(self, pid, reset=False):
        """Rail modes list only that line's stations; every other mode lists places."""
        prov = RWD.PROVIDERS[pid]
        kind = prov.get("kind", "road")
        self.mode_desc.configure(text=prov["desc"])
        if kind == "rail":
            names = TR.RAIL.line_station_names(prov["line"])
            titles = ("Boarding Station · %s" % prov["label"],
                      "Drop-off Station · %s" % prov["label"])
            defaults = (names[0], names[-1])
        else:
            names = self.place_names
            defaults = ("Ayala Center", "BGC Taguig")
            titles = ("Starting Point", "Destination") if kind in ("jeepney", "bus") \
                else ("Pickup Point", "Drop-off Point")
        for cb, title, default in zip((self.start_combo, self.end_combo), titles, defaults):
            keep = cb.get() if (not reset and cb.get() in names) else default
            cb.configure(values=names)
            cb.set(keep)
            cb.eyebrow.configure(text=title.upper())

    def _mode_changed(self, _e=None):
        """Switching ride type swaps the whole map view to that mode's own network."""
        pid = self._current_pid()
        prov = RWD.PROVIDERS[pid]
        kind = prov.get("kind", "road")
        self._apply_mode_pickers(pid)
        self.trip = None
        self.map.clear_transit()
        self._summary_placeholder(kind)
        if kind == "rail":
            self.map.show_rail_network(prov["line"])
            self.map.set_status("%s · %d stations — fixed railway" % (
                prov["label"], len(TR.RAIL.lines[prov["line"]]["stations"])))
        elif kind in ("jeepney", "bus"):
            self._preview_token += 1
            self.map.set_status("Loading %s routes…" % kind)
            threading.Thread(target=self._preview_worker,
                             args=(kind, self._preview_token), daemon=True).start()
        else:
            self._preview_token += 1
            self.map.set_status("%s · road navigation" % prov["label"])

    def _preview_worker(self, kind, token):
        routes = TR.ROUTES.preview(kind)
        self._post(self._preview_ready, kind, routes, token)

    def _preview_ready(self, kind, routes, token):
        if token != self._preview_token:
            return
        self.map.show_preview(routes)
        self.map.set_status("%d designated %s route%s" % (
            len(routes), kind, "" if len(routes) == 1 else "s"))

    def _trip_ready(self, trip):
        self.trip = trip
        plan = trip.get("plan")
        self.map.preview = None
        if plan:
            self.map.route = None
            self.map.transit = plan
            self.map.display = "rail" if trip["kind"] == "rail" else "traffic"
            if trip["kind"] == "rail":
                self.map.rail_filter = plan["line_id"]
            self.map.fit(plan["points"])
        else:
            self.map.transit = None
            self.map.display = "traffic"
            self.map.route_labels = (trip["start"], trip["end"])
            self.map.route = trip["coords"]
            self.map.fit(trip["coords"])
        self._render_summary()
        self._show("planner")
        if self.user:
            conn = sqlite3.connect(DATABASE)
            conn.execute("INSERT INTO trips (user_id,start,end,mode,traffic,fare) VALUES (?,?,?,?,?,?)",
                         (self.user["id"], trip["start"], trip["end"], trip["mode_label"],
                          trip["preset"], trip["fare"]))
            conn.commit()
            conn.close()
            self.refresh_recent()

    def save_destination(self):
        if not self.trip:
            messagebox.showinfo("RoadWise PH", "Calculate a route first, then save it.")
            return
        if not self.user:
            messagebox.showinfo("RoadWise PH", "Log in to save destinations.")
            self._show("account")
            return
        conn = sqlite3.connect(DATABASE)
        conn.execute("INSERT INTO trips (user_id,start,end,mode,traffic,fare) VALUES (?,?,?,?,?,?)",
                     (self.user["id"], self.trip["start"], self.trip["end"],
                      self.trip["mode_label"], "Saved", self.trip["fare"]))
        conn.commit()
        conn.close()
        self.refresh_recent()
        messagebox.showinfo("Success", "Destination saved to your commutes.")

    def refresh_recent(self):
        if not hasattr(self, "recent_list"):
            return
        conn = sqlite3.connect(DATABASE)
        if self.user and self.user["role"] == "admin":
            rows = conn.execute("SELECT start,end,mode,traffic,fare,created_at FROM trips "
                                "ORDER BY id DESC LIMIT 40").fetchall()
        elif self.user:
            rows = conn.execute("SELECT start,end,mode,traffic,fare,created_at FROM trips "
                                "WHERE user_id=? ORDER BY id DESC LIMIT 40",
                                (self.user["id"],)).fetchall()
        else:
            rows = []
        conn.close()
        self.recent_list.delete(0, tk.END)
        for r in rows:
            self.recent_list.insert(tk.END, "%s → %s · %s · %s · ₱%d · %s" %
                                    (r[0], r[1], r[2], r[3], round(r[4]), str(r[5])[:16]))

    def refresh_hazards(self):
        conn = sqlite3.connect(DATABASE)
        rows = conn.execute("SELECT id,title,desc,lat,lng FROM hazards ORDER BY id DESC").fetchall()
        conn.close()
        self.hazards = [{"id": r[0], "title": r[1], "desc": r[2],
                         "lat": r[3] if r[3] is not None else RWD.CENTER_LAT,
                         "lng": r[4] if r[4] is not None else RWD.CENTER_LNG} for r in rows]
        self.hazard_tree.delete(*self.hazard_tree.get_children())
        for h in self.hazards:
            self.hazard_tree.insert("", "end", iid=str(h["id"]),
                                    values=(h["title"], h["desc"],
                                            "%.4f, %.4f" % (h["lat"], h["lng"])))
        if self.network:
            RT.bind_hazards(self.hazards, self.network)
        self.map.hazards = self.hazards

    def _hazard_selected(self, _e=None):
        sel = self.hazard_tree.selection()
        if not sel:
            return
        h = next((x for x in self.hazards if str(x["id"]) == sel[0]), None)
        if h:
            self.map.center_on(h["lat"], h["lng"], 15)
            self.map.set_status("⚠ %s" % h["title"])

    def _jump_to_hazard(self):
        if not self.hazard_tree.selection():
            messagebox.showinfo("RoadWise PH", "Pick a hazard from the list first.")
            return
        self._hazard_selected()
        self._show("planner")

    def add_hazard(self):
        title = self.ent_h_title.get().strip()
        desc = self.ent_h_desc.get().strip()
        if not title or not desc:
            messagebox.showerror("Error", "Fill out title and description.")
            return
        lat, lng = self.picked if self.picked else (RWD.CENTER_LAT, RWD.CENTER_LNG)
        conn = sqlite3.connect(DATABASE)
        conn.execute("INSERT INTO hazards (title,desc,lat,lng,type) VALUES (?,?,?,?,?)",
                     (title, desc, lat, lng, "Hazard"))
        conn.commit()
        conn.close()
        self.ent_h_title.delete(0, tk.END)
        self.ent_h_desc.delete(0, tk.END)
        self.picked = None
        self.map.user_pos = None
        self.pick_lbl.configure(text="No spot pinned yet.", fg=MUTED)
        self.refresh_hazards()
        messagebox.showinfo("Success", "Hazard report added and pinned on the map.")

    def _build_gate(self):
        self.gate = tk.Frame(self.root, bg=BG)
        wrap = tk.Frame(self.gate, bg=BG)
        wrap.place(relx=0.5, rely=0.46, anchor="center")
        tk.Label(wrap, text="🛣  RoadWise PH", bg=BG, fg=TEXT, font=F(26, "bold")).pack()
        tk.Label(wrap, text="Log in to plan trips, see live traffic and save your commutes.",
                 bg=BG, fg=MUTED, font=F(10)).pack(pady=(2, 16))
        card = self._card(wrap, 24)
        card.pack()
        inner = card.inner
        tk.Label(inner, text="Name  (only needed to sign up)", bg=CARD, fg=SOFT,
                 font=F(9, "bold")).pack(anchor="w")
        self.g_name = self._entry(inner, 36)
        self.g_name.pack(fill="x", pady=(2, 8))
        tk.Label(inner, text="Email", bg=CARD, fg=SOFT, font=F(9, "bold")).pack(anchor="w")
        self.g_email = self._entry(inner, 36)
        self.g_email.pack(fill="x", pady=(2, 8))
        tk.Label(inner, text="Password", bg=CARD, fg=SOFT, font=F(9, "bold")).pack(anchor="w")
        self.g_pass = self._entry(inner, 36)
        self.g_pass.configure(show="*")
        self.g_pass.pack(fill="x", pady=(2, 8))
        self.gate_msg = tk.Label(inner, text="", bg=CARD, fg="#f87171", font=F(9, "bold"),
                                 wraplength=300, justify="left")
        self.gate_msg.pack(anchor="w", pady=(0, 4))
        self._btn(inner, "Log in", self.login_user, "primary")
        self._btn(inner, "Create account", self.signup_user, "ghost")
        for e in (self.g_name, self.g_email, self.g_pass):
            e.bind("<Return>", lambda ev: self.login_user())

    def _enter_gate(self):
        """Show only the login screen; hide every tab until someone logs in."""
        self.user = None
        for b in self.nav_btns.values():
            b.pack_forget()
        self.content.pack_forget()
        self.gate.pack(fill="both", expand=True)
        for e in (self.g_name, self.g_email, self.g_pass):
            e.delete(0, tk.END)
        self.gate_msg.configure(text="")
        self.g_email.focus_set()

    def _enter_app(self):
        self.gate.pack_forget()
        self.content.pack(fill="both", expand=True)
        order = ["account"] + (["admin"] if self.user["role"] == "admin" else []) + \
                ["hazards", "planner"]
        for key in order:
            self.nav_btns[key].pack(side="right", padx=2)
        self.nav_btns["account"].configure(text="👤  %s" % self.user["name"])
        self.lbl_user_status.configure(text="Logged in as: %s  (%s)" % (
            self.user["name"], self.user["role"].upper()))
        self.refresh_recent()
        if self.user["role"] == "admin":
            self.load_admin_data()
        self._show("planner")

    def login_user(self):
        email = self.g_email.get().strip().lower()
        if not email or not self.g_pass.get():
            self.gate_msg.configure(text="Enter your email and password.")
            return
        conn = sqlite3.connect(DATABASE)
        row = conn.execute("SELECT id,name,email,role FROM users WHERE email=? AND password=?",
                           (email, _pw(self.g_pass.get()))).fetchone()
        conn.close()
        if not row:
            self.gate_msg.configure(text="Wrong email or password.")
            return
        self.user = {"id": row[0], "name": row[1], "email": row[2], "role": row[3]}
        self._enter_app()

    def signup_user(self):
        name = self.g_name.get().strip()
        email = self.g_email.get().strip().lower()
        password = self.g_pass.get()
        if not name or not email or not password:
            self.gate_msg.configure(text="To sign up, fill in name, email and password.")
            return
        if "@" not in email or "." not in email.split("@")[-1]:
            self.gate_msg.configure(text="That doesn't look like an email address.")
            return
        if len(password) < 6:
            self.gate_msg.configure(text="Password must be at least 6 characters.")
            return
        conn = sqlite3.connect(DATABASE)
        try:
            cur = conn.execute("INSERT INTO users (name,email,password) VALUES (?,?,?)",
                               (name, email, _pw(password)))
            conn.commit()
            uid = cur.lastrowid
        except sqlite3.IntegrityError:
            self.gate_msg.configure(text="That email already has an account. Log in instead.")
            return
        finally:
            conn.close()
        self.user = {"id": uid, "name": name, "email": email, "role": "user"}
        self._enter_app()

    def logout_user(self):
        self.trip = None
        self.map.clear_transit()
        self._summary_placeholder()
        self._enter_gate()

    def load_admin_data(self):
        if not self.user or self.user["role"] != "admin":
            self.lbl_admin_status.configure(
                text="Status: Access denied — admin accounts only", fg="#f87171")
            self.admin_text.delete("1.0", tk.END)
            self.admin_text.insert(tk.END, "Access denied. This page is for admin accounts only.")
            return
        self.lbl_admin_status.configure(text="Status: Authorized admin view", fg=GREEN)
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        self.admin_text.delete("1.0", tk.END)
        self.admin_text.insert(tk.END, "=== REGISTERED USERS ===\n")
        for r in c.execute("SELECT id,name,email,role,created_at FROM users"):
            self.admin_text.insert(tk.END, "ID %d | %s | %s | %s | %s\n" % r)
        self.admin_text.insert(tk.END, "\n=== ROAD HAZARDS ===\n")
        for r in c.execute("SELECT id,title,desc,lat,lng FROM hazards"):
            self.admin_text.insert(tk.END, "ID %d | %s | %s (%.4f, %.4f)\n" % r)
        self.admin_text.insert(tk.END, "\n=== TRIP LOGS ===\n")
        for r in c.execute("SELECT id,user_id,start,end,mode,traffic,fare,created_at FROM trips"):
            self.admin_text.insert(tk.END, "Trip #%d | user %s | %s -> %s | %s | %s | PHP %s | %s\n" % r)
        conn.close()

    def _post(self, fn, *args):
        self._q.put((fn, args))

    def _drain(self):
        while True:
            try:
                fn, args = self._q.get_nowait()
            except queue.Empty:
                return
            try:
                fn(*args)
            except Exception:
                traceback.print_exc()

    def _sync_time(self):
        if sync_clock():
            self._post(self._go_live)

    def _load_network(self):
        try:
            net = RT.build_network()
        except Exception:
            traceback.print_exc()
            net = []
        self._post(self._network_ready, net)

    def _network_ready(self, net):
        self.network = net
        RT.bind_hazards(self.hazards, net)
        self.map.network = net
        self.map.hazards = self.hazards
        self.map.bad_spots = RT.derive_bad_spots(net)
        self.map.set_status("Road network linked")

    def _loop(self):
        self._drain()
        now = time.monotonic() * 1000.0
        dt_real = max(0.0, min(120.0, now - self._last))
        self._last = now
        if self.live:
            if self.mult == 1.0:
                self.sim = manila_now()
            else:
                self.sim += datetime.timedelta(milliseconds=dt_real * self.mult)

        minutes = self.minutes
        self.map.minutes = minutes
        self.map.live = self.live
        self.map.rain = self.rain

        if self.network:
            demand = RT.demand_at(minutes)
            avg = sum(RT.corridor_jam(c, minutes, demand, RT.hazard_near(c, self.hazards))
                      for c in self.network) / len(self.network)
        else:
            avg = 0.35
        self.panel.update_state(minutes, self.live, self.rain, RT.level_for(avg),
                                RT.speed_for(avg), self.map.style)
        if self.live and int(minutes) != self._last_minute:
            self._last_minute = int(minutes)
            self.panel.set_minutes(minutes)

        self.clock_lbl.configure(text="🕐  %s" % M.fmt_clock(minutes))
        self.phase_lbl.configure(text=M.period_label(minutes) +
                                 (" · Live" if self.live else " · Manual"))

        try:
            self.map.render(now)
        except tk.TclError:
            return
        gap = now - self._prev_tick if self._prev_tick else 0.0
        self._prev_tick = now
        self.root.after(max(8, int(32 - gap)), self._loop)


def _selfcheck_transit():
    TR.ROUTES.online = False
    P = lambda n: (RWD.PLACES[n]["lat"], RWD.PLACES[n]["lng"])
    assert len(TR.RAIL.stations) == 51
    assert fare_for("Bus", 10) == 26
    assert [p["label"] for p in RWD.PROVIDERS.values()] == [
        "Angkas", "Move It", "JoyRide", "Grab Car", "Jeepney", "Bus", "LRT-1", "LRT-2", "MRT-3"]
    assert all(p.get("desc") for p in RWD.PROVIDERS.values())
    for pid, n in (("lrt1", 25), ("lrt2", 13), ("mrt3", 13)):
        prov = RWD.PROVIDERS[pid]
        names = TR.RAIL.line_station_names(prov["line"])
        assert len(names) == n and prov["kind"] == "rail"
        p = TR.RAIL.plan_line(prov["line"], names[0], names[-1])
        assert p["ok"] and p["transfers"] == 0 and p["lines"] == [prov["label"]], p
        track = set(TR.RAIL.lines[prov["line"]]["track"])
        assert all(c in track for leg in p["legs"] for c in leg["coords"])
        assert [l["type"] for l in p["legs"]] == ["ride"]
        assert len(p["legs"][0]["stops"]) == n
        q = TR.RAIL.plan_line(prov["line"], names[-1], names[0])
        assert q["ok"] and q["legs"][0]["board"]["name"] == names[-1]
    assert not TR.RAIL.plan_line("lrt1", "Baclaran", "Baclaran")["ok"]
    assert not TR.RAIL.plan_line("lrt1", "Recto", "Baclaran")["ok"]
    p = TR.RAIL.plan(P("SM North EDSA"), P("PITX"))
    assert p["ok"] and p["lines"] == ["MRT-3", "LRT-1"] and p["transfers"] == 1, p
    track = {c for ln in TR.RAIL.lines.values() for c in ln["track"]}
    assert all(c in track for leg in p["legs"] if leg["type"] == "ride" for c in leg["coords"])
    assert [s["kind"] for s in p["steps"]].count("board") == 2
    p = TR.RAIL.plan(P("Marikina City Hall"), P("Quiapo Church"))
    assert p["ok"] and p["lines"] == ["LRT-2"] and p["legs"][1]["toward"] == "Recto"
    assert not TR.RAIL.plan(P("Antipolo Cathedral"), P("Quiapo Church"))["ok"]
    assert not TR.RAIL.plan(P("Ayala Center"), P("Makati CBD"))["ok"]
    p = TR.ROUTES.plan("jeepney", P("Antipolo Cathedral"), P("Cubao Araneta Center"))
    assert p["ok"] and p["legs"][1]["board"]["name"] == "Antipolo Cathedral"
    assert p["legs"][1]["toward"].startswith("Cubao")
    p = TR.ROUTES.plan("bus", P("Ayala Center"), P("SM North EDSA"), 1.35)
    assert p["ok"] and p["route"].startswith("EDSA Carousel")
    assert not TR.ROUTES.plan("bus", P("BGC Taguig"), P("Marikina City Hall"))["ok"]
    assert {r["kind"] for r in TR.ROUTES.routes.values()} == {"jeepney", "bus"}
    for pid, prov in RWD.PROVIDERS.items():
        assert prov["kind"] in ("rail", "road", "jeepney", "bus"), pid


def selfcheck():
    init_db()
    assert fare_for("Grab Car", 5) == 180
    assert fare_for("LRT-1", 10) == 24
    assert fare_for("jeepney", 10) == 24
    assert fare_for("angkas", 2) == 50
    assert RWD.TRAFFIC_PRESETS["Auto – Live Traffic"] is None
    coords = RT.densify(RWD.CORRIDORS[0]["waypoints"])
    assert len(coords) > 100
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + RT.haversine_m(coords[i - 1], coords[i]))
    fake = [{"id": "edsa", "name": "Test Road", "coords": coords, "cum": cum, "segb": [],
             "lengthKm": cum[-1] / 1000.0, "lanes": 2, "base": 0.6, "peak": 0.9,
             "seed": 0.5, "freeflow": 40, "jam": 0.3}]
    assert 0.04 <= RT.chunk_jam(fake[0], 0.5, 0.5, 480) <= 1.0
    assert all("lat" in s and "icon" in s for s in RT.derive_bad_spots(fake))
    hz = RT.bind_hazards([{"lat": 14.6, "lng": 121.0}], fake)
    assert RT.auto_factor(fake, 480, hz) > 1.0
    assert RT.level_for(0.9)["label"] == "Standstill"
    assert len(RWD.TRAIN_LINES) == 3
    _selfcheck_transit()
    print("SELFCHECK OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        selfcheck()
        sys.exit(0)
    root = tk.Tk()
    RoadWiseApp(root)
    root.mainloop()
