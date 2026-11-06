import os, shutil, sqlite3, sys, time

here = os.path.dirname(os.path.abspath(__file__))
db = os.path.join(here, "roadwise.db")
if not os.path.exists(db):
    print("No roadwise.db here - nothing to fix. Just start the app.")
    sys.exit(0)

backup = "%s.corrupt-%d" % (db, int(time.time()))
shutil.copy2(db, backup)
print("Backup saved:", backup)
for ext in ("-journal", "-wal", "-shm"):
    if os.path.exists(db + ext):
        os.remove(db + ext)

fresh = db + ".new"
if os.path.exists(fresh):
    os.remove(fresh)
new = sqlite3.connect(fresh)
schema = {
    "users": "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, "
             "password TEXT NOT NULL, role TEXT DEFAULT 'user', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "hazards": "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, desc TEXT NOT NULL, "
               "lat REAL, lng REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, type TEXT",
    "trips": "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, start TEXT NOT NULL, end TEXT NOT NULL, "
             "mode TEXT NOT NULL, traffic TEXT, fare REAL NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
}
for t, cols in schema.items():
    new.execute("CREATE TABLE %s (%s)" % (t, cols))

old = None
try:
    old = sqlite3.connect("file:%s?mode=ro" % backup.replace("\\", "/"), uri=True)
except sqlite3.Error as e:
    print("Could not open the old file:", e)

saved = {}
for t in schema:
    saved[t] = 0
    if old is None:
        continue
    try:
        cols = [r[1] for r in old.execute("PRAGMA table_info(%s)" % t)]
        keep = [c for c in cols if c in new.execute("SELECT * FROM %s" % t).description and True] or cols
        want = [d[0] for d in new.execute("SELECT * FROM %s" % t).description]
        use = [c for c in want if c in cols]
        cur = old.execute("SELECT %s FROM %s" % (",".join(use), t))
        while True:
            try:
                row = cur.fetchone()
            except sqlite3.Error:
                break
            if row is None:
                break
            try:
                new.execute("INSERT INTO %s (%s) VALUES (%s)" % (t, ",".join(use), ",".join("?" * len(use))), row)
                saved[t] += 1
            except sqlite3.Error:
                pass
    except sqlite3.Error as e:
        print("  %s: could not read (%s)" % (t, e))
new.commit()
new.close()
if old:
    old.close()
os.replace(fresh, db)
print("Recovered rows:", saved)
print("Done. Start the app again (missing admin/hazards are recreated automatically;")
print("default admin login: admin@roadwise.ph / admin123).")
