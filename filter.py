from thresholds import HARD, SOFT, SHAPE_MIN_CROWD


def free_kill(t) -> str | None:
    """Pass one. Runs on the whole universe, costs nothing, touches no network.
       Everything it reads came back with the FOMO batch."""
    # null is not fine: a hard check that cannot run is a kill, with its own reason
    for f in ("age_minutes", "liquidity_usd", "volume_h24", "mcap_usd"):
        if t.get(f) is None:
            return f"no_{f}"
    if not HARD["min_age_minutes"] <= t["age_minutes"] <= HARD["max_age_hours"] * 60:
        return "age"
    if t["liquidity_usd"] < HARD["min_liquidity_usd"]:      return "liquidity"
    if t["volume_h24"]    < HARD["min_volume_h24"]:         return "volume"
    if not HARD["min_mcap_usd"] <= t["mcap_usd"] <= HARD["max_mcap_usd"]:
        return "mcap"
    return None


def trade_kill(t) -> str | None:
    """Pass two. One DexScreener call already spent on this token. Tens, not hundreds."""
    if t["trades_h24"] is None:                             return "no_pair"
    if t["trades_h24"] < HARD["min_trades_h24"]:            return "trades"
    if t["sells_h1"] == 0 and (t["buys_h1"] or 0) > 20:     return "no_sells"
    return None


def chain_kill(d) -> str | None:
    """After the dossier, still free. Facts, not judgements."""
    # both percents arrive 0-100, both limits are fractions
    if d.get("top_wallet_percent") is not None and \
       float(d["top_wallet_percent"]) / 100 > HARD["max_top_wallet"]:
        return "top_wallet"
    if d.get("top_10_percent") is not None and \
       float(d["top_10_percent"]) / 100 > HARD["max_top_10"]:
        return "top_10"
    if d.get("holder_count") is not None and d["holder_count"] < HARD["min_holders"]:
        return "holders"
    if d["chain"] == "solana" and (d["mint_authority"] or d["freeze_authority"]):
        return "authority_open"          # a fact, no model needed
    if d.get("is_honeypot") is True:     # any chain: bsc, base, and robinhood when indexed
        return "honeypot"                # also a fact
    return None


def soft_kill(ans) -> str | None:
    """Jev's answers against SOFT. First failure wins."""
    for name, (direction, limit) in SOFT.items():
        a = ans.get(name)
        if a is None:
            continue                     # question not asked for this chain
        v = a.get("noul", a.get("score"))
        if v is None:
            continue
        if direction == "max" and v > limit: return name
        if direction == "min" and v < limit: return name

    shape = ans.get("shape")
    if shape:
        if shape["choice"] in ("fading", "one_buyer"):        return "shape"
        if shape["probabilities"]["crowd"] < SHAPE_MIN_CROWD: return "shape_weak"

    chain = ans.get("sell_side_risk")
    if chain and chain["choice"] in ("flagged", "suspicious"): return "sell_side"
    return None
