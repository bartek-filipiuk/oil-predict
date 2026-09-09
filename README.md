# Jutro na pylonie

Next-day and 7-day forecast of Polish pump prices (Pb95, Pb98, ON) with an event simulator. Hobby project.

## Pipeline

```
uv sync
uv run python fetch.py       # Orlen wholesale, Brent, ULSD, USD/PLN, EU Weekly Oil Bulletin -> data/*.csv
uv run python test_model.py  # fits model.py, writes site/data.json, asserts it beats the naive forecast
uv run python build.py       # -> dist/index.html (standalone, CSP) and dist/artifact.html
```

`.github/workflows/daily.yml` runs the same three steps every morning, commits refreshed CSVs (our own archive in case the
undocumented Orlen API disappears) and deploys `dist/` to GitHub Pages. Enable Pages with source "GitHub Actions" once.

## Model

Target: next-day log change of Orlen wholesale price net of fixed taxes. Features: lags 0-4 of daily log returns of Brent
and US ULSD in PLN, two own lags, deviation from import parity. Plain least squares, trained 2023-2025, evaluated
out-of-sample on 2026. Retail = wholesale gross + median station margin from the last 8 weeks of the Oil Bulletin.
Event scenarios apply an empirical pass-through curve (1-7 days) to the reference product price.

Sources and 2026 event timeline: `docs/research-2026-09-09.md`.

## Ledger and events

- `ledger.py --run morning|evening` appends each forecast to `data/predictions.csv`, scores past ones against the next Orlen
  price list and exports verdicts, a 30-day rolling error and the last rows to the page. 2026 backtest rows seed the history.
- `events.py` pulls fuel/oil headlines from RSS (last 48 h), asks Gemini 3.8 Flash via OpenRouter for up to 7 dated events
  with clamped shock sizes (Brent, diesel crack, USD/PLN, domestic), and writes `site/events.json`. Without
  `OPENROUTER_API_KEY` it keeps the static scenario list.
- `govmax.py` scrapes the Ministry of Energy daily maximum retail prices (CPN periods) into `data/govmax.csv`.

## Setup on GitHub

1. Push the repo, Settings -> Pages -> Source: GitHub Actions.
2. Settings -> Secrets and variables -> Actions -> New repository secret `OPENROUTER_API_KEY`.
3. Actions -> refresh -> Run workflow (first run publishes the page).
