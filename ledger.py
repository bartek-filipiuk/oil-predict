"""Prediction ledger: append today's forecasts, score past ones against Orlen actuals, export summary into site/data.json.
Run after model.py. `--run morning|evening` tags the row (two crons a day)."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
from model import fixed_tax, vat

ROOT = Path(__file__).parent; DATA = ROOT / "data"; LEDGER = DATA / "predictions.csv"
FUELS = ["pb95", "pb98", "on"]
run = sys.argv[sys.argv.index("--run") + 1] if "--run" in sys.argv else "morning"

site = json.loads((ROOT / "site" / "data.json").read_text())
orlen = pd.read_csv(DATA / "orlen.csv", index_col=0, parse_dates=True)
today = pd.Timestamp.today().normalize()

# --- append today's live forecasts -----------------------------------------------------------------
rows = []
for f in FUELS:
    F = site["fuels"][f]
    rows.append({"issued": str(today.date()), "run": run, "fuel": f, "last_orlen_date": F["last_date"],
                 "last_net": F["last_net"], "pred_net": F["base_net"][0], "pred_net_h7": F["base_net"][6]})
led = pd.read_csv(LEDGER) if LEDGER.exists() else pd.DataFrame()
bt = pd.read_csv(DATA / "backtest_2026.csv")
bt["issued"] = pd.to_datetime(bt["issued"]).dt.strftime("%Y-%m-%d"); bt["last_orlen_date"] = bt["issued"]
led = pd.concat([bt, led, pd.DataFrame(rows)], ignore_index=True)
led = led.drop_duplicates(subset=["issued", "run", "fuel"], keep="last").sort_values(["issued", "fuel", "run"])
led.to_csv(LEDGER, index=False)

# --- score: actual = first Orlen price list published after the one the forecast was based on ------
def actual_after(date, fuel):
    nxt = orlen.index[orlen.index > pd.Timestamp(date)]
    return (nxt[0], float(orlen.loc[nxt[0], fuel])) if len(nxt) else (None, None)

def gross(net, date, fuel):
    d = pd.DatetimeIndex([date]); return float((net + fixed_tax(d, fuel).iloc[0]) * vat(d).iloc[0] / 1000)

scored = []
for _, r in led.iterrows():
    tdate, act = actual_after(r.last_orlen_date, r.fuel)
    if act is None: continue
    last_net = float(r.last_net) if "last_net" in r and not pd.isna(r.get("last_net")) else None
    if last_net is None:  # backtest rows: naive = price on issue date
        last_net = float(orlen.loc[pd.Timestamp(r.issued), r.fuel]) - fixed_tax([pd.Timestamp(r.issued)], r.fuel).iloc[0]
    act_net = act - fixed_tax([tdate], r.fuel).iloc[0]
    scored.append({"issued": r.issued, "run": r.run, "fuel": r.fuel, "target": str(tdate.date()),
                   "pred": gross(r.pred_net, tdate, r.fuel), "actual": gross(act_net, tdate, r.fuel), "naive": gross(last_net, tdate, r.fuel)})
sc = pd.DataFrame(scored)
sc["err"] = (sc.pred - sc.actual).abs() * 100; sc["err_naive"] = (sc.naive - sc.actual).abs() * 100
sc["hit"] = np.sign(sc.pred - sc.naive) == np.sign(sc.actual - sc.naive)
sc["flat"] = (sc.actual - sc.naive).abs() < 1e-9

out = {"fuels": {}, "recent": [], "rolling": {}}
for f in FUELS:
    d = sc[(sc.fuel == f)].sort_values("target").drop_duplicates("target", keep="last")
    last = d.iloc[-1]; w30 = d.tail(30)
    out["fuels"][f] = {"target": last.target, "pred": round(last.pred, 3), "actual": round(last.actual, 3), "naive": round(last.naive, 3),
                       "err_gr": round(last.err, 1), "hit": bool(last.hit), "flat": bool(last.flat), "run": last.run,
                       "mae30": round(float(w30.err.mean()), 1), "mae30_naive": round(float(w30.err_naive.mean()), 1),
                       "hit30": round(float(w30[~w30.flat].hit.mean()), 2) if (~w30.flat).any() else None, "n30": int(len(w30)),
                       "n_total": int(len(d)), "n_live": int((d.run != "backtest").sum())}
    out["recent"] += [{"target": r.target, "fuel": f, "pred": round(r.pred, 2), "actual": round(r.actual, 2), "naive": round(r.naive, 2),
                       "err_gr": round(r.err, 1), "hit": bool(r.hit), "flat": bool(r.flat), "run": r.run} for _, r in d.tail(10).iterrows()]
    # rolling 30-day MAE series for the chart
    roll = d.set_index("target")[["err", "err_naive"]].rolling(30, min_periods=10).mean().dropna()
    out["rolling"][f] = [[i, round(a, 1), round(b, 1)] for i, (a, b) in zip(roll.index, roll.values)]
out["recent"] = sorted(out["recent"], key=lambda r: (r["target"], r["fuel"]), reverse=True)
site["ledger"] = out
(ROOT / "site" / "data.json").write_text(json.dumps(site, ensure_ascii=False, separators=(",", ":")))
print(f"ledger: {len(led)} rows, {len(sc)} scored;", {f: (out['fuels'][f]['mae30'], out['fuels'][f]['mae30_naive'], out['fuels'][f]['hit30']) for f in FUELS})
