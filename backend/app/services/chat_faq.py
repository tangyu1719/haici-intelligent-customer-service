"""对话 FAQ：DB 持久化 + 内存缓存；点击/命中问题时直出标准答案。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from sqlalchemy.orm import Session

from app.models import ChatFaq

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 30.0
_cache_at: float = 0.0
_cache_rows: list[ChatFaq] = []

_NORM_RE = re.compile(r"[？?！!。.\s]+")


def invalidate_faq_cache() -> None:
    global _cache_at, _cache_rows
    _cache_at = 0.0
    _cache_rows = []


def _norm_question(text: str) -> str:
    return _NORM_RE.sub("", (text or "").strip())


def _load_enabled_rows(db: Session) -> list[ChatFaq]:
    global _cache_at, _cache_rows
    now = time.time()
    if _cache_rows and now - _cache_at < _CACHE_TTL_SEC:
        return _cache_rows
    rows = (
        db.query(ChatFaq)
        .filter(ChatFaq.enabled == 1)
        .order_by(ChatFaq.sort_order.asc(), ChatFaq.id.asc())
        .all()
    )
    _cache_rows = rows
    _cache_at = now
    return rows


def faq_to_dict(row: ChatFaq) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "category": row.category or "通用",
        "question": row.question,
        "answer": row.answer,
        "sort_order": int(row.sort_order or 0),
        "enabled": int(row.enabled or 0),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_chat_faq_items(db: Session, *, include_disabled: bool = False) -> list[dict[str, Any]]:
    if include_disabled:
        rows = db.query(ChatFaq).order_by(ChatFaq.sort_order.asc(), ChatFaq.id.asc()).all()
    else:
        rows = _load_enabled_rows(db)
    return [faq_to_dict(r) for r in rows]


def get_faq_by_id(db: Session, faq_id: int) -> ChatFaq | None:
    return db.get(ChatFaq, faq_id)


def find_faq_by_question(db: Session, question: str) -> ChatFaq | None:
    q_raw = (question or "").strip()
    if not q_raw:
        return None
    q_norm = _norm_question(q_raw)
    for row in _load_enabled_rows(db):
        if row.question.strip() == q_raw or _norm_question(row.question) == q_norm:
            return row
    return None


# 首次启动种子：来自 RAG 测试文档、售后政策与已验证的运维助手优质回答
DEFAULT_FAQ_SEED: list[dict[str, str | int]] = [
    {
        "category": "运维助手",
        "sort_order": 1,
        "question": "运维助手如何进行版本升级？",
        "answer": (
            "运维助手系统提供版本升级模块，用于开展低版本升级至高版本的相关操作。\n\n"
            "1. 进入「基础管理 > 版本升级」界面，首先选择正式区或测试区环境。\n"
            "2. 点击「选择文件」上传版本包；服务器路径会默认带入，可在此基础上编辑。\n"
            "3. 编辑后点击【检查合法性】，检查不通过会报错，需修正后再继续。\n"
            "4. 准备就绪后，点击「立即升级」执行升级。\n"
            "5. 升级完成后，使用「环境信息维护」中配置的账号和密码验证是否升级成功。"
        ),
    },
    {
        "category": "运维助手",
        "sort_order": 2,
        "question": "版本升级前为什么要选择正式区或测试区？",
        "answer": (
            "正式区与测试区的环境参数、升级包路径和校验规则相互独立。"
            "升级前必须选定目标环境，避免误对生产或测试环境执行错误版本包。"
        ),
    },
    {
        "category": "运维助手",
        "sort_order": 3,
        "question": "运维助手怎么查询系统操作日志？",
        "answer": (
            "在左侧菜单进入「日志查询」，可按时间、操作人、菜单名、接口地址等维度筛选，"
            "查看客户端 IP、请求参数、响应内容与耗时，便于快速定位问题。"
        ),
    },
    {
        "category": "售后政策",
        "sort_order": 10,
        "question": "未拆封商品可以退货吗？",
        "answer": (
            "可以。未拆封商品签收后 7 日内可申请无理由退货。"
            "已拆封且非质量问题原则上不支持退货，可协商换货；质量问题 15 日内凭凭证退换，运费由我方承担。"
        ),
    },
    {
        "category": "售后政策",
        "sort_order": 11,
        "question": "产品保修多久？",
        "answer": (
            "整机保修 12 个月；核心部件（电机、主板）保修 24 个月。"
            "人为损坏、私自拆修不在保修范围内。"
        ),
    },
    {
        "category": "售后政策",
        "sort_order": 12,
        "question": "退款一般多久到账？",
        "answer": "审核通过后 3–5 个工作日原路退款；大额订单可能延长至 7 个工作日。",
    },
    {
        "category": "产品介绍",
        "sort_order": 20,
        "question": "HaiCi 智能客服能做什么？",
        "answer": (
            "HaiCi 企业智能客服基于 RAG 知识库与多模态文档解析，"
            "可回答产品咨询、售后政策与运维文档问题，支持流式对话、引用溯源与多模态入库。"
        ),
    },
    {
        "category": "产品介绍",
        "sort_order": 21,
        "question": "客服热线和在线支持怎么用？",
        "answer": "客服热线 400-800-1234（工作日 9:00–18:00）；在线客服可在控制台「智能对话」中使用。",
    },
    {
        "category": "使用说明",
        "sort_order": 30,
        "question": "每天可以提问多少次？",
        "answer": "每次提问不超过 500 字；普通用户每日默认最多 100 次，管理员账号不限次数。",
    },
    {
        "category": "使用说明",
        "sort_order": 31,
        "question": "知识库支持上传哪些文档？",
        "answer": (
            "支持 txt、md、pdf、Word、Excel 等格式。"
            "含图文档会先 OCR/VLM 识别并写入 kb_assets，再供检索与回答引用。"
        ),
    },
]


def seed_default_chat_faq(db: Session) -> None:
    """表为空时写入默认 FAQ（仅首次）。"""
    if db.query(ChatFaq.id).limit(1).first():
        return
    for item in DEFAULT_FAQ_SEED:
        db.add(
            ChatFaq(
                category=str(item["category"]),
                question=str(item["question"]),
                answer=str(item["answer"]),
                sort_order=int(item.get("sort_order") or 0),
                enabled=1,
            )
        )
    db.commit()
    invalidate_faq_cache()
    logger.info(
        "[智能客服-FAQ|chat_faq.seed_default_chat_faq|chat_faq|硬编执行|完成] count=%s",
        len(DEFAULT_FAQ_SEED),
    )
