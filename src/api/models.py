"""Pydantic request/response schemas for the API."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    mode: str = Field(default="revive", pattern="^(revive|exchange)$")

class ChatResponse(BaseModel):
    chat_id: str
    answer: str
    tool_calls_made: list[str]

class HealthResponse(BaseModel):
    status: str
    provider: str
    active_sessions: int
