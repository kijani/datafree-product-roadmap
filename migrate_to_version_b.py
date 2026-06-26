"""One-off data migration: bring an existing database in line with Version B
of the roadmap doc.

Run once after installing v7 of the app code. Safe to re-run — uses titles
to detect existing items and avoid duplicates. Soft-deletes any item that
is no longer in the canonical list (so you can restore from the bin if you
disagree).

Usage:
    python migrate_to_version_b.py

Effects on a typical pre-v7 database:
  - Soft-deletes: Redirect to Paid URL, Customers to edit their own D-Direct apps,
    Connect Distributor Billing Report
  - Moves: Productisation of Push Notifications Next -> Now,
    MVNO Enablement Next -> Later
  - Inserts: 3 new Now items, 13 backlog items, 1 investigation, 1 hunch

It does NOT touch Effort or Value on existing items — those stay as you set them.
"""
import sys
from db import init_db, get_connection


# Items canonical in Version B. Each entry has the title (which we use as the
# match key), the target bucket, and seed values for items being newly inserted.
# (title, bucket, theme, effort, value, products, rationale)
CANONICAL = [
    # NOW
    ("IPAMS", "Now", "OPS", 3, 4, [],
     "IP address management system. Operational tooling for managing the IP address allocations that underpin Datafree's routing and zero-rating infrastructure."),
    ("Billing Report for Direct Customers", "Now", "FIN", 2, 4, [],
     "Reporting capability for billing direct customers — the customers Datafree bills directly rather than via a distributor. Foundational FIN reporting."),
    ("OTP Fallback as Voice", "Now", "GROW", 2, 3, ["Connect"],
     "When SMS-based OTP delivery fails, fall back to a voice channel so users still complete authentication. Improves OTP success rates in markets or scenarios where SMS is unreliable."),
    ("Productisation of Push Notifications", "Now", "GROW", 3, 3, ["Connect"],
     "Take push notifications from current state to a properly productised capability — generally available, supported, documented, sold. Enables customer engagement campaigns through Connect."),
    ("User Access Management", "Now", "OPS", 3, 4, [],
     "Manage who can access what within the Datafree platform. Operational hygiene and likely a prerequisite for customer-facing self-service."),
    ("Automatic HAR File Generation", "Now", "OPS", 2, 3, ["Reach"],
     "Automate generation of HAR files for diagnostics on Reach. Reduces manual effort and time-to-resolution for Reach-related support and integration work."),
    ("Investigate using Entri to Simplify DNS Changes", "Now", "OPS", 1, 3,
     ["D-Direct", "S-Direct"],
     "Investigation into using Entri to streamline DNS changes required for Direct (both D-Direct and S-Direct) setup. Reduces customer friction in onboarding."),
    ("Data Taxonomy Audit", "Now", "FIN", 2, 4, [],
     "Map every place the four-way data taxonomy (datafree / paid / wifi / other) is referenced across reporting, finance systems, dashboards, billing, contracts, APIs, Kafka streams, documentation. Output is a complete surface list and sizing for the migration. Prerequisite for FIN reporting to be built confidently on the new commercial model."),
    ("Per-App Usage Logging and Reporting for Connect", "Now", "GROW", 3, 4, ["Connect"],
     "Give Connect customers visibility into which apps are consuming datafree traffic, broken down by app, volume, and time period. Closes a baseline gap — customers paying for datafree consumption can see what they're paying for."),
    ("Tappable In-App Notification Messages", "Now", "GROW", 3, 3, ["Connect"],
     "Make in-app notifications actionable by allowing them to link to URLs, so customers can drive users to specific destinations via the Connect ecosystem. Turns notifications from passive FYI messages into campaign vehicles."),
    # NEXT
    ("Visibility into D-Direct Slot Availability", "Next", "GROW", 2, 3, ["D-Direct"],
     "Give customers (or internal teams) visibility into D-Direct slot availability so allocation decisions can be made without guessing. GROW item."),
    ("Billing Reports for Distributor Customers", "Next", "FIN", 2, 4, [],
     "Reporting for customers billed via distributors, complementing the Direct billing report already in Now. Extends FIN reporting coverage to the distributor channel."),
    ("Combine Reach + Switch", "Next", "OPS", 3, 4, ["Reach", "Switch"],
     "Combine the Reach and Switch products operationally. OPS item — likely about reducing operational overhead and/or simplifying the customer-facing product surface."),
    # LATER
    ("MVNO Enablement", "Later", "MVNO", 4, 5, ["MVNO"],
     "Enable MVNO partners to operate on the Datafree platform. Strategic for expanding the operator network beyond traditional MNOs. Possibly dependent on the Enablement Layer (in backlog)."),
    ("Distributor Invoicing Report", "Later", "FIN", 2, 3, [],
     "Reporting capability supporting invoicing of distributors. Continuation of the FIN reporting trajectory."),
    ("Premium Reporting Billing Report", "Later", "FIN", 2, 3, [],
     "Billing report for the Premium Reporting tier. Continuation of the FIN reporting trajectory."),
    ("AWS Marketplace Listing and Transactability", "Later", "INTL", 3, 4, [],
     "List Datafree on AWS Marketplace and enable transactions through it. INTL item — broadens commercial reach via a major procurement channel."),
    ("MNO Colocation Viability", "Later", "INTL", 2, 4, [],
     "Investigate the viability of colocating with MNOs. Strategic exploration — possibly related to the on-prem hunch in backlog."),
    # BACKLOG
    ("Report Builder", "Backlog", "GROW", 4, 4, ["Reporting"],
     "Customer-facing report composition powered by a Kafka → ClickHouse pipeline. A value-add layer on top of raw log streams, allowing customers to build their own reports rather than consuming raw data. Strategic GROW play — deepens customer relationships and creates expansion-revenue potential. Needs decomposition before sizing."),
    ("Data Optimisation / Balance-Aware Failover", "Backlog", "GROW", 4, 4, ["Switch"],
     "Use the end user's own data balance first, then fail over to the zero-rated channel when exhausted. Customer pays less in aggregate; Datafree captures a share of the saving. Likely Switch-adjacent. Gated on resolving the detection mechanism (MNO API vs. inference vs. device signal)."),
    ("Enablement Layer", "Backlog", "OPS", 5, 4, [],
     "Read/write API layer enforcing a commercial-agnostic core, with country-specific concerns (finance, pricing, portals, reporting) sitting at the country-operator level. Platform infrastructure. Strategically significant for INTL and potentially a prerequisite for MVNO Enablement. Needs shaping paired with a first concrete unlock."),
    ("Laptop VPN (Education, MTN, ERISN)", "Backlog", "GROW", 4, 4, ["Connect"],
     "VPN product extending Connect-style capability to laptops. Education-segment focus, MTN as MNO partner, ERISN as anchor customer. Strongest customer-anchored candidate so far. Slot depends on ERISN commitment level and platform scope (especially ChromeOS)."),
    ("Video Delivery within Reach", "Backlog", "GROW", 4, 3, ["Reach"],
     "Hosted video upload, transcoding, and delivery within Reach, addressing the gap that YouTube and Vimeo aren't Reach-compatible. Gated on a critical unknown: can any embeddable third-party platform (Mux, Cloudflare Stream, Bunny, api.video) be made Reach-compatible, or is build the only path?"),
    ("Wrap with Native Android Capabilities (Wrap 2.0)", "Backlog", "GROW", 4, 3, ["Wrap"],
     "Extend Wrap beyond its current bare-bones skeleton to expose more native Android functionality. Extends Wrap's depth — reduces customer attrition to native development. Strategic interaction with iOS Wrap (same team, shared architectural question on hybrid frameworks)."),
    ("Wrap for iOS — Productise the POC", "Backlog", "GROW", 4, 4, ["Wrap"],
     "Productise the iOS version of Wrap, building on a successful POC. Extends Wrap's reach — makes it a credible cross-platform mobile platform rather than an Android wrapper. Open question on App Store review risk; possible architectural interaction with Wrap-native-Android item."),
    ("Customer Traffic Anomaly Alerting", "Backlog", "OPS", 3, 3, [],
     "Real-time-ish notification of consumption spikes (viral content, unexpected campaigns) so customers can react before billing surprises. v1 shape: customer-configurable thresholds, email + Slack, batch detection. Strong retention play. Worth scoping alongside FIN reporting work."),
    ("Play Store / App Store Submission as a Service", "Backlog", "GROW", 2, 3, ["Wrap"],
     "Productise the support Datafree presumably already provides ad-hoc for customers submitting their signed Wrap apps to the Play Store. Couples naturally with iOS Wrap for the App Store side. Services-flavoured (software + process)."),
    ("Datafree Campaign Landing Pages + Wrap Sideload Hosting", "Backlog", "GROW", 3, 4, ["Wrap"],
     "Purpose-built install-flow landing pages for campaigns, with datafree-hosted APK sideload to bypass Play Store policy restrictions (betting and similar categories). Strong segment-unlock value. Combined item — landing page and sideload are one workflow."),
    ("Datafree Sideload of Connect Itself", "Backlog", "GROW", 2, 3, ["Connect"],
     "Optional sideload link added to the existing personalised Connect landing page in the workspace-user → SMS → landing page → download flow. Closes the irony of users burning data to download the data-saving app. Smaller than the customer-Wrap sideload work because end-to-end is owned by Datafree."),
    ("Reach v2 (Optimiser Rebuild)", "Backlog", "OPS", 5, 4, ["Reach"],
     "Rebuild Reach on new tech to reduce operational cost, ease maintenance, and unlock capabilities (HTTP/2, possibly HTTP/3, better instrumentation). Substrate for several other backlog items. Needs shaping paired with a specific first-unlock capability."),
    ("Wrap v2 (Optimiser Rebuild)", "Backlog", "OPS", 5, 4, ["Wrap"],
     "Rebuild Wrap on new tech, same pattern as Reach v2. Open question: do Reach v2 and Wrap v2 share underlying infrastructure (build once, two products) or are they truly independent?"),
    # INVESTIGATION
    ("Banking-Segment Product, Inline with Cloudflare", "Investigation", "GROW", None, None, [],
     "Zero-rating product for banking consumer apps, working inline with Cloudflare where banking traffic typically terminates. No technical shape yet — correctly framed as discovery-first. First phase is a learning artefact, not a build."),
    # HUNCH
    ("On-Prem MNO Deployment", "Hunch", "MVNO", None, None, [],
     "Something deployed inside the MNO's environment, possibly for usage tracking. No concrete shape yet — needs a problem statement before it can be shaped. May collapse into the Enablement Layer once articulated."),
]


