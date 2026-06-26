# Deploying to a server

This app is a single-process Flask + SQLite app. Cheapest and simplest hosting options first.

## Before you deploy: data handling

Your local `roadmap.db` is your sandbox. Production gets its own database, seeded once on first deploy. After that, **never re-run `seed.py` in production** — it would wipe real edits.

Workflow:
1. Develop locally, change code freely
2. Push code to the server
3. On the very first deploy: run `python seed.py` once
4. On every subsequent deploy: just restart the app; the database stays put

If you want to copy your local data to production as the starting state, upload `roadmap.db` once after first deploy (instead of running seed). Then leave it alone.

## Option 1 — Fly.io (recommended for SQLite)

Fly supports persistent volumes for SQLite. Free tier covers a small app like this.

```bash
# Install flyctl, then:
fly launch                    # answer prompts, decline Postgres
fly volumes create roadmap_data --size 1
```

Then add to `fly.toml`:

```toml
[mounts]
  source = "roadmap_data"
  destination = "/data"
```

And in `db.py`, change `DB_PATH` to `/data/roadmap.db` (or use an env var).

```bash
fly deploy
fly ssh console
python seed.py                # ONLY on first deploy
exit
```

## Option 2 — Render

Similar to Fly. Use a Web Service with a persistent disk attached at `/data`. Set `DB_PATH=/data/roadmap.db`. First deploy: open a shell, run `python seed.py`.

Add a `gunicorn` line to `requirements.txt` and use this start command:
```
gunicorn app:app
```

## Option 3 — Any small VPS (Hetzner, DigitalOcean, etc.)

The most flexible option, ~$5/month.

```bash
# On the server, as your user (not root):
git clone <your-repo>
cd roadmap
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt gunicorn
python seed.py                # only first time

# Run under systemd (see systemd unit below)
```

Example systemd unit at `/etc/systemd/system/roadmap.service`:

```ini
[Unit]
Description=Product Roadmap
After=network.target

[Service]
User=youruser
WorkingDirectory=/home/youruser/roadmap
Environment="PATH=/home/youruser/roadmap/.venv/bin"
ExecStart=/home/youruser/roadmap/.venv/bin/gunicorn -b 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now roadmap
```

Then put nginx in front for TLS:

```nginx
server {
    listen 443 ssl http2;
    server_name roadmap.yourdomain.com;
    # ssl certs via certbot

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Option 4 — PythonAnywhere

Easiest if you just want it hosted with minimal fuss. Upload files, point a Flask web app at `app.py`, run seed once in the web console.

## Backups

SQLite backups are trivial — the database is one file.

```bash
# On the server, run nightly via cron:
cp /data/roadmap.db /backups/roadmap-$(date +%Y%m%d).db
```

Or use Fly's volume snapshots, Render's disk backups, etc. For a board-level roadmap that changes weekly, even a weekly `scp` of the db file to your laptop is enough.

## Adding auth later

When you're ready:

1. Install `flask-login` or use a simple password gate via middleware
2. Hash passwords with `werkzeug.security.generate_password_hash`
3. Add a `users` table and a `login_required` decorator on routes

A bare-minimum single-password gate is ~30 lines. Open an issue with me when you want this added.
