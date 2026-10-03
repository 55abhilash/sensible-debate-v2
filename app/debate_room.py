"""
The turn-by-turn debate logic.

Unlike the single-process version of this app, there is no long-lived
"Room" object here anymore - state is a plain dict that lives in Redis
(via app/realtime.py), and every function below reads it, computes the
next state, and writes it back. That's what lets any process handle any
request: a process only ever needs two small pieces of purely local
information, kept in the module-level dict below:

    _local_connections[session_id][user_id] -> the websocket THIS
    process is holding for that person, if any.

Everything else - whose turn it is, how much time is left, the full
transcript - is shared, authoritative Redis state. When it changes,
every process is notified over Pub/Sub and pushes the update to
whichever local websockets it happens to be holding for that debate.

Phase cycle between user A (the topic's opener) and user B:

    waiting -> arguing(A) -> reflecting -> arguing(B) -> reflecting -> arguing(A) -> ...

"waiting" lasts until both people's browsers have an open websocket to
the room - to *any* process - which is what stops the clock from
starting before the second person has actually arrived.
"""
import asyncio
import time
from datetime import datetime
from typing import Optional

from fastapi import WebSocket

from app.config import settings
from app.database import get_session
from app.models import DebateSession, DebateMessage, Topic
from app.realtime import realtime


class UnknownSession(Exception):
    pass


class NotAParticipant(Exception):
    pass


# session_id -> user_id -> websocket THIS process is holding
_local_connections: dict[str, dict[str, WebSocket]] = {}


def register_local(session_id: str, user_id: str, ws: WebSocket) -> None:
    _local_connections.setdefault(session_id, {})[user_id] = ws


def unregister_local(session_id: str, user_id: str, ws: WebSocket) -> None:
    conns = _local_connections.get(session_id)
    if conns and conns.get(user_id) is ws:
        del conns[user_id]
        if not conns:
            _local_connections.pop(session_id, None)


# -- loading / building state ------------------------------------------

def _load_session_and_topic_sync(session_id: str):
    db = get_session()
    try:
        session = db.query(DebateSession).filter(DebateSession.id == session_id).first()
        if session is None:
            return None, None, []
        topic = db.query(Topic).filter(Topic.id == session.topic_id).first()
        messages = [
            {
                "user_id": m.user_id,
                "user_name": m.user_name,
                "round": m.round_number,
                "text": m.text,
                "auto_submitted": m.auto_submitted,
                "created_at": m.created_at.isoformat() + "Z",
            }
            for m in session.messages
        ]
        return session, topic, messages
    finally:
        db.close()


def _persist_message_sync(session_id: str, user_id: str, user_name: str, round_number: int, text: str, auto: bool) -> None:
    db = get_session()
    try:
        db.add(DebateMessage(
            session_id=session_id, user_id=user_id, user_name=user_name,
            round_number=round_number, text=text, auto_submitted=auto,
        ))
        db.commit()
    finally:
        db.close()


def _persist_ended_sync(session_id: str, reason: str) -> None:
    db = get_session()
    try:
        record = db.query(DebateSession).filter(DebateSession.id == session_id).first()
        if record:
            record.status = "ended"
            record.end_reason = reason
            record.ended_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


