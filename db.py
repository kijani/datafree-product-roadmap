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
-- display_order controls ordering in dropdowns and pickers — items with the
-- same display_order fall back to alphabetical by name.
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 999
);

-- Roadmap items.
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    bucket TEXT NOT NULL CHECK (bucket IN ('Now', 'Next', 'Later', 'Backlog', 'Recently Done', 'Investigation', 'Hunch')),
    theme_id INTEGER REFERENCES themes(id) ON DELETE SET NULL,
    effort INTEGER CHECK (effort BETWEEN 1 AND 5),
    value INTEGER CHECK (value BETWEEN 1 AND 5),
    rationale TEXT DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    completed_at TEXT,
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


def _items_table_has_new_buckets(cursor):
    """Return True if the items table's CHECK constraint already permits
    'Investigation' and 'Hunch' buckets.
    """
    row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='items'"
    ).fetchone()
    if not row or not row["sql"]:
        return True  # No table yet — fresh install will use new schema
    sql = row["sql"]
    return "Investigation" in sql and "Hunch" in sql


def _rebuild_items_table_with_new_buckets(cursor):
    """Rebuild the items table to widen the bucket CHECK constraint.

    SQLite doesn't support altering a CHECK constraint in place, so we:
      1. Create a new table with the desired constraint
      2. Copy all rows over
      3. Drop the old table
      4. Rename the new table
      5. Recreate indexes (DROP cascade kills them)

    Foreign key references from item_products and item_history use item_id
    which retains its values, so they remain valid after the swap.
    """
    cursor.execute("""
        CREATE TABLE items_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            bucket TEXT NOT NULL CHECK (bucket IN ('Now', 'Next', 'Later', 'Backlog', 'Recently Done', 'Investigation', 'Hunch')),
            theme_id INTEGER REFERENCES themes(id) ON DELETE SET NULL,
            effort INTEGER CHECK (effort BETWEEN 1 AND 5),
            value INTEGER CHECK (value BETWEEN 1 AND 5),
            rationale TEXT DEFAULT '',
            position INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # completed_at may not exist on the old table; fall back to NULL if not.
    old_has_completed = any(
        r["name"] == "completed_at"
        for r in cursor.execute("PRAGMA table_info(items)").fetchall()
    )
    if old_has_completed:
        cursor.execute("""
            INSERT INTO items_new (id, title, bucket, theme_id, effort, value,
                                    rationale, position, deleted_at, completed_at,
                                    created_at, updated_at)
            SELECT id, title, bucket, theme_id, effort, value,
                   rationale, position, deleted_at, completed_at,
                   created_at, updated_at
            FROM items
        """)
    else:
        cursor.execute("""
            INSERT INTO items_new (id, title, bucket, theme_id, effort, value,
                                    rationale, position, deleted_at,
                                    created_at, updated_at)
            SELECT id, title, bucket, theme_id, effort, value,
                   rationale, position, deleted_at,
                   created_at, updated_at
            FROM items
        """)
    cursor.execute("DROP TABLE items")
    cursor.execute("ALTER TABLE items_new RENAME TO items")


def migrate_db():
    """Apply additive schema changes to an existing database.

    Idempotent — safe to run on every startup. Currently handles:
      - Adding the 'position' column to items (introduced after v1).
      - Adding the 'deleted_at' column to items (introduced after v2).
      - Widening the bucket CHECK constraint to allow Investigation and Hunch (v7).
      - Adding the 'completed_at' column to items (v8); backfills existing
        Recently Done items with their updated_at as the closest available signal.
      - Adding 'display_order' to products (v11); defaults to 999, set to
        canonical values by migrate_products.py.
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

    # completed_at (v8): timestamp of when an item entered 'Recently Done'.
    # Used to compute "x days ago" on the Recently Done view.
    if not _column_exists(cur, "items", "completed_at"):
        cur.execute("ALTER TABLE items ADD COLUMN completed_at TEXT")
        # Backfill: existing Recently Done items get their updated_at as the
        # best-available completion timestamp (we don't know precisely when
        # they moved into Recently Done, but updated_at is the closest signal).
        cur.execute(
            "UPDATE items SET completed_at = updated_at "
            "WHERE bucket = 'Recently Done' AND completed_at IS NULL"
        )

    # display_order on products (v11): controls ordering in dropdowns and
    # pickers. Backfilled to 999 (existing default); the migrate_products.py
    # script sets canonical values for known tag names.
    if not _column_exists(cur, "products", "display_order"):
        cur.execute("ALTER TABLE products ADD COLUMN display_order INTEGER NOT NULL DEFAULT 999")

    # Bucket constraint widening (v7): rebuild table if the old CHECK is still in place.
    if not _items_table_has_new_buckets(cur):
        _rebuild_items_table_with_new_buckets(cur)

    # Indexes are created here (not in SCHEMA) because columns may not have existed
    # when SCHEMA was last executed. Also recreated after any table rebuild.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_items_position ON items(bucket, position)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_items_deleted ON items(deleted_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_items_completed ON items(completed_at)")

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


def expire_old_completed(days=60):
    """Soft-delete Recently Done items completed more than `days` days ago.

    These age out of the active Archive view into the Bin, where they wait
    out the normal 30-day Bin window before final purge. Net effect: an item
    sits in Recently Done for 60 days, then in the Bin for 30, then is gone.
    The Bin window gives a recovery path if you realise you wanted to keep
    something around.

    Items without a completed_at timestamp are not affected (they shouldn't
    exist in Recently Done in practice, but if they do, this leaves them be
    rather than vanishing them without an age signal).

    Called lazily before rendering Archive and Bin pages. Returns the number
    of rows affected. Logs each item's transition to item_history so the
    audit trail captures the expiration.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Find items to expire first so we can log them.
        rows = cur.execute(
            "SELECT id, title FROM items "
            "WHERE bucket = 'Recently Done' "
            "  AND deleted_at IS NULL "
            "  AND completed_at IS NOT NULL "
            "  AND completed_at < datetime('now', ?)",
            (f"-{int(days)} days",),
        ).fetchall()

        for r in rows:
            cur.execute(
                "INSERT INTO item_history (item_id, field, old_value, new_value) "
                "VALUES (?, 'expired', 'Recently Done', "
                "'soft-deleted after 60 days in Recently Done')",
                (r["id"],),
            )

        cur.execute(
            "UPDATE items SET deleted_at = datetime('now') "
            "WHERE bucket = 'Recently Done' "
            "  AND deleted_at IS NULL "
            "  AND completed_at IS NOT NULL "
            "  AND completed_at < datetime('now', ?)",
            (f"-{int(days)} days",),
        )
        expired = cur.rowcount
        conn.commit()
        return expired
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
