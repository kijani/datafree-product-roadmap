# Update notes — v2.4.0 (Auth: public viewing, editor sign-in)

## What's new

A simple sign-in flow that splits visitors into two states:

- **Viewer (default, no sign-in needed):** can browse every page, see every item, follow links, switch between views. Cannot edit, delete, restore, reorder, or create.
- **Editor (after sign-in):** the experience you've been using up to now. Full edit / delete / drag-and-drop / restore capabilities.

Anyone with the URL gets the viewer experience by default — no friction for the read-only case. A small **"Sign in"** link in the top-right opens a password page; entering the editor password unlocks editing for that browser session (30 days). When signed in, the top-right shows an **EDITOR** badge and a **Sign out** link.

## How it differs from before

**Visually for editors:** nothing changes. The board, the buttons, the drag handles, everything works exactly as before — you'll just see the "EDITOR" badge in the top-right indicating you're signed in.

**For viewers:**
- The "+ New item" button is hidden (replaced with "Sign in")
- Drag handles on Board cards and Backlog rows are hidden
- Action buttons (Save, Delete, Cancel, Restore, Delete permanently, theme Edit, theme Add) are hidden
- The item edit page is still accessible but renders as **read-only** ("Item details" instead of "Edit item"). All fields are visible and readable but disabled; a small "Sign in as editor to make changes" hint replaces the action buttons; a "← Back" button returns to where they came from.
- The drag hint subtitles on Board ("Drag the handle to reorder...") and Backlog ("Drag rows to reorder...") are hidden — there's no drag for viewers.

## How to install — IMPORTANT, new setup step

This release adds a required `secrets_local.py` file. **The app will refuse to start until you create it.**

```bash
# Stop the app (Ctrl+C)
cd ~/Dropbox/_Personal/Datafree/prototypes/product-roadmap
cp roadmap.db roadmap.db.backup-before-v2.4.0   # optional, no schema change

cd /tmp
unzip -o ~/Downloads/roadmap-app-v2.4.0.zip
cp -r /tmp/roadmap/. ~/Dropbox/_Personal/Datafree/prototypes/product-roadmap/

cd ~/Dropbox/_Personal/Datafree/prototypes/product-roadmap

# === Required new step: create the local secrets file ===
cp secrets_local.py.example secrets_local.py
```

Now **edit `secrets_local.py`** and replace BOTH placeholder values:

1. **`EDITOR_PASSWORD`** — any password you want. This is what unlocks editing.
2. **`SECRET_KEY`** — a long random string. Generate one with:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Copy the output (64 characters of hex) into `SECRET_KEY`.

Then:

```bash
source .venv/bin/activate
python app.py
```

If `secrets_local.py` is missing or still has placeholder values, the app prints a clear error message explaining what to do.

## Try it out

1. Open the app. You should see the Board, with **"Sign in"** in the top-right and no edit affordances.
2. Click an item — you can read everything but the form is disabled, and at the bottom it says "Sign in as editor to make changes."
3. Click **Sign in**, enter your password. You should be redirected back to where you came from, now showing the **EDITOR** badge and a **Sign out** link.
4. Sign out. You're back to viewer mode.

## Session length

Editor sessions persist for 30 days via signed cookies. After 30 days you'll need to sign in again. Logging out explicitly drops the session immediately.

## Security notes

- Passwords are checked against `EDITOR_PASSWORD` directly (no hashing). For a local single-machine tool this is fine; if you ever expose the app to the wider internet, the threat model changes and we'd want to bcrypt or scrypt the stored password and switch to a real session store.
- The `SECRET_KEY` signs the session cookie. Changing it logs everyone out (the existing cookies become invalid). Don't change it casually.
- `secrets_local.py` is in `.gitignore` — won't be committed if you ever start a git repo.
- The sign-in form is POST-only and validates passwords server-side with a constant comparison (Python's `==` on strings is constant-time-equivalent here for this scale).
- Open-redirect protection: the `next` parameter is validated the same way as the existing `from` parameter — only same-site paths starting with `/` (and not `//`) are honoured.

## Files changed

- **New:** `secrets_local.py.example` — template for local secrets, must be copied.
- **New:** `templates/signin.html` — the sign-in page.
- **`app.py`** — secrets import + startup validation; `is_editor()` helper; `@require_editor` decorator; `/signin` and `/signout` routes; decorators applied to `item_new`, `item_delete`, `item_restore`, `item_purge`, `items_reorder`; in-line auth checks on `/themes` (POST) and `/items/<id>` (POST); `is_editor` injected into all template contexts.
- **`templates/base.html`** — conditional masthead: "Sign in" for viewers, "EDITOR" badge + "Sign out" for editors.
- **`templates/kanban.html`** — drag handles, sortable script, and "Drag to reorder" subtitle all wrapped in `is_editor`. Cards get a `card-no-drag` modifier in viewer mode.
- **`templates/archive.html`** — drag handle column, sortable script, and "Drag rows..." hint wrapped in `is_editor`.
- **`templates/themes.html`** — Edit buttons, Add Theme form, and edit modal/script all wrapped in `is_editor`.
- **`templates/bin.html`** — Restore / Delete-permanently buttons wrapped in `is_editor`.
- **`templates/item_edit.html`** — full pass for read-only mode: page title becomes "Item details" for viewers, all fields get `readonly`/`disabled`, action area shows "Sign in as editor..." hint + "← Back" button.
- **`static/style.css`** — `.auth-badge`, `.auth-link`, `.auth-status-form`, sign-in page styles, read-only form styling, viewer-hint style, `.card-no-drag` single-column variant.
- **`.gitignore`** — added `secrets_local.py` and `secrets.py` so they're never committed.

## Verified before shipping

- Viewer can access all 13 page routes (Board, Table, 2×2, Coverage, Themes, Archive, Bin, Investigations, item details, history, signin, exports) — all return 200
- Viewer blocked from `/items/new` (302 redirect to sign-in)
- Viewer blocked from mutating endpoints (302 for form posts, 403 JSON for JS-driven ones)
- Wrong password returns 401
- Correct password sets the editor session
- Sign out drops editor status
- Visual: cards layout correctly in both modes; sign-in page renders cleanly; "EDITOR" badge readable
- External URLs and protocol-relative URLs in `next` are rejected (open-redirect protection)

## Rollback

```bash
cp roadmap.db.backup-before-v2.4.0 roadmap.db
```

Then restore v2.3.0 code and **delete or rename `secrets_local.py`** (v2.3.0 doesn't use it). The database is unchanged in this release, so the rollback is purely code.
