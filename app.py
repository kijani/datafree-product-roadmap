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
    /signin            Editor sign-in
    /signout           Sign out (POST)
"""
import csv
import io
import json
import os
import sys
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   abort, Response, flash, jsonify, session)

from db import init_db, get_connection, db_cursor, log_change, purge_old_deleted, expire_old_completed

# --- Load local secrets (editor password + session signing key). ---
# Refuse to start if secrets.py is missing or still has the placeholder
# values. This makes the security choice explicit rather than letting the
# app run with default credentials.
try:
    from secrets_local import EDITOR_PASSWORD, SECRET_KEY  # type: ignore
except ImportError:
    try:
        # Allow either filename: secrets_local.py (preferred — no clash with
        # Python's stdlib `secrets` module) or secrets.py (matches the
        # secrets_local.py.example template shipped in the zip).
        from secrets import EDITOR_PASSWORD, SECRET_KEY  # type: ignore
    except ImportError:
        sys.stderr.write(
            "\nERROR: secrets_local.py is missing.\n\n"
            "To set up authentication:\n"
            "  1. cp secrets_local.py.example secrets_local.py\n"
            "  2. Edit secrets_local.py and replace both placeholder values\n"
            "     with your own EDITOR_PASSWORD and SECRET_KEY.\n"
            "  3. Re-run python app.py.\n\n"
        )
        sys.exit(1)

if EDITOR_PASSWORD == "CHANGE_ME_BEFORE_STARTING" or SECRET_KEY == "CHANGE_ME_BEFORE_STARTING":
    sys.stderr.write(
        "\nERROR: secrets_local.py still has placeholder values.\n\n"
        "Edit secrets_local.py and replace both:\n"
        "  - EDITOR_PASSWORD (any password you want to use)\n"
        "  - SECRET_KEY      (a long random string — generate one with:\n"
        "                     python -c \"import secrets; print(secrets.token_hex(32))\")\n\n"
    )
    sys.exit(1)


app = Flask(__name__)
app.secret_key = SECRET_KEY
# Sessions persist 30 days. The cookie is signed with SECRET_KEY so it
# survives browser restarts. Logging out clears it explicitly.
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# App version. Follows roughly semver: MAJOR.MINOR.PATCH.
#   MAJOR — breaking changes, schema rewrites, data-model overhauls
#   MINOR — new features added without breaking existing usage
#   PATCH — small tweaks, copy edits, bug fixes
# Bump intentionally — version moves are user-visible (shown in the footer).
APP_VERSION = "2.4.0"

# Bucket display order
BUCKET_ORDER = ["Now", "Next", "Later"]
ARCHIVE_BUCKETS = ["Backlog", "Recently Done"]
INVESTIGATION_BUCKETS = ["Investigation", "Hunch"]
ALL_BUCKETS = BUCKET_ORDER + ARCHIVE_BUCKETS + INVESTIGATION_BUCKETS

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
            i.created_at, i.updated_at, i.completed_at,
            CASE
                WHEN i.completed_at IS NOT NULL THEN
                    CAST(julianday(datetime('now')) - julianday(i.completed_at) AS INTEGER)
                ELSE NULL
            END AS days_done,
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
                WHEN 'Investigation' THEN 6
                WHEN 'Hunch' THEN 7
            END,
            -- Within Recently Done, sort newest-completed first (overrides position).
            CASE WHEN i.bucket = 'Recently Done' THEN -julianday(i.completed_at) END,
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
    rows = conn.execute(
        "SELECT * FROM products ORDER BY display_order, name"
    ).fetchall()
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
    """Return Value / Effort as a ratio rounded to one decimal place.

    Replaces the older V-E subtraction. Ratios are more honest about the
    "must do regardless of effort" case (V5/E5 = 1.0, neither dismissed
    nor over-praised).

    Returns None if either Effort or Value is missing.
    """
    if item.get("effort") is None or item.get("value") is None:
        return None
    e = item["effort"]
    if e == 0:  # defensive; effort is 1-5 per the model
        return None
    return round(item["value"] / e, 1)


def priority_band(score):
    """Map a ratio score to a color band class used in templates.

    Bands (one decimal precision):
        good     >= 2.0   strong return per unit of effort
        neutral  1.0-1.9  proportional / table-stakes territory
        weak     < 1.0    cost exceeds value, worth challenging
    """
    if score is None:
        return ""
    if score >= 2.0:
        return "good"
    if score >= 1.0:
        return "neutral"
    return "weak"


# Make helpers available in all templates.
@app.context_processor
def inject_globals():
    def edit_url(item_id):
        """Build /items/<id>?from=<current path> so the edit page can return
        the user to where they came from. Falls back to the kanban if there's
        no request context (e.g. background rendering).
        """
        try:
            current = request.full_path.rstrip("?") if request.query_string else request.path
        except RuntimeError:
            current = url_for("kanban")
        return url_for("item_edit", item_id=item_id) + f"?from={current}"

    return {
        "BUCKET_ORDER": BUCKET_ORDER,
        "ARCHIVE_BUCKETS": ARCHIVE_BUCKETS,
        "INVESTIGATION_BUCKETS": INVESTIGATION_BUCKETS,
        "ALL_BUCKETS": ALL_BUCKETS,
        "THEME_COLORS": THEME_COLORS,
        "priority_score": priority_score,
        "priority_band": priority_band,
        "edit_url": edit_url,
        "APP_VERSION": APP_VERSION,
        "is_editor": is_editor(),
    }


# ---------------- AUTH ----------------

def is_editor():
    """True if the current session has been authenticated as an editor.

    Read-only check — pure session inspection, no DB hit. Safe to call from
    templates (via the context processor) and from request handlers.
    """
    return session.get("is_editor") is True


def require_editor(view_func):
    """Decorator: gate a route behind editor auth.

    For GET requests, viewers are redirected to the sign-in page with a
    `next` param so they return here after signing in. For POSTs and other
    mutating verbs, a 403 is returned — APIs and JS calls get a clean
    error response rather than an HTML redirect.
    """
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not is_editor():
            if request.method == "GET":
                return redirect(url_for("signin", next=request.path))
            # Mutating request from a non-editor — refuse outright.
            if request.is_json or request.accept_mimetypes.best == "application/json":
                return jsonify({"error": "editor login required"}), 403
            flash("Sign in as editor to do that.")
            return redirect(url_for("signin", next=request.referrer or url_for("kanban")))
        return view_func(*args, **kwargs)
    return wrapped


def safe_return_to(default_endpoint="kanban"):
    """Read a 'from' value from form or query string and validate it.

    Only allows same-site relative paths (must start with '/'). Anything else
    falls back to the default endpoint. This prevents open-redirect attacks
    where a malicious link could craft `?from=https://evil.com` and have us
    redirect there after a form post.
    """
    raw = request.form.get("from") or request.args.get("from") or ""
    # Must start with '/' (same-origin path), must NOT start with '//' (which
    # browsers treat as protocol-relative — a different origin).
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return url_for(default_endpoint)


# ---------------- ROUTES ----------------

# ----- Auth routes -----

@app.route("/signin", methods=["GET", "POST"])
def signin():
    """Editor sign-in. Anyone can browse without signing in; this just
    unlocks edit actions for the session.

    On successful sign-in we redirect to the `next` param (validated to be
    same-site) or fall back to the Board.
    """
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == EDITOR_PASSWORD:
            session["is_editor"] = True
            session.permanent = True  # 30-day cookie
            flash("Signed in as editor.")
            return redirect(safe_return_to())
        # Wrong password — re-render with an error. Don't reveal whether
        # the password is "almost right" or anything cute. Generic error.
        flash("Incorrect password.")
        return render_template("signin.html",
                               next_url=request.form.get("next", "")), 401
    # GET — show the form. `next` flows through as a hidden field.
    return render_template("signin.html",
                           next_url=request.args.get("next", ""))


@app.route("/signout", methods=["POST"])
def signout():
    """Drop editor status. Returns to whatever page the user was on."""
    session.pop("is_editor", None)
    flash("Signed out.")
    return redirect(safe_return_to())


# ----- Page routes -----

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
        if not is_editor():
            # Viewers can see themes but not modify them.
            flash("Sign in as editor to manage themes.")
            return redirect(url_for("signin", next=url_for("themes_admin")))
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
    """Archive page: Backlog (top) and Recently Done (below).

    Both sections are collapsible client-side, open by default. Recently
    Done items show 'X days ago' computed from their completed_at timestamp.
    """
    # Lazy expiration: Recently Done items completed >60 days ago move to Bin.
    expire_old_completed(days=60)
    items = fetch_items(buckets=ARCHIVE_BUCKETS)
    columns = {b: [i for i in items if i["bucket"] == b] for b in ARCHIVE_BUCKETS}
    return render_template("archive.html", columns=columns)


@app.route("/bin")
def bin_page():
    """Recently deleted items. Auto-purged after 30 days.

    Named 'bin_page' rather than 'bin' to avoid clashing with the Python
    built-in. The user-facing URL and label are both 'Bin'.
    """
    # Lazy purge: opportunistically clean up items soft-deleted more than 30 days ago.
    purge_old_deleted(days=30)
    # Also run the Recently Done expiration here so items that age out
    # appear in the Bin without needing to visit Archive first.
    expire_old_completed(days=60)
    deleted_items = fetch_deleted_items()
    return render_template("bin.html", deleted_items=deleted_items)


@app.route("/investigations")
def investigations():
    """Investigations & Hunches page — pre-roadmap exploration.

    Investigations are time-boxed work to determine whether something
    should become a roadmap candidate. Hunches are pre-investigation
    ideas that need a problem statement before they can be shaped.
    """
    items = fetch_items(buckets=INVESTIGATION_BUCKETS)
    columns = {b: [i for i in items if i["bucket"] == b] for b in INVESTIGATION_BUCKETS}
    return render_template("investigations.html", columns=columns)


@app.route("/items/new", methods=["GET", "POST"])
@require_editor
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
        # Viewers can read the edit page but not save changes.
        if not is_editor():
            flash("Sign in as editor to make changes.")
            return redirect(url_for("signin", next=request.path))
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

    # Completed date — read from form. Blank means "no completion date set" or
    # "user explicitly cleared it" depending on context (handled below).
    # Date input gives us "YYYY-MM-DD"; we store as "YYYY-MM-DD 12:00:00" so the
    # exact time isn't all 00:00:00 (which can read as "midnight = end of prior day"
    # depending on timezone display).
    completed_at_raw = form.get("completed_at", "").strip()
    if completed_at_raw:
        # Basic shape check; the input is type=date so the browser already constrains it.
        if len(completed_at_raw) == 10 and completed_at_raw[4] == '-' and completed_at_raw[7] == '-':
            completed_at_form = f"{completed_at_raw} 12:00:00"
        else:
            flash("Invalid completed date format. Date not saved.")
            completed_at_form = None
    else:
        completed_at_form = ""  # empty string = blank from form (distinct from None = unset)

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

            # Determine completed_at for the new item. The form field is hidden
            # unless bucket is "Recently Done", so:
            #   bucket != Recently Done -> always NULL
            #   bucket == Recently Done + form has date -> use it
            #   bucket == Recently Done + form blank -> stamp now()
            if bucket != "Recently Done":
                cur.execute("""
                    INSERT INTO items (title, bucket, theme_id, effort, value, rationale, position)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (title, bucket, theme_id, effort, value, rationale, max_pos + 1))
            elif completed_at_form:
                cur.execute("""
                    INSERT INTO items (title, bucket, theme_id, effort, value, rationale, position, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (title, bucket, theme_id, effort, value, rationale, max_pos + 1, completed_at_form))
            else:
                cur.execute("""
                    INSERT INTO items (title, bucket, theme_id, effort, value, rationale, position, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
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
                "SELECT title, bucket, theme_id, effort, value, rationale, position, completed_at "
                "FROM items WHERE id = ?",
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

            # Decide the new completed_at value. Since the form field is hidden
            # unless bucket is "Recently Done", we treat bucket as the source of
            # truth for whether completed_at applies:
            #   bucket != Recently Done -> completed_at must be NULL
            #   bucket == Recently Done -> use the form value, or auto-stamp
            #                              when moving in from another bucket
            old_completed = old["completed_at"]
            if bucket != "Recently Done":
                # Item isn't in Recently Done, so completed_at is irrelevant.
                # Clear it regardless of what the (hidden) form field said.
                new_completed = None
            elif completed_at_form:
                # In Recently Done with a user-provided date — use it.
                new_completed = completed_at_form
            elif old["bucket"] != "Recently Done":
                # Moving INTO Recently Done with a blank form -> auto-stamp now.
                new_completed = "AUTO_NOW"  # sentinel; handled in SQL below
            else:
                # Already in Recently Done, form was cleared by user — clear it.
                new_completed = None

            # Build SQL — completed_at handled separately because of the datetime('now') sentinel
            if new_completed == "AUTO_NOW":
                cur.execute("""
                    UPDATE items
                    SET title = ?, bucket = ?, theme_id = ?, effort = ?, value = ?,
                        rationale = ?, position = ?, updated_at = datetime('now'),
                        completed_at = datetime('now')
                    WHERE id = ?
                """, (title, bucket, theme_id, effort, value, rationale, new_position, item_id))
            else:
                cur.execute("""
                    UPDATE items
                    SET title = ?, bucket = ?, theme_id = ?, effort = ?, value = ?,
                        rationale = ?, position = ?, updated_at = datetime('now'),
                        completed_at = ?
                    WHERE id = ?
                """, (title, bucket, theme_id, effort, value, rationale, new_position, new_completed, item_id))

            log_change(cur, item_id, "title", old["title"], title)
            log_change(cur, item_id, "bucket", old["bucket"], bucket)
            log_change(cur, item_id, "theme_id", old["theme_id"], theme_id)
            log_change(cur, item_id, "effort", old["effort"], effort)
            log_change(cur, item_id, "value", old["value"], value)
            log_change(cur, item_id, "rationale", old["rationale"], rationale)
            # Log completed_at changes (excluding the auto-stamp case, which is implied
            # by the bucket change to Recently Done and would be noisy to log twice).
            if new_completed != "AUTO_NOW":
                # Compare just the date part so a same-day re-save (with auto-converted
                # 12:00:00 suffix matching a stored time) doesn't spam the history.
                old_date = (old_completed or "")[:10]
                new_date = (new_completed or "")[:10]
                if old_date != new_date:
                    log_change(cur, item_id, "completed_at", old_completed, new_completed)

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

    # Return to where the user came from (Board, Archive, Coverage, etc.).
    # The 'from' field is set by the edit template's hidden input.
    return redirect(safe_return_to())


@app.route("/items/<int:item_id>/delete", methods=["POST"])
@require_editor
def item_delete(item_id):
    """Soft-delete: marks the item as deleted but keeps it in the database for 30 days.

    The item disappears from all active views but appears in the Bin page.
    After 30 days it's hard-deleted by purge_old_deleted().
    """
    with db_cursor() as cur:
        # Verify item exists and isn't already deleted
        existing = cur.execute(
            "SELECT title FROM items WHERE id = ? AND deleted_at IS NULL",
            (item_id,)
        ).fetchone()
        if existing is None:
            flash("Item not found.")
            return redirect(safe_return_to())
        cur.execute(
            "UPDATE items SET deleted_at = datetime('now') WHERE id = ?",
            (item_id,)
        )
        log_change(cur, item_id, "deleted", None, "soft-deleted")
    flash("Item moved to Bin. You can restore it within 30 days.")
    return redirect(safe_return_to())


@app.route("/items/<int:item_id>/restore", methods=["POST"])
@require_editor
def item_restore(item_id):
    """Restore a soft-deleted item. Brings it back to the end of its original bucket."""
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT bucket, title FROM items WHERE id = ? AND deleted_at IS NOT NULL",
            (item_id,)
        ).fetchone()
        if row is None:
            flash("Item not found or not deleted.")
            return redirect(url_for("bin_page"))

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
    return redirect(url_for("bin_page"))


@app.route("/items/<int:item_id>/purge", methods=["POST"])
@require_editor
def item_purge(item_id):
    """Permanently delete a soft-deleted item. No going back."""
    with db_cursor() as cur:
        # Only allow purging items that are already soft-deleted, as a safety check
        existing = cur.execute(
            "SELECT title FROM items WHERE id = ? AND deleted_at IS NOT NULL",
            (item_id,)
        ).fetchone()
        if existing is None:
            flash("Item not found in Bin.")
            return redirect(url_for("bin_page"))
        cur.execute("DELETE FROM items WHERE id = ?", (item_id,))
    flash("Item permanently deleted.")
    return redirect(url_for("bin_page"))


@app.route("/items/reorder", methods=["POST"])
@require_editor
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

            # Detect bucket change for history logging and completed_at management
            old = cur.execute(
                "SELECT bucket FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if old is None:
                continue
            old_bucket = old["bucket"]

            # Manage completed_at when crossing the Recently Done boundary
            if old_bucket != "Recently Done" and bucket == "Recently Done":
                completed_clause = ", completed_at = datetime('now')"
            elif old_bucket == "Recently Done" and bucket != "Recently Done":
                completed_clause = ", completed_at = NULL"
            else:
                completed_clause = ""

            cur.execute(f"""
                UPDATE items
                SET bucket = ?, position = ?, updated_at = datetime('now')
                    {completed_clause}
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
            score_str = str(score) if score is not None else ""
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
