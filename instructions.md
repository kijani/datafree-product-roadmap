# Running the Roadmap App

Quick reference for daily use. The project lives in Dropbox, so these instructions work across any machine you've set it up on.

---

## Start the app

Open a terminal, then:

```bash
cd ~/Dropbox/_Personal/Datafree/prototypes/product-roadmap
source .venv/bin/activate
python app.py
```

Open in browser: **http://127.0.0.1:5000**

> Use `127.0.0.1`, not `localhost` — on macOS, `localhost:5000` is hijacked by the AirPlay Receiver and returns 403.

---

## Stop the app

In the terminal where it's running:

1. Press **`Ctrl + C`** to stop the Flask server
2. (Optional) Type `deactivate` to exit the virtual environment
3. Or just close the terminal window — does both at once

Your data is saved in `roadmap.db` and persists between runs.

---

## First-time setup on a new machine

If you've synced the folder via Dropbox to a new machine, the `.venv` folder won't be there (it's ignored — see below). You'll need to recreate it once:

```bash
cd ~/Dropbox/_Personal/Datafree/prototypes/product-roadmap
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then ignore the venv from Dropbox sync (see next section), and you're ready to run the app normally.

**Do not run `python seed.py` again** — your existing `roadmap.db` is your real data. Seed is only for first-ever setup.

---

## Tell Dropbox to ignore the virtual environment

The `.venv` folder contains hundreds of small files that don't need to sync. Run this once per machine:

**macOS:**
```bash
cd ~/Dropbox/_Personal/Datafree/prototypes/product-roadmap
xattr -w com.dropbox.ignored 1 .venv
```

**Linux:**
```bash
cd ~/Dropbox/_Personal/Datafree/prototypes/product-roadmap
attr -s com.dropbox.ignored -V 1 .venv
```

**Windows (PowerShell):**
```powershell
cd "$env:USERPROFILE\Dropbox\_Personal\Datafree\prototypes\product-roadmap"
Set-Content -Path '.venv' -Stream com.dropbox.ignored -Value 1
```

**To verify it worked (macOS/Linux):**
```bash
xattr -p com.dropbox.ignored .venv
```
Should print `1`.

This is safe to run while the app is running — it only changes file metadata, not the venv contents.

---

## Other commands worth knowing

**Wipe everything and reset to seeded starter data:**
```bash
python seed.py --force
```
> Destructive — deletes all items, themes, and history. Only use if you want to start fresh.

**Export data manually:**
- Use the CSV / Markdown links in the footer of any page in the running app
- Or back up the whole database: copy `roadmap.db` somewhere safe

**Where to find things:**
- `roadmap.db` — your data (gets backed up automatically by Dropbox)
- `app.py` — Flask routes, edit to change behavior
- `templates/` — HTML, edit to change page layout
- `static/style.css` — design, edit to change colors/fonts/spacing
- `seed.py` — only used for initial setup; don't run on existing data

---

## A word of caution on multiple machines

Dropbox syncs the database file (`roadmap.db`) automatically — that's good, it acts as backup. But:

**Don't run the app on two machines at the same time** pointed at the same synced database. SQLite uses file locks, and concurrent edits across machines can corrupt the file. Use one machine at a time. If you switch machines, wait a moment for Dropbox to finish syncing before starting the app on the new one.

If something does go wrong, Dropbox keeps version history for files — right-click `roadmap.db` on dropbox.com and you can restore an earlier version.
