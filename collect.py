import time, requests
from fomo_api import Fomo                      # Privy bearer out of Chrome over CDP

GT  = "https://api.geckoterminal.com/api/v2"
DEX = "https://api.dexscreener.com/latest/dex/tokens"

# the three chains the desk trades, plus Base which shares the BSC question set
GT_NET   = {1399811149: "solana", 4663: "robinhood", 56: "bsc", 8453: "base"}
FOMO_NET = {v: k for k, v in GT_NET.items()}

GT_GAP = 6.0                                    # 10/min free tier -> one call every 6s, enforced here
_gt_last = 0.0


def gt_get(path: str, **params) -> dict:
    """Every GeckoTerminal call goes through here. The budget is a sleep, not a promise."""
    global _gt_last
    wait = _gt_last + GT_GAP - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _gt_last = time.monotonic()
    r = requests.get(f"{GT}{path}", params=params, timeout=20)
    r.raise_for_status()                        # a 429 body has no "data"; fail loudly, not with a KeyError
    return r.json()


def age_minutes(created):
    """createdAt comes back as epoch seconds or milliseconds depending on the row.
       Unknown age stays None: 0.0 would read as 'brand new', which is an invented number."""
    if not created:
        return None
    c = float(created)
    if c > 1e11:                                # milliseconds
        c /= 1000
    return max(0.0, (time.time() - c) / 60)


def universe(nets=("solana", "bsc", "robinhood"), pages=2) -> list[str]:
    """Where the whole thing starts. Fresh pools per chain -> ['<addr>:<netId>', ...].
       Costs one GeckoTerminal slot per chain per page, so keep pages small."""
    ids, seen = [], set()
    for net in nets:
        for page in range(1, pages + 1):
            try:
                r = gt_get(f"/networks/{net}/new_pools", page=page)
            except Exception:
                break
            for pool in r.get("data", []):
                base = ((pool.get("relationships") or {}).get("base_token") or {})
                gid  = (base.get("data") or {}).get("id")      # 'solana_<addr>'
                if not gid:
                    continue
                addr = gid.split("_", 1)[1]
                tid  = f"{addr}:{FOMO_NET[net]}"
                if tid not in seen:
                    seen.add(tid)
                    ids.append(tid)
    return ids


def normalise(tid: str, m: dict) -> dict:
    """FOMO's field names become the desk's field names, once, here.
       Every file downstream reads these names and only these."""
    addr, net = tid.split(":")
    ch = {str(k): v for k, v in (m.get("change") or {}).items()}   # int or str keys, depending on JSON
    return {"addr": addr, "net": int(net), "tid": tid, "ticker": m["symbol"],
            "mcap_usd": m["mcap"], "liquidity_usd": m["liq"],
            "volume_h24": m["vol24"], "price_usd": m["price"],
            "holder_count": m["holders"] or None,
            "change": {"5m": ch.get("300"), "1h": ch.get("3600"),
                       "4h": ch.get("14400"), "24h": ch.get("86400")},
            "age_minutes": age_minutes(m["created"])}


def shortlist(fomo: Fomo, ids: list[str]) -> list[dict]:
    """Pass one over everything FOMO knows. No network beyond FOMO itself:
       one call per twenty tokens, and not a single request per token."""
    out = []
    for tid, m in fomo.tokens(ids).items():             # 20 per call
        t = normalise(tid, m)
        if t["net"] in GT_NET:
            out.append(t)
    # turnover ranks the queue. It orders work, it does not decide anything.
    # null volume or mcap ranks last, it does not crash the sort.
    out.sort(key=lambda t: (t["volume_h24"] or 0) / max(t["mcap_usd"] or 0, 1), reverse=True)
    return out


NO_TRADES = {"buys_h1": None, "sells_h1": None, "buys_h6": None, "sells_h6": None,
             "trades_h24": None}


def trade_counts(t: dict) -> dict:
    """buys and sells per window. FOMO does not return them, DexScreener does.
       Called ONLY for tokens that already cleared the free checks. One per token,
       so this runs on tens, never on the whole universe."""
    try:
        pairs = requests.get(f"{DEX}/{t['addr']}", timeout=20).json().get("pairs") or []
        if not pairs:
            return dict(NO_TRADES)
        x = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)["txns"]
        return {"buys_h1": x["h1"]["buys"], "sells_h1": x["h1"]["sells"],
                "buys_h6": x["h6"]["buys"], "sells_h6": x["h6"]["sells"],
                "trades_h24": x["h24"]["buys"] + x["h24"]["sells"]}
    except Exception:
        return dict(NO_TRADES)


def dossier(t: dict) -> dict:
    """One GT call per token. Fills what the chain actually has, null where it does not."""
    net = GT_NET[t["net"]]
    a = gt_get(f"/networks/{net}/tokens/{t['addr']}/info")["data"]["attributes"]

    d = {**t, "chain": net,
         # GT first, FOMO as the fallback. On Robinhood GT is null and FOMO is all you get.
         "holder_count": (a.get("holders") or {}).get("count") or t["holder_count"],
         "top_10_percent": ((a.get("holders") or {}).get("distribution_percentage")
                            or {}).get("top_10"),
         "developer_holding_percentage": a.get("developer_holding_percentage"),
         "gt_score_details": a.get("gt_score_details"),
         "is_honeypot": a.get("is_honeypot"),
         "mint_authority": a.get("mint_authority"),
         "freeze_authority": a.get("freeze_authority"),
         "description": a.get("description"),
         "x_handle": clean_handle(a.get("twitter_handle"))}

    # Solana only: exact top wallet share, free, off the public RPC
    if t["net"] == 1399811149:
        d["top_wallet_percent"] = sol_top_wallet(t["addr"])

    return d


def clean_handle(h):
    """GT returned 'LuffyX100X/status/2102659581109272876' on a Robinhood token.
       Take the first path segment, or treat the account as missing."""
    if not h:
        return None
    h = h.strip().lstrip("@").split("?")[0].split("/")[0]
    return h if h and h.replace("_", "").isalnum() and len(h) <= 15 else None


def sol_top_wallet(mint: str):
    """Largest token account as a PERCENT (0-100), same unit as top_10_percent.
       NOTE: the largest account is often the pool or bonding curve, not a holder.
       Public RPC throttles hard: any failure is None, never a guess."""
    rpc = "https://api.mainnet-beta.solana.com"
    q = lambda m, p: requests.post(rpc, json={"jsonrpc": "2.0", "id": 1,
                                              "method": m, "params": p},
                                   timeout=20).json()["result"]
    try:
        supply = float(q("getTokenSupply", [mint])["value"]["amount"])
        top = q("getTokenLargestAccounts", [mint])["value"]
    except Exception:
        return None
    return 100 * float(top[0]["amount"]) / supply if supply and top else None


def social_state(d: dict) -> dict:
    """What SOCIAL hands the judge. The X block is filled by the bot's X plugin."""
    return {"x_account": d["x_account"],                 # collected by SOCIAL, not here
            # age_minutes: recycled_account compares the account's timeline to the token's
            "token": {"ticker": d["ticker"], "narrative": d.get("description"),
                      "age_minutes": d.get("age_minutes")}}
