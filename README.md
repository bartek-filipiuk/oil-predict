# Jutro na pylonie

Next-day and 7-day forecast of Polish pump prices (Pb95, Pb98, ON) with an event simulator. Hobby project.

## Pipeline

```
uv sync
uv run python fetch.py       # Orlen wholesale, Brent, ULSD, USD/PLN, EU Weekly Oil Bulletin -> data/*.csv
uv run python test_model.py  # fits model.py, writes site/data.json, asserts it beats the naive forecast
uv run python build.py       # -> dist/index.html (standalone, CSP) and dist/artifact.html
```

`https://paliwometr.pl/api` (same file as `/api.json`) serves the numbers the page shows: today, tomorrow and the
seven-day path per fuel in PLN/l, plus the wholesale net price, the station margin and the 30-day error. Static file,
no API.

`.github/workflows/daily.yml` runs the same steps six times a day (05:15, 08:30, 11:30, 14:30, 17:30, 20:00 UTC; the
middle four on weekdays only), commits refreshed CSVs (our own archive in case the undocumented Orlen API disappears)
and Coolify redeploys on the push. Coolify rebuilds the image from the `Dockerfile`
(`build.py` -> nginx on port 80) and serves it. `DEPLOY.md` has the full setup.

## Model

Target: next-day log change of Orlen wholesale price net of fixed taxes. Features: lags 0-4 of daily log returns of Brent
and US ULSD in PLN (lag 0 = the same day's close, or the latest intraday price when run during the session — Orlen sets
the next day's list overnight, after the close), two own lags, deviation from import parity. Plain least squares, trained 2023-2025, evaluated
out-of-sample on 2026. Retail = wholesale gross + median station margin from the last 8 weeks of the Oil Bulletin.
Event scenarios apply an empirical pass-through curve (1-7 days) to the reference product price.

Sources and 2026 event timeline: `docs/research-2026-09-09.md`.

## Ledger and events

- `ledger.py` keeps one live row per day and fuel in `data/predictions.csv` (each run overwrites it, so the last run of the
  day is the one that gets scored), scores past rows against the next Orlen price list and exports verdicts (trafione ≤ 3 gr,
  blisko ≤ 6 gr, pudło above), a 30-day rolling error and the last rows to the page. 2026 backtest rows seed the history.
- `events.py` pulls fuel/oil headlines from RSS (last 48 h), asks Gemini 3.8 Flash via OpenRouter for up to 7 dated events
  with clamped shock sizes (Brent, diesel crack, USD/PLN, domestic), and writes `site/events.json`. Without
  `OPENROUTER_API_KEY` it keeps the static scenario list.
- `govmax.py` scrapes the Ministry of Energy daily maximum retail prices (CPN periods) into `data/govmax.csv`.

## Setup

1. Push the repo to GitHub, create the Coolify app from it (Dockerfile build pack, port 80).
2. Repository secrets: `OPENROUTER_API_KEY` (AI events) plus `COOLIFY_URL`, `COOLIFY_TOKEN`, `COOLIFY_APP_UUID` (deploy trigger).
3. Actions -> refresh -> Run workflow (first run refreshes data and publishes the page).

Steps, the domain switch and rollback: `DEPLOY.md`.
