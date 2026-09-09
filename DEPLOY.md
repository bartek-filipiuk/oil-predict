# Deploy guide

The site is static. GitHub Actions refreshes the data twice a day and commits it; Coolify builds the Docker image
(`build.py` -> nginx) and serves it. No database, no runtime secrets.

## 1. Local run (any machine)

Requirements: Python 3.12 via [uv](https://docs.astral.sh/uv/) (`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`).

```bash
git clone git@github.com:bartek-filipiuk/oil-predict.git
cd oil-predict
uv sync                       # creates .venv with pandas, numpy, openpyxl, requests
uv run python fetch.py        # Orlen wholesale, Brent, ULSD, USD/PLN, EU Weekly Oil Bulletin -> data/*.csv
uv run python govmax.py       # Ministry of Energy max prices (CPN periods) -> data/govmax.csv
uv run python test_model.py   # fits model.py, writes site/data.json, asserts it beats the naive forecast
uv run python ledger.py --run morning
uv run python events.py       # static list without OPENROUTER_API_KEY, AI list with it
uv run python build.py        # -> dist/index.html
open dist/index.html
```

To test the AI events locally:

```bash
OPENROUTER_API_KEY=sk-or-... uv run python events.py
```

To test exactly what production serves:

```bash
docker build -t oil-predict . && docker run --rm -p 8080:80 oil-predict   # http://localhost:8080
```

## 2. Push to GitHub

Repository: `https://github.com/bartek-filipiuk/oil-predict` (create it empty on GitHub first, no README).
Public is easiest — Coolify then clones it without a deploy key.

```bash
git remote add origin git@github.com:bartek-filipiuk/oil-predict.git
git push -u origin main
```

`data/`, `site/data.json` and `site/events.json` are committed on purpose: they are the archive the bot keeps growing, the
fallback if the undocumented Orlen API ever disappears, and the input the Docker build reads. `dist/` is ignored, it is
rebuilt on every deploy.

## 3. Coolify app (once)

Instance: `https://cool.qaci.pl`. Build pack **Dockerfile**, port **80**, no env vars, no database.
Already created: project `oil-predict` (`s0kw8wco4gkcoc08o8gsksw8`), application `oil-predict`
(`l0w0sks00c484w8g4o4kcw40`), server `localhost` (65.109.60.26). The identifiers are in `.coolify.env`.
To recreate it from scratch:

Either click it in the UI (New resource -> Public repository -> paste the repo URL) or use the API:

```bash
source ~/.config/coolify/config
curl -s -X POST -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" \
  "$COOLIFY_URL/api/v1/applications/public" -d '{
    "project_uuid": "<project uuid>", "server_uuid": "'"$COOLIFY_SERVER_UUID"'",
    "environment_name": "production", "git_repository": "https://github.com/bartek-filipiuk/oil-predict",
    "git_branch": "main", "build_pack": "dockerfile", "ports_exposes": "80",
    "name": "oil-predict", "instant_deploy": false }'
```

Save the returned UUID in `.coolify.env` (gitignored):

```
COOLIFY_PROJECT_UUID=...
COOLIFY_APP_UUID=...
COOLIFY_DOMAIN=https://...
```

## 4. GitHub settings (once)

Settings -> Secrets and variables -> Actions -> New repository secret:

| Secret | Value | Needed for |
|---|---|---|
| `OPENROUTER_API_KEY` | key from https://openrouter.ai/settings/keys | AI event list; without it the page shows the static scenarios |
| `COOLIFY_URL` | `https://cool.qaci.pl` | deploy trigger at the end of each refresh |
| `COOLIFY_TOKEN` | Coolify -> Keys & Tokens -> API tokens | deploy trigger |
| `COOLIFY_APP_UUID` | UUID from step 3 | deploy trigger |

Without the three `COOLIFY_*` secrets the workflow still runs and commits data, it just prints
`Coolify secrets not set, skipping deploy`.

Also: Settings -> Actions -> General -> Workflow permissions -> **Read and write permissions** (the bot commits refreshed
CSVs back to `main`).

Leave Coolify's own git webhook / auto-deploy **off** — the workflow triggers the deploy itself, after the data commit.
A code push without a data refresh deploys on the next scheduled run, or immediately from the Deploy button in Coolify.

## 5. Domain

Currently live at `http://l0w0sks00c484w8g4o4kcw40.65.109.60.26.sslip.io`.

Until a domain is bought, use the generated sslip.io address (no DNS needed, HTTP only) — Coolify only routes traffic to
an app that has an FQDN set, so set it right after creating the app:

```bash
curl -s -X PATCH -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" \
  "$COOLIFY_URL/api/v1/applications/$COOLIFY_APP_UUID" \
  -d '{"fqdn":"http://'"$COOLIFY_APP_UUID"'.65.109.60.26.sslip.io"}'
```

When the domain is ready:

1. DNS: A record `@` (and `www` if wanted) -> `65.109.60.26`, Cloudflare proxy **off** (needed for the Let's Encrypt check).
2. Coolify -> application -> Configuration -> Domains -> `https://example.com`, save, redeploy. Certificate is automatic.
   Same thing via API: `curl -X PATCH ... "$COOLIFY_URL/api/v1/applications/$COOLIFY_APP_UUID" -d '{"fqdn":"https://example.com"}'`
3. Update `COOLIFY_DOMAIN` in `.coolify.env`.

Nothing in the code references the host, so no rebuild-and-fix pass is needed — only the two steps above.

## 6. What runs when

| Cron (UTC) | Winter (CET) | Summer (CEST) | Purpose |
|---|---|---|---|
| `0 4 * * *` | 05:00 daily | 06:00 daily | Orlen list is out: score yesterday's forecast, new forecast, AI events, publish |
| `45 18 * * 1-5` | 19:45 Mon-Fri | 20:45 Mon-Fri | Markets closed: refresh forecast with today's Brent/FX, publish |

Cron runs on UTC and does not follow daylight saving, hence the two local columns. `ledger.py` tags a run `morning`
when the UTC hour is below 12, so both crons keep their labels regardless of the season.

Each run: `fetch.py` -> `govmax.py` -> `test_model.py` -> `ledger.py` -> `events.py` -> `build.py` -> commit data -> trigger Coolify.
If `test_model.py` fails (model stops beating the naive forecast, data broken) the run stops and the previous page stays live.

## 7. Checking a run

Actions -> latest "refresh" run -> job "build":
- step "AI events" should log `events: source=ai n=...`. `source=static` means no key or OpenRouter failed (error is in the log).
- step "Ledger" logs `ledger: N rows, M scored`.
- step "Run fetch.py" logs one line per source; `orlen (MIRROR cenypaliw.fyi)` means the Orlen API was down and the fallback kicked in.
- step "Deploy to Coolify" returns the deployment UUID; the build itself is in Coolify -> application -> Deployments.

## 8. Rollback

Every run is a commit on `main`. `git revert <sha>` of a data commit and push, then redeploy — or in Coolify open an older
successful deployment and use "Redeploy" to bring that image back.
