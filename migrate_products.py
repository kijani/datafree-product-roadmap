"""One-off data migration: consolidate the product tag list.

Run once after installing the new code. Safe to re-run — uses tag names as
identifiers and handles missing tags gracefully.

Mapping:
    Connect           -> Connect           (keep)
    D-Direct          -> Direct            (merge)
    S-Direct          -> Direct            (merge)
    MVNO              -> (removed; items untagged from MVNO only)
    Reach             -> Reach             (keep, absorbing Switch)
    Switch            -> Reach             (merge)
    Portals and Tools -> Portals & Tools   (rename)
    Reporting         -> Cross-Product Capabilities  (rename)
    Wrap              -> Wrap              (keep)

Final tag list (in display order):
    Connect, Direct, Reach, Wrap, Portals & Tools, Cross-Product Capabilities

Items that had both members of a merge pair (e.g. D-Direct AND S-Direct) will
have a single dedupe'd Direct tag after migration.

Usage:
    python migrate_products.py
"""
import sqlite3


# Display order = the order we want them to appear in the form dropdown.
# Implemented via a `display_order` column added to products by this migration.
DESIRED_ORDER = [
    "Connect",
    "Direct",
    "Reach",
    "Wrap",
    "Portals & Tools",
    "Cross-Product Capabilities",
]


def run():
    conn = sqlite3.connect("roadmap.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # --- Step 1: ensure the target tags exist (idempotent) ---
    for name in DESIRED_ORDER:
        cur.execute("INSERT OR IGNORE INTO products (name) VALUES (?)", (name,))

    # Fetch a name -> id map of all products currently in the table
    def get_id(name):
        row = cur.execute("SELECT id FROM products WHERE name = ?", (name,)).fetchone()
        return row["id"] if row else None

    # --- Step 2: rewire item_products links from old tags to new tags ---
    # Each migration step does the same dance:
    #   1. Find all (item, product) links pointing at the OLD product
    #   2. Insert equivalent links pointing at the NEW product (OR IGNORE handles
    #      the case where the item already has the new product, avoiding duplicates)
    #   3. Delete the old links
    #   4. Delete the old product row itself

    def remap(old_name, new_name):
        old_id = get_id(old_name)
        new_id = get_id(new_name)
        if old_id is None:
            return 0  # nothing to do; old tag already gone
        if new_id is None:
            # Shouldn't happen — we created the new tags above — but guard anyway.
            print(f"  ! Target tag '{new_name}' missing, skipping {old_name} migration")
            return 0
        if old_id == new_id:
            return 0  # same tag (e.g. Connect -> Connect, where the row just exists)
        # Move links
        cur.execute(
            "INSERT OR IGNORE INTO item_products (item_id, product_id) "
            "SELECT item_id, ? FROM item_products WHERE product_id = ?",
            (new_id, old_id),
        )
        cur.execute("DELETE FROM item_products WHERE product_id = ?", (old_id,))
        cur.execute("DELETE FROM products WHERE id = ?", (old_id,))
        return 1

    actions = []
    if remap("D-Direct", "Direct"):           actions.append("D-Direct -> Direct")
    if remap("S-Direct", "Direct"):           actions.append("S-Direct -> Direct")
    if remap("Switch", "Reach"):              actions.append("Switch -> Reach")
    if remap("Portals and Tools", "Portals & Tools"):
        actions.append("Portals and Tools -> Portals & Tools")
    if remap("Reporting", "Cross-Product Capabilities"):
        actions.append("Reporting -> Cross-Product Capabilities")

    # --- Step 3: remove MVNO entirely ---
    # Items currently tagged MVNO simply lose that tag (per user direction).
    mvno_id = get_id("MVNO")
    if mvno_id is not None:
        n_unlinks = cur.execute(
            "SELECT COUNT(*) FROM item_products WHERE product_id = ?", (mvno_id,)
        ).fetchone()[0]
        cur.execute("DELETE FROM item_products WHERE product_id = ?", (mvno_id,))
        cur.execute("DELETE FROM products WHERE id = ?", (mvno_id,))
        actions.append(f"MVNO removed (untagged {n_unlinks} item link(s))")

    # --- Step 4: add display_order column if missing, then set canonical order ---
    cols = [r["name"] for r in cur.execute("PRAGMA table_info(products)").fetchall()]
    if "display_order" not in cols:
        cur.execute("ALTER TABLE products ADD COLUMN display_order INTEGER NOT NULL DEFAULT 999")

    for i, name in enumerate(DESIRED_ORDER):
        cur.execute("UPDATE products SET display_order = ? WHERE name = ?", (i, name))

    conn.commit()

    # --- Step 5: report ---
    final = cur.execute(
        "SELECT name, display_order FROM products ORDER BY display_order, name"
    ).fetchall()

    print("Product tag migration complete.\n")
    if actions:
        print("Changes applied:")
        for a in actions:
            print(f"  - {a}")
        print()
    else:
        print("No changes needed — tags already match the canonical list.\n")

    print("Final tag list (in display order):")
    for r in final:
        print(f"  {r['display_order']:>3}  {r['name']}")

    conn.close()


if __name__ == "__main__":
    run()
