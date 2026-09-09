"""Headlines (RSS, last 48h) -> Gemini via OpenRouter -> site/events.json. Falls back to the static list when no key / failure."""
import json, os, re, sys, html
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
import requests

ROOT = Path(__file__).parent; OUT = ROOT / "site" / "events.json"
MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-3.8-flash")
KEY = os.environ.get("OPENROUTER_API_KEY")
FEEDS = [
    "https://news.google.com/rss/search?q=ropa+brent+OR+ceny+paliw+OR+Orlen+hurt&hl=pl&gl=PL&ceid=PL:pl",
    "https://news.google.com/rss/search?q=brent+crude+oil+OR+opec+OR+hormuz+OR+diesel+ara&hl=en-US&gl=US&ceid=US:en",
    "https://oilprice.com/rss/main",
]
KW = re.compile(r"ropa|paliw|orlen|brent|oil|opec|hormuz|diesel|rafiner|refiner|akcyz|vat|tanker|iran|crude|gasoline|sanction|sankcj", re.I)
LIMIT = {"brent": .15, "crack": .15, "fx": .05, "pl": .05}
STATIC = [
  {"id":"hormuz","label":"Eskalacja w Ormuz, ataki na tankowce","note":"Jak 6 III (+28% w tydzień) i 23 VII 2026 (+7% w dzień)","brent":.12,"crack":.08},
  {"id":"truce","label":"Zawieszenie broni USA–Iran","note":"Jak 8 IV 2026: Brent −13% w jeden dzień","brent":-.12,"crack":-.06},
  {"id":"opec","label":"OPEC+ podnosi wydobycie","note":"Kolejna transza +188 tys. b/d, rynek reaguje słabo","brent":-.03},
  {"id":"ru","label":"Drony na rosyjskie rafinerie","note":"Ropa bez zmian, drożeje europejski diesel","brent":.01,"crack":.06},
  {"id":"plock","label":"Awaria lub remont w Płocku","note":"Krajowa podaż w dół, Orlen podnosi hurt niezależnie od rynku","pl":.02},
  {"id":"pln","label":"Złoty umacnia się o 3%","note":"Jak 30 III–17 IV 2026: USD/PLN z 3,68 na 3,57","fx":-.03},
]

def headlines():
    since = datetime.now(timezone.utc) - timedelta(hours=48); out = []
    for url in FEEDS:
        try: root = ET.fromstring(requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).content)
        except Exception as e: print("feed fail", url, e, file=sys.stderr); continue
        for it in root.iter("item"):
            t = html.unescape(it.findtext("title") or ""); link = it.findtext("link") or ""; pub = it.findtext("pubDate") or ""
            try: dt = datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S").replace(tzinfo=timezone.utc)
            except Exception: dt = datetime.now(timezone.utc)
            if dt >= since and KW.search(t): out.append({"title": t[:200], "url": link[:300], "published": dt.strftime("%Y-%m-%d %H:%M")})
    seen, uniq = set(), []
    for h in sorted(out, key=lambda h: h["published"], reverse=True):
        k = re.sub(r"\W+", "", h["title"].lower())[:60]
        if k not in seen: seen.add(k); uniq.append(h)
    return uniq[:40]

PROMPT = """Jesteś analitykiem rynku paliw. Poniżej nagłówki z ostatnich 48 godzin. Wybierz maksymalnie 7 realnych, aktualnych wydarzeń lub ryzyk,
które mogą w najbliższym tygodniu przesunąć cenę ropy Brent, europejskiego diesla, kurs USD/PLN albo krajową cenę hurtową paliw w Polsce.
Dla każdego oszacuj szok jako ułamek (np. 0.05 = +5%) w skali tygodnia, ostrożnie: typowe dzienne ruchy Brent to 1-3%, w 2026 duże szoki to 5-13%.
Zwróć WYŁĄCZNIE JSON: {"events":[{"id":"krotki_slug","label":"po polsku, max 45 znaków","note":"jedno zdanie po polsku, co i dlaczego, max 110 znaków",
"brent":0.0,"crack":0.0,"fx":0.0,"pl":0.0,"confidence":"low|medium|high","source_url":"url nagłówka"}]}
Pola: brent = ruch ceny Brent; crack = dodatkowy ruch europejskiego diesla ponad Brent; fx = ruch USD/PLN (dodatni = słabszy złoty); pl = ruch hurtu Orlen niezależny od rynku (podaż krajowa, decyzje Orlenu). Pomijaj pole, gdy 0. Nie wymyślaj wydarzeń, których nie ma w nagłówkach. Jeśli nagłówek dotyczy zmiany podatków na paliwa w Polsce, opisz go z pl równym szacowanemu efektowi.

NAGŁÓWKI:
"""

def ask(hl):
    body = {"model": MODEL, "temperature": 0.2, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": PROMPT + "\n".join(f"- [{h['published']}] {h['title']} ({h['url']})" for h in hl)}]}
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", json=body, timeout=90,
                      headers={"Authorization": f"Bearer {KEY}", "HTTP-Referer": "https://github.com/oil-predict", "X-Title": "Jutro na pylonie"})
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    txt = txt[txt.find("{"): txt.rfind("}") + 1]
    return json.loads(txt)["events"]

def clean(evs):
    out = []
    for e in evs[:7]:
        if not isinstance(e, dict) or not e.get("label"): continue
        c = {"id": re.sub(r"[^a-z0-9_]", "", str(e.get("id", "ev")).lower())[:24] or f"ev{len(out)}",
             "label": str(e["label"])[:60], "note": str(e.get("note", ""))[:140],
             "confidence": e.get("confidence") if e.get("confidence") in ("low", "medium", "high") else "low",
             "source_url": str(e.get("source_url", ""))[:300] if str(e.get("source_url", "")).startswith("http") else ""}
        for k, lim in LIMIT.items():
            try: v = float(e.get(k, 0) or 0)
            except (TypeError, ValueError): v = 0.0
            if v: c[k] = round(max(-lim, min(lim, v)), 3)
        if any(k in c for k in LIMIT): out.append(c)
    return out

if __name__ == "__main__":
    hl = headlines(); res = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "headlines": hl[:12], "source": "static", "model": None, "events": STATIC}
    if KEY and hl:
        try:
            ev = clean(ask(hl))
            if len(ev) >= 3: res.update(source="ai", model=MODEL, events=ev)
            else: print("ai returned too few events, keeping static", file=sys.stderr)
        except Exception as e: print("openrouter failed, keeping static:", e, file=sys.stderr)
    elif not KEY: print("OPENROUTER_API_KEY not set, static events", file=sys.stderr)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"events: source={res['source']} n={len(res['events'])} headlines={len(hl)}")
