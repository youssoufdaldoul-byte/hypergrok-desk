# desk_ui.py
# The screen the team trades from, 24/7. It follows the token the desk is on:
# the held position first (book), the team's own focus second. Change either and
# the token panel, the candles and the gates follow on the next poll (5s).
import hmac, os, re, threading, time, requests
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import book
from thresholds import HARD, SOFT

DESK_SECRET = os.environ["DESK_SECRET"]      # seats push feed lines and holdings
VIEW_KEY    = os.environ["DESK_VIEW_KEY"]    # the team's screens: read + switch token, nothing else

GT  = "https://api.geckoterminal.com/api/v2"
DEX = "https://api.dexscreener.com/latest/dex/tokens"
GT_NET = {1399811149: "solana", 4663: "robinhood", 56: "bsc", 8453: "base"}
# button -> (GT timeframe, aggregate, candles)
TF = {"LIVE": ("minute", 1, 90), "1H": ("minute", 1, 60),
      "4H": ("minute", 5, 48), "ALL": ("hour", 1, 168)}
DEX_TTL, CANDLE_TTL, POOL_TTL = 5, 60, 600
# GeckoTerminal is 10/min per IP and the shift needs 9 of them in a burst every cycle.
# The screen takes at most one call per DESK_GT_GAP seconds and serves stale candles between.
GT_GAP = float(os.environ.get("DESK_GT_GAP", 30))
ADDR = re.compile(r"^(0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})$")

router = APIRouter()
PAGE = Path(__file__).parent / "desk" / "index.html"

book.DB.executescript("""
CREATE TABLE IF NOT EXISTS focus(
  id INTEGER PRIMARY KEY CHECK (id = 1), addr TEXT, net INT, at REAL);
CREATE TABLE IF NOT EXISTS feed(seat TEXT, text TEXT, at REAL);
CREATE TABLE IF NOT EXISTS holding(
  name TEXT, addr TEXT, entry_mcap_usd REAL, value_usd REAL, at REAL,
  PRIMARY KEY (name, addr));
""")

_cache, _lock = {}, threading.Lock()
_gt_next = 0.0


def cached(key, ttl, fetch):
    """Stale beats blank, blank beats invented. A failed fetch serves the last good value."""
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        val = fetch()
    except Exception:
        return hit[1] if hit else None
    with _lock:
        _cache[key] = (time.time(), val)
    return val


def gt(path, **params):
    global _gt_next
    with _lock:
        if time.monotonic() < _gt_next:
            raise RuntimeError("screen GT budget spent")
        _gt_next = time.monotonic() + GT_GAP
    r = requests.get(f"{GT}{path}", params=params, timeout=15)
    if r.status_code == 429:
        with _lock:
            _gt_next = time.monotonic() + 120      # the shift is short too: back off hard
    r.raise_for_status()
    return r.json()


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def token(addr):
    def fetch():
        pairs = requests.get(f"{DEX}/{addr}", timeout=10).json().get("pairs") or []
        if not pairs:
            return None
        p = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
        base, x = p.get("baseToken") or {}, p.get("txns") or {}
        ch, vol = p.get("priceChange") or {}, p.get("volume") or {}
        created = p.get("pairCreatedAt")
        h24 = x.get("h24") or {}
        return {"symbol": base.get("symbol"), "name": base.get("name"),
                "image": (p.get("info") or {}).get("imageUrl"),
                "price_usd": num(p.get("priceUsd")),
                "mcap_usd": num(p.get("marketCap") or p.get("fdv")),
                "change": {k: num(ch.get(k)) for k in ("m5", "h1", "h6", "h24")},
                "liquidity_usd": num((p.get("liquidity") or {}).get("usd")),
                "volume_h24": num(vol.get("h24")),
                "trades_h24": (h24["buys"] + h24["sells"]) if "buys" in h24 else None,
                "age_minutes": (time.time() - created / 1000) / 60 if created else None,
                "pair": p.get("pairAddress"), "url": p.get("url")}
    return cached(("dex", addr), DEX_TTL, fetch)


def pool_for(addr, net, t):
    if t and t.get("pair"):
        return t["pair"]
    def fetch():                                   # robinhood: DexScreener may not index it
        d = gt(f"/networks/{GT_NET[net]}/tokens/{addr}/pools", page=1)["data"]
        return d[0]["attributes"]["address"] if d else None
    return cached(("pool", addr), POOL_TTL, fetch)


def candles(net, pool, tf):
    frame, agg, limit = TF[tf]
    def fetch():
        r = gt(f"/networks/{GT_NET[net]}/pools/{pool}/ohlcv/{frame}",
               aggregate=agg, limit=limit, currency="usd", token="base")
        rows = r["data"]["attributes"]["ohlcv_list"]       # [ts, o, h, l, c, v], newest first
        return sorted(([float(v) for v in row] for row in rows), key=lambda row: row[0])
    return cached(("ohlcv", pool, tf), CANDLE_TTL, fetch)


