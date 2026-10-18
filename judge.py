import hmac
import os
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typesafe_sdk import AsyncTypeSafeClient
from questions import SETS
from book_api import router as book_router

DESK_SECRET = os.environ["DESK_SECRET"]     # for the bots. NOT the TypeSafe key.
client = AsyncTypeSafeClient()              # reads TYPESAFE_API_KEY itself
app = FastAPI()
app.include_router(book_router)       # POST /release, RISK only


class Ask(BaseModel):
    question_set: str
    state: dict


@app.post("/judge")
async def judge(ask: Ask, authorization: str = Header("")):
    # constant-time compare: a plain != leaks the secret byte by byte through timing.
    if not hmac.compare_digest(authorization, f"Bearer {DESK_SECRET}"):
        raise HTTPException(401, "bad desk secret")
    if ask.question_set not in SETS:
        raise HTTPException(422, f"unknown question set {ask.question_set}")

    qs = SETS[ask.question_set]
    qs = qs(ask.state) if callable(qs) else qs        # pick builds options at call time

    r = await client.system_one(state=ask.state, questions=qs)

    # raw answers out. never flattened, never thresholded here.
    return {"model": r.model,
            "answers": {k: v.model_dump() for k, v in r.answers.items()},
            "usage": r.usage.model_dump()}
