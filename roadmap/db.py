"""Database layer for the roadmap app.

SQLite schema and connection helpers. Keep this thin — business logic
lives in the views.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "roadmap.db"


SCHEMA = """
-- Themes: the strategic pillars items are tagged against.
CREATE TABLE IF NOT EXISTS themes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    priority INTEGER NOT NULL,
    description TEXT DEFAULT ''
);

-- Product/Tool tags: multi-tag system, items can have many.
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

-- Roadmap items.
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    bucket TEXT NOT NULL CHECK (bucket IN ('Now', 'Next', 'Later', 'Backlog', 'Recently Done')),
    theme_id INTEGER REFERENCES themes(id) ON DELETE SET NULL,
    effort INTEGER CHECK (effort BETWEEN 1 AND 5),
    value INTEGER CHECK (value BETWEEN 1 AND 5),
    rationale TEXT DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Many-to-many: items to products.
CREATE TABLE IF NOT EXISTS item_products (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, product_id)
);

-- History log: records changes to items.
CREATE TABLE IF NOT EXISTS item_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    changed_at TEXT NOT NULL DEFAULT (datetime('now')),
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_bucket ON items(bucket);
CREATE INDEX IF NOT EXISTS idx_items_theme ON items(theme_id);
CREATE INDEX IF NOT EXISTS idx_history_item ON item_history(item_id);
"""


def get_connection():
    """Open a new connection with foreign keys enabled and row factory set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor():
    """Context manager that yields a cursor and commits on success."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _column_exists(cursor, table, column):
    """Check whether a column exists on a given table."""
    rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def migrate_db():
    """Apply additive schema changes to an existing database.

    Idempotent — safe to run on every startup. Currently handles:
      - Adding the 'position' column to items (introduced after v1).
      - Adding the 'deleted_at' column to items (introduced after v2).
    """
    conn = get_connection()
    cur = conn.cursor()

    if not _column_exists(cur, "items", "position"):
        cur.execute("ALTER TABLE items ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
        # Backfill positions per bucket, preserving the existing display order
        # (theme priority then title — matches how fetch_items() previously sorted).
        buckets = [r["bucket"] for r in cur.execute(
            "SELECT DISTINCT bucket FROM items"
        ).fetchall()]
        for bucket in buckets:
            rows = cur.execute("""
                SELECT i.id FROM items i
                LEFT JOIN themes t ON i.theme_id = t.id
                WHERE i.bucket = ?
                ORDER BY COALESCE(t.priority, 999), i.title
            """, (bucket,)).fetchall()
            for pos, row in enumerate(rows):
                cur.execute("UPDATE items SET position = ? WHERE id = ?",
                            (pos, row["id"]))

    if not _column_exists(cur, "items", "deleted_at"):
        # Nullable column — existing rows stay non-deleted.
        cur.execute("ALTER TABLE items ADD COLUMN deleted_at TEXT")

    # Indexes are created here (not in SCHEMA) because columns may not have existed
    # when SCHEMA was last executed. Safe to call repeatedly.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_items_position ON items(bucket, position)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_items_deleted ON items(deleted_at)")

    conn.commit()
    conn.close()


def purge_old_deleted(days=30):
    """Hard-delete items soft-deleted more than `days` days ago.

    Called on startup and lazily before rendering the Archive page. Cheap query
    so it's fine to call frequently. Returns the number of rows purged.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM items WHERE deleted_at IS NOT NULL "
            "AND deleted_at < datetime('now', ?)",
            (f"-{int(days)} days",),
        )
        purged = cur.rowcount
        conn.commit()
        return purged
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist, then run migrations."""
    with db_cursor() as cur:
        cur.executescript(SCHEMA)
    migrate_db()


def log_change(cursor, item_id, field, old_value, new_value):
    """Record a single field change in the history table."""
    if str(old_value or "") == str(new_value or ""):
        return
    cursor.execute(
        "INSERT INTO item_history (item_id, field, old_value, new_value) "
        "VALUES (?, ?, ?, ?)",
        (item_id, field, str(old_value) if old_value is not None else None,
         str(new_value) if new_value is not None else None),
    )
