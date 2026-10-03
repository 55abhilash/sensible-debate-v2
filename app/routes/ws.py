"""
Websocket endpoints. There are two: one for the "waiting for someone to
join my topic" page, and one for the debate room itself. Identity is
passed as a query parameter (?user_id=...&name=...) because it is
generated client-side in localStorage - see static/js/identity.js -
rather than through a login system, which v1 deliberately doesn't have.

Both endpoints work no matter which process handles the connection -
see app/realtime.py, app/matchmaking.py and app/debate_room.py for how
that coordination actually happens.
"""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import matchmaking, debate_room

router = APIRouter()


@router.websocket("/ws/waiting/{topic_id}")
async def waiting_socket(websocket: WebSocket, topic_id: str):
    await websocket.accept()
    queue = matchmaking.register_waiter(topic_id)
    try:
        while True:
            get_task = asyncio.ensure_future(queue.get())
            recv_task = asyncio.ensure_future(websocket.receive_text())
            done, pending = await asyncio.wait(
                {get_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()

            if get_task in done:
                message = get_task.result()
                await websocket.send_json(message)
                if message.get("type") in ("matched", "cancelled"):
                    break

            if recv_task in done:
                recv_task.result()  # raises WebSocketDisconnect if the tab closed
    except WebSocketDisconnect:
        pass
    finally:
        matchmaking.unregister_waiter(topic_id, queue)


@router.websocket("/ws/debate/{session_id}")
async def debate_socket(websocket: WebSocket, session_id: str):
    user_id = websocket.query_params.get("user_id", "")
    user_name = websocket.query_params.get("name", "Anonymous")
    await websocket.accept()

    try:
        state = await debate_room.connect(session_id, user_id, user_name)
    except debate_room.UnknownSession:
        await websocket.send_json({"type": "error", "detail": "This debate no longer exists."})
        await websocket.close()
        return
    except debate_room.NotAParticipant:
        await websocket.send_json({"type": "error", "detail": "You are not part of this debate."})
        await websocket.close()
        return

    debate_room.register_local(session_id, user_id, websocket)
    await websocket.send_json(debate_room.viewer_payload(state, user_id))

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "submit":
                await debate_room.submit(session_id, user_id, data.get("text", ""))
            elif msg_type == "leave":
                await debate_room.leave(session_id, user_id)
    except WebSocketDisconnect:
        pass
    finally:
        debate_room.unregister_local(session_id, user_id, websocket)
        await debate_room.disconnect(session_id, user_id)
