"""
A quick, dependency-light smoke test for the whole matching + debate flow.

This isn't a full pytest suite - it's a single script that plays both
sides of a debate over real WebSockets against a server you already have
running, so you can confirm a change didn't break the turn-taking logic
before you deploy it.

Usage:
    # Terminal 1 - run the server with short timers so the test finishes quickly
    SD_ARGUMENT_SECONDS=3 SD_REFLECTION_SECONDS=2 python run.py

    # Terminal 2
    pip install -r requirements-dev.txt
    python tests/end_to_end_check.py
"""
import asyncio
import json
import sys

import httpx
import websockets

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"


async def wait_for(ws, predicate, timeout=10):
    async def _loop():
        while True:
            msg = json.loads(await ws.recv())
            if predicate(msg):
                return msg
    return await asyncio.wait_for(_loop(), timeout=timeout)


async def main():
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{BASE}/api/topics", json={
            "title": "Should cats be allowed outdoors?",
            "description": "Smoke test topic",
            "user_id": "user-a", "user_name": "Thoughtful Heron",
        })
        r.raise_for_status()
        topic = r.json()
        print("created topic:", topic["id"])

        r = await client.get(f"{BASE}/api/topics", params={"viewer_id": "user-b"})
        assert any(t["id"] == topic["id"] for t in r.json()), "topic not listed for another viewer"
        print("topic listed for other viewer: OK")

        r = await client.post(f"{BASE}/api/topics/{topic['id']}/join", json={
            "user_id": "user-b", "user_name": "Curious Fox",
        })
        r.raise_for_status()
        session_id = r.json()["session_id"]
        print("joined, session:", session_id)

        r = await client.post(f"{BASE}/api/topics/{topic['id']}/join", json={
            "user_id": "user-c", "user_name": "Someone Else",
        })
        assert r.status_code == 409, "joining an already-matched topic should fail"
        print("double-join correctly rejected: OK")

    async with websockets.connect(
        f"{WS}/ws/debate/{session_id}?user_id=user-a&name=Thoughtful+Heron"
    ) as wsa, websockets.connect(
        f"{WS}/ws/debate/{session_id}?user_id=user-b&name=Curious+Fox"
    ) as wsb:

        sa = await wait_for(wsa, lambda m: m["phase"] == "arguing")
        sb = await wait_for(wsb, lambda m: m["phase"] == "arguing")
        assert sa["your_turn"] is True and sb["your_turn"] is False
        print("round 1 opens with the topic's creator: OK")

        await wsa.send(json.dumps({"type": "submit", "text": "Cats should stay indoors for their own safety."}))
        sa = await wait_for(wsa, lambda m: m["phase"] == "reflecting")
        assert len(sa["messages"]) == 1 and sa["messages"][0]["auto_submitted"] is False
        print("explicit submit moves to reflection: OK")

        sb = await wait_for(wsb, lambda m: m["phase"] == "arguing" and m["your_turn"], timeout=8)
        print("reflection times out into the other person's turn: OK")

        sa = await wait_for(wsa, lambda m: m["phase"] == "reflecting" and m["messages"][-1]["auto_submitted"], timeout=8)
        print("an unanswered turn auto-submits when time runs out: OK")

        sa = await wait_for(wsa, lambda m: m["phase"] == "arguing" and m["your_turn"], timeout=8)
        assert sa["round"] == 2
        print("round counter advances correctly: OK")

        await wsa.send(json.dumps({"type": "leave"}))
        sa = await wait_for(wsa, lambda m: m["phase"] == "ended")
        sb = await wait_for(wsb, lambda m: m["phase"] == "ended")
        assert sa["ended_by_you"] is True and sb["ended_by_you"] is False
        print("leaving ends the debate for both sides: OK")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        sys.exit(1)