async def _build_initial_state(session_id: str) -> dict:
    session, topic, messages = await asyncio.to_thread(_load_session_and_topic_sync, session_id)
    if session is None:
        raise UnknownSession(f"No debate with id {session_id}")

    if session.status == "ended":
        return {
            "session_id": session_id,
            "topic_title": topic.title if topic else "(topic unavailable)",
            "topic_description": topic.description if topic else "",
            "user_a_id": session.user_a_id, "user_a_name": session.user_a_name,
            "user_b_id": session.user_b_id, "user_b_name": session.user_b_name,
            "turn_index": 0,
            "round": 1,
            "phase": "ended",
            "deadline": None,
            "duration_seconds": None,
            "end_reason": session.end_reason or "unknown",
            "ended_by": None,
            "connected_user_ids": [],
            "messages": messages,
        }

    # Still active in the database, but Redis has no live state for it -
    # either nobody has connected yet (the normal case), or Redis lost
    # its memory of an in-progress debate (a restart, an eviction - rare,
    # and documented as a known trade-off). Either way, resume sensibly:
    # if there's already a transcript, pick up with a fresh turn for
    # whoever's turn is next, rather than dropping back to "waiting" and
    # asking both people to reconnect from scratch.
    if messages:
        last = messages[-1]
        if last["user_id"] == session.user_a_id:
            turn_index, round_number, phase = 1, last["round"], "arguing"
        else:
            turn_index, round_number, phase = 0, last["round"] + 1, "arguing"
    else:
        turn_index, round_number, phase = 0, 1, "waiting"

    state = {
        "session_id": session_id,
        "topic_title": topic.title if topic else "(topic unavailable)",
        "topic_description": topic.description if topic else "",
        "user_a_id": session.user_a_id, "user_a_name": session.user_a_name,
        "user_b_id": session.user_b_id, "user_b_name": session.user_b_name,
        "turn_index": turn_index,
        "round": round_number,
        "phase": "waiting",
        "deadline": None,
        "duration_seconds": None,
        "end_reason": None,
        "ended_by": None,
        "connected_user_ids": [],
        "messages": messages,
    }
    if phase == "arguing":
        state = _begin_argument_phase(state)
        await realtime.schedule_deadline(session_id, state["deadline"])
    return state


async def _get_state(session_id: str) -> Optional[dict]:
    state = await realtime.get_state(session_id)
    if state is not None:
        return state
    return await _build_initial_state(session_id)


# -- pure phase transitions (no I/O) ------------------------------------

def _current_turn_user_id(state: dict) -> Optional[str]:
    if state["phase"] != "arguing":
        return None
    return state["user_a_id"] if state["turn_index"] == 0 else state["user_b_id"]

def _current_turn_user_name(state: dict) -> str:
    return state["user_a_name"] if state["turn_index"] == 0 else state["user_b_name"]

def _begin_argument_phase(state: dict) -> dict:
    state["phase"] = "arguing"
    state["deadline"] = time.time() + settings.ARGUMENT_SECONDS
    state["duration_seconds"] = settings.ARGUMENT_SECONDS
    return state

def _enter_reflect(state: dict) -> dict:
    state["phase"] = "reflecting"
    state["deadline"] = time.time() + settings.REFLECTION_SECONDS
    state["duration_seconds"] = settings.REFLECTION_SECONDS
    return state

def _end(state: dict, reason: str, ended_by: Optional[str]) -> dict:
    state["phase"] = "ended"
    state["deadline"] = None
    state["duration_seconds"] = None
    state["end_reason"] = reason
    state["ended_by"] = ended_by
    return state

def _append_message(state: dict, user_id: str, text: str, auto: bool) -> None:
    state["messages"].append({
        "user_id": user_id,
        "user_name": state["user_a_name"] if user_id == state["user_a_id"] else state["user_b_name"],
        "round": state["round"],
        "text": text,
        "auto_submitted": auto,
        "created_at": datetime.utcnow().isoformat() + "Z",
    })


# -- public API, called from routes/ws.py -----------------------------

async def connect(session_id: str, user_id: str, user_name_hint: str) -> dict:
    state = await _get_state(session_id)
    if user_id not in (state["user_a_id"], state["user_b_id"]):
        raise NotAParticipant()

    if state["phase"] != "ended":
        connected = await realtime.add_connected(session_id, user_id)
        state["connected_user_ids"] = connected

        if state["phase"] == "waiting" and len(connected) >= 2:
            if await realtime.try_acquire_start_lock(session_id):
                state = _begin_argument_phase(state)
                await realtime.schedule_deadline(session_id, state["deadline"])

    await realtime.save_and_publish(session_id, state)
    return state


async def disconnect(session_id: str, user_id: str) -> None:
    state = await _get_state(session_id)
    if state["phase"] == "ended":
        return
    connected = await realtime.remove_connected(session_id, user_id)
    state["connected_user_ids"] = connected
    await realtime.save_and_publish(session_id, state)


