"""Busca cotações na brapi.dev, calcula as médias móveis e as mudanças de um dia para o outro."""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from statistics import mean

TOKEN = os.environ.get("BRAPI_TOKEN", "")
RANGE = os.environ.get("BRAPI_RANGE") or "3mo"  # use 1y no plano Startup
URL = "https://brapi.dev/api/quote/{}?range={}&interval=1d"
HIST, OUT, STATUS = "data/history.json", "data/data.json", "data/status.json"
MAS = ("d20", "d200", "w14", "w20")


def today_brt():
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d")


def fetch(ticker):
    req = urllib.request.Request(
        URL.format(ticker, RANGE),
        headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "ibov-mm"},
    )
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["results"][0]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After", "30")))
                continue
            raise
    raise RuntimeError("limite de requisições")


def weekly_closes(closes):
    """closes: {'AAAA-MM-DD': fechamento}. Retorna o último fechamento de cada semana ISO."""
    weeks = {}
    for d in sorted(closes):
        y, w, _ = datetime.strptime(d, "%Y-%m-%d").isocalendar()
        weeks[(y, w)] = closes[d]
    return [weeks[k] for k in sorted(weeks)]


def sma(vals, n):
    return round(mean(vals[-n:]), 2) if len(vals) >= n else None


def build_row(ticker, sector, res, hist):
    for b in res.get("historicalDataPrice") or []:
        if b.get("close") is not None:
            day = datetime.fromtimestamp(b["date"], timezone.utc).strftime("%Y-%m-%d")
            hist.setdefault(ticker, {})[day] = b["close"]
    closes = hist.get(ticker, {})
    daily = [closes[d] for d in sorted(closes)]
    weekly = weekly_closes(closes)
    price = res.get("regularMarketPrice") or (daily[-1] if daily else None)
    return {
        "ticker": ticker,
        "name": res.get("shortName") or ticker,
        "sector": sector,
        "logo": res.get("logourl") or f"https://icons.brapi.dev/icons/{ticker}.svg",
        "price": price,
        "change": res.get("regularMarketChangePercent"),
        "volume": res.get("regularMarketVolume"),
        "d20": sma(daily, 20),
        "d200": sma(daily, 200),
        "w14": sma(weekly, 14),
        "w20": sma(weekly, 20),
        "days": len(daily),
        "weeks": len(weekly),
    }


def statuses(row):
    """Para cada média: 'above' se o preço está acima dela, 'below' se abaixo, None se não há média."""
    p = row.get("price")
    return {k: (None if row.get(k) is None or p is None else ("above" if p > row[k] else "below")) for k in MAS}


def find_changes(rows, prev):
    out = []
    for r in rows:
        before = prev.get(r["ticker"], {})
        for k, now in statuses(r).items():
            if now and before.get(k) and now != before[k]:
                out.append({"ticker": r["ticker"], "ma": k, "to": now, "price": r["price"], "sma": r[k]})
    return out


def main():
    items = []
    for line in open("tickers.txt"):
        if line.strip():
            t, _, s = line.strip().partition(";")
            items.append((t.strip(), s.strip() or "Outros"))
    hist = json.load(open(HIST)) if os.path.exists(HIST) else {}
    old = {}
    if os.path.exists(OUT):
        old = {r["ticker"]: r for r in json.load(open(OUT)).get("rows", [])}
    rows, errors = [], 0
    for t, sector in items:
        try:
            rows.append(build_row(t, sector, fetch(t), hist))
        except Exception as e:  # mantém o dado anterior se falhar
            errors += 1
            print(f"{t}: {e}", file=sys.stderr)
            if t in old:
                old[t]["sector"] = sector
                rows.append(old[t])
        time.sleep(0.3)
    if errors == len(items):
        sys.exit("Nenhum ticker atualizado. Confira o token.")

    # mudanças: compara com o último dia anterior guardado
    today = today_brt()
    snaps = json.load(open(STATUS)) if os.path.exists(STATUS) else {}
    before = sorted(d for d in snaps if d < today)
    prev_date = before[-1] if before else None
    changes = find_changes(rows, snaps[prev_date]) if prev_date else []
    snaps[today] = {r["ticker"]: statuses(r) for r in rows}
    snaps = {d: snaps[d] for d in sorted(snaps)[-30:]}

    os.makedirs("data", exist_ok=True)
    json.dump(hist, open(HIST, "w"))
    json.dump(snaps, open(STATUS, "w"))
    json.dump(
        {"updated": datetime.now(timezone.utc).isoformat(), "rows": rows,
         "changes": changes, "changes_from": prev_date, "changes_to": today},
        open(OUT, "w"), ensure_ascii=False,
    )
    print(f"{len(rows)} ativos, {errors} erros, {len(changes)} mudanças")


if __name__ == "__main__":
    main()
