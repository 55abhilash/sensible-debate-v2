"""
Everything about finding an opponent: posting a topic, listing open topics,
and joining one. Once two people are joined to a topic, control passes to
app/debate_room.py for the actual timed exchange.

A topic's row in the database is the source of truth for "is this still
open". The person waiting for someone to join needs to find out the
instant it happens, and needs to find out even if the join request lands
on a *different* process than the one holding their waiting-room
websocket - so that notification goes through Redis Pub/Sub (see
app/realtime.py), not a plain local queue.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Topic, DebateSession
from app.realtime import realtime


class TopicError(Exception):
    """Raised for any matchmaking failure the API layer should report cleanly."""


# topic_id -> local asyncio.Queues waiting for a match/cancel notification.
# Only ever one entry per topic in practice (one browser tab waits per
# topic), but kept as a list for the same reason any pub/sub fan-out is:
# it costs nothing and avoids a subtle assumption baked into the code.
_local_waiters: dict[str, list[asyncio.Queue]] = {}


def register_waiter(topic_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _local_waiters.setdefault(topic_id, []).append(queue)
    return queue


def unregister_waiter(topic_id: str, queue: asyncio.Queue) -> None:
    listeners = _local_waiters.get(topic_id, [])
    if queue in listeners:
        listeners.remove(queue)
    if not listeners:
        _local_waiters.pop(topic_id, None)


async def _on_waiting_event(payload: dict) -> None:
    topic_id = payload.get("topic_id")
    if not topic_id:
        return
    for queue in list(_local_waiters.get(topic_id, [])):
        queue.put_nowait(payload)


realtime.set_waiting_event_handler(_on_waiting_event)


def _expire_stale_topics(db: Session) -> None:
    cutoff = datetime.utcnow() - timedelta(minutes=settings.TOPIC_EXPIRY_MINUTES)
    stale = (
        db.query(Topic)
        .filter(Topic.status == "open", Topic.created_at < cutoff)
        .all()
    )
    for topic in stale:
        topic.status = "closed"
    if stale:
        db.commit()


def create_topic(db: Session, title: str, description: str, user_id: str, user_name: str) -> Topic:
    topic = Topic(
        title=title.strip(),
        description=description.strip(),
        creator_id=user_id,
        creator_name=user_name.strip(),
        status="open",
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


def list_open_topics(db: Session, viewer_id: Optional[str] = None) -> list[Topic]:
    _expire_stale_topics(db)
    return (
        db.query(Topic)
        .filter(Topic.status == "open")
        .order_by(Topic.created_at.desc())
        .limit(50)
        .all()
    )


def cancel_topic(db: Session, topic_id: str, user_id: str) -> None:
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if topic is None:
        raise TopicError("That topic no longer exists.")
    if topic.creator_id != user_id:
        raise TopicError("Only the person who opened a topic can withdraw it.")
    if topic.status != "open":
        raise TopicError("That topic isn't open anymore.")
    topic.status = "closed"
    db.commit()


def join_topic(db: Session, topic_id: str, user_id: str, user_name: str) -> DebateSession:
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if topic is None:
        raise TopicError("That topic no longer exists.")
    if topic.status != "open":
        raise TopicError("Someone else just joined this topic. Pick another one.")
    if topic.creator_id == user_id:
        raise TopicError("You opened this topic - wait for someone else to join it.")

    session = DebateSession(
        topic_id=topic.id,
        user_a_id=topic.creator_id,
        user_a_name=topic.creator_name,
        user_b_id=user_id,
        user_b_name=user_name.strip(),
        status="active",
    )
    topic.status = "matched"
    db.add(session)
    db.commit()
    db.refresh(session)
    return session
