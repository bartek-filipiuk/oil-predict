# Deploy guide

The site is static. GitHub Actions rebuilds it twice a day and publishes `dist/` to GitHub Pages. Nothing else to host.

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

## 2. Push to GitHub

Repository: `https://github.com/bartek-filipiuk/oil-predict` (create it empty on GitHub first, no README).

```bash
git remote add origin git@github.com:bartek-filipiuk/oil-predict.git
git push -u origin main
```

`data/` and `site/data.json` are committed on purpose: they are the archive the bot keeps growing, and the fallback if the
undocumented Orlen API ever disappears. `dist/` is ignored, CI builds it.

## 3. GitHub settings (once)

1. **Pages**: Settings -> Pages -> Build and deployment -> Source: **GitHub Actions**. Nothing else to pick.
2. **Secret**: Settings -> Secrets and variables -> Actions -> New repository secret.
   Name `OPENROUTER_API_KEY`, value: your key from https://openrouter.ai/settings/keys.
   Optional: repository variable or edit `.github/workflows/daily.yml` to change `OPENROUTER_MODEL` (default `google/gemini-3.8-flash`).
3. **Workflow permissions**: Settings -> Actions -> General -> Workflow permissions -> "Read and write permissions"
   (the bot commits refreshed CSVs back to `main`).
4. **First run**: Actions -> "refresh" -> Run workflow -> Run. After ~2 minutes the page is at
   `https://bartek-filipiuk.github.io/oil-predict/`. The deploy job prints the URL.

## 4. What runs when

| Cron (UTC) | Local (CEST) | Purpose |
|---|---|---|
| `40 5 * * *` | 07:40 daily | Orlen list is out: score yesterday's forecast, new forecast, AI events, publish |
| `45 18 * * 1-5` | 20:45 Mon-Fri | Markets closed: refresh forecast with today's Brent/FX, publish |

Each run: `fetch.py` -> `govmax.py` -> `test_model.py` -> `ledger.py` -> `events.py` -> `build.py` -> commit data -> deploy.
If `test_model.py` fails (model stops beating the naive forecast, data broken) the run stops and the previous page stays live.

## 5. Checking a run

Actions -> latest "refresh" run -> job "build":
- step "AI events" should log `events: source=ai n=...`. `source=static` means no key or OpenRouter failed (error is in the log).
- step "Ledger" logs `ledger: N rows, M scored`.
- step "Run fetch.py" logs one line per source; `orlen (MIRROR cenypaliw.fyi)` means the Orlen API was down and the fallback kicked in.

## 6. Custom domain (optional)

Settings -> Pages -> Custom domain, add a CNAME at your DNS pointing to `bartek-filipiuk.github.io`, then commit a `CNAME`
file into `site/` and copy it in `build.py` (one line: `shutil.copy(ROOT/"site"/"CNAME", dist)`).

## 7. Rollback

Every run is a commit on `main`. `git revert <sha>` of a data commit and re-run the workflow, or re-run an older successful
workflow from the Actions tab ("Re-run all jobs") to redeploy that state.
