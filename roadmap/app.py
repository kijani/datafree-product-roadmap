"""Roadmap web app.

Routes:
    /                  Kanban (Now/Next/Later)
    /table             Sortable table view
    /scatter           2x2 Effort vs Value scatter
    /coverage          Theme coverage summary
    /themes            Themes admin
    /archive           Backlog + Recently Done
    /items/new         Create item form
    /items/<id>        Edit item form
    /items/<id>/delete Delete (POST)
    /items/<id>/history View history
    /export/csv        Download CSV
    /export/markdown   Download markdown
"""
import csv
import io
import json
from datetime import datetime

from flask import (Flask, render_template, request, redirect, url_for,
                   abort, Response, flash, jsonify)

from db import init_db, get_connection, db_cursor, log_change, purge_old_deleted


app = Flask(__name__)
app.secret_key = "change-me-in-production"  # only used for flash messages

# Bucket display order
BUCKET_ORDER = ["Now", "Next", "Later"]
ARCHIVE_BUCKETS = ["Backlog", "Recently Done"]
ALL_BUCKETS = BUCKET_ORDER + ARCHIVE_BUCKETS

# Theme code -> CSS class fragment (used for color-coding in templates)
THEME_COLORS = {
    "GROW": "grow",
    "FIN": "fin",
    "OPS": "ops",
    "MVNO": "mvno",
    "INTL": "intl",
}


def fetch_items(buckets=None):
    """Return all items with theme + products joined.

    If buckets is None, returns the active roadmap (Now/Next/Later).
    """
    if buckets is None:
        buckets = BUCKET_ORDER

    placeholders = ",".join("?" * len(buckets))
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT
            i.id, i.title, i.bucket, i.effort, i.value, i.rationale, i.position,
            i.created_at, i.updated_at,
            t.code AS theme_code, t.name AS theme_name, t.priority AS theme_priority,
            GROUP_CONCAT(p.name, ', ') AS products
        FROM items i
        LEFT JOIN themes t ON i.theme_id = t.id
        LEFT JOIN item_products ip ON i.id = ip.item_id
        LEFT JOIN products p ON ip.product_id = p.id
        WHERE i.bucket IN ({placeholders})
          AND i.deleted_at IS NULL
        GROUP BY i.id
        ORDER BY
            CASE i.bucket
                WHEN 'Now' THEN 1
                WHEN 'Next' THEN 2
                WHEN 'Later' THEN 3
                WHEN 'Backlog' THEN 4
                WHEN 'Recently Done' THEN 5
            END,
            i.position, i.title
    """, buckets).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_deleted_items():
    """Return soft-deleted items, newest first, with days-remaining computed."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            i.id, i.title, i.bucket, i.effort, i.value, i.rationale,
            i.deleted_at, i.updated_at,
            t.code AS theme_code, t.name AS theme_name,
            GROUP_CONCAT(p.name, ', ') AS products,
            CAST(julianday(datetime('now')) - julianday(i.deleted_at) AS INTEGER) AS days_in_bin
        FROM items i
        LEFT JOIN themes t ON i.theme_id = t.id
        LEFT JOIN item_products ip ON i.id = ip.item_id
        LEFT JOIN products p ON ip.product_id = p.id
        WHERE i.deleted_at IS NOT NULL
        GROUP BY i.id
        ORDER BY i.deleted_at DESC
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        days_in = d.get("days_in_bin") or 0
        d["days_remaining"] = max(0, 30 - days_in)
        result.append(d)
    return result


