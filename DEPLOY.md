# Deploying Seiche

## Current deployment (live since 2026-06-11)

- **Site**: https://seiche.vercel.app (Vercel project `seiche`, static deploy
  of `site/`; `seiche.mccomb.ca` attached, waiting on a GoDaddy A record
  `seiche -> 76.76.21.21`). Deploy with `cd site && vercel deploy --prod --yes`
  (must run from `site/`, not the repo root).
- **Worker**: GCE VM `buoycast`, zone `us-central1-a`, e2-micro free tier,
  IP 34.172.202.78, 4GB swap. Publishes every 10 minutes (:04, :14, ...), retrains Sundays
  09:30 UTC (systemd timers `seiche-publish` / `seiche-retrain`). Code lives in /opt/seiche;
  update by scp'ing a tarball (repo is private, the VM has no git auth).
- **Naming note**: the project rebranded buoycast -> Seiche on 2026-06-13. Two
  internal labels intentionally stay `buoycast`: the GCE instance name (immutable
  without recreating the VM) and the unix service user (renaming it risks file
  ownership and the venv). Everything user-facing and the paths/units are `seiche`.
- **Data path**: browser -> Vercel -> rewrite proxy -> Caddy on the VM at
  https://34.172.202.78.sslip.io (Let's Encrypt via sslip.io, since Vercel
  rewrites require an https origin). `site/.vercelignore` excludes
  data.json/stats.json from deploys so the proxy, not a stale static copy,
  serves them.
- **Version pin**: scikit-learn==1.8.0 everywhere; the VM loads model pickles
  trained on this machine and minor-version drift breaks unpickling.
- **Cost**: $0/month (free-tier VM, Vercel hobby, keyless APIs).

The system is two independent halves:

1. **The worker** (any small Linux VM): fetches buoy + weather data, runs the
   model, writes `site/data.json` + `site/stats.json`. Hourly publish, weekly
   retrain, all via systemd timers. No API keys, no inbound traffic required.
2. **The site** (static files in `site/`): can be served by the same VM with
   Caddy, or by Vercel/any static host reading the json cross-origin from the
   worker.

## 1. Create the VM (Google Cloud example)

```bash
gcloud compute instances create buoycast \
  --zone=us-central1-a \
  --machine-type=e2-medium \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=20GB \
  --tags=https-server,http-server
```

e2-medium (2 vCPU / 4 GB, ~$25/mo) retrains in ~15 min. e2-small (2 GB,
~$12/mo) works for hourly publishing but is tight during the weekly retrain;
add swap if you use it. Sustained-use discounts apply automatically.

## 2. Provision

```bash
gcloud compute ssh buoycast --zone=us-central1-a
sudo git clone https://github.com/de-bayes/seiche.git /opt/seiche
cd /opt/seiche/deploy && sudo bash setup_vps.sh
```

The setup script installs deps, creates a `buoycast` system user and venv,
enables the timers, and runs the initial fetch + train + publish (expect
30-60 minutes; the model trains on ~600k rows). After it finishes the
forecast self-maintains: publish at :08 every hour, full retrain Sundays
09:30 UTC, both resume on boot (`Persistent=true`).

## 3. Serve the site

**Option A, simplest: everything on the VM.**
```bash
sudo apt-get install -y caddy
sudo cp /opt/seiche/deploy/Caddyfile /etc/caddy/Caddyfile  # edit domain first
sudo systemctl reload caddy
```
Point DNS (an A record) at the VM's static IP; Caddy gets HTTPS certificates
automatically. Done: `https://yourdomain` is the dashboard, `/ml` the explainer.

**Option B: Vercel serves the site, the VM serves only the data.**
1. Keep Caddy on the VM (Option A config): its CORS headers already allow
   cross-origin reads of `/data.json` and `/stats.json`.
2. Deploy the `site/` directory to Vercel as a static project (no framework,
   output dir = `site`). Add a rewrite for `/ml` -> `/ml.html` in
   `vercel.json` if wanted.
3. In `site/index.html`, before `app.js` loads, set the data origin:
   `<script>window.DATA_BASE = "https://data.yourdomain.com";</script>`
4. The browser then loads the page from Vercel and the live json from the VM.

Option B buys Vercel's CDN for the static shell. The json itself is ~100 KB
and regenerates hourly, so honestly Option A on a $12-25 VM is the whole
product; choose B if you want the site on existing Vercel infrastructure.

**Not recommended:** committing `data.json` to git hourly to trigger Vercel
rebuilds. It works (24 deploys/day, inside free limits) but turns the repo
history into a data log.

## 4. Operations

```bash
systemctl list-timers 'seiche-*'        # next scheduled runs
journalctl -u seiche-publish -n 30      # last publish log
journalctl -u seiche-retrain -n 50      # last retrain log
sudo systemctl start seiche-publish     # force a publish now
```

Updating code: `cd /opt/seiche && sudo -u buoycast git pull`, then
`sudo systemctl start seiche-publish` to verify.

## Notes

- Every data source is keyless and free (NDBC, Open-Meteo ERA5/forecast/
  ensemble). The hourly publish makes ~40 small HTTP requests; the weekly
  retrain re-downloads the ERA5 archive (~80 MB).
- The buoy is seasonal (roughly May-November). Off season the dashboard
  shows the last observation and the model carries the forecast; nothing
  crashes, but consider pausing the VM December-March to save money.
- `models/*.joblib` are ~10 MB artifacts regenerated weekly on the VM;
  they do not need to be in git for deployment (the bootstrap trains fresh).
