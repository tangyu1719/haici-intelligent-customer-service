import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.intent import get_recognizer
from app.llms import get_llm
from app.models import ChatMessage, ChatSession, User
from app.rag import build_prompt_messages, citations_from_docs, retrieve
from app.schemas import ChatStreamRequest
from app.services.rate_limit import check_and_increment_daily_quota

router = APIRouter(prefix="/chat", tags=["对话"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def stream_chat(payload: ChatStreamRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    if len(question) > settings.MAX_QUESTION_LENGTH:
        raise HTTPException(status_code=400, detail=f"单次提问不能超过 {settings.MAX_QUESTION_LENGTH} 字")

    session = db.get(ChatSession, payload.session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="会话不存在")

    check_and_increment_daily_quota(db, current_user)
    intent = get_recognizer().recognize(question).intent.value

    user_msg = ChatMessage(session_id=session.id, role="user", content=question, intent_label=intent)
    db.add(user_msg)
    if session.title == "新对话":
        session.title = question[:30]
    db.commit()
    db.refresh(user_msg)

    history = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id, ChatMessage.id < user_msg.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(settings.CHAT_HISTORY_TURNS * 2)
        .all()
    )
    history.reverse()
    hist_dicts = [{"role": m.role, "content": m.content} for m in history]

    docs = retrieve(question, tenant_id=str(current_user.id))
    citations = citations_from_docs(docs)

    async def generator() -> AsyncIterator[str]:
        yield _sse("meta", {"intent": intent, "user_message_id": user_msg.id})
        if citations:
            yield _sse("citations", {"items": citations})

        parts: list[str] = []
        if not docs:
            fallback = settings.FALLBACK_NO_CONTEXT
            parts.append(fallback)
            yield _sse("token", {"content": fallback})
        else:
            messages = build_prompt_messages(question, docs, hist_dicts, intent)
            async for token in get_llm().stream_chat(messages):
                parts.append(token)
                yield _sse("token", {"content": token})

        answer = "".join(parts).strip()
        assistant = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=answer,
            intent_label=intent,
            citations_json=citations or None,
        )
        db.add(assistant)
        db.commit()
        db.refresh(assistant)
        yield _sse("done", {"assistant_message_id": assistant.id, "content": answer})

    return StreamingResponse(generator(), media_type="text/event-stream")
