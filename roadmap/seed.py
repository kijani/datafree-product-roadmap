"""One-time seed script for the roadmap database.

Run once on first setup of a new environment. After that, the database
is the source of truth and shouldn't be re-seeded.

Usage:
    python seed.py

Will refuse to run if the database already has data, unless you pass --force.
"""
import sys
from db import init_db, get_connection


THEMES = [
    ("GROW", "Enterprise & Vertical Growth Enablement", 1,
     "Features and capabilities that unlock new enterprise customers and vertical-specific use cases."),
    ("FIN", "Financial & Billing Foundations", 2,
     "Billing reports, invoicing, and financial visibility for direct customers and distributors."),
    ("OPS", "Platform Scalability & Operational Foundations", 3,
     "Infrastructure, access management, and internal tooling that supports scale and operational maturity."),
    ("MVNO", "MVNO-Ready Datafree Platform", 4,
     "Capabilities required to serve the MVNO market segment."),
    ("INTL", "Internationalisation", 5,
     "Features and channels supporting expansion into new geographic markets."),
]

PRODUCTS = ["Connect", "Reach", "Switch", "Wrap", "D-Direct", "S-Direct",
            "Portals and Tools", "Reporting"]

# (title, bucket, theme_code, effort, value, products, rationale)
ITEMS = [
    # NOW
    ("IPAMS", "Now", "OPS", 3, 4, [],
     "IP address management is foundational infrastructure that unblocks scale and prevents operational incidents."),
    ("Billing Report for Direct Customers", "Now", "FIN", 2, 4, [],
     "Direct customers need self-serve billing visibility to reduce support load and improve retention."),
    ("User Access Management", "Now", "OPS", 3, 4, [],
     "Role-based access is a prerequisite for enterprise customers and internal governance."),
    ("OTP Fallback as Voice", "Now", "GROW", 2, 3, ["Connect"],
     "Voice fallback closes a reliability gap that blocks enterprise adoption in low-signal contexts."),
    ("Automatic HAR File Generation", "Now", "OPS", 2, 3, ["Reach"],
     "Removes manual diagnostic work that currently slows Reach onboarding and support."),
    ("Redirect to Paid URL", "Now", "GROW", 1, 3, ["Reach"],
     "Low-effort feature that improves monetisation path for end users hitting data limits."),
    ("Customers to edit their own D-Direct apps", "Now", "GROW", 2, 4, ["D-Direct"],
     "Self-service editing removes a major support bottleneck and accelerates customer time-to-value."),
    ("Investigate using Entri to Simplify DNS Changes", "Now", "OPS", 1, 3,
     ["D-Direct", "S-Direct"],
     "Investigation-only; if viable, dramatically reduces friction for customer onboarding."),
    # NEXT
    ("Billing Reports for Distributor Customers", "Next", "FIN", 2, 4, [],
     "Mirrors direct billing reports; distributors need equivalent visibility to manage their downstream customers."),
    ("MVNO Enablement", "Next", "MVNO", 4, 5, [],
     "Core strategic capability — unlocks the MVNO market segment we've explicitly prioritised."),
    ("Productisation of Push Notifications", "Next", "GROW", 3, 3, ["Connect"],
     "Converts an existing capability into a monetisable, productised feature for Connect customers."),
    ("Combine Reach + Switch", "Next", "OPS", 3, 4, ["Reach", "Switch"],
     "Consolidating two products reduces maintenance overhead and simplifies the customer-facing portfolio."),
    ("Visibility into D-Direct Slot Availability", "Next", "GROW", 2, 3, ["D-Direct"],
     "Removes a sales bottleneck — currently a manual check that delays customer commitments."),
    # LATER
    ("Distributor Invoicing Report", "Later", "FIN", 2, 3, [],
     "Completes the distributor billing picture alongside the Next-bucket billing reports."),
    ("MNO Colocation Viability", "Later", "INTL", 2, 4, [],
     "Investigation that could unlock significant international expansion at lower infrastructure cost."),
    ("Connect Distributor Billing Report", "Later", "FIN", 2, 3, [],
     "Extends billing visibility to Connect-specific distributor relationships."),
    ("Premium Reporting Billing Report", "Later", "FIN", 2, 3, [],
     "Enables monetisation of the Premium Reporting tier we've built."),
    ("AWS Marketplace Listing and Transactability", "Later", "INTL", 3, 4, [],
     "Marketplace presence is a major channel for international and enterprise customer acquisition."),
]


def seed(force=False):
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    existing = cur.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    if existing > 0 and not force:
        print(f"Database already has {existing} items. Refusing to re-seed.")
        print("Use --force to wipe and re-seed (destructive).")
        conn.close()
        return

    if force:
        cur.execute("DELETE FROM item_history")
        cur.execute("DELETE FROM item_products")
        cur.execute("DELETE FROM items")
        cur.execute("DELETE FROM products")
        cur.execute("DELETE FROM themes")

    # Themes
    for code, name, priority, description in THEMES:
        cur.execute(
            "INSERT INTO themes (code, name, priority, description) VALUES (?, ?, ?, ?)",
            (code, name, priority, description),
        )

    # Products
    for name in PRODUCTS:
        cur.execute("INSERT INTO products (name) VALUES (?)", (name,))

    # Items + product links
    bucket_positions = {}
    for title, bucket, theme_code, effort, value, products, rationale in ITEMS:
        theme_id = cur.execute(
            "SELECT id FROM themes WHERE code = ?", (theme_code,)
        ).fetchone()[0]

        position = bucket_positions.get(bucket, 0)
        bucket_positions[bucket] = position + 1

        cur.execute(
            "INSERT INTO items (title, bucket, theme_id, effort, value, rationale, position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, bucket, theme_id, effort, value, rationale, position),
        )
        item_id = cur.lastrowid

        for prod_name in products:
            prod_id = cur.execute(
                "SELECT id FROM products WHERE name = ?", (prod_name,)
            ).fetchone()[0]
            cur.execute(
                "INSERT INTO item_products (item_id, product_id) VALUES (?, ?)",
                (item_id, prod_id),
            )

    conn.commit()
    conn.close()
    print(f"Seeded {len(THEMES)} themes, {len(PRODUCTS)} products, {len(ITEMS)} items.")


if __name__ == "__main__":
    force = "--force" in sys.argv
    seed(force=force)