def gates(t):
    """The HARD checks free_kill and trade_kill run, live on the screen's token.
       A field that came back null is unknown, not a pass."""
    def g(name, v, ok):
        return {"gate": name, "state": None if v is None else ("PASS" if ok(v) else "FAIL")}
    return [
        g("min_liquidity_usd", t["liquidity_usd"], lambda v: v >= HARD["min_liquidity_usd"]),
        g("min_volume_h24", t["volume_h24"], lambda v: v >= HARD["min_volume_h24"]),
        g("mcap_usd", t["mcap_usd"],
          lambda v: HARD["min_mcap_usd"] <= v <= HARD["max_mcap_usd"]),
        g("min_trades_h24", t["trades_h24"], lambda v: v >= HARD["min_trades_h24"]),
        g("age_minutes", t["age_minutes"],
          lambda v: HARD["min_age_minutes"] <= v <= HARD["max_age_hours"] * 60),
    ]


def focus(follow=True):
    if follow:
        r = book.DB.execute("SELECT addr, net FROM position WHERE id=1").fetchone()
        if r:
            return r[0], r[1], "position"
    r = book.DB.execute("SELECT addr, net FROM focus WHERE id=1").fetchone()
    return (r[0], r[1], "team") if r else (None, None, None)


def view(key):
    if not hmac.compare_digest(key, VIEW_KEY):
        raise HTTPException(401, "bad view key")


def desk(auth):
    if not hmac.compare_digest(auth, f"Bearer {DESK_SECRET}"):
        raise HTTPException(401, "bad desk secret")


@router.get("/desk")
def page():
    return FileResponse(PAGE)          # no data in it; the key lives in the URL fragment


@router.get("/desk/state")
def state(tf: str = "LIVE", follow: int = 1, x_desk_key: str = Header("")):
    view(x_desk_key)
    tf = tf if tf in TF else "LIVE"
    addr, net, src = focus(bool(follow))
    t = token(addr) if addr else None
    out = {"focus": {"addr": addr, "net": net, "chain": GT_NET.get(net), "source": src},
           "token": t, "tf": tf, "candles": [], "supply": None,
           "gates": gates(t) if t else [], "held": book.held(),
           "rejected_24h": book.rejections_today(),
           "thresholds": {"HARD": HARD, "SOFT": SOFT}}
    if t and net in GT_NET:
        pool = pool_for(addr, net, t)
        out["candles"] = (candles(net, pool, tf) or []) if pool else []
        if t["price_usd"] and t["mcap_usd"]:
            out["supply"] = t["mcap_usd"] / t["price_usd"]     # candles are price, the chart is MC
    out["feed"] = [{"seat": s, "text": x, "at": a} for s, x, a in book.DB.execute(
        "SELECT seat, text, at FROM feed ORDER BY at DESC LIMIT 7")]
    out["holders"] = [{"name": n, "entry_mcap_usd": e, "value_usd": v} for n, e, v in
                      book.DB.execute("SELECT name, entry_mcap_usd, value_usd FROM holding "
                                      "WHERE addr=? ORDER BY value_usd DESC", (addr,))]
    out["rejections"] = [{"tid": tid, "reason": r, "at": a} for tid, r, a in book.DB.execute(
        "SELECT tid, reason, at FROM rejection ORDER BY at DESC LIMIT 8")]
    return out


class Focus(BaseModel):
    address: str | None
    network_id: int = 1399811149


@router.post("/desk/focus")
def set_focus(f: Focus, x_desk_key: str = Header("")):
    """The team switches token from the screen. A held position still wins while Following is on."""
    view(x_desk_key)
    if f.address is None:
        book.DB.execute("DELETE FROM focus")
    else:
        if not ADDR.match(f.address) or f.network_id not in GT_NET:
            raise HTTPException(422, "bad address or network")
        book.DB.execute("INSERT OR REPLACE INTO focus VALUES (1,?,?,?)",
                        (f.address, f.network_id, time.time()))
    book.DB.commit()
    return {"focus": f.address}


class Line(BaseModel):
    seat: str = Field(max_length=16)
    text: str = Field(max_length=280)


@router.post("/desk/feed")
def post_feed(line: Line, authorization: str = Header("")):
    """Any seat posts one line. The screen shows the last seven."""
    desk(authorization)
    book.DB.execute("INSERT INTO feed VALUES (?,?,?)", (line.seat, line.text, time.time()))
    book.DB.execute("DELETE FROM feed WHERE at < ?", (time.time() - 7 * 86_400,))
    book.DB.commit()
    return {"ok": True}


class Holding(BaseModel):
    name: str = Field(max_length=32)
    address: str
    entry_mcap_usd: float | None = None
    value_usd: float | None = None      # null removes the row: the holder is out


@router.post("/desk/holding")
def post_holding(h: Holding, authorization: str = Header("")):
    """FILLS posts after every fill, RISK after every close. Nobody else."""
    desk(authorization)
    if h.value_usd is None:
        book.DB.execute("DELETE FROM holding WHERE name=? AND addr=?", (h.name, h.address))
    else:
        book.DB.execute("INSERT OR REPLACE INTO holding VALUES (?,?,?,?,?)",
                        (h.name, h.address, h.entry_mcap_usd, h.value_usd, time.time()))
    book.DB.commit()
    return {"ok": True}
