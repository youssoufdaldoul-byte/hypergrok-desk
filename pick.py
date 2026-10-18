# pick.py
from collections import Counter
from thresholds import PICK_MIN_WORTH, PICK_MIN_CONF, DARK_TICKET_CUT, NO_SOCIAL_CUT


def summary(d, ans) -> str:
    """Two lines per candidate, built from answers Jev already gave.
       Never the raw dossier. A fat state costs accuracy."""
    bits = [f"{d['chain']}, {d['age_minutes']:.0f}m old, ${d['mcap_usd']:,.0f} mcap, "
            f"${d['liquidity_usd']:,.0f} liq, {d['holder_count'] or '?'} holders",
            f"crowd {ans['shape']['probabilities']['crowd']:.2f}, "
            f"concentration risk {ans['concentration_is_exit_risk']['noul']:.2f}"]

    if "authority_risk" in ans:
        bits.append(f"authority {ans['authority_risk']['choice']}")
    if "sell_side_risk" in ans:
        bits.append(f"sell side {ans['sell_side_risk']['choice']}")
    if "data_coverage" in ans:
        bits.append(f"data {ans['data_coverage']['choice']}")
    if "account_is_the_project" in ans:
        bits.append(f"official account {ans['account_is_the_project']['noul']:.2f}, "
                    f"effort {ans['effort']['score']:.1f}")
    else:
        bits.append("no usable X account")
    return "; ".join(bits)


def labels(survivors) -> list[str]:
    """Choice options are keyed by label. Two PEPEs would collapse into one option
       and one candidate would vanish, so a repeated ticker carries its address prefix."""
    n = Counter(d["ticker"] for d, _ in survivors)
    return [d["ticker"] if n[d["ticker"]] == 1 else f"{d['ticker']}:{d['addr'][:6]}"
            for d, _ in survivors]


def order(d, ans, model=None, confidence=None, runner_up=()) -> dict:
    """Sizing is arithmetic. It lives here, not in the model."""
    size_factor = 1.0
    if ans.get("data_coverage", {}).get("choice") == "dark":
        size_factor *= DARK_TICKET_CUT   # less visibility, smaller ticket
    if "account_is_the_project" not in ans:
        size_factor *= NO_SOCIAL_CUT

    return {"model": model,
            "token": {"ticker": d["ticker"], "address": d["addr"],
                      "network_id": d["net"], "chain": d["chain"]},
            "size_factor": round(size_factor, 2),
            "confidence": confidence,
            "runner_up": list(runner_up),
            "why": {k: v for k, v in ans.items()}}


def pick(judge, survivors) -> dict | None:
    """survivors: [(dossier, answers), ...], all past soft_kill. Returns the order, or None."""
    if not survivors:
        return None
    if len(survivors) == 1:              # a choice over one option is fake confidence.
        return order(*survivors[0], model="single-survivor")   # cleared SOFT: straight to the bot.

    keys = labels(survivors)
    state = {"candidates": [{"ticker": k, "summary": summary(d, a)}
                            for k, (d, a) in zip(keys, survivors)]}
    r = judge("pick", state)
    best, worth = r["answers"]["best"], r["answers"]["worth_trading_at_all"]

    if worth["noul"] < PICK_MIN_WORTH:
        return None                      # every candidate is mediocre. Normal outcome.
    if best["confidence"] < PICK_MIN_CONF:
        return None                      # flat over ten options means no favourite.

    hit = dict(zip(keys, survivors)).get(best["choice"])
    if hit is None:
        return None                      # the schema guarantees the option is in the
                                         # list, so log this one and stand down.

    return order(*hit, model=r["model"], confidence=best["confidence"],
                 runner_up=sorted(best["probabilities"].items(), key=lambda kv: -kv[1])[1:2])
