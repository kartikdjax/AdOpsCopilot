"""Persistent, user-scoped chat history APIs."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth import get_current_user
from src.api.db import get_db

router = APIRouter(prefix="/history", tags=["chat history"])


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_chat(row: Any, include_messages: bool = True) -> dict[str, Any]:
    item = {"id": row["id"], "mode": row["mode"], "title": row["title"], "created_at": row["created_at"], "updated_at": row["updated_at"]}
    if include_messages:
        item["messages"] = json.loads(row["messages_json"])
        item["tool_calls_made"] = json.loads(row["tool_calls_json"])
    return item


class SaveChatRequest(BaseModel):
    chat_id: str | None = Field(default=None, max_length=80)
    mode: str = Field(pattern="^(revive|exchange)$")
    messages: list[dict[str, Any]]
    tool_calls_made: list[str] = []
    title: str | None = Field(default=None, max_length=120)


@router.get("")
def list_history(user=Depends(get_current_user)):
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM chats WHERE user_id=? ORDER BY updated_at DESC LIMIT 100", (user["id"],)).fetchall()
        return {"chats": [_row_to_chat(r, False) for r in rows]}
    finally:
        db.close()


@router.get("/{chat_id}")
def get_chat(chat_id: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Chat not found")
        return _row_to_chat(row)
    finally:
        db.close()


@router.put("/{chat_id}")
def save_chat(chat_id: str, payload: SaveChatRequest, user=Depends(get_current_user)):
    db = get_db()
    try:
        if payload.chat_id and payload.chat_id != chat_id:
            raise HTTPException(status_code=400, detail="chat_id mismatch")
        title = (payload.title or _derive_title(payload.messages))[:120]
        stamp = now()
        existing = db.execute("SELECT id FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"])).fetchone()
        if existing:
            db.execute("UPDATE chats SET mode=?, title=?, messages_json=?, tool_calls_json=?, updated_at=? WHERE id=? AND user_id=?", (payload.mode, title, json.dumps(payload.messages), json.dumps(payload.tool_calls_made), stamp, chat_id, user["id"]))
        else:
            db.execute("INSERT INTO chats VALUES(?,?,?,?,?,?,?)", (chat_id, user["id"], payload.mode, title, json.dumps(payload.messages), json.dumps(payload.tool_calls_made), stamp, stamp))
        db.commit()
        return {"chat": {"id": chat_id, "mode": payload.mode, "title": title, "updated_at": stamp}}
    finally:
        db.close()


@router.delete("/{chat_id}")
def delete_chat(chat_id: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        cur = db.execute("DELETE FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"]))
        db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Chat not found")
        return {"status": "deleted"}
    finally:
        db.close()


@router.delete("")
def clear_history(user=Depends(get_current_user)):
    db = get_db()
    try:
        db.execute("DELETE FROM chats WHERE user_id=?", (user["id"],))
        db.commit()
        return {"status": "cleared"}
    finally:
        db.close()


def _derive_title(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") == "user" and message.get("content"):
            text = " ".join(str(message["content"]).split())
            return text[:80] + ("…" if len(text) > 80 else "")
    return "New conversation"
