"""Inline site/data.json into site/page.html -> dist/index.html (standalone, CSP) and dist/artifact.html (body-only)."""
import base64, hashlib, re
from pathlib import Path

ROOT = Path(__file__).parent
page = (ROOT / "site" / "page.html").read_text()
import json
blob = json.loads((ROOT / "site" / "data.json").read_text())
ev = ROOT / "site" / "events.json"
blob["events"] = json.loads(ev.read_text()) if ev.exists() else None
data = json.dumps(blob, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")   # never let data close the script tag
body = page.replace("__DATA__", data)

def sha(s): return "sha256-" + base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()
inline_scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", body, flags=re.S)
hashes = " ".join(f"'{sha(s)}'" for s in inline_scripts)
csp = ("default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; "
       f"script-src https://cdnjs.cloudflare.com {hashes}; "
       "style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
       "img-src data:; connect-src 'none'")
title = re.search(r"<title>(.*?)</title>", body).group(1)
head = f'''<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="referrer" content="no-referrer">
<meta name="description" content="Prognoza cen Pb95, Pb98 i ON na stacjach w Polsce na jutro i na tydzień, z symulacją wydarzeń rynkowych.">
<meta name="color-scheme" content="dark">
'''
# ponytail: not an API, just a JSON file nginx happens to serve. Same numbers the page shows.
def price(fuel, net):
    """Station price in PLN/l: wholesale net + fixed taxes, VAT, plus the station margin."""
    tax, reg = blob["meta"]["tax"], blob["meta"]["regime_now"]
    cut = (280 if fuel == "on" else 290) if reg["excise_cut"] else 0
    fixed = tax["excise"][fuel] - cut + tax["charge"][fuel] + tax["emission"]
    return round((net + fixed) * reg["vat"] / 1000 + blob["margins"][fuel]["current"], 3)

def day(iso, n):
    from datetime import date, timedelta
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()

api = {"source": "https://paliwometr.pl", "unit": "PLN/l",
       "generated": (blob.get("events") or {}).get("generated") or blob["meta"]["generated"],
       "data_date": blob["fuels"]["pb95"]["last_date"], "fuels": {}}
for f, F in blob["fuels"].items():
    L = blob["ledger"]["fuels"][f]
    api["fuels"][f] = {
        "today": price(f, F["last_net"]),
        "tomorrow": price(f, F["base_net"][0]),
        "forecast": [{"date": day(F["last_date"], i + 1), "price": price(f, n)} for i, n in enumerate(F["base_net"])],
        "wholesale_net": F["last_net"], "station_margin": blob["margins"][f]["current"],
        "mae_30d_gr": L["mae30"], "mae_30d_naive_gr": L["mae30_naive"], "hit_rate_30d": L["hit30"],
    }

dist = ROOT / "dist"; dist.mkdir(exist_ok=True)
(dist / "api.json").write_text(json.dumps(api, ensure_ascii=False, indent=1))
head_bits = re.findall(r"<(?:title|link)\b[^>]*>(?:.*?</title>)?", body, flags=re.S)
standalone_body = body
for h in head_bits: standalone_body = standalone_body.replace(h, "", 1)
(dist / "index.html").write_text(head + "\n".join(head_bits) + "\n</head>\n<body>\n" + standalone_body + "\n</body></html>\n")
(dist / "artifact.html").write_text(body)
print("built", (dist / "index.html").stat().st_size // 1024, "KB;", len(inline_scripts), "inline script(s) hashed;",
      "api.json", (dist / "api.json").stat().st_size, "B")
