"""FastAPI backend for the AI Analytics Copilot."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from mcp import Client

from src.api.auth import get_current_user, router as auth_router, user_scope
from src.api.history import router as history_router
from src.api.mcp_guidance import router as mcp_router
from src.api.models import ChatRequest, ChatResponse, HealthResponse
from src.api.tour import router as tour_router
from src.config import get_settings
from src.llm_providers.groq_provider import AllModelsFailedError
from src.mcp_server import mcp
from src.orchestrator import answer_question
from src.provider_factory import build_provider
from src.api.db import get_db

logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger(__name__)
app_state: dict[str, object] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting up: provider=%s", settings.llm_provider)
    app_state["settings"] = settings
    app_state["provider"] = build_provider(settings)
    # Remove expired sessions at startup; SQLite remains the source of truth.
    db = get_db()
    try:
        from datetime import datetime, timezone
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (datetime.now(timezone.utc).isoformat(),))
        db.commit()
    finally:
        db.close()
    async with Client(mcp) as mcp_client:
        app_state["mcp_client"] = mcp_client
        app.state.app_state = app_state
        logger.info("Ready.")
        yield
    app_state.clear()

app = FastAPI(title="AI Analytics Copilot", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(history_router)
app.include_router(mcp_router)
app.include_router(tour_router)

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user=Depends(get_current_user)) -> ChatResponse:
    from src.api.history import _derive_title, now
    import json
    import secrets
    scope = user_scope(user)
    if request.mode == "revive" and scope is None:
        raise HTTPException(status_code=403, detail=(
            "Your account doesn't have Revive access yet. Ask a Copilot admin to grant you "
            "the admin or manager role."))
    db = get_db()
    try:
        row = db.execute("SELECT * FROM chats WHERE id=? AND user_id=?", (request.session_id, user["id"])).fetchone()
        history = json.loads(row["messages_json"]) if row else []
        # A mode switch intentionally starts a fresh thread to avoid cross-domain context.
        if row and row["mode"] != request.mode:
            history = []
            db.execute("UPDATE chats SET mode=?, messages_json='[]', tool_calls_json='[]', title='New conversation', updated_at=? WHERE id=? AND user_id=?", (request.mode, now(), request.session_id, user["id"]))
            db.commit()
    finally:
        db.close()

    try:
        result = await answer_question(request.message, app_state["mcp_client"], app_state["provider"], conversation_history=history, mode=request.mode, scope=scope)  # type: ignore[arg-type]
    except AllModelsFailedError as e:
        logger.error("LLM request failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        logger.exception("Unexpected error handling chat request")
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again.")

    messages = result["messages"]
    stamp = now()
    db = get_db()
    try:
        title = _derive_title(messages)
        db.execute("""INSERT INTO chats(id,user_id,mode,title,messages_json,tool_calls_json,created_at,updated_at)
                      VALUES(?,?,?,?,?,?,?,?)
                      ON CONFLICT(id) DO UPDATE SET mode=excluded.mode,title=excluded.title,messages_json=excluded.messages_json,tool_calls_json=excluded.tool_calls_json,updated_at=excluded.updated_at""",
                   (request.session_id, user["id"], request.mode, title, json.dumps(messages), json.dumps(result["tool_calls_made"]), stamp, stamp))
        db.commit()
    finally:
        db.close()
    return ChatResponse(chat_id=request.session_id, answer=result["answer"], tool_calls_made=result["tool_calls_made"])

@app.delete("/chat/{session_id}/{mode}")
async def clear_session(session_id: str, mode: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        db.execute("DELETE FROM chats WHERE id=? AND user_id=? AND mode=?", (session_id, user["id"], mode))
        db.commit()
        return {"status": "cleared"}
    finally:
        db.close()

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = app_state.get("settings")
    db = get_db()
    try:
        active = db.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    finally:
        db.close()
    return HealthResponse(status="ok", provider=settings.llm_provider if settings else "unknown", active_sessions=active)

app.mount("/", StaticFiles(directory="static", html=True), name="static")
