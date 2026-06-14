import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.llms import get_llm
from app.models import ChatMessage, ChatSession, User
from app.rag import build_prompt_messages, citations_from_docs, safe_retrieve_merged
from app.schemas import ChatStreamRequest
from app.services.agent_pipeline import run_agent_pipeline
from app.services.chat_attachment_context import enrich_question_with_attachments
from app.services.agent_call_logger import set_agent_chain, set_agent_trace
from app.services.chat_context import history_char_budget, rows_to_hist_dicts, select_history_messages
from app.services.chat_session_store import schedule_persist_assistant, schedule_persist_user
from app.services.follow_up import generate_follow_ups
from app.services.intent_suggest import build_intent_alternatives
from app.services.llm_gateway import get_llm_gateway
from app.services.term_dictionary import INTENT_LABELS
from app.services.rate_limit import check_and_increment_daily_quota

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["对话"])

CHITCHAT_SYSTEM = (
    "你是 HaiCi 企业智能客服助手。用简洁中文回答用户。"
    "可介绍自己的身份与能力（产品咨询、售后政策、知识库问答）。"
    "不要编造具体产品参数或政策细节；不确定时建议用户换种问法或联系人工客服。"
)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _emit_simulated_stream(text: str, chunk_size: int = 2, delay_s: float = 0.035) -> AsyncIterator[str]:
    content = text or ""
    if not content:
        return
    step = max(1, chunk_size)
    for i in range(0, len(content), step):
        yield _sse("token", {"content": content[i:i + step]})
        if i + step < len(content):
            await asyncio.sleep(delay_s)


def _chitchat_messages(question: str, history: list[dict]) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = [{"role": "system", "content": CHITCHAT_SYSTEM}]
    budget = history_char_budget()
    used = len(CHITCHAT_SYSTEM) + len(question)
    picked: list[dict] = []
    for h in reversed(history):
        content = (h.get("content") or "").strip()
        if h.get("role") not in ("user", "assistant") or not content:
            continue
        clen = len(content)
        if picked and used + clen > budget:
            break
        picked.append({"role": h["role"], "content": content[: settings.MAX_QUESTION_LENGTH]})
        used += clen
    for h in reversed(picked):
        msgs.append(h)
    msgs.append({"role": "user", "content": question})
    return msgs


def _load_history_rows(db: Session, session_id: int) -> list:
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )


@router.get("/config")
def chat_config(_user: User = Depends(get_current_user)):
    return {
        "ok": True,
        "max_question_length": settings.MAX_QUESTION_LENGTH,
        "max_context_chars": settings.CHAT_MAX_CONTEXT_CHARS,
        "context_reserve_chars": settings.CHAT_CONTEXT_RESERVE_CHARS,
        "history_char_budget": history_char_budget(),
        "max_history_turns": settings.CHAT_HISTORY_TURNS,
    }


