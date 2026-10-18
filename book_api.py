# book_api.py
# RISK runs in xAI's cloud and cannot call book.release() in this process.
# This is its one door. It takes RISK_SECRET, which only the RISK seat holds:
# not DESK_SECRET, so no other seat can free the book.
import hmac, os
from fastapi import APIRouter, Header, HTTPException
import book

RISK_SECRET = os.environ["RISK_SECRET"]
router = APIRouter()


@router.post("/release")
def release(authorization: str = Header("")):
    if not hmac.compare_digest(authorization, f"Bearer {RISK_SECRET}"):
        raise HTTPException(401, "bad risk secret")
    was = book.held()
    book.release()
    return {"released": was["ticker"] if was else None}
