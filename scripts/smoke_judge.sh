#!/usr/bin/env bash
# Prove the link FROM A BOT'S TERMINAL, not from your laptop.
# Passing on your machine and failing on theirs is a firewall problem, and that is how
# this setup dies quietly.
set -euo pipefail
: "${JUDGE_URL:?set JUDGE_URL}" "${DESK_SECRET:?set DESK_SECRET}"

curl -sS --fail-with-body -X POST "$JUDGE_URL" \
  -H "Authorization: Bearer $DESK_SECRET" -H "Content-Type: application/json" \
  -d '{"question_set":"market","state":{"ticker":"TEST","age_minutes":42,
       "holder_count":310,"change":{"5m":0.04,"1h":0.22,"24h":0.61},
       "buys_h1":540,"sells_h1":120,"liquidity_usd":48000,"mcap_usd":310000,
       "volume_h24":610000,"intended_ticket_usd":900}}' |
python3 -c '
import json, re, sys
r = json.load(sys.stdin)
s = r["answers"]["shape"]
ok = True
if s["choice"] not in ("crowd", "one_buyer", "fading", "too_early"):
    print("FAIL choice not one of the options:", s["choice"]); ok = False
if abs(sum(s["probabilities"].values()) - 1) > 1e-3:
    print("FAIL probabilities sum to", sum(s["probabilities"].values())); ok = False
if not re.search(r"\d+\.\d+\.\d+", r["model"]):
    print("FAIL model is an alias, not a version:", r["model"]); ok = False
print(json.dumps(r, indent=2))
sys.exit(0 if ok else 1)
'
echo "OK: choice valid, probabilities sum to 1, model is versioned"