@router.get("/intent-alternatives")
async def intent_alternatives(
    message_id: int = Query(..., ge=1),
    retrieval_terms: str | None = Query(None, description="逗号分隔的 pipeline 检索词"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """意图理解有误时：术语表备选 + 检索词提示 + LLM 推测意图。"""
    msg = db.get(ChatMessage, message_id)
    if not msg or msg.role != "assistant":
        raise HTTPException(status_code=404, detail="消息不存在")
    session = db.get(ChatSession, msg.session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问")

    prev = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == msg.session_id,
            ChatMessage.id < msg.id,
            ChatMessage.role == "user",
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )
    question = (prev.content or "").strip() if prev else ""
    answer = (msg.content or "").strip()
    detected = (msg.intent_label or "").strip()
    detected_label = INTENT_LABELS.get(detected, detected)
    terms_list: list[str] | None = None
    if retrieval_terms:
        terms_list = [t.strip() for t in retrieval_terms.split(",") if t.strip()]

    data = await asyncio.to_thread(
        build_intent_alternatives,
        question=question,
        answer=answer,
        detected_intent=detected,
        detected_label=detected_label,
        retrieval_terms=terms_list,
        include_llm=True,
    )
    return {"ok": True, **data}


@router.post("/stream")
async def stream_chat(payload: ChatStreamRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    question = payload.question.strip()
    attachments = payload.attachments or []
    if not question and not attachments:
        raise HTTPException(status_code=400, detail="问题或附件不能同时为空")
    if question and len(question) > settings.MAX_QUESTION_LENGTH:
        raise HTTPException(status_code=400, detail=f"单次提问不能超过 {settings.MAX_QUESTION_LENGTH} 字")

    session = db.get(ChatSession, payload.session_id)
    if not session or session.user_id != current_user.id or session.status != 1:
        raise HTTPException(status_code=404, detail="会话不存在")

    check_and_increment_daily_quota(db, current_user)

    user_id = int(current_user.id)
    session_id_val = int(payload.session_id)

    async def generator() -> AsyncIterator[str]:
        import time as _time
        _t_start = _time.time()
        stream_db = SessionLocal()
        persist_tasks: list[asyncio.Task] = []
        trace_id = set_agent_trace(user_id=user_id)
        set_agent_chain("chat/stream")
        try:
            sess = stream_db.get(ChatSession, session_id_val)
            if not sess or sess.user_id != user_id:
                err_text = "会话无效或已过期。"
                yield _sse("token", {"content": err_text})
                yield _sse("done", {"assistant_message_id": None, "content": err_text, "error": True})
                return

            all_rows = _load_history_rows(stream_db, session_id_val)
            hist_rows = select_history_messages(all_rows)
            hist_dicts = rows_to_hist_dicts(hist_rows)

            enriched_question, attachment_meta = await asyncio.to_thread(
                enrich_question_with_attachments, question, attachments
            )
            pipeline = await asyncio.to_thread(run_agent_pipeline, enriched_question, hist_dicts)

            auto_title = None
            if sess.title == "新对话":
                auto_title = (question or (attachments[0].name if attachments else ""))[:30]
            persist_tasks.append(
                schedule_persist_user(
                    session_id=session_id_val,
                    user_id=user_id,
                    question=question or f"[附件] {attachments[0].name}" if attachments else question,
                    intent=pipeline.intent,
                    auto_title=auto_title,
                )
            )

            # 确定 RAG 检索的 tenant_id：优先 payload.kb_id，其次自动路由
            tenant_id = str(payload.kb_id) if payload.kb_id else str(user_id)
            auto_routed = False
            if not payload.kb_id:
                try:
                    from app.models import KnowledgeDocument as KD
                    from app.models import KnowledgeBase

                    kbs = (
                        stream_db.query(KnowledgeBase)
                        .filter(
                            KnowledgeBase.user_id == user_id,
                            KnowledgeBase.status == 1,
                        )
                        .all()
                    )
                    if kbs and len(kbs) > 1:
                        q_lower = (question or "").lower()
                        q_kw = set(q_lower.split())
                        kb_scores: list[tuple[int, float]] = []
                        for kb in kbs:
                            docs = (
                                stream_db.query(KD)
                                .filter(KD.kb_id == kb.id, KD.status == "ready")
                                .all()
                            )
                            if not docs:
                                kb_scores.append((kb.id, 0.0))
                                continue
                            hits = sum(
                                1 for d in docs
                                if any(kw in d.filename.lower() for kw in q_kw)
                            )
                            ratio = hits / len(docs) if docs else 0.0
                            kb_scores.append((kb.id, ratio))
                        kb_scores.sort(key=lambda x: x[1], reverse=True)
                        if kb_scores[0][1] >= 0.1:
                            tenant_id = str(kb_scores[0][0])
                            auto_routed = True
                        else:
                            default = next((kb for kb in kbs if kb.is_default == 1), kbs[0])
                            tenant_id = str(default.id)
                except Exception:
                    pass
            anti_dilution_summary: str | None = None

            docs = []
            if pipeline.intent != "chitchat" and not pipeline.faq_answer:
                docs, anti_dilution_summary = await asyncio.to_thread(
                    safe_retrieve_merged,
                    pipeline.rag_query or enriched_question,
                    tenant_id,
                )

            citations = citations_from_docs(docs)
            task_type = "summary" if pipeline.intent in ("complaint",) else "qa"
            node = get_llm_gateway().choose(task_type)

            meta = {
                "intent": pipeline.intent,
                "intent_label": pipeline.intent_label,
                "user_message_id": None,
                "persist_async": True,
                "eval_trace_id": trace_id,
                "llm_provider": node.provider if node else "",
                "llm_node_name": node.name if node else "",
                "llm_model": node.model if node else "",
                "llm_task_type": task_type,
                "context_budget_chars": history_char_budget(),
                "anti_dilution": anti_dilution_summary is not None,
                "kb_id": payload.kb_id or (int(tenant_id) if auto_routed else None),
                "auto_routed": auto_routed,
                "pipeline": {
                    "source": pipeline.pipeline_source,
                    "rewritten_query": pipeline.rewritten_query,
                    "query_keywords": pipeline.query_keywords,
                    "retrieval_terms": pipeline.retrieval_terms,
                    "rag_query": pipeline.rag_query,
                },
                "attachments": attachment_meta,
            }
            yield _sse("meta", meta)
            if citations:
                yield _sse("citations", {"items": citations, "slices": citations})

            parts: list[str] = []
            if pipeline.faq_answer:
                parts.append(pipeline.faq_answer)
                async for evt in _emit_simulated_stream(pipeline.faq_answer):
                    yield evt
            elif pipeline.intent == "chitchat":
                messages = _chitchat_messages(enriched_question, hist_dicts)
                async for token in get_llm().stream_chat(messages, task_type=task_type):
                    parts.append(token)
                    yield _sse("token", {"content": token})
            elif not docs:
                fallback = settings.FALLBACK_NO_CONTEXT
                parts.append(fallback)
                async for evt in _emit_simulated_stream(fallback):
                    yield evt
            else:
                messages = build_prompt_messages(enriched_question, docs, hist_dicts, pipeline.intent, anti_dilution_summary)
                async for token in get_llm().stream_chat(messages, task_type=task_type):
                    parts.append(token)
                    yield _sse("token", {"content": token})

            answer = "".join(parts).strip()
            assistant_task = schedule_persist_assistant(
                session_id=session_id_val,
                user_id=user_id,
                answer=answer,
                intent=pipeline.intent,
                citations=citations or None,
            )
            persist_tasks.append(assistant_task)

            follow_ups: list[str] = []
            if not pipeline.faq_answer:
                follow_ups = await asyncio.to_thread(generate_follow_ups, question or enriched_question, answer, pipeline.intent)
            if follow_ups:
                yield _sse("follow_ups", {"items": follow_ups})

            assistant_message_id = None
            try:
                assistant_message_id = await asyncio.wait_for(asyncio.shield(assistant_task), timeout=0.05)
            except asyncio.TimeoutError:
                pass

            # 异步记录RAG对话指标（不阻塞SSE）
            from app.services.agent_call_logger import log_rag_conversation
            _t_now = _time.time()
            _top_score = max((float(d.metadata.get("score", 0)) for d in docs), default=0.0)
            log_rag_conversation(
                trace_id=trace_id,
                user_id=user_id,
                question=question or enriched_question,
                intent=pipeline.intent,
                intent_label=pipeline.intent_label,
                rewritten_query=pipeline.rewritten_query or "",
                rag_query=pipeline.rag_query or "",
                keywords=pipeline.query_keywords or [],
                retrieval_terms=pipeline.retrieval_terms or [],
                citations_count=len(citations),
                top_score=_top_score,
                anti_dilution=anti_dilution_summary is not None,
                kb_id=payload.kb_id or (int(tenant_id) if auto_routed else None),
                auto_routed=auto_routed,
                llm_provider=node.provider if node else "",
                llm_model=node.model if node else "",
                llm_task_type=task_type,
                answer_length=len(answer),
                follow_ups_count=len(follow_ups),
                total_tokens=len(answer) // 2,
                time_consume_ms=int((_t_now - _t_start) * 1000),
            )

            yield _sse(
                "done",
                {
                    "assistant_message_id": assistant_message_id,
                    "content": answer,
                    "persist_async": assistant_message_id is None,
                },
            )
        except Exception as exc:
            logger.exception(
                "[智能客服-对话|chat.stream|SSE|Agent执行|失败] error_type=%s; error_message=%s",
                type(exc).__name__,
                str(exc)[:200],
            )
            err_text = "对话服务异常，请稍后重试。"
            yield _sse("token", {"content": err_text})
            yield _sse("done", {"assistant_message_id": None, "content": err_text, "error": True})
        finally:
            stream_db.close()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
