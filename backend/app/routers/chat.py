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
from app.llms import LLMStreamDelta, get_llm
from app.models import ChatMessage, ChatSession, User
from app.auth.rbac import get_user_roles
from app.rag import build_prompt_messages, citations_from_docs
from app.schemas import ChatFaqApplyRequest, ChatStreamRequest
from app.intent import get_recognizer
from app.services.agent_pipeline import run_agent_pipeline
from app.services.react_agent import is_complex_query, run_react_rag, stream_react_final_answer
from app.services.chat_attachment_context import enrich_question_with_attachments
from app.services.agent_call_logger import set_agent_chain, set_agent_trace
from app.services.chat_context import history_char_budget, rows_to_hist_dicts
from app.services.session_context_manager import inject_summary_prefix, prepare_session_context
from app.services.chat_session_store import (
    persist_assistant_message_async,
    persist_user_message_async,
    schedule_persist_assistant,
    schedule_persist_user,
    set_session_streaming,
)
from app.services.follow_up import generate_follow_ups
from app.services.intent_suggest import build_intent_alternatives
from app.services.llm_gateway import get_llm_gateway
from app.services.term_dictionary import INTENT_LABELS
from app.services.rate_limit import check_and_increment_daily_quota, get_daily_quota_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["对话"])

from app.services.prompt_segments import build_chitchat_system_prompt

CHITCHAT_SYSTEM = build_chitchat_system_prompt()


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


