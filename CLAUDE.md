# oil-predict — Jutro na pylonie / paliwometr.pl

## Mapa terenu (2026-09-10)

### Architektura
Jeden katalog, bez pakietów. Pipeline to pięć skryptów uruchamianych po kolei przez GitHub Actions, wynik to jeden
statyczny HTML serwowany z nginxa na Coolify.

- `fetch.py` — surowe serie do `data/*.csv` (Orlen hurt z `tool.orlen.pl`, mirror cenypaliw.fyi jako fallback; Brent,
  ULSD, USD/PLN z Yahoo z fallbackiem FRED; kurs NBP; EU Weekly Oil Bulletin). Wywala się, gdy padnie **którekolwiek**
  źródło poza Orlenem — wtedy cały przebieg stoi i strona zostaje stara.
- `govmax.py` — urzędowe ceny maksymalne (okresy CPN) do `data/govmax.csv`.
- `model.py` — regresja OLS na log-zwrotach, per paliwo; pisze `site/data.json` (współczynniki, prognoza 7 dni,
  marże, historia, eval) i `data/backtest_2026.csv`. `test_model.py` uruchamia go i asertuje, że bije prognozę naiwną.
- `ledger.py` — dopisuje dzisiejszą prognozę do `data/predictions.csv`, punktuje stare względem kolejnego cennika Orlenu,
  dokleja sekcję `ledger` do `site/data.json`.
- `events.py` — RSS (48 h) → Gemini przez OpenRouter → `site/events.json`; bez klucza lista statyczna.
- `build.py` — stdlib only. Wtapia `data.json` + `events.json` w `site/page.html` → `dist/index.html` (z CSP liczonym
  z hashy inline scriptów) i `dist/api.json`.
- `site/page.html` — cała strona: CSS, markup, JS (Chart.js z cdnjs). Motyw tylko ciemny, celowo.
- `Dockerfile` + `nginx.conf` — build stage uruchamia `build.py`, nginx serwuje `/`, `/api`, `/api.json`.

### Przepływy krytyczne
- Odświeżenie: cron (6× dziennie, UTC) → `fetch` → `govmax` → `test_model` → `ledger` → `events` → `build` →
  commit `data/`, `site/data.json`, `site/events.json` → push → webhook GitHub → Coolify buduje obraz → nginx.
- Rozliczenie prognozy: `ledger.py` trzyma **jeden** wiersz `run=live` na (dzień, paliwo), każdy przebieg go nadpisuje;
  punktowana jest więc ostatnia prognoza dnia (20:00 UTC), względem pierwszego cennika Orlenu po `last_orlen_date`.
  Werdykt z progu w groszach: `hit ≤ 3`, `near ≤ 6`, `miss` powyżej (`HIT`, `NEAR` w `ledger.py`); `hit` (bool)
  to osobna miara kierunku względem „jutro = dziś”.
- Wyrównanie danych rynkowych: wiersz Orlenu z dnia t niesie zamknięcie z dnia **t** (Orlen publikuje cennik na t+1
  w nocy, po sesji). Ostatni wiersz w ciągu dnia to cena intraday — prognoza jest nowcastem.
- Symulator wydarzeń działa w całości w przeglądarce; `connect-src` w CSP dopuszcza wyłącznie Umami.

### Konwencje (z kodu)
- Skrypty są płaskie, bez funkcji `main` poza `model.py`; komentarze `ponytail:` oznaczają świadome uproszczenia.
- Ceny: hurt netto w PLN/m³ (`*_net`), hurt brutto w zł/l (`gross()` = (netto + stałe podatki) × VAT / 1000), cena na
  stacji = brutto + `margins[f].current`. Ledger i sekcja „Rozliczenie” mówią w hurcie brutto; kafelki i `/api` w cenie
  na stacji.
- Daty w UTC w danych; strona przelicza `issued_at` na czas przeglądarki (`fmtIssued`).
- Kod, komentarze, commity, dokumentacja po angielsku; treść strony po polsku.

### Pułapki
- `build.py` musi zostać stdlib-only, bo stage buildu w Dockerze nie ma pandas.
- `frame-ancestors` w CSP jest w `<meta>`, więc przeglądarki go ignorują (działa tylko jako nagłówek HTTP).
- `tool.orlen.pl` odrzuca część adresów IP („Request Rejected”); z runnerów GitHuba działa, lokalnie zwykle nie —
  fallback na mirror jest w `fetch.py`.
- `gh secret set` przez prompt Claude Code zapisuje **pustą** wartość (brak TTY); sekrety ustawiać w UI GitHuba.
- Backtest w `predictions.csv` jest nadpisywany świeżym z `model.py` przy każdym przebiegu (kolejność `concat`
  w `ledger.py` ma znaczenie).
- Pole domen w API Coolify to `domains`, nie `fqdn`.

### Jak dodać feature
Dane → `model.py` lub `ledger.py` dopisują pole do `site/data.json`; strona czyta je z `D` w `page.html`; jeśli ma
być w `/api`, `build.py` przepisuje je do `api.json`. Testy: rozszerz asercje w `test_model.py` albo `assert` na końcu
`ledger.py`. Nic nie dodawaj do triggera deployu w workflow — deploy robi webhook.

### Weryfikacja
```
uv run python test_model.py      # "ok"; model bije naiwną prognozę na 2026
uv run python ledger.py          # "ledger: N rows, M scored; {...}"; asertuje jeden wiersz live na dzień
python3 build.py                 # "built NNN KB; 2 inline script(s) hashed; api.json NNNN B"
docker build -t oil-predict . && docker run --rm -p 8080:80 oil-predict   # / i /api zwracają 200
```
Produkcja: `https://paliwometr.pl`, Coolify `cool.qaci.pl`, aplikacja `l0w0sks00c484w8g4o4kcw40`. Szczegóły w `DEPLOY.md`.
