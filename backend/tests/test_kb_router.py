"""多知识库路由单元测试。"""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.config import settings
from app.services.kb_router import (
    retrieval_sufficient,
    select_kb_route,
)


class TestRetrievalSufficient:
    def test_empty_docs_insufficient(self):
        ok, score, count = retrieval_sufficient([])
        assert ok is False
        assert score == 0.0
        assert count == 0

    def test_low_count_insufficient(self):
        docs = [Document(page_content="a", metadata={"score": 0.9})]
        ok, _, count = retrieval_sufficient(docs)
        assert count == 1
        assert ok is False

    def test_low_score_insufficient(self):
        min_k = settings.RAG_TOP_K
        docs = [
            Document(page_content=f"x{i}", metadata={"score": 0.1})
            for i in range(min_k)
        ]
        ok, top, _ = retrieval_sufficient(docs)
        assert top == 0.1
        assert ok is False

    def test_meets_threshold(self):
        min_k = settings.RAG_TOP_K
        threshold = settings.RAG_SCORE_THRESHOLD
        docs = [
            Document(page_content=f"x{i}", metadata={"score": threshold + 0.1})
            for i in range(min_k)
        ]
        ok, _, count = retrieval_sufficient(docs)
        assert count == min_k
        assert ok is True


class TestSelectKbRoute:
    @patch("app.services.kb_router.list_accessible_knowledge_bases")
    def test_explicit_kb_permission(self, mock_list):
        kb = MagicMock()
        kb.id = 5
        kb.name = "产品库"
        kb.status = 1
        kb.user_id = 10
        mock_list.return_value = [kb]
        db = MagicMock()
        db.get.return_value = kb

        decision = select_kb_route(db, 10, "保修多久", "保修多久", explicit_kb_id=5)
        assert decision.kb_id == 5
        assert decision.tenant_id == "5"
        assert decision.routed is False

    @patch("app.services.kb_router.list_accessible_knowledge_bases")
    def test_no_accessible_kbs_fallback_user(self, mock_list):
        mock_list.return_value = []
        db = MagicMock()
        decision = select_kb_route(db, 99, "问题", "问题", fallback_user_tenant="99")
        assert decision.kb_id is None
        assert decision.tenant_id == "99"

    @patch("app.services.kb_router.list_accessible_knowledge_bases")
    def test_single_kb_auto_pick(self, mock_list):
        kb = MagicMock()
        kb.id = 1
        kb.name = "默认库"
        kb.is_default = 1
        mock_list.return_value = [kb]
        db = MagicMock()
        decision = select_kb_route(db, 1, "云盒怎么用", "云盒怎么用")
        assert decision.kb_id == 1
        assert decision.routed is True

    @patch("app.services.kb_router.rank_knowledge_bases")
    @patch("app.services.kb_router.list_accessible_knowledge_bases")
    def test_multi_kb_vector_probe(self, mock_list, mock_rank):
        kb1 = MagicMock(id=1, name="售后", is_default=0)
        kb2 = MagicMock(id=2, name="产品", is_default=1)
        mock_list.return_value = [kb1, kb2]
        mock_rank.return_value = [(kb2, 0.8), (kb1, 0.2)]
        db = MagicMock()
        decision = select_kb_route(db, 1, "产品参数", "产品参数")
        assert decision.kb_id == 2
        assert decision.routed is True
        assert decision.route_score == 0.8
