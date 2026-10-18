# grok-trading-desk

Le code rapporte, le modèle juge, le code décide.

## Judge (`judge.py`)

Runs on ONE machine. Holds the only TypeSafe (Jev) key. Makes no trading decision.
Bots hold `DESK_SECRET` only, never the key.

```bash
pip install -r requirements.txt
export TYPESAFE_API_KEY=...                     # judge machine only
export DESK_SECRET="$(openssl rand -hex 24)"
uvicorn judge:app --host 127.0.0.1 --port 8080  # tunnel reaches localhost; no need to expose 0.0.0.0
cloudflared tunnel --url http://localhost:8080  # bots run in xAI's cloud, not on your box
```

### Rules

- ONE CALL PER TOKEN, never one per question. State is tokenized once.
- STATE IS A NAMED OBJECT, never a blob. Send only fields the questions read.
- ANSWERS GO BACK RAW. The caller owns the threshold, the judge does not.
- THRESHOLDS DO NOT TRANSFER between primitives. A choice is relative and settles which.
  A noul is absolute and can be low for all of them.
- LOG THE MODEL ID from the response. Aliases move when a release ships.
- ARITHMETIC STAYS IN CODE. Compute it, pass the result in as a field.
- 401 bad key, 422 bad question, 429 rate limit, 529 overloaded. Back off on 429 and 529.
  Never retry a 422.

## Collector (`collect.py`)

Jev fetches nothing. SCAN owns the universe and the shortlist, VET pulls the dossier.

- NEVER invent a number. A field that came back null stays null and the question sees it.
- NEVER let null mean fine. Missing data gets its own option and its own consequence.
- NEVER pull a dossier for a token stage 2 killed. That is a wasted rate limit slot.
- Every GeckoTerminal call goes through `gt_get` (one call per 6s = 10/min).

## Questions (`questions.py`)

Every question the desk can ask lives here and nowhere else. `judge.py` imports `SETS`.

- ROUTE THE CHAIN SET IN CODE. `CHAIN_SET[net]` picks the set written for that chain's evidence.
- `data_coverage` IS A REAL QUESTION. `dark` does not mean skip, it means cut the ticket.
- THE PICK NEEDS `worth_trading_at_all` NEXT TO IT. Choice is relative, noul is the absolute gate.
- THE SUMMARY IN `candidates` IS TWO LINES, assembled in code from answers already given.

## Filter (`thresholds.py` + `filter.py`)

Retune the desk by editing `thresholds.py` and nothing else. `filter.py` is the order they fire in:
`free_kill` (no network, hundreds) -> `trade_kill` (one DexScreener call, tens) ->
`chain_kill` (one GeckoTerminal slot, max 3) -> `soft_kill` (one judgement, a handful).
Facts kill before judgements. Log every rejection with the check that fired.
Fewer than ten rejections a day means the filter is misconfigured, not the market.

## SOCIAL seat (`prompts/social.md`)

A prompt, not a file the desk runs. The handle comes off the chain, already cleaned by the collector.
Never let the seat go looking for "the project's Twitter": it will find a fan account and be confident.
No handle means no social read, and the token carries that as a hole (`NO_SOCIAL_CUT`), not a pass.

## Pick (`pick.py`)

CHIEF runs it. The only call that sees more than one token at once.

- NEVER re-rank the winner. Disagree with a threshold, not with the pick.
- NEVER run pick on one survivor. One survivor already cleared SOFT and goes straight to the bot.
- NEVER skip `worth_trading_at_all`. Choice settles which, the noul settles whether today is a day.
- No trade is a result. Log it with the reason, send it to Telegram, wait for the next cycle.
