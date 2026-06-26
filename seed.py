"""One-time seed script for the roadmap database.

Run once on first setup of a new environment. After that, the database
is the source of truth and shouldn't be re-seeded.

Usage:
    python seed.py
    python seed.py --force   # wipe and re-seed (destructive)

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

# Canonical product/tool tags. List order = display order in dropdowns.
# Convention: core products first (Connect, Direct, Reach, Wrap), then
# cross-cutting categories (Portals & Tools, Cross-Product Capabilities).
PRODUCTS = [
    "Connect",
    "Direct",
    "Reach",
    "Wrap",
    "Portals & Tools",
    "Cross-Product Capabilities",
]

# (title, bucket, theme_code, effort, value, products, rationale)
# Aligns with Version B of the roadmap doc:
#   Now=10, Next=3, Later=5, Backlog=13, Investigation=1, Hunch=1
# Effort/Value defaults are conservative for newly-added items — adjust in-app.
ITEMS = [
    # ====== NOW (10) ======
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
     ["Direct"],
     "Investigation into using Entri to streamline DNS changes required for Direct (both D-Direct and S-Direct) setup. Reduces customer friction in onboarding."),
    ("Data Taxonomy Audit", "Now", "FIN", 2, 4, [],
     "Map every place the four-way data taxonomy (datafree / paid / wifi / other) is referenced across reporting, finance systems, dashboards, billing, contracts, APIs, Kafka streams, documentation. Output is a complete surface list and sizing for the migration. Prerequisite for FIN reporting to be built confidently on the new commercial model."),
    ("Per-App Usage Logging and Reporting for Connect", "Now", "GROW", 3, 4, ["Connect"],
     "Give Connect customers visibility into which apps are consuming datafree traffic, broken down by app, volume, and time period. Closes a baseline gap — customers paying for datafree consumption can see what they're paying for."),
    ("Tappable In-App Notification Messages", "Now", "GROW", 3, 3, ["Connect"],
     "Make in-app notifications actionable by allowing them to link to URLs, so customers can drive users to specific destinations via the Connect ecosystem. Turns notifications from passive FYI messages into campaign vehicles."),

    # ====== NEXT (3) ======
    ("Visibility into D-Direct Slot Availability", "Next", "GROW", 2, 3, ["Direct"],
     "Give customers (or internal teams) visibility into D-Direct slot availability so allocation decisions can be made without guessing. GROW item."),
    ("Billing Reports for Distributor Customers", "Next", "FIN", 2, 4, [],
     "Reporting for customers billed via distributors, complementing the Direct billing report already in Now. Extends FIN reporting coverage to the distributor channel."),
    ("Combine Reach + Switch", "Next", "OPS", 3, 4, ["Reach"],
     "Combine the Reach and Switch products operationally. OPS item — likely about reducing operational overhead and/or simplifying the customer-facing product surface."),

    # ====== LATER (5) ======
    ("MVNO Enablement", "Later", "MVNO", 4, 5, [],
     "Enable MVNO partners to operate on the Datafree platform. Strategic for expanding the operator network beyond traditional MNOs. Possibly dependent on the Enablement Layer (in backlog)."),
    ("Distributor Invoicing Report", "Later", "FIN", 2, 3, [],
     "Reporting capability supporting invoicing of distributors. Continuation of the FIN reporting trajectory."),
    ("Premium Reporting Billing Report", "Later", "FIN", 2, 3, [],
     "Billing report for the Premium Reporting tier. Continuation of the FIN reporting trajectory."),
    ("AWS Marketplace Listing and Transactability", "Later", "INTL", 3, 4, [],
     "List Datafree on AWS Marketplace and enable transactions through it. INTL item — broadens commercial reach via a major procurement channel."),
    ("MNO Colocation Viability", "Later", "INTL", 2, 4, [],
     "Investigate the viability of colocating with MNOs. Strategic exploration — possibly related to the on-prem hunch in backlog."),

    # ====== BACKLOG (13) ======
    ("Report Builder", "Backlog", "GROW", 4, 4, ["Cross-Product Capabilities"],
     "Customer-facing report composition powered by a Kafka → ClickHouse pipeline. A value-add layer on top of raw log streams, allowing customers to build their own reports rather than consuming raw data. Strategic GROW play — deepens customer relationships and creates expansion-revenue potential. Needs decomposition before sizing."),
    ("Data Optimisation / Balance-Aware Failover", "Backlog", "GROW", 4, 4, ["Reach"],
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

    # ====== INVESTIGATION (1) ======
    ("Banking-Segment Product, Inline with Cloudflare", "Investigation", "GROW", None, None, [],
     "Zero-rating product for banking consumer apps, working inline with Cloudflare where banking traffic typically terminates. No technical shape yet — correctly framed as discovery-first. First phase is a learning artefact, not a build."),

    # ====== HUNCH (1) ======
    ("On-Prem MNO Deployment", "Hunch", "MVNO", None, None, [],
     "Something deployed inside the MNO's environment, possibly for usage tracking. No concrete shape yet — needs a problem statement before it can be shaped. May collapse into the Enablement Layer once articulated."),
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

    # Products — list index is the display_order, so the order in PRODUCTS
    # above is preserved in dropdowns and pickers.
    for order, name in enumerate(PRODUCTS):
        cur.execute(
            "INSERT INTO products (name, display_order) VALUES (?, ?)",
            (name, order),
        )

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
