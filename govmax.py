"""Ministry of Energy daily maximum retail prices (price-cap periods) -> data/govmax.csv. Incremental: only new URLs are fetched."""
import html, re, sys
from pathlib import Path
import pandas as pd, requests

DATA = Path(__file__).parent / "data"; OUT = DATA / "govmax.csv"
UA = {"User-Agent": "Mozilla/5.0"}
BASE = "https://www.gov.pl"
MONTHS = {m: i + 1 for i, m in enumerate("stycznia lutego marca kwietnia maja czerwca lipca sierpnia wrzesnia pazdziernika listopada grudnia".split())}
norm = lambda s: s.lower().replace("ś", "s").replace("ź", "z").replace("ż", "z").replace("ą", "a").replace("ę", "e").replace("ó", "o").replace("ł", "l").replace("ć", "c").replace("ń", "n")

def listing(pages):
    urls = set()
    for p in range(1, pages + 1):
        r = requests.get(f"{BASE}/web/energia/wiadomosci?page={p}&size=10", headers=UA, timeout=30)
        found = re.findall(r'href="(/web/energia/maksymalna-cena-detaliczna[^"]*)"', r.text)
        if not found and p > 3: break
        urls |= set(found)
    return sorted(urls)

def parse(url):
    t = html.unescape(re.sub(r"<[^>]+>", " ", requests.get(BASE + url, headers=UA, timeout=30).text)); t = re.sub(r"\s+", " ", t)
    title = norm(re.search(r"obowiazujac[ae] (.*?2026)", norm(t)).group(1))
    m = re.search(r"(?:(\d{1,2})\s*[-–]\s*)?(\d{1,2}) (\w+) 2026", title)
    d1, d2, mon = m.group(1), int(m.group(2)), MONTHS[m.group(3)]
    days = range(int(d1), d2 + 1) if d1 else [d2]
    px = re.search(r"enzyna 95\D*(\d+,\d+)\D*?enzyna 98\D*(\d+,\d+)\D*?nap[eę]dowy\D*(\d+,\d+)", t)
    pb95, pb98, on = (float(x.replace(",", ".")) for x in px.groups())
    return [{"date": f"2026-{mon:02d}-{d:02d}", "pb95_max": pb95, "pb98_max": pb98, "on_max": on, "url": url} for d in days]

if __name__ == "__main__":
    old = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame(columns=["date", "pb95_max", "pb98_max", "on_max", "url"])
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    rows = []
    for u in listing(pages):
        if u in set(old.url): continue
        try: rows += parse(u)
        except Exception as e: print("skip", u, e, file=sys.stderr)
    df = pd.concat([old, pd.DataFrame(rows)]).drop_duplicates("date", keep="last").sort_values("date")
    df.to_csv(OUT, index=False); print("govmax", len(df), "days;", "new", len(rows), df.date.min(), "->", df.date.max())
