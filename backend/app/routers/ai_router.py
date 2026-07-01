"""
AI Chat router — POST /api/ai/chat

Stateless: history ownership lives in the frontend.
The backend receives the full session history, applies a sliding window,
injects fresh context, calls Gemini, and returns the reply + session metadata.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ChatMessage(BaseModel):
    role: str    # "user" or "assistant"
    content: str


class ChatContext(BaseModel):
    host_name: Optional[str] = None
    url: Optional[str] = None
    service_type: Optional[str] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    response_time_ms: Optional[int] = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    context: Optional[ChatContext] = None
    session_key: str = ""   # f"{host_id}_{service_type}", e.g. "42_https"


@router.post("/chat")
async def ai_chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Send a conversation to the ServiceMonitor AI copilot.

    - Auth required (JWT cookie)
    - Backend is stateless — frontend owns history
    - Returns { reply, session_key, turns_sent }
    """
    from app.services.ai_service import chat

    if not body.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    context = body.context.model_dump() if body.context else None

    result = await chat(
        messages=messages,
        context=context,
        session_key=body.session_key,
    )
    return JSONResponse(result)
