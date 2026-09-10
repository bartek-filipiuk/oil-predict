"""Fit next-day wholesale model per fuel, evaluate out-of-sample on 2026, dump site data JSON."""
import json
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).parent; DATA = ROOT / "data"
FUELS = ["pb95", "pb98", "on"]
LAGS = 5            # lags 0..4 of market returns
RIDGE = 1e-6   # ponytail: near-OLS; 13 features on ~700 obs needs no real shrinkage
TEST_FROM = "2026-01-01"

# --- fixed tax components, PLN/m3 net (excise + fuel charge + emission charge) -------------------
# ponytail: 2023-2025 fuel charge approximated with 2025 values; only step days matter for daily diffs.
def fixed_tax(dates, fuel):
    d = pd.DatetimeIndex(dates)
    excise = np.where(fuel == "on", 1160.0, 1529.0)
    cut = (d >= "2026-03-28") & (d <= "2026-06-15")
    excise = np.where(cut, excise - (280 if fuel == "on" else 290), excise)
    charge = np.where(d >= "2026-01-01", 453.52 if fuel == "on" else 210.29, 436.07 if fuel == "on" else 202.20)
    return pd.Series(excise + charge + 80.0, index=d)

def vat(dates):
    d = pd.DatetimeIndex(dates)
    # CPN I: 31 Mar - 30 Jun 2026; CPN II: 17 - 31 Aug 2026 (VAT only, excise not cut). Source: Dz.U. 2026 poz. 771 and 1095.
    low = ((d >= "2026-03-31") & (d <= "2026-06-30")) | ((d >= "2026-08-17") & (d <= "2026-08-31"))
    return pd.Series(np.where(low, 1.08, 1.23), index=d)

# --- data ------------------------------------------------------------------------------------------
def load():
    rd = lambda n: pd.read_csv(DATA / f"{n}.csv", index_col=0, parse_dates=True).iloc[:, 0]
    orlen = pd.read_csv(DATA / "orlen.csv", index_col=0, parse_dates=True)
    mkt = pd.concat({"brent": rd("brent"), "ulsd": rd("ulsd"), "usdpln": rd("usdpln")}, axis=1).ffill()
    # Orlen publishes the list for day t+1 overnight (not in the API at 23:00 of day t, there by 05:00 of t+1), i.e.
    # after day t's close. So the row for day t carries day t's close, and the last row carries the latest intraday
    # price when the pipeline runs during the session: the next-day forecast is a nowcast that firms up through the day.
    # Aligning to the previous close instead (the original choice) costs ~0.7 gr/l MAE on Pb95 and ~1.3 on ON in the
    # 2026 backtest and drops direction hits from ~61% to ~72%.
    idx = orlen.index
    mkt = mkt.reindex(idx.union(mkt.index)).ffill().reindex(idx).ffill()
    df = orlen.join(mkt).dropna()
    df["brent_pln"] = df.brent * df.usdpln
    df["ulsd_pln"] = df.ulsd * df.usdpln * 1000 / 3.785  # USD/gal -> PLN/m3
    return df

def features(df, fuel):
    net = df[fuel] - fixed_tax(df.index, fuel)
    lw = np.log(net)
    X = {}
    rb, ru = np.log(df.brent_pln).diff(), np.log(df.ulsd_pln).diff()
    for k in range(LAGS):
        X[f"rb{k}"] = rb.shift(k); X[f"ru{k}"] = ru.shift(k)
    X["dw1"], X["dw2"] = lw.diff().shift(0), lw.diff().shift(1)
    ref = np.log(df.ulsd_pln if fuel == "on" else df.brent_pln)
    X["gap"] = lw - ref                      # deviation from import parity (intercept absorbs the mean)
    X["const"] = 1.0
    X = pd.DataFrame(X)
    y = lw.shift(-1) - lw                    # next-day log change of tax-free wholesale
    return X, y, net

def base_forecast(beta, last_feat, last_net, horizon=7):
    """Recursive next-day model with zero future market returns -> list of net wholesale for h=1..horizon."""
    f = dict(last_feat); net = float(last_net); out = []
    for _ in range(horizon):
        pred = sum(beta[k] * f.get(k, 0.0) for k in beta)
        for k in range(LAGS - 1, 0, -1):
            f[f"rb{k}"] = f[f"rb{k-1}"]; f[f"ru{k}"] = f[f"ru{k-1}"]
        f["rb0"] = f["ru0"] = 0.0; f["dw2"] = f["dw1"]; f["dw1"] = pred; f["gap"] += pred
        net *= np.exp(pred); out.append(net)
    return out

def fit(X, y):
    A = X.values; I = np.eye(A.shape[1]); I[-1, -1] = 0
    return pd.Series(np.linalg.solve(A.T @ A + RIDGE * len(A) * I, A.T @ y.values), index=X.columns)