def _chitchat_messages(question: str, history: list[dict], budget: int | None = None) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = [{"role": "system", "content": CHITCHAT_SYSTEM}]
    char_budget = budget if budget is not None else history_char_budget()
    used = len(CHITCHAT_SYSTEM) + len(question)
    picked: list[dict] = []
    for h in reversed(history):
        content = (h.get("content") or "").strip()
        if h.get("role") not in ("user", "assistant") or not content:
            continue
        clen = len(content)
        if picked and used + clen > char_budget:
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
def chat_config(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services.chat_faq import get_chat_faq_items

    roles = get_user_roles(db, user.id)
    quota = get_daily_quota_status(db, user, roles)
    faq_items = get_chat_faq_items(db)
    return {
        "ok": True,
        "max_question_length": settings.MAX_QUESTION_LENGTH,
        "max_context_chars": settings.CHAT_MAX_CONTEXT_CHARS,
        "context_reserve_chars": settings.CHAT_CONTEXT_RESERVE_CHARS,
        "history_char_budget": history_char_budget(),
        "max_history_turns": settings.CHAT_HISTORY_TURNS,
        "sliding_window_turns": settings.CHAT_SLIDING_WINDOW_TURNS,
        "summary_threshold_ratio": settings.CHAT_SUMMARY_THRESHOLD_RATIO,
        "auto_summary_enabled": settings.CHAT_AUTO_SUMMARY_ENABLED,
        "faq_items": faq_items,
        **quota,
    }


@router.post("/faq-apply")
async def apply_chat_faq(
    payload: ChatFaqApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """点击 FAQ 卡片：直出缓存标准答案并落库，不走 RAG/LLM。"""
    from app.services.chat_faq import get_faq_by_id

    session = db.get(ChatSession, payload.session_id)
    if not session or session.user_id != current_user.id or session.status != 1 or getattr(session, "user_deleted", 0) == 1:
        raise HTTPException(status_code=404, detail="会话不存在")

    faq = get_faq_by_id(db, payload.faq_id)
    if not faq or faq.enabled != 1:
        raise HTTPException(status_code=404, detail="FAQ 不存在或已停用")

    roles = get_user_roles(db, current_user.id)
    check_and_increment_daily_quota(db, current_user, roles)

    user_id = int(current_user.id)
    session_id_val = int(payload.session_id)
    question = faq.question.strip()
    answer = faq.answer.strip()
    auto_title = None
    if session.title == "新对话":
        auto_title = question[:30]

    user_message_id = await persist_user_message_async(
        session_id=session_id_val,
        user_id=user_id,
        question=question,
        intent="faq_cached",
        auto_title=auto_title,
    )
    assistant_message_id = await persist_assistant_message_async(
        session_id=session_id_val,
        user_id=user_id,
        answer=answer,
        intent="faq_cached",
        citations=None,
    )
    logger.info(
        "[智能客服-FAQ|chat.faq_apply|faq_id=%s|硬编执行|完成] session_id=%s; user_msg=%s; assistant_msg=%s",
        faq.id,
        session_id_val,
        user_message_id,
        assistant_message_id,
    )
    return {
        "ok": True,
        "cached": True,
        "faq_id": int(faq.id),
        "question": question,
        "answer": answer,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "intent": "faq_cached",
        "intent_label": "FAQ 缓存",
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


async def _produce_chat_stream(
    emit,
    *,
    question: str,
    attachments: list,
    payload: ChatStreamRequest,
    user_id: int,
    session_id_val: int,
) -> None:
    """后台生成 SSE 事件；客户端断开后仍继续 LLM 调用并落库。"""
    import time as _time

    _t_start = _time.time()
    stream_db = SessionLocal()
    persist_tasks: list[asyncio.Task] = []
    trace_id = set_agent_trace(user_id=user_id)
    set_agent_chain("chat/stream")
    parts: list[str] = []
    pipeline_intent: str | None = None
    stream_citations: list[dict] | None = None
    assistant_persisted = False
    asyncio.create_task(
        set_session_streaming(session_id=session_id_val, user_id=user_id, streaming=True)
    )
    await emit(_sse("status", {"text": "正在理解..."}))

    # 规则引擎毫秒级预判（不查库），让「意图识别」行立刻出现
    preview_intent: str | None = None
    preview_label: str | None = None
    if (question or "").strip():
        quick = get_recognizer().recognize(question.strip())
        preview_intent = quick.intent.value
        preview_label = INTENT_LABELS.get(preview_intent, preview_intent)
        await emit(
            _sse(
                "intent",
                {
                    "intent": preview_intent,
                    "intent_label": preview_label,
                    "source": "rule_preview",
                },
            )
        )

    try:
        sess = stream_db.get(ChatSession, session_id_val)
        if not sess or sess.user_id != user_id or getattr(sess, "user_deleted", 0) == 1:
            err_text = "会话无效或已过期。"
            await emit(_sse("token", {"content": err_text}))
            await emit(_sse("done", {"assistant_message_id": None, "content": err_text, "error": True}))
            return

        all_rows = _load_history_rows(stream_db, session_id_val)
        ctx_pack = prepare_session_context(stream_db, sess, all_rows, task_type="qa")
        hist_dicts = inject_summary_prefix(ctx_pack.hist_dicts, ctx_pack.rolling_summary)

        from app.services.user_profile_memory import get_profile_context_snippet

        profile_snippet = get_profile_context_snippet(user_id)
        if profile_snippet:
            hist_dicts = [
                {"role": "system", "content": f"【用户长期记忆画像】\n{profile_snippet}"},
                *hist_dicts,
            ]

        # 更新会话上下文占用元数据
        meta_patch = dict(sess.meta_json or {})
        meta_patch["context_mode"] = ctx_pack.mode
        meta_patch["context_usage_ratio"] = ctx_pack.usage_ratio
        meta_patch["context_turn_count"] = ctx_pack.turn_count
        sess.meta_json = meta_patch
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(sess, "meta_json")
        try:
            stream_db.commit()
        except Exception:
            stream_db.rollback()

        enriched_question, attachment_meta = await asyncio.to_thread(
            enrich_question_with_attachments, question, attachments
        )

        # FAQ 缓存直出：命中标准问答时不走 Agent/RAG/LLM
        if not attachments and (question or "").strip():
            from app.services.chat_faq import find_faq_by_question

            faq_hit = find_faq_by_question(stream_db, question)
            if faq_hit:
                pipeline_intent = "faq_cached"
                answer = faq_hit.answer.strip()
                parts.append(answer)
                auto_title = None
                if sess.title == "新对话":
                    auto_title = question[:30]
                persist_tasks.append(
                    schedule_persist_user(
                        session_id=session_id_val,
                        user_id=user_id,
                        question=question,
                        intent=pipeline_intent,
                        auto_title=auto_title,
                    )
                )
                await emit(
                    _sse(
                        "intent",
                        {
                            "intent": pipeline_intent,
                            "intent_label": "FAQ 缓存",
                            "source": "faq_cache",
                        },
                    )
                )
                await emit(
                    _sse(
                        "meta",
                        {
                            "intent": pipeline_intent,
                            "intent_label": "FAQ 缓存",
                            "faq_id": int(faq_hit.id),
                            "cached": True,
                            "persist_async": True,
                        },
                    )
                )
                async for evt in _emit_simulated_stream(answer):
                    await emit(evt)
                assistant_task = schedule_persist_assistant(
                    session_id=session_id_val,
                    user_id=user_id,
                    answer=answer,
                    intent=pipeline_intent,
                    citations=None,
                )
                persist_tasks.append(assistant_task)
                assistant_persisted = True
                assistant_message_id = None
                try:
                    assistant_message_id = await asyncio.wait_for(asyncio.shield(assistant_task), timeout=0.05)
                except asyncio.TimeoutError:
                    pass
                faq_follow_ups: list[str] = []
                if answer and len(answer) >= 20:
                    faq_follow_ups = await asyncio.to_thread(
                        generate_follow_ups, question, answer, pipeline_intent
                    )
                if faq_follow_ups:
                    await emit(_sse("follow_ups", {"items": faq_follow_ups}))
                await emit(
                    _sse(
                        "done",
                        {
                            "assistant_message_id": assistant_message_id,
                            "content": answer,
                            "cached": True,
                            "faq_id": int(faq_hit.id),
                            "persist_async": assistant_message_id is None,
                            "follow_ups": faq_follow_ups,
                        },
                    )
                )
                return

        pipeline = await asyncio.to_thread(run_agent_pipeline, enriched_question, hist_dicts)
        pipeline_intent = pipeline.intent

        if (
            preview_intent != pipeline.intent
            or preview_label != pipeline.intent_label
            or pipeline.pipeline_source == "llm"
        ):
            await emit(
                _sse(
                    "intent",
                    {
                        "intent": pipeline.intent,
                        "intent_label": pipeline.intent_label,
                        "source": pipeline.pipeline_source,
                    },
                ),
            )

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

        tenant_id = str(payload.kb_id) if payload.kb_id else str(user_id)
        auto_routed = False
        kb_route_meta: dict = {}
        roles = get_user_roles(stream_db, user_id)
        anti_dilution_summary: str | None = None
        use_react = (
            settings.REACT_ENABLED
            and pipeline.intent != "chitchat"
            and not pipeline.faq_answer
            and is_complex_query(enriched_question or question)
        )
        route_decision = None
        if pipeline.intent != "chitchat" and not pipeline.faq_answer and use_react:
            from app.services.kb_router import select_kb_route

            route_decision = select_kb_route(
                stream_db,
                user_id,
                question or enriched_question,
                pipeline.rag_query or enriched_question,
                roles=roles,
                explicit_kb_id=payload.kb_id,
                fallback_user_tenant=str(user_id),
            )
            tenant_id = route_decision.tenant_id
            auto_routed = route_decision.routed and payload.kb_id is None
            kb_route_meta = {
                "kb_route_reason": route_decision.reason,
                "kb_route_score": route_decision.route_score,
                "kb_route_round": route_decision.round_index,
            }

        if pipeline.intent != "chitchat" and not pipeline.faq_answer:
            await emit(_sse("status", {"text": "正在检索知识库..."}))

        docs = []
        react_observations: list[str] = []
        meta_react: dict = {"react_mode": False}
        if use_react:
            await emit(_sse("status", {"phase": "thinking", "text": "复杂问题，启动 ReAct 推理…"}))
            await emit(_sse("meta", {"react_mode": True, "react_max_steps": settings.REACT_MAX_STEPS}))

            async def _react_emit(event: str, data: dict) -> None:
                await emit(_sse(event, data))

            react_result = await run_react_rag(
                enriched_question,
                tenant_id,
                hist_dicts,
                pipeline.intent,
                emit=_react_emit,
                rolling_summary=ctx_pack.rolling_summary,
                initial_rag_query=pipeline.rag_query or enriched_question,
            )
            docs = react_result.all_docs
            anti_dilution_summary = react_result.anti_dilution_summary
            react_observations = [
                s.content for s in react_result.steps if s.phase == "observe"
            ]
            meta_react = {
                "react_mode": True,
                "react_rag_calls": react_result.rag_call_count,
                "react_steps": len(react_result.steps),
            }
            if payload.kb_id is None and route_decision and route_decision.kb_id is not None:
                from app.services.kb_router import retrieval_sufficient, select_kb_route
                from app.rag import safe_retrieve_merged

                sufficient, _top, _cnt = retrieval_sufficient(docs)
                if not sufficient:
                    secondary = select_kb_route(
                        stream_db,
                        user_id,
                        question or enriched_question,
                        pipeline.rag_query or enriched_question,
                        roles=roles,
                        exclude_kb_ids={route_decision.kb_id},
                        round_index=1,
                        fallback_user_tenant=str(user_id),
                    )
                    if secondary.kb_id and secondary.kb_id != route_decision.kb_id:
                        fb_docs, fb_ad = await asyncio.to_thread(
                            safe_retrieve_merged,
                            pipeline.rag_query or enriched_question,
                            secondary.tenant_id,
                        )
                        fb_ok, fb_top, fb_cnt = retrieval_sufficient(fb_docs)
                        if fb_ok or fb_cnt > _cnt or fb_top > _top:
                            docs = fb_docs
                            anti_dilution_summary = fb_ad
                            tenant_id = secondary.tenant_id
                            auto_routed = True
                            kb_route_meta = {
                                **kb_route_meta,
                                "kb_route_reason": secondary.reason,
                                "kb_route_score": secondary.route_score,
                                "kb_route_round": secondary.round_index,
                                "kb_fallback_applied": True,
                                "kb_primary_id": route_decision.kb_id,
                            }
        elif pipeline.intent != "chitchat" and not pipeline.faq_answer:
            from app.services.kb_router import retrieve_with_kb_fallback

            kb_result = await asyncio.to_thread(
                retrieve_with_kb_fallback,
                stream_db,
                user_id,
                question or enriched_question,
                pipeline.rag_query or enriched_question,
                roles=roles,
                explicit_kb_id=payload.kb_id,
                allow_fallback=payload.kb_id is None,
            )
            docs = kb_result.docs
            anti_dilution_summary = kb_result.anti_dilution_summary
            tenant_id = kb_result.decision.tenant_id
            auto_routed = (kb_result.decision.routed or kb_result.fallback_applied) and payload.kb_id is None
            kb_route_meta = {
                "kb_route_reason": kb_result.decision.reason,
                "kb_route_score": kb_result.decision.route_score,
                "kb_route_round": kb_result.decision.round_index,
            }
            if kb_result.fallback_applied:
                kb_route_meta["kb_fallback_applied"] = True
                kb_route_meta["kb_primary_id"] = (
                    kb_result.primary_decision.kb_id if kb_result.primary_decision else None
                )
            meta_react = {"react_mode": False}

        citations = citations_from_docs(docs)
        stream_citations = citations or None
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
            "context_budget_chars": ctx_pack.budget_chars,
            "context_mode": ctx_pack.mode,
            "context_usage_ratio": ctx_pack.usage_ratio,
            "model_context_chars": ctx_pack.model_context_chars,
            "rolling_summary": bool(ctx_pack.rolling_summary),
            "anti_dilution": anti_dilution_summary is not None,
            "kb_id": payload.kb_id or (int(tenant_id) if tenant_id.isdigit() else None),
            "auto_routed": auto_routed,
            **kb_route_meta,
            **meta_react,
            "pipeline": {
                "source": pipeline.pipeline_source,
                "rewritten_query": pipeline.rewritten_query,
                "query_keywords": pipeline.query_keywords,
                "retrieval_terms": pipeline.retrieval_terms,
                "rag_query": pipeline.rag_query,
            },
            "attachments": attachment_meta,
        }
        await emit(_sse("meta", meta))
        if citations:
            await emit(_sse("citations", {"items": citations, "slices": citations}))
        elif pipeline.intent != "chitchat" and not pipeline.faq_answer:
            await emit(
                _sse(
                    "status",
                    {"phase": "retrieval_done", "text": "未检索到相关知识库片段", "count": 0},
                )
            )

        async def _emit_llm_delta(delta: LLMStreamDelta) -> None:
            if delta.kind == "think":
                await emit(_sse("think", {"content": delta.content}))
            else:
                parts.append(delta.content)
                await emit(_sse("token", {"content": delta.content}))

        llm_error_code: str | None = None
        generation_status_sent = False
        thinking_status_sent = False

        async def _emit_generating_status() -> None:
            nonlocal generation_status_sent
            if generation_status_sent:
                return
            generation_status_sent = True
            await emit(_sse("status", {"phase": "generating", "text": "正在生成回答…"}))

        async def _emit_thinking_status() -> None:
            nonlocal thinking_status_sent
            if thinking_status_sent:
                return
            thinking_status_sent = True
            await emit(_sse("status", {"phase": "thinking", "text": "正在思考…"}))

        try:
            if pipeline.faq_answer:
                parts.append(pipeline.faq_answer)
                async for evt in _emit_simulated_stream(pipeline.faq_answer):
                    await emit(evt)
            elif pipeline.intent == "chitchat":
                messages = _chitchat_messages(enriched_question, hist_dicts, ctx_pack.budget_chars)
                async for delta in get_llm().stream_chat(messages, task_type=task_type):
                    if delta.kind == "think":
                        await _emit_thinking_status()
                    elif delta.kind == "answer":
                        await _emit_generating_status()
                    await _emit_llm_delta(delta)
            elif not docs:
                fallback = settings.FALLBACK_NO_CONTEXT
                parts.append(fallback)
                async for evt in _emit_simulated_stream(fallback):
                    await emit(evt)
            elif use_react:
                async for delta in stream_react_final_answer(
                    enriched_question,
                    docs,
                    hist_dicts,
                    pipeline.intent,
                    react_observations,
                    anti_dilution_summary,
                    ctx_pack.rolling_summary,
                ):
                    if delta.kind == "think":
                        await _emit_thinking_status()
                    elif delta.kind == "answer":
                        await _emit_generating_status()
                    await _emit_llm_delta(delta)
            else:
                messages = build_prompt_messages(
                    enriched_question,
                    docs,
                    hist_dicts,
                    pipeline.intent,
                    anti_dilution_summary,
                    ctx_pack.rolling_summary,
                )
                async for delta in get_llm().stream_chat(messages, task_type=task_type):
                    if delta.kind == "think":
                        await _emit_thinking_status()
                    elif delta.kind == "answer":
                        await _emit_generating_status()
                    await _emit_llm_delta(delta)
        except Exception as llm_exc:
            from app.services.llm_error_recovery import LLMCallError

            if isinstance(llm_exc, LLMCallError):
                llm_error_code = llm_exc.error_code.value
                msg = llm_exc.message
                logger.error(
                    "[RAG-LLM错误|chat|LLM|Agent执行|失败] code=%s; node=%s; msg=%s",
                    llm_error_code,
                    llm_exc.node_id,
                    msg,
                )
            else:
                from app.services.gateway_error_handler import normalize_error

                err_str = str(llm_exc)[:500]
                code, msg = normalize_error(
                    node.provider if node else "ark", 0, "", err_str
                )
                llm_error_code = code.value
                logger.error("[RAG-LLM错误] code=%s msg=%s", llm_error_code, msg)
                from app.services.gateway_circuit_breaker import breaker

                breaker.handle_response(
                    node.id if node else "unknown",
                    node.provider if node else "ark",
                    500,
                    "",
                    err_str,
                )
            parts.append(f"AI服务异常 [{llm_error_code}]: {msg}")
            await emit(_sse("token", {"content": parts[0]}))

        answer = "".join(parts).strip()
        assistant_task = schedule_persist_assistant(
            session_id=session_id_val,
            user_id=user_id,
            answer=answer,
            intent=pipeline.intent,
            citations=stream_citations,
        )
        persist_tasks.append(assistant_task)
        if answer:
            assistant_persisted = True

        assistant_message_id = None
        try:
            assistant_message_id = await asyncio.wait_for(asyncio.shield(assistant_task), timeout=0.05)
        except asyncio.TimeoutError:
            pass

        follow_ups: list[str] = []
        if (
            not pipeline.faq_answer
            and pipeline.intent not in ("chitchat",)
            and answer
            and len(answer) >= 20
        ):
            await emit(_sse("status", {"phase": "follow_ups", "text": "正在生成追问建议…"}))
            follow_ups = await asyncio.to_thread(
                generate_follow_ups, question or enriched_question, answer, pipeline.intent
            )
        if follow_ups:
            await emit(_sse("follow_ups", {"items": follow_ups}))

        await emit(
            _sse(
                "done",
                {
                    "assistant_message_id": assistant_message_id,
                    "content": answer,
                    "persist_async": assistant_message_id is None,
                    "error_code": llm_error_code,
                    "follow_ups": follow_ups,
                },
            )
        )

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
            kb_id=payload.kb_id or (int(tenant_id) if str(tenant_id).isdigit() else None),
            auto_routed=auto_routed,
            llm_provider=node.provider if node else "",
            llm_model=node.model if node else "",
            llm_task_type=task_type,
            answer_length=len(answer),
            follow_ups=follow_ups,
            follow_ups_count=len(follow_ups),
            total_tokens=len(answer) // 2,
            time_consume_ms=int((_t_now - _t_start) * 1000),
        )

        # 会话消息数达上限时自动归档并写入长期记忆
        try:
            from sqlalchemy import func
            from app.services.session_context_manager import should_auto_archive
            from app.services.user_profile_memory import archive_session_to_user_memory
            from app.services.session_context_manager import mark_session_archived

            stream_db.refresh(sess)
            msg_count = (
                stream_db.query(func.count(ChatMessage.id))
                .filter(ChatMessage.session_id == session_id_val)
                .scalar()
                or 0
            )
            if should_auto_archive(sess, int(msg_count)):
                await asyncio.to_thread(archive_session_to_user_memory, stream_db, sess, "auto_full")
                await asyncio.to_thread(mark_session_archived, stream_db, sess, "auto_full")
        except Exception as arch_exc:
            logger.warning(
                "[智能客服-上下文|chat.stream|auto_archive|硬编执行|失败] error_type=%s",
                type(arch_exc).__name__,
            )

    except Exception as exc:
        logger.exception(
            "[智能客服-对话|chat.stream|SSE|Agent执行|失败] error_type=%s; error_message=%s",
            type(exc).__name__,
            str(exc)[:200],
        )
        err_text = "对话服务异常，请稍后重试。"
        await emit(_sse("token", {"content": err_text}))
        await emit(_sse("done", {"assistant_message_id": None, "content": err_text, "error": True}))
    finally:
        if not assistant_persisted:
            partial = "".join(parts).strip()
            if partial and pipeline_intent:
                try:
                    await persist_assistant_message_async(
                        session_id=session_id_val,
                        user_id=user_id,
                        answer=partial,
                        intent=pipeline_intent,
                        citations=stream_citations,
                    )
                    logger.info(
                        "[智能客服-对话|chat.stream|persist_partial|硬编执行|完成] session_id=%s; partial_len=%s",
                        session_id_val,
                        len(partial),
                    )
                except Exception as persist_exc:
                    logger.warning(
                        "[智能客服-对话|chat.stream|persist_partial|硬编执行|失败] session_id=%s; error_type=%s; error_message=%s",
                        session_id_val,
                        type(persist_exc).__name__,
                        str(persist_exc)[:120],
                    )
        await set_session_streaming(session_id=session_id_val, user_id=user_id, streaming=False)
        stream_db.close()


@router.post("/stream")
async def stream_chat(payload: ChatStreamRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    question = payload.question.strip()
    attachments = payload.attachments or []
    if not question and not attachments:
        raise HTTPException(status_code=400, detail="问题或附件不能同时为空")
    if question and len(question) > settings.MAX_QUESTION_LENGTH:
        raise HTTPException(status_code=400, detail=f"单次提问不能超过 {settings.MAX_QUESTION_LENGTH} 字")

    session = db.get(ChatSession, payload.session_id)
    if not session or session.user_id != current_user.id or session.status != 1 or getattr(session, "user_deleted", 0) == 1:
        raise HTTPException(status_code=404, detail="会话不存在")

    meta = session.meta_json if isinstance(session.meta_json, dict) else {}
    if meta.get("streaming"):
        raise HTTPException(status_code=409, detail="该会话正在生成回答，请稍候或刷新页面查看结果")

    roles = get_user_roles(db, current_user.id)
    check_and_increment_daily_quota(db, current_user, roles)

    user_id = int(current_user.id)
    session_id_val = int(payload.session_id)
    event_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=256)

    async def emit(evt: str) -> None:
        # 阻塞入队，避免高频 token 时静默丢弃 follow_ups 等尾部事件
        await event_queue.put(evt)

    async def producer() -> None:
        try:
            await _produce_chat_stream(
                emit,
                question=question,
                attachments=attachments,
                payload=payload,
                user_id=user_id,
                session_id_val=session_id_val,
            )
        finally:
            await event_queue.put(None)

    producer_task = asyncio.create_task(producer())

    async def client_generator() -> AsyncIterator[str]:
        # SSE 注释行：促使代理/浏览器立即建立流式连接
        yield ": stream-open\n\n"
        try:
            while True:
                item = await event_queue.get()
                if item is None:
                    break
                yield item
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.info(
                "[智能客服-对话|chat.stream|SSE|Agent执行|客户端断开] session_id=%s; background=continue",
                session_id_val,
            )
            raise
        finally:
            if not producer_task.done():
                producer_task.add_done_callback(
                    lambda t: t.exception() if not t.cancelled() else None
                )

    return StreamingResponse(
        client_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
