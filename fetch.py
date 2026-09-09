"""Fetch raw series into data/*.csv. Idempotent; re-run daily."""
import io, json, sys, time
from pathlib import Path
import pandas as pd, requests

DATA = Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36",
      "Accept": "application/json, text/plain, */*"}
START = "2023-01-01"
TODAY = pd.Timestamp.today().strftime("%Y-%m-%d")

def get(url, **kw):
    for i in range(3):
        r = requests.get(url, headers=UA, timeout=30, **kw)
        if r.ok and "Request Rejected" not in r.text[:500]:
            return r
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url} -> {r.status_code}: {r.text[:200]}")

def orlen_mirror():
    """ponytail: fallback when tool.orlen.pl is down; cenypaliw.fyi mirrors the same series (PLN/l net) since 2020."""
    d = get("https://cenypaliw.fyi/api/chart-data.json").json()["series"]
    frames = []
    for key, name in {"PB 95": "pb95", "PB 98": "pb98", "ON": "on"}.items():
        s = pd.Series({pd.Timestamp(ts, unit="ms").normalize(): v * 1000 for ts, v in d[key]}, name=name)
        frames.append(s[~s.index.duplicated(keep="last")])
    out = pd.concat(frames, axis=1).sort_index(); out = out[out.index >= START]
    out.to_csv(DATA / "orlen.csv"); print("orlen (MIRROR cenypaliw.fyi)", out.shape, out.index.max().date())

def orlen():
    frames = []
    for pid, name in {41: "pb95", 42: "pb98", 43: "on"}.items():
        r = get(f"https://tool.orlen.pl/api/wholesalefuelprices/ByProduct?productId={pid}&from={START}&to={TODAY}")
        df = pd.DataFrame(r.json())
        df["date"] = pd.to_datetime(df["effectiveDate"]).dt.normalize()
        frames.append(df.groupby("date")["value"].last().rename(name))
    out = pd.concat(frames, axis=1).sort_index()  # PLN/m3 net
    out.to_csv(DATA / "orlen.csv"); print("orlen", out.shape, out.index.min().date(), out.index.max().date())

def yahoo(symbol, name, fred=None):
    # ponytail: Yahoo 429s on long UA / Accept:json; plain "Mozilla/5.0" + range works. FRED (1 week lag) as fallback.
    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=4y&interval=1d",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30); r.raise_for_status()
    except Exception as e:
        if not fred: raise
        print("yahoo failed, FRED fallback:", e, file=sys.stderr)
        s = pd.read_csv(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred}&cosd={START}", index_col=0, parse_dates=True).iloc[:, 0]
        s = pd.to_numeric(s, errors="coerce").dropna().rename(name)
        s.to_csv(DATA / f"{name}.csv"); print(name, "(FRED)", len(s), s.index.max().date()); return
    res = r.json()["chart"]["result"][0]
    s = pd.Series(res["indicators"]["quote"][0]["close"],
                  index=pd.to_datetime(res["timestamp"], unit="s").normalize(), name=name).dropna()
    s = s.groupby(level=0).last(); s = s[s.index >= START]
    s.to_csv(DATA / f"{name}.csv"); print(name, len(s), s.index.min().date(), s.index.max().date(), round(s.iloc[-1], 3))

def nbp():
    parts = []
    for a, b in [("2023-01-01", "2023-12-31"), ("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31"), ("2026-01-01", TODAY)]:
        r = get(f"https://api.nbp.pl/api/exchangerates/rates/a/usd/{a}/{b}/?format=json")
        parts += r.json()["rates"]
    s = pd.Series({pd.Timestamp(x["effectiveDate"]): x["mid"] for x in parts}, name="usdpln_nbp").sort_index()
    s.to_csv(DATA / "usdpln_nbp.csv"); print("nbp", len(s), s.index.max().date())

def wob():
    url = ("https://energy.ec.europa.eu/document/download/906e60ca-8b6a-44e7-8589-652854d2fd3f_en"
           "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx")
    r = get(url)
    raw = pd.read_excel(io.BytesIO(r.content), sheet_name="Prices with taxes", header=None)
    # locate header row containing 'PL_price_with_tax_euro95'
    hdr = raw.index[raw.apply(lambda row: row.astype(str).str.contains("PL_price_with_tax_euro95").any(), axis=1)][0]
    cols = raw.iloc[hdr].astype(str).tolist()
    df = raw.iloc[hdr + 1:].copy(); df.columns = cols
    date_col = cols[0]
    df = df[[date_col, "PL_exchange_rate", "PL_price_with_tax_euro95", "PL_price_with_tax_diesel"]]
    df.columns = ["date", "rate", "pb95_eur", "on_eur"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="mixed"); df = df.dropna(subset=["date"])
    for c in ["rate", "pb95_eur", "on_eur"]: df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna().set_index("date").sort_index()
    out = pd.DataFrame({"pb95_retail": df.pb95_eur / df.rate / 1000, "on_retail": df.on_eur / df.rate / 1000})  # PLN/l gross
    out = out[out.index >= START]
    out.to_csv(DATA / "retail_weekly.csv"); print("wob", out.shape, out.index.max().date(), out.iloc[-1].round(2).to_dict())

if __name__ == "__main__":
    jobs = {"orlen": orlen, "brent": lambda: yahoo("BZ%3DF", "brent", "DCOILBRENTEU"), "ulsd": lambda: yahoo("HO%3DF", "ulsd", "DDFUELUSGULF"),
            "usdpln": lambda: yahoo("PLN%3DX", "usdpln"), "nbp": nbp, "wob": wob}
    failed = []
    for k, f in jobs.items():
        try: f()
        except Exception as e:
            print("FAIL", k, e, file=sys.stderr)
            if k == "orlen":
                try: orlen_mirror(); continue
                except Exception as e2: print("FAIL orlen mirror", e2, file=sys.stderr)
            failed.append(k)
    sys.exit(1 if failed else 0)
