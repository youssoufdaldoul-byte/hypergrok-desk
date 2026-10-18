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
