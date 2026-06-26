# Product Roadmap

A lightweight strategic roadmap app. Now / Next / Later board, themes, Effort × Value scoring, scatter plot, change history, CSV/markdown export.

Built with Flask + SQLite. One process, one database file, no external services.

## Quick start (local)

```bash
# 1. Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Seed the database with starter data (18 items, 5 themes)
python seed.py

# 4. Run the app
python app.py
```

Open <http://localhost:5000> in your browser.

## File layout

```
roadmap/
├── app.py              # Flask app, all routes
├── db.py               # SQLite schema and connection helpers
├── seed.py             # One-time seed script
├── requirements.txt
├── roadmap.db          # Created on first run (gitignored)
├── static/
│   └── style.css       # All styling
└── templates/
    ├── base.html       # Shared layout
    ├── kanban.html     # /
    ├── table.html      # /table
    ├── scatter.html    # /scatter (2×2)
    ├── coverage.html   # /coverage
    ├── themes.html     # /themes
    ├── archive.html    # /archive
    ├── item_edit.html  # /items/new and /items/<id>
    └── item_history.html
```

## What's where

- **Board** (`/`) — kanban view, Now / Next / Later, click any card to edit
- **Table** (`/table`) — all items in a sortable list
- **2×2** (`/scatter`) — Effort × Value scatter chart, colored by bucket
- **Coverage** (`/coverage`) — theme × bucket matrix, surfaces gaps
- **Themes** (`/themes`) — manage the five strategic themes
- **Archive** (`/archive`) — Backlog and Recently Done, kept separate from the strategic view
- **Export** — CSV and Markdown links in the footer of every page

## CRUD

- **Items** — create via "+ New item" in the top right; edit by clicking any card or table row; delete from the edit form
- **Themes** — inline editing on `/themes`; add new ones via the form below
- **Product/Tool tags** — currently seeded; add new ones by editing `seed.py` and re-running with `--force`, or via the database directly (a UI for this can be added if it becomes useful)

## Change history

Every edit to an item is logged to the `item_history` table. View per item via the "history" link on the edit form. Logged fields: title, bucket, theme, effort, value, rationale, products.

## Export

- **CSV** — full export of all items including archive
- **Markdown** — formatted as a roadmap document, suitable for board packs (only Now/Next/Later)

## Resetting

```bash
rm roadmap.db
python seed.py
```

## Production

See `DEPLOY.md`.
