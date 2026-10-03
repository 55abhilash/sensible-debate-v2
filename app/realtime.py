"""
Cross-process coordination, via Redis.

The moment this app runs as more than one process - which is what
autoscaling means by definition - nothing that needs to be seen by
"whichever process the other participant happens to be connected to"
can live only in one process's memory anymore. This module is the
shared layer that makes that work:

  - live debate state (phase, turn, round, deadline, messages-so-far)
    is stored in Redis as a small JSON blob, not in a Python object
  - one Redis Pub/Sub channel relays "this debate's state changed" to
    every process, so whichever process holds each participant's actual
    websocket can push the update down to them
  - a Redis sorted set of "session id -> deadline timestamp", claimed
    with an atomic ZREM, makes sure a 5-minute argument timer or
    2-minute reflection timer fires exactly once - even though every
    process is independently watching for expired ones
  - a short-lived Redis lock (SET ... NX) makes sure that when both
    participants connect at nearly the same moment (quite possibly to
    two different processes), only one process actually starts the
    debate

Durable history (topics, finished messages) still goes through
SQLAlchemy to the real database exactly as before - this module is
only for short-lived, ephemeral, "right now" coordination. See
app/debate_room.py and app/matchmaking.py for how it's used.
"""
import asyncio
import json
import logging
import time
from typing import Awaitable, Callable, Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger("sensible_debate.realtime")

STATE_KEY = "sd:room:{session_id}:state"
STATE_TTL_SECONDS = 6 * 60 * 60  # comfortably longer than any realistic debate
CONNECTED_KEY = "sd:room:{session_id}:connected"
START_LOCK_KEY = "sd:room:{session_id}:starting"
DEADLINES_KEY = "sd:deadlines"
ROOM_EVENTS_CHANNEL = "sd:room-events"
WAITING_EVENTS_CHANNEL = "sd:waiting-events"

RoomEventHandler = Callable[[dict], Awaitable[None]]
WaitingEventHandler = Callable[[dict], Awaitable[None]]
DeadlineHandler = Callable[[str], Awaitable[None]]


class Realtime:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._sweeper_task: Optional[asyncio.Task] = None
        self._room_event_handler: Optional[RoomEventHandler] = None
        self._waiting_event_handler: Optional[WaitingEventHandler] = None
        self._deadline_handler: Optional[DeadlineHandler] = None

    # -- lifecycle ---------------------------------------------------

    async def start(self) -> None:
        self.redis = aioredis.from_url(self._redis_url, decode_responses=True)
        await self.redis.ping()
        self._pubsub = self.redis.pubsub()
        await self._pubsub.subscribe(ROOM_EVENTS_CHANNEL, WAITING_EVENTS_CHANNEL)
        self._listener_task = asyncio.create_task(self._listen_loop())
        self._sweeper_task = asyncio.create_task(self._sweep_loop())
        logger.info("realtime: connected to redis, listener and sweeper running")

    async def stop(self) -> None:
        for task in (self._listener_task, self._sweeper_task):
            if task:
                task.cancel()
        if self._pubsub:
            await self._pubsub.aclose()
        if self.redis:
            await self.redis.aclose()

    # -- handler registration (each module wires itself up on import) --

    def set_room_event_handler(self, handler: RoomEventHandler) -> None:
        self._room_event_handler = handler

    def set_waiting_event_handler(self, handler: WaitingEventHandler) -> None:
        self._waiting_event_handler = handler

    def set_deadline_handler(self, handler: DeadlineHandler) -> None:
        self._deadline_handler = handler

    # -- background loops ---------------------------------------------

    async def _listen_loop(self) -> None:
        assert self._pubsub is not None
        async for message in self._pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, ValueError):
                continue
            channel = message["channel"]
            handler = (
                self._room_event_handler
                if channel == ROOM_EVENTS_CHANNEL
                else self._waiting_event_handler
            )
            if handler is None:
                continue
            try:
                await handler(payload)
            except Exception:
                logger.exception("event handler failed for channel %s", channel)

    async def _sweep_loop(self) -> None:
        """Runs on every process. Whichever process's ZREM actually
        removes a given session id is the one that processes its
        timeout - everyone else's ZREM for the same id returns 0."""
        while True:
            try:
                await asyncio.sleep(1)
                if self.redis is None:
                    continue
                now = time.time()
                due = await self.redis.zrangebyscore(DEADLINES_KEY, min=0, max=now)
                for session_id in due:
                    claimed = await self.redis.zrem(DEADLINES_KEY, session_id)
                    if claimed and self._deadline_handler:
                        asyncio.create_task(self._deadline_handler(session_id))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("deadline sweep failed")
                await asyncio.sleep(1)

    # -- room state ------------------------------------------------------

    async def get_state(self, session_id: str) -> Optional[dict]:
        raw = await self.redis.get(STATE_KEY.format(session_id=session_id))
        return json.loads(raw) if raw else None

    async def set_state(self, session_id: str, state: dict) -> None:
        await self.redis.set(
            STATE_KEY.format(session_id=session_id), json.dumps(state), ex=STATE_TTL_SECONDS
        )

    async def publish_room_state(self, session_id: str, state: dict) -> None:
        await self.redis.publish(
            ROOM_EVENTS_CHANNEL, json.dumps({"session_id": session_id, "state": state})
        )

    async def save_and_publish(self, session_id: str, state: dict) -> None:
        await self.set_state(session_id, state)
        await self.publish_room_state(session_id, state)

    # -- connection presence (who's actually online right now, anywhere) --

    async def add_connected(self, session_id: str, user_id: str) -> list[str]:
        key = CONNECTED_KEY.format(session_id=session_id)
        await self.redis.sadd(key, user_id)
        await self.redis.expire(key, STATE_TTL_SECONDS)
        return list(await self.redis.smembers(key))

    async def remove_connected(self, session_id: str, user_id: str) -> list[str]:
        key = CONNECTED_KEY.format(session_id=session_id)
        await self.redis.srem(key, user_id)
        return list(await self.redis.smembers(key))

    # -- one-shot coordination primitives ---------------------------------

    async def try_acquire_start_lock(self, session_id: str) -> bool:
        """True if THIS call is the one that gets to start the debate."""
        key = START_LOCK_KEY.format(session_id=session_id)
        return bool(await self.redis.set(key, "1", nx=True, ex=30))

    async def schedule_deadline(self, session_id: str, deadline_ts: float) -> None:
        await self.redis.zadd(DEADLINES_KEY, {session_id: deadline_ts})

    async def cancel_deadline(self, session_id: str) -> bool:
        """True if a pending deadline was actually removed by this call -
        used as a lightweight mutex: if it's False, something else (the
        timeout sweeper) already claimed this turn's ending first."""
        removed = await self.redis.zrem(DEADLINES_KEY, session_id)
        return bool(removed)

    async def waiting_room_users(self) -> None:  # pragma: no cover - unused, kept for symmetry
        return None

    async def publish_waiting_event(self, topic_id: str, payload: dict) -> None:
        await self.redis.publish(
            WAITING_EVENTS_CHANNEL, json.dumps({"topic_id": topic_id, **payload})
        )


realtime = Realtime(settings.REDIS_URL)
