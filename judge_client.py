# judge_client.py
import os, time, requests

URL, SECRET = os.environ["JUDGE_URL"], os.environ["DESK_SECRET"]
RETRY = {429, 500, 502, 503, 529}      # 500: the judge does not yet map SDK 429/529, see judge.py


def judge(question_set: str, state: dict, tries: int = 4) -> dict:
    for i in range(tries):
        r = requests.post(URL, timeout=30,
                          headers={"Authorization": f"Bearer {SECRET}"},
                          json={"question_set": question_set, "state": state})
        if r.status_code == 422:        # the question is wrong and will stay wrong. never retry.
            raise RuntimeError(f"malformed question set {question_set}: {r.text}")
        if r.status_code not in RETRY or i == tries - 1:
            break
        time.sleep(2 ** (i + 1))        # 2, 4, 8s
    r.raise_for_status()
    return r.json()
