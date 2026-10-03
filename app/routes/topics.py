"""JSON API for posting, browsing, joining and withdrawing topics."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.identity import suggest_name
from app import matchmaking
from app.realtime import realtime
from app.schemas import TopicCreate, TopicOut, JoinRequest, JoinResponse, CancelRequest, IdentityOut

router = APIRouter(prefix="/api")


@router.get("/identity/name", response_model=IdentityOut)
async def identity_name():
    return IdentityOut(suggested_name=suggest_name())


@router.post("/topics", response_model=TopicOut)
async def post_topic(payload: TopicCreate, db: Session = Depends(get_db)):
    topic = matchmaking.create_topic(
        db, title=payload.title, description=payload.description,
        user_id=payload.user_id, user_name=payload.user_name,
    )
    return TopicOut(
        id=topic.id, title=topic.title, description=topic.description,
        creator_name=topic.creator_name, created_at=topic.created_at.isoformat() + "Z",
        is_mine=True,
    )


@router.get("/topics", response_model=list[TopicOut])
async def get_topics(viewer_id: str = "", db: Session = Depends(get_db)):
    topics = matchmaking.list_open_topics(db, viewer_id=viewer_id)
    return [
        TopicOut(
            id=t.id, title=t.title, description=t.description,
            creator_name=t.creator_name, created_at=t.created_at.isoformat() + "Z",
            is_mine=(t.creator_id == viewer_id),
        )
        for t in topics
    ]


@router.get("/topics/{topic_id}", response_model=TopicOut)
async def get_topic(topic_id: str, viewer_id: str = "", db: Session = Depends(get_db)):
    from app.models import Topic
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if topic is None:
        raise HTTPException(status_code=404, detail="That topic no longer exists.")
    return TopicOut(
        id=topic.id, title=topic.title, description=topic.description,
        creator_name=topic.creator_name, created_at=topic.created_at.isoformat() + "Z",
        is_mine=(topic.creator_id == viewer_id),
    )


@router.post("/topics/{topic_id}/join", response_model=JoinResponse)
async def join_topic(topic_id: str, payload: JoinRequest, db: Session = Depends(get_db)):
    try:
        session = matchmaking.join_topic(db, topic_id, payload.user_id, payload.user_name)
    except matchmaking.TopicError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await realtime.publish_waiting_event(topic_id, {"type": "matched", "session_id": session.id})
    return JoinResponse(session_id=session.id)


@router.post("/topics/{topic_id}/cancel")
async def cancel_topic(topic_id: str, payload: CancelRequest, db: Session = Depends(get_db)):
    try:
        matchmaking.cancel_topic(db, topic_id, payload.user_id)
    except matchmaking.TopicError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await realtime.publish_waiting_event(topic_id, {"type": "cancelled"})
    return {"ok": True}