async def submit(session_id: str, user_id: str, text: str) -> None:
    text = (text or "").strip()
    if not text:
        return

    state = await _get_state(session_id)
    if state["phase"] != "arguing" or _current_turn_user_id(state) != user_id:
        return

    won_race = await realtime.cancel_deadline(session_id)
    if not won_race:
        return  # the timeout sweeper already closed this turn out

    state = await _get_state(session_id)
    if state["phase"] != "arguing":
        return

    _append_message(state, user_id, text, auto=False)
    await asyncio.to_thread(
        _persist_message_sync, session_id, user_id,
        state["messages"][-1]["user_name"], state["round"], text, False,
    )
    state = _enter_reflect(state)
    await realtime.schedule_deadline(session_id, state["deadline"])
    await realtime.save_and_publish(session_id, state)


async def leave(session_id: str, user_id: str) -> None:
    state = await _get_state(session_id)
    if state["phase"] == "ended":
        return
    await realtime.cancel_deadline(session_id)
    state = _end(state, reason="left", ended_by=user_id)
    await asyncio.to_thread(_persist_ended_sync, session_id, "left")
    await realtime.save_and_publish(session_id, state)


async def handle_deadline(session_id: str) -> None:
    state = await _get_state(session_id)

    if state["phase"] == "arguing":
        user_id = _current_turn_user_id(state)
        _append_message(state, user_id, "No response was submitted in time.", auto=True)
        await asyncio.to_thread(
            _persist_message_sync, session_id, user_id,
            _current_turn_user_name(state), state["round"],
            "No response was submitted in time.", True,
        )
        state = _enter_reflect(state)
        await realtime.schedule_deadline(session_id, state["deadline"])
        await realtime.save_and_publish(session_id, state)

    elif state["phase"] == "reflecting":
        state["turn_index"] = 1 - state["turn_index"]
        if state["turn_index"] == 0:
            state["round"] += 1
        if settings.MAX_ROUNDS and state["round"] > settings.MAX_ROUNDS:
            state = _end(state, reason="rounds_complete", ended_by=None)
            await asyncio.to_thread(_persist_ended_sync, session_id, "rounds_complete")
        else:
            state = _begin_argument_phase(state)
            await realtime.schedule_deadline(session_id, state["deadline"])
        await realtime.save_and_publish(session_id, state)

    # any other phase means this deadline is stale (already handled by
    # an explicit action that also cancelled it) - nothing to do.


# -- building what a specific viewer's browser should see -----------------

def viewer_payload(state: dict, viewer_id: str) -> dict:
    is_a = viewer_id == state["user_a_id"]
    opponent_id = state["user_b_id"] if is_a else state["user_a_id"]
    opponent_name = state["user_b_name"] if is_a else state["user_a_name"]
    you_name = state["user_a_name"] if is_a else state["user_b_name"]
    turn_user_id = _current_turn_user_id(state)

    return {
        "type": "state",
        "session_id": state["session_id"],
        "topic": {"title": state["topic_title"], "description": state["topic_description"]},
        "phase": state["phase"],
        "round": state["round"],
        "turn_user_id": turn_user_id,
        "your_turn": turn_user_id == viewer_id,
        "deadline": (
            datetime.utcfromtimestamp(state["deadline"]).isoformat() + "Z"
            if state["deadline"] else None
        ),
        "duration_seconds": state["duration_seconds"],
        "end_reason": state["end_reason"],
        "ended_by_you": (state["ended_by"] == viewer_id) if state["ended_by"] else None,
        "you": {"id": viewer_id, "name": you_name},
        "opponent": {
            "id": opponent_id, "name": opponent_name,
            "connected": opponent_id in state.get("connected_user_ids", []),
        },
        "messages": state["messages"],
    }


# -- wiring this process into the shared Redis event stream -----------

async def _on_room_event(payload: dict) -> None:
    session_id = payload.get("session_id")
    state = payload.get("state")
    if not session_id or not state:
        return
    conns = _local_connections.get(session_id)
    if not conns:
        return
    for user_id, ws in list(conns.items()):
        try:
            await ws.send_json(viewer_payload(state, user_id))
        except Exception:
            unregister_local(session_id, user_id, ws)


realtime.set_room_event_handler(_on_room_event)
realtime.set_deadline_handler(handle_deadline)