def run():
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    # Ensure the "MVNO" product exists (added in this version for MVNO Enablement)
    cur.execute("INSERT OR IGNORE INTO products (name) VALUES ('MVNO')")

    canonical_titles = {row[0] for row in CANONICAL}

    # 1. Soft-delete anything in the DB that's not in the canonical set.
    rows = cur.execute(
        "SELECT id, title, bucket FROM items WHERE deleted_at IS NULL"
    ).fetchall()
    soft_deleted = []
    for row in rows:
        if row["title"] not in canonical_titles:
            cur.execute(
                "UPDATE items SET deleted_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
            cur.execute(
                "INSERT INTO item_history (item_id, field, old_value, new_value) "
                "VALUES (?, 'deleted', NULL, 'soft-deleted by migrate_to_version_b')",
                (row["id"],),
            )
            soft_deleted.append(f"{row['title']} (was {row['bucket']})")

    # 2. For each canonical item: update bucket if it exists, otherwise insert.
    moved = []
    inserted = []
    for title, bucket, theme_code, effort, value, products, rationale in CANONICAL:
        existing = cur.execute(
            "SELECT id, bucket FROM items WHERE title = ? AND deleted_at IS NULL",
            (title,),
        ).fetchone()

        if existing:
            # Item exists. Update bucket if it's changed. Don't touch E/V/rationale —
            # the user may have edited those.
            if existing["bucket"] != bucket:
                cur.execute(
                    "UPDATE items SET bucket = ?, updated_at = datetime('now') WHERE id = ?",
                    (bucket, existing["id"]),
                )
                cur.execute(
                    "INSERT INTO item_history (item_id, field, old_value, new_value) "
                    "VALUES (?, 'bucket', ?, ?)",
                    (existing["id"], existing["bucket"], bucket),
                )
                moved.append(f"{title}: {existing['bucket']} -> {bucket}")
        else:
            # Item is new — insert it with the seed values.
            theme_row = cur.execute(
                "SELECT id FROM themes WHERE code = ?", (theme_code,)
            ).fetchone()
            theme_id = theme_row["id"] if theme_row else None

            # Find next position in target bucket
            max_pos = cur.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM items "
                "WHERE bucket = ? AND deleted_at IS NULL",
                (bucket,),
            ).fetchone()[0]

            cur.execute(
                "INSERT INTO items (title, bucket, theme_id, effort, value, "
                "rationale, position) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (title, bucket, theme_id, effort, value, rationale, max_pos),
            )
            new_id = cur.lastrowid

            for prod_name in products:
                prod = cur.execute(
                    "SELECT id FROM products WHERE name = ?", (prod_name,)
                ).fetchone()
                if prod:
                    cur.execute(
                        "INSERT INTO item_products (item_id, product_id) "
                        "VALUES (?, ?)",
                        (new_id, prod["id"]),
                    )

            inserted.append(f"{title} -> {bucket}")

    conn.commit()
    conn.close()

    print("Migration to Version B complete.\n")
    if soft_deleted:
        print(f"Soft-deleted ({len(soft_deleted)} — restore from Archive if wanted):")
        for s in soft_deleted:
            print(f"  - {s}")
        print()
    if moved:
        print(f"Moved between buckets ({len(moved)}):")
        for m in moved:
            print(f"  - {m}")
        print()
    if inserted:
        print(f"Inserted ({len(inserted)}):")
        for i in inserted:
            print(f"  - {i}")
    if not (soft_deleted or moved or inserted):
        print("No changes needed — database already matches Version B.")


if __name__ == "__main__":
    run()