def main():
    df = load(); out = {"fuels": {}, "meta": {}}; backtests = []
    for fuel in FUELS:
        X, y, net = features(df, fuel)
        ok = X.notna().all(axis=1) & y.notna()
        train = ok & (X.index < TEST_FROM); test = ok & (X.index >= TEST_FROM)
        beta = fit(X[train], y[train])
        pred = X[test] @ beta
        gross = lambda n, d: (n + fixed_tax(d, fuel).values) * vat(d).values / 1000   # PLN/l retail-comparable
        # out-of-sample next-day error in gr/l on gross wholesale
        d_next = X.index[test] + pd.Timedelta(days=1)
        actual_next = net.shift(-1)[test]
        model_next = net[test] * np.exp(pred)
        naive_next = net[test]
        mae = lambda a: float(np.mean(np.abs(gross(a.values, d_next) - gross(actual_next.values, d_next))) * 100)
        hit = float(np.mean(np.sign(pred) == np.sign(y[test])))
        # refit on everything for live forecast
        beta_all = fit(X[ok], y[ok])
        last = X.iloc[-1]
        base = base_forecast(beta_all.to_dict(), last.to_dict(), net.iloc[-1])
        # true out-of-sample next-day predictions for 2026 (coefficients fitted through 2025) -> ledger backfill
        bt = pd.DataFrame({"issued": X.index[test], "fuel": fuel, "pred_net": (net[test] * np.exp(pred)).values, "run": "backtest"})
        backtests.append(bt)
        # empirical pass-through of h-day market move into tax-free wholesale (used for event scenarios)
        ref = np.log(df.ulsd_pln if fuel == "on" else df.brent_pln); lnet = np.log(net)
        pt = []
        for h in range(1, 8):
            dy, dx = lnet.diff(h).shift(-h), ref.diff(h).shift(-h); mm = dy.notna() & dx.notna()
            pt.append(round(float(np.polyfit(dx[mm], dy[mm], 1)[0]), 3))
        out["fuels"][fuel] = {
            "beta": {k: round(float(v), 6) for k, v in beta_all.items()},
            "passthrough": pt,
            "base_net": [round(v, 2) for v in base],
            "last_date": str(X.index[-1].date()),
            "last_net": round(float(net.iloc[-1]), 2),
            "last_gross": round(float(gross(np.array([net.iloc[-1]]), [X.index[-1]])[0]), 3),
            "last_features": {k: round(float(v), 6) for k, v in last.items()},
            "eval": {"mae_model_gr": round(mae(model_next), 2), "mae_naive_gr": round(mae(naive_next), 2),
                     "hit_rate": round(hit, 3), "n_test": int(test.sum())},
            "history": [[str(d.date()), round(float(v), 3)] for d, v in
                        zip(df.index[df.index >= "2025-09-01"], gross(net[df.index >= "2025-09-01"].values, df.index[df.index >= "2025-09-01"]))],
        }
        print(f"{fuel}: n_test={test.sum()} MAE model {mae(model_next):.2f} gr/l vs naive {mae(naive_next):.2f} gr/l, hit {hit:.2%}")
        print("  beta:", beta_all.round(3).to_dict())
    # retail margin: weekly WOB retail (Mon) minus gross wholesale same day
    wob = pd.read_csv(DATA / "retail_weekly.csv", index_col=0, parse_dates=True)
    margins = {}
    for fuel in ["pb95", "on"]:
        X, y, net = features(df, fuel)
        g = pd.Series((net + fixed_tax(df.index, fuel)) * vat(df.index) / 1000, index=df.index)
        m = (wob[f"{fuel}_retail"] - g.reindex(wob.index, method="ffill")).dropna()
        m = m[m > -0.10]   # guard against broken bulletin rows (retail below wholesale gross)
        margins[fuel] = {"current": round(float(m.iloc[-8:].median()), 3), "current_date": str(m.index[-1].date()), "longrun": round(float(m[m.index >= "2024-01-01"].median()), 3),
                         "series": [[str(d.date()), round(float(v), 3)] for d, v in m[m.index >= "2025-09-01"].items()],
                         "retail": [[str(df.index[df.index.get_indexer([d], method="nearest")[0]].date()), round(float(v), 3)]
                                    for d, v in wob[f"{fuel}_retail"][(wob.index >= "2025-09-01") & wob.index.isin(m.index)].items()]}
        print(f"margin {fuel}: last4w {margins[fuel]['current']:.3f} zl/l, longrun {margins[fuel]['longrun']:.3f}")
    margins["pb98"] = {**margins["pb95"], "series": [], "retail": []}
    out["margins"] = margins
    m = df.index >= "2025-09-01"
    out["market"] = {"brent": [[str(d.date()), round(float(v), 2)] for d, v in df.brent[m].items()],
                     "usdpln": [[str(d.date()), round(float(v), 4)] for d, v in df.usdpln[m].items()],
                     "ulsd_pln": [[str(d.date()), round(float(v), 0)] for d, v in df.ulsd_pln[m].items()],
                     "last": {"brent": round(float(df.brent.iloc[-1]), 2), "usdpln": round(float(df.usdpln.iloc[-1]), 4), "ulsd": round(float(df.ulsd.iloc[-1]), 3)}}
    gm = DATA / "govmax.csv"
    if gm.exists():
        g = pd.read_csv(gm, index_col=0, parse_dates=True); g = g[g.index >= "2025-09-01"]
        out["market"]["govmax"] = {f: [[str(d.date()), float(v)] for d, v in g[f"{f}_max"].items()] for f in ["pb95", "pb98", "on"]}
    out["meta"] = {"generated": str(pd.Timestamp.today().date()), "lags": LAGS, "train_from": str(df.index[0].date()), "test_from": TEST_FROM,
                   "tax": {"excise": {"pb95": 1529, "pb98": 1529, "on": 1160}, "charge": {"pb95": 210.29, "pb98": 210.29, "on": 453.52}, "emission": 80, "vat": 1.23},
                   "regime_now": {"vat": float(vat([df.index[-1]]).iloc[0]), "excise_cut": bool(fixed_tax([df.index[-1]], "pb95").iloc[0] < 1529 + 210.29 + 80)}}
    pd.concat(backtests).to_csv(DATA / "backtest_2026.csv", index=False)
    (ROOT / "site").mkdir(exist_ok=True)
    (ROOT / "site" / "data.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print("wrote site/data.json", (ROOT / "site" / "data.json").stat().st_size // 1024, "KB")

if __name__ == "__main__":
    main()
