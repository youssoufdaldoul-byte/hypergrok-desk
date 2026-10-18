# main.py
import time, logging
from datetime import datetime, timezone
from fomo_api import Fomo
from collect import universe, shortlist, trade_counts, dossier, social_state
from filter import free_kill, trade_kill, chain_kill, soft_kill
from pick import pick
import book

CHAIN_SET     = {1399811149: "solana", 56: "bsc", 8453: "bsc", 4663: "robinhood"}
CYCLE_SECONDS = 900
GT_PER_MINUTE = 10          # free tier
GT_UNIVERSE   = 6           # 3 chains x 2 pages, spent before the funnel starts
GT_DOSSIER    = 3           # what is left for dossiers in the same minute
DEX_BUDGET    = 25          # DexScreener calls per cycle, pass two only
log = logging.getLogger("desk")

# STATE IS A NAMED OBJECT, never a blob. Each set gets only the fields its questions read.
# Missing keys go in as null on purpose: data_coverage reads the holes.
MARKET_FIELDS = ("ticker", "age_minutes", "holder_count", "change", "price_usd",
                 "buys_h1", "sells_h1", "buys_h6", "sells_h6", "trades_h24",
                 "volume_h1", "volume_h6", "volume_h24",
                 "liquidity_usd", "mcap_usd", "intended_ticket_usd")
CHAIN_FIELDS  = ("ticker", "chain", "holder_count", "top_10_percent", "top_wallet_percent",
                 "developer_holding_percentage", "mint_authority", "freeze_authority",
                 "is_honeypot", "gt_score_details", "liquidity_usd", "age_minutes",
                 "buys_h1", "sells_h1", "buys_h6", "sells_h6", "trades_h24")


def named(d, fields):
    return {k: d.get(k) for k in fields}


def status(e):
    return getattr(getattr(e, "response", None), "status_code", None)


def run_once(fomo, judge, desk, bank, shadow=True):
    if (h := book.held()):                       # RISK owns the desk right now
        log.info("holding %s for %.0f min, no scan this cycle",
                 h["ticker"], h["minutes"])
        return None, {"held": h["ticker"], "minutes": round(h["minutes"])}

    stats = {"seen": 0, "benched": 0, "free": {}, "trade": {},
             "chain": {}, "soft": {}}
    survivors = []
    gt_slots, dex_slots = GT_DOSSIER, DEX_BUDGET

    ids = universe()                             # fresh pools, 3 chains, GT_UNIVERSE slots
    for t in shortlist(fomo, ids):               # pass one: free, no per-token requests
        stats["seen"] += 1
        if book.benched(t["tid"]):               # already judged, still serving its time
            stats["benched"] += 1
            continue
        if (k := free_kill(t)):
            book.sit(t["tid"], k)
            stats["free"][k] = stats["free"].get(k, 0) + 1
            continue

        if dex_slots <= 0 or gt_slots <= 0:
            break                                # out of budget, not out of ideas

        t |= trade_counts(t)                     # pass two: one DexScreener call
        dex_slots -= 1
        if (k := trade_kill(t)):
            book.sit(t["tid"], k)
            stats["trade"][k] = stats["trade"].get(k, 0) + 1
            continue

        try:
            d = dossier(t)                       # pass three: one GeckoTerminal slot
            gt_slots -= 1
        except Exception as e:
            gt_slots -= 1                        # a failed call still cost you the slot
            if status(e) == 429:                 # our budget, not the token's fault: no bench,
                log.warning("GT 429, no more dossiers this cycle")   # gt_get waits a minute
                gt_slots = 0
                continue
            log.warning("dossier failed %s: %s", t["ticker"], e)
            book.sit(t["tid"], "dossier_failed")
            continue                             # missing is missing, not a pass

        if (k := chain_kill(d)):
            book.sit(t["tid"], k)                # facts bench longest
            stats["chain"][k] = stats["chain"].get(k, 0) + 1
            continue

        d["intended_ticket_usd"] = bank * 0.06   # the most SIZE could ever allow
        d["x_account"] = desk.read_x(d["x_handle"]) if d["x_handle"] else None

        ans = {}
        try:
            ans |= judge("market", named(d, MARKET_FIELDS))["answers"]       # pass four
            ans |= judge(CHAIN_SET[d["net"]], named(d, CHAIN_FIELDS))["answers"]
            if d["x_account"]:
                ans |= judge("social", social_state(d))["answers"]
        except Exception as e:
            # 422 means every token hits the same wall; unreachable means no judge.
            # Either way the desk stands down for the cycle. It never falls back to guessing.
            log.error("judge failed on %s, standing down this cycle: %s", d["ticker"], e)
            stats["judge_failed"] = str(e)
            return None, stats                   # no bench: the token is not at fault

        if (k := soft_kill(ans)):
            book.sit(t["tid"], k)
            stats["soft"][k] = stats["soft"].get(k, 0) + 1
            continue

        survivors.append((d, ans))

    log.info("cycle: %(seen)s seen, %(benched)s benched, free %(free)s, "
             "trade %(trade)s, chain %(chain)s, soft %(soft)s", stats)

    # pass five. pick() sends one survivor straight through (a choice over one option
    # proves nothing) and still applies the dark / no-social size cuts.
    order = pick(judge, survivors)
    if order is None:
        return None, stats
    order["order_id"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if shadow:
        desk.log_shadow(order, stats)            # written, never sent
        return None, stats

    book.take(order)          # the desk is now held. No scan until RISK calls release().
    return order, stats


def main(fomo, judge, desk, shadow=True):
    """desk is your Grok Bot side. It has to provide five things:
         bank()                 -> float, free cash right now
         read_x(handle)         -> the X block SOCIAL collects with its plugin, or None
         log_shadow(order, st)  -> append a row for the shadow week
         report(order, stats)   -> one line to Telegram, trade or no trade
         send_to_seats(order)   -> hand it to SIZE, then FILLS, then RISK, in that order
    """
    while True:
        try:
            fomo.token()                         # Privy bearer lives ~60 min, refresh it
            order, stats = run_once(fomo, judge, desk, desk.bank(), shadow)
            desk.report(order, stats)            # every cycle, trade or not
            if order:
                desk.send_to_seats(order)
        except Exception as e:
            log.exception("cycle blew up: %s", e)
        time.sleep(CYCLE_SECONDS)