def fetch_themes():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM themes ORDER BY priority").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_products():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_item(item_id):
    """Fetch a single item with its products as a list of IDs.

    Returns None for soft-deleted items as well as nonexistent ones —
    callers should treat deleted items as gone.
    """
    conn = get_connection()
    row = conn.execute("""
        SELECT i.*, t.code AS theme_code, t.name AS theme_name
        FROM items i
        LEFT JOIN themes t ON i.theme_id = t.id
        WHERE i.id = ? AND i.deleted_at IS NULL
    """, (item_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    item = dict(row)
    product_ids = [r["product_id"] for r in conn.execute(
        "SELECT product_id FROM item_products WHERE item_id = ?", (item_id,)
    ).fetchall()]
    item["product_ids"] = product_ids
    conn.close()
    return item


def priority_score(item):
    """Return Value - Effort, or None if either is missing."""
    if item.get("effort") is None or item.get("value") is None:
        return None
    return item["value"] - item["effort"]


# Make helpers available in all templates.
@app.context_processor
def inject_globals():
    return {
        "BUCKET_ORDER": BUCKET_ORDER,
        "ARCHIVE_BUCKETS": ARCHIVE_BUCKETS,
        "ALL_BUCKETS": ALL_BUCKETS,
        "THEME_COLORS": THEME_COLORS,
        "priority_score": priority_score,
    }


# ---------------- ROUTES ----------------

@app.route("/")
def kanban():
    items = fetch_items()
    columns = {b: [i for i in items if i["bucket"] == b] for b in BUCKET_ORDER}
    themes = fetch_themes()
    # Count active items per theme for the legend below the board
    theme_counts = {t["code"]: 0 for t in themes}
    for it in items:
        code = it.get("theme_code")
        if code in theme_counts:
            theme_counts[code] += 1
    return render_template("kanban.html", columns=columns, themes=themes,
                           theme_counts=theme_counts)


@app.route("/table")
def table():
    items = fetch_items()
    return render_template("table.html", items=items, themes=fetch_themes())


@app.route("/scatter")
def scatter():
    items = fetch_items()
    scored = [i for i in items if i["effort"] and i["value"]]
    # Data formatted for Chart.js
    bucket_data = {b: [] for b in BUCKET_ORDER}
    for it in scored:
        bucket_data[it["bucket"]].append({
            "x": it["effort"],
            "y": it["value"],
            "label": it["title"],
            "theme": it.get("theme_code", ""),
        })
    return render_template("scatter.html",
                           bucket_data_json=json.dumps(bucket_data),
                           total_scored=len(scored),
                           total_items=len(items))


@app.route("/coverage")
def coverage():
    themes = fetch_themes()
    items = fetch_items()

    # Build a grid: theme -> bucket -> [items]
    grid = []
    for t in themes:
        row = {"theme": t, "buckets": {b: [] for b in BUCKET_ORDER}, "total": 0}
        for it in items:
            if it.get("theme_code") == t["code"]:
                row["buckets"][it["bucket"]].append(it)
                row["total"] += 1
        grid.append(row)

    # Items missing a theme
    missing = [it for it in items if not it.get("theme_code")]

    return render_template("coverage.html", grid=grid, missing=missing,
                           total_items=len(items))


@app.route("/themes", methods=["GET", "POST"])
def themes_admin():
    if request.method == "POST":
        action = request.form.get("action")
        with db_cursor() as cur:
            if action == "create":
                cur.execute(
                    "INSERT INTO themes (code, name, priority, description) VALUES (?, ?, ?, ?)",
                    (request.form["code"].strip().upper(),
                     request.form["name"].strip(),
                     int(request.form["priority"]),
                     request.form.get("description", "").strip()),
                )
                flash("Theme created.")
            elif action == "update":
                theme_id = int(request.form["id"])
                cur.execute(
                    "UPDATE themes SET code = ?, name = ?, priority = ?, description = ? WHERE id = ?",
                    (request.form["code"].strip().upper(),
                     request.form["name"].strip(),
                     int(request.form["priority"]),
                     request.form.get("description", "").strip(),
                     theme_id),
                )
                flash("Theme updated.")
            elif action == "delete":
                theme_id = int(request.form["id"])
                cur.execute("DELETE FROM themes WHERE id = ?", (theme_id,))
                flash("Theme deleted. Items previously tagged with it now have no theme.")
        return redirect(url_for("themes_admin"))

    return render_template("themes.html", themes=fetch_themes())


@app.route("/archive")
def archive():
    # Lazy purge: opportunistically clean up items soft-deleted more than 30 days ago.
    purge_old_deleted(days=30)
    items = fetch_items(buckets=ARCHIVE_BUCKETS)
    columns = {b: [i for i in items if i["bucket"] == b] for b in ARCHIVE_BUCKETS}
    deleted_items = fetch_deleted_items()
    return render_template("archive.html", columns=columns,
                           deleted_items=deleted_items)


@app.route("/items/new", methods=["GET", "POST"])
def item_new():
    if request.method == "POST":
        return _save_item(item_id=None, form=request.form)
    return render_template("item_edit.html",
                           item=None,
                           themes=fetch_themes(),
                           products=fetch_products())


@app.route("/items/<int:item_id>", methods=["GET", "POST"])
def item_edit(item_id):
    item = fetch_item(item_id)
    if item is None:
        abort(404)
    if request.method == "POST":
        return _save_item(item_id=item_id, form=request.form)
    return render_template("item_edit.html",
                           item=item,
                           themes=fetch_themes(),
                           products=fetch_products())


def _save_item(item_id, form):
    """Handle create or update from a form post.

    Logs field-level changes to item_history.
    """
    title = form.get("title", "").strip()
    bucket = form.get("bucket", "").strip()
    theme_id = form.get("theme_id") or None
    if theme_id:
        theme_id = int(theme_id)
    effort = form.get("effort") or None
    value = form.get("value") or None
    if effort:
        effort = int(effort)
    if value:
        value = int(value)
    rationale = form.get("rationale", "").strip()
    product_ids = [int(p) for p in form.getlist("product_ids")]

    if not title:
        flash("Title is required.")
        return redirect(request.referrer or url_for("kanban"))
    if bucket not in ALL_BUCKETS:
        flash("Invalid bucket.")
        return redirect(request.referrer or url_for("kanban"))

    with db_cursor() as cur:
        if item_id is None:
            # New items go to the end of their bucket
            max_pos = cur.execute(
                "SELECT COALESCE(MAX(position), -1) FROM items WHERE bucket = ?",
                (bucket,)
            ).fetchone()[0]
            cur.execute("""
                INSERT INTO items (title, bucket, theme_id, effort, value, rationale, position)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (title, bucket, theme_id, effort, value, rationale, max_pos + 1))
            new_id = cur.lastrowid
            log_change(cur, new_id, "created", None, title)
            for pid in product_ids:
                cur.execute("INSERT INTO item_products (item_id, product_id) VALUES (?, ?)",
                            (new_id, pid))
            flash("Item created.")
            item_id = new_id
        else:
            # Fetch current values for diff
            old = cur.execute(
                "SELECT title, bucket, theme_id, effort, value, rationale, position FROM items WHERE id = ?",
                (item_id,)
            ).fetchone()
            if old is None:
                abort(404)
            old = dict(old)

            # If the bucket changed, move the item to the end of the new bucket
            new_position = old["position"]
            if old["bucket"] != bucket:
                max_pos = cur.execute(
                    "SELECT COALESCE(MAX(position), -1) FROM items WHERE bucket = ? AND id != ?",
                    (bucket, item_id)
                ).fetchone()[0]
                new_position = max_pos + 1

            cur.execute("""
                UPDATE items
                SET title = ?, bucket = ?, theme_id = ?, effort = ?, value = ?,
                    rationale = ?, position = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (title, bucket, theme_id, effort, value, rationale, new_position, item_id))

            log_change(cur, item_id, "title", old["title"], title)
            log_change(cur, item_id, "bucket", old["bucket"], bucket)
            log_change(cur, item_id, "theme_id", old["theme_id"], theme_id)
            log_change(cur, item_id, "effort", old["effort"], effort)
            log_change(cur, item_id, "value", old["value"], value)
            log_change(cur, item_id, "rationale", old["rationale"], rationale)

            # Sync products: simplest is delete + reinsert
            old_pids = {r["product_id"] for r in cur.execute(
                "SELECT product_id FROM item_products WHERE item_id = ?", (item_id,)
            ).fetchall()}
            new_pids = set(product_ids)
            if old_pids != new_pids:
                cur.execute("DELETE FROM item_products WHERE item_id = ?", (item_id,))
                for pid in product_ids:
                    cur.execute("INSERT INTO item_products (item_id, product_id) VALUES (?, ?)",
                                (item_id, pid))
                log_change(cur, item_id, "products",
                           ",".join(str(p) for p in sorted(old_pids)),
                           ",".join(str(p) for p in sorted(new_pids)))
            flash("Item updated.")

    return redirect(url_for("item_edit", item_id=item_id))


@app.route("/items/<int:item_id>/delete", methods=["POST"])
def item_delete(item_id):
    """Soft-delete: marks the item as deleted but keeps it in the database for 30 days.

    The item disappears from all active views but appears in the Archive page's
    'Recently deleted' section. After 30 days it's hard-deleted by purge_old_deleted().
    """
    with db_cursor() as cur:
        # Verify item exists and isn't already deleted
        existing = cur.execute(
            "SELECT title FROM items WHERE id = ? AND deleted_at IS NULL",
            (item_id,)
        ).fetchone()
        if existing is None:
            flash("Item not found.")
            return redirect(url_for("kanban"))
        cur.execute(
            "UPDATE items SET deleted_at = datetime('now') WHERE id = ?",
            (item_id,)
        )
        log_change(cur, item_id, "deleted", None, "soft-deleted")
    flash("Item moved to Recently deleted. You can restore it within 30 days.")
    return redirect(url_for("kanban"))


@app.route("/items/<int:item_id>/restore", methods=["POST"])
def item_restore(item_id):
    """Restore a soft-deleted item. Brings it back to the end of its original bucket."""
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT bucket, title FROM items WHERE id = ? AND deleted_at IS NOT NULL",
            (item_id,)
        ).fetchone()
        if row is None:
            flash("Item not found or not deleted.")
            return redirect(url_for("archive"))

        original_bucket = row["bucket"]
        # If the original bucket somehow disappeared from valid buckets, default to Now.
        if original_bucket not in ALL_BUCKETS:
            original_bucket = "Now"

        # Place at the end of the original bucket's current position list
        max_pos = cur.execute(
            "SELECT COALESCE(MAX(position), -1) FROM items "
            "WHERE bucket = ? AND deleted_at IS NULL",
            (original_bucket,)
        ).fetchone()[0]

        cur.execute(
            "UPDATE items SET deleted_at = NULL, bucket = ?, position = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (original_bucket, max_pos + 1, item_id)
        )
        log_change(cur, item_id, "restored", "soft-deleted", original_bucket)
    flash(f"Item restored to {original_bucket}.")
    return redirect(url_for("archive"))


@app.route("/items/<int:item_id>/purge", methods=["POST"])
def item_purge(item_id):
    """Permanently delete a soft-deleted item. No going back."""
    with db_cursor() as cur:
        # Only allow purging items that are already soft-deleted, as a safety check
        existing = cur.execute(
            "SELECT title FROM items WHERE id = ? AND deleted_at IS NOT NULL",
            (item_id,)
        ).fetchone()
        if existing is None:
            flash("Item not found in Recently deleted.")
            return redirect(url_for("archive"))
        cur.execute("DELETE FROM items WHERE id = ?", (item_id,))
    flash("Item permanently deleted.")
    return redirect(url_for("archive"))


@app.route("/items/reorder", methods=["POST"])
def items_reorder():
    """Receive new ordering after a drag-and-drop on the board.

    Expects JSON: {"order": [{"id": 5, "bucket": "Now", "position": 0}, ...]}

    All items present in the payload are updated. Items not present are left alone.
    Bucket changes are logged to history so the audit trail captures them.
    """
    payload = request.get_json(silent=True)
    if not payload or "order" not in payload:
        return jsonify({"error": "Missing 'order' in body"}), 400

    updates = payload["order"]
    if not isinstance(updates, list):
        return jsonify({"error": "'order' must be a list"}), 400

    valid_buckets = set(ALL_BUCKETS)
    with db_cursor() as cur:
        for entry in updates:
            try:
                item_id = int(entry["id"])
                bucket = entry["bucket"]
                position = int(entry["position"])
            except (KeyError, TypeError, ValueError):
                return jsonify({"error": f"Bad entry: {entry}"}), 400
            if bucket not in valid_buckets:
                return jsonify({"error": f"Invalid bucket: {bucket}"}), 400

            # Detect bucket change for history logging
            old = cur.execute(
                "SELECT bucket FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if old is None:
                continue
            old_bucket = old["bucket"]

            cur.execute("""
                UPDATE items
                SET bucket = ?, position = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (bucket, position, item_id))

            if old_bucket != bucket:
                log_change(cur, item_id, "bucket", old_bucket, bucket)

    return jsonify({"ok": True, "updated": len(updates)})


@app.route("/items/<int:item_id>/history")
def item_history(item_id):
    item = fetch_item(item_id)
    if item is None:
        abort(404)
    conn = get_connection()
    history = conn.execute("""
        SELECT * FROM item_history
        WHERE item_id = ?
        ORDER BY changed_at DESC, id DESC
    """, (item_id,)).fetchall()
    themes = {t["id"]: t for t in fetch_themes()}
    products = {p["id"]: p for p in fetch_products()}
    conn.close()

    # Pretty-print theme_id changes by resolving to codes
    formatted = []
    for h in history:
        h = dict(h)
        if h["field"] == "theme_id":
            h["old_value"] = themes.get(int(h["old_value"]), {}).get("code") if h["old_value"] else "—"
            h["new_value"] = themes.get(int(h["new_value"]), {}).get("code") if h["new_value"] else "—"
        elif h["field"] == "products":
            def resolve(pid_str):
                if not pid_str:
                    return "—"
                names = [products.get(int(p), {}).get("name", "?") for p in pid_str.split(",") if p]
                return ", ".join(names) if names else "—"
            h["old_value"] = resolve(h["old_value"])
            h["new_value"] = resolve(h["new_value"])
        formatted.append(h)

    return render_template("item_history.html", item=item, history=formatted)


@app.route("/export/csv")
def export_csv():
    items = fetch_items(buckets=ALL_BUCKETS)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Title", "Bucket", "Theme", "Products", "Effort", "Value",
                     "Priority Score", "Rationale", "Created", "Updated"])
    for it in items:
        score = priority_score(it)
        writer.writerow([
            it["title"], it["bucket"], it.get("theme_code", ""),
            it.get("products", "") or "",
            it.get("effort", "") or "", it.get("value", "") or "",
            score if score is not None else "",
            it["rationale"], it["created_at"], it["updated_at"],
        ])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition":
                 f"attachment; filename=roadmap-{datetime.now():%Y%m%d}.csv"},
    )


@app.route("/export/markdown")
def export_markdown():
    items = fetch_items()
    themes = fetch_themes()

    lines = [f"# Product Roadmap\n",
             f"*Exported {datetime.now():%Y-%m-%d}*\n"]

    for bucket in BUCKET_ORDER:
        bucket_items = [i for i in items if i["bucket"] == bucket]
        if not bucket_items:
            continue
        lines.append(f"\n## {bucket}\n")
        lines.append("| Item | Theme | Products | Effort | Value | Score | Rationale |")
        lines.append("|---|---|---|---|---|---|---|")
        for it in bucket_items:
            score = priority_score(it)
            score_str = f"+{score}" if score is not None and score > 0 else (str(score) if score is not None else "")
            lines.append("| {title} | {theme} | {products} | {effort} | {value} | {score} | {rationale} |".format(
                title=it["title"],
                theme=it.get("theme_code", ""),
                products=it.get("products", "") or "",
                effort=it.get("effort", "") or "",
                value=it.get("value", "") or "",
                score=score_str,
                rationale=it["rationale"].replace("|", "\\|").replace("\n", " "),
            ))

    lines.append("\n\n## Themes\n")
    lines.append("| Code | Name | Priority |")
    lines.append("|---|---|---|")
    for t in themes:
        lines.append(f"| {t['code']} | {t['name']} | {t['priority']} |")

    content = "\n".join(lines)
    return Response(
        content,
        mimetype="text/markdown",
        headers={"Content-Disposition":
                 f"attachment; filename=roadmap-{datetime.now():%Y%m%d}.md"},
    )


if __name__ == "__main__":
    init_db()
    purge_old_deleted(days=30)
    app.run(debug=True, port=5000)
