"""
migrate.py — Add missing columns to existing neuroscan.db
Run once: python migrate.py
"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), "instance", "neuroscan.db")

if not os.path.exists(DB_PATH):
    print(f"DB not found at {DB_PATH}")
    print("Trying current directory...")
    DB_PATH = "neuroscan.db"
    if not os.path.exists(DB_PATH):
        print("No DB found — just run app.py normally, it will create a fresh one.")
        exit(0)

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()

# Check existing columns
cur.execute("PRAGMA table_info(reading)")
existing = {row[1] for row in cur.fetchall()}
print(f"Existing columns: {existing}")

# Columns to add: (name, type, default)
new_cols = [
    ("focus",   "REAL", "50.0"),
    ("fatigue", "REAL", "50.0"),
    ("anxiety", "REAL", "50.0"),
]

for col, typ, default in new_cols:
    if col not in existing:
        sql = f"ALTER TABLE reading ADD COLUMN {col} {typ} DEFAULT {default}"
        cur.execute(sql)
        print(f"  ✓ Added column: {col}")
    else:
        print(f"  — Already exists: {col}")

conn.commit()
conn.close()
print("\nMigration complete. Run python app.py now.")