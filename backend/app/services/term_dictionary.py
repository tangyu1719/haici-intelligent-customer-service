"""内部业务术语映射（轻量版）。"""

from __future__ import annotations

# 外部/口语 → 知识库常用检索词
TERM_DICTIONARY: dict[str, str] = {
    "SSD": "固态硬盘",
    "GPU": "图形处理器",
    "CPU": "中央处理器",
    "RAM": "内存",
    "内存条": "内存",
    "显卡": "图形处理器",
    "退货": "退换货政策",
    "退款": "退换货政策",
    "换货": "退换货政策",
    "保修": "售后服务",
    "售后": "售后服务",
    "运费": "配送政策",
    "包邮": "配送政策",
    "FAQ": "常见问题",
    "客服": "智能客服",
    "RAG": "知识库检索",
    "向量": "知识库",
}

# 智能客服场景：产品/售后/闲聊/投诉
INTENT_LABELS = {
    "product_consult": "产品介绍",
    "after_sale": "售后问题",
    "chitchat": "闲聊",
    "complaint": "投诉",
    "faq_cached": "FAQ 缓存",
}


def map_retrieval_terms(text: str, keywords: list[str] | None = None) -> list[str]:
    """将原问与关键词映射为内部检索词列表。"""
    terms: list[str] = []
    q = text or ""

    for kw in keywords or []:
        if kw and kw not in terms:
            terms.append(kw)

    for src, dst in TERM_DICTIONARY.items():
        if src in q and dst not in terms:
            terms.append(dst)
        for kw in keywords or []:
            if src in kw and dst not in terms:
                terms.append(dst)

    for token in q.replace("，", " ").replace("。", " ").replace("？", " ").split():
        token = token.strip(" ，。；;：:?")
        if len(token) >= 2 and token not in terms:
            terms.append(token)

    return terms[:12]
