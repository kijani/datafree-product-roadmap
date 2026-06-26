# Update notes — v4 (readability, Themes redesign, Board legend)

## What's new

### Full contrast audit and fix-up

A systematic sweep of every text/background pairing across both themes. Outcomes:

- **Neutral greys are darker.** `ink-muted` and `ink-faint` tokens each shifted one step darker (and one step lighter in dark mode). Everything that uses them — page subtitles, table cell labels, history timestamps, hint text, column counts — is now properly legible against its background.
- **E/V chips on the Board** are no longer washed out. They now use a proper neutral background plus a darker mono number, so "E2 V3 +1" reads clearly.
- **The 2×2 scatter chart** quadrant labels (QUICK WINS, STRATEGIC BETS, FILL-IN, AVOID), axis tick marks, and grid lines all bumped to readable contrast.
- **Score column in the Table view:** the "0" value is now visible (was previously the muted grey that made it disappear).
- **Card meta font size** bumped from 12px to 13px, with bolder weight on the score number, for board readability.

### Themes tab redesigned

The inline-editing table was a constraint that compromised readability. Replaced with:

- **Display rows** showing the priority number large on the left, the theme code chip + name in a heading, the full description as prose, and a small **Edit** button on the right.
- **Edit modal** opens centered over the page. Uses native `<dialog>` so it's accessible (Escape closes, focus is trapped). The form posts to the same endpoint as before — no AJAX, consistent with the rest of the app.
- **Delete** moved inside the modal, with confirmation.
- **Add new theme** stays as an inline form below the cards.

### Board theme legend

Below the Now/Next/Later columns, a slim strip shows each theme as a pill:

- Code chip (GROW, FIN, OPS, MVNO, INTL)
- Theme name
- Count of active items in that theme

Serves as both a key for the chips on the cards and a quick at-a-glance balance check. The full coverage breakdown still lives on the Coverage page; this is the lighter version that earns its place by being visible during board work.

## How to install the update

Only CSS, two HTML templates, one Python route change, one JS file change. No database migration needed.

### Steps

1. **Stop the running app** (`Ctrl+C`)

2. **Back up your database** out of habit (no schema change in this release, but it's cheap):
   ```bash
   cd ~/Dropbox/_Personal/Datafree/prototypes/product-roadmap
   cp roadmap.db roadmap.db.backup-before-v4
   ```

3. **Replace files from the new zip:**
   - `app.py`
   - `static/style.css`
   - `templates/base.html` (unchanged from v3 but safe to overwrite)
   - `templates/kanban.html`
   - `templates/scatter.html`
   - `templates/themes.html`

4. **Start the app:**
   ```bash
   source .venv/bin/activate
   python app.py
   ```

No migration runs because the schema hasn't changed. Your data is untouched.

### Rolling back

```bash
cp roadmap.db.backup-before-v4 roadmap.db
```

Then put the old code files back. Your data is intact regardless.

## Files changed

- `app.py` — kanban route now computes per-theme counts for the legend.
- `static/style.css` — contrast tokens bumped, score chip restyled, theme card layout, modal styles, board legend styles.
- `templates/kanban.html` — added the theme legend section below the kanban columns.
- `templates/scatter.html` — Chart.js now uses `ink` / `inkMuted` for axis titles, ticks, grid, and quadrant labels.
- `templates/themes.html` — full rewrite. Display rows, native `<dialog>` modal, JSON-embedded theme data for the modal to read.

## Things deliberately not changed

- The Add-new-theme form still uses inline fields (no modal). Adding a theme is deliberate and infrequent enough that a persistent form invites the action rather than burying it.
- All form submissions still POST and reload the page (no AJAX). Consistent with the rest of the app and simpler to reason about.
- The bucket pill colors and theme accent colors stayed the same. The contrast issue was greys and chart elements, not the brand colors.
