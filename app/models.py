"""
Persisted data. The live, in-memory turn-by-turn state of an active debate
lives in app/debate_room.py; what's stored here is the durable record -
what topics exist and what was actually said, so a finished debate can be
looked back on and the server can restart without losing history.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


def new_id() -> str:
    return uuid.uuid4().hex


class Topic(Base):
    __tablename__ = "topics"

    id = Column(String, primary_key=True, default=new_id)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")

    creator_id = Column(String, nullable=False)
    creator_name = Column(String, nullable=False)

    # open -> matched -> closed
    status = Column(String, nullable=False, default="open")

    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("DebateSession", back_populates="topic", uselist=False)


class DebateSession(Base):
    __tablename__ = "debate_sessions"

    id = Column(String, primary_key=True, default=new_id)
    topic_id = Column(String, ForeignKey("topics.id"), nullable=False)

    user_a_id = Column(String, nullable=False)
    user_a_name = Column(String, nullable=False)
    user_b_id = Column(String, nullable=False)
    user_b_name = Column(String, nullable=False)

    # active -> ended
    status = Column(String, nullable=False, default="active")
    end_reason = Column(String, nullable=True)

    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    topic = relationship("Topic", back_populates="session")
    messages = relationship("DebateMessage", back_populates="session",
                             order_by="DebateMessage.created_at")


class DebateMessage(Base):
    __tablename__ = "debate_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("debate_sessions.id"), nullable=False)

    user_id = Column(String, nullable=False)
    user_name = Column(String, nullable=False)
    round_number = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    auto_submitted = Column(Boolean, default=False)  # true if the 5-minute timer ran out

    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("DebateSession", back_populates="messages")
