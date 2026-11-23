"""Busca cotações na brapi.dev, calcula a MM20 diária e semanal e grava data/data.json."""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
from statistics import mean

TOKEN = os.environ.get("BRAPI_TOKEN", "")
RANGE = os.environ.get("BRAPI_RANGE") or "3mo"  # use 1y no plano Startup
URL = "https://brapi.dev/api/quote/{}?range={}&interval=1d"
HIST, OUT = "data/history.json", "data/data.json"


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


def build_row(ticker, res, hist):
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


def main():
    tickers = [t.strip() for t in open("tickers.txt") if t.strip()]
    hist = json.load(open(HIST)) if os.path.exists(HIST) else {}
    old = {}
    if os.path.exists(OUT):
        old = {r["ticker"]: r for r in json.load(open(OUT)).get("rows", [])}
    rows, errors = [], 0
    for t in tickers:
        try:
            rows.append(build_row(t, fetch(t), hist))
        except Exception as e:  # mantém o dado anterior se falhar
            errors += 1
            print(f"{t}: {e}", file=sys.stderr)
            if t in old:
                rows.append(old[t])
        time.sleep(0.3)
    if errors == len(tickers):
        sys.exit("Nenhum ticker atualizado. Confira o token.")
    os.makedirs("data", exist_ok=True)
    json.dump(hist, open(HIST, "w"))
    json.dump(
        {"updated": datetime.now(timezone.utc).isoformat(), "rows": rows},
        open(OUT, "w"), ensure_ascii=False,
    )
    print(f"{len(rows)} ativos, {errors} erros")


if __name__ == "__main__":
    main()
