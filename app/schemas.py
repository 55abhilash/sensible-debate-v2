"""Pydantic request/response shapes for the JSON API."""
from typing import Optional
from pydantic import BaseModel, Field


class TopicCreate(BaseModel):
    title: str = Field(..., min_length=4, max_length=200)
    description: str = Field("", max_length=1000)
    user_id: str
    user_name: str = Field(..., min_length=1, max_length=60)


class TopicOut(BaseModel):
    id: str
    title: str
    description: str
    creator_name: str
    created_at: str
    is_mine: bool = False


class JoinRequest(BaseModel):
    user_id: str
    user_name: str = Field(..., min_length=1, max_length=60)


class JoinResponse(BaseModel):
    session_id: str


class CancelRequest(BaseModel):
    user_id: str


class IdentityOut(BaseModel):
    suggested_name: str
