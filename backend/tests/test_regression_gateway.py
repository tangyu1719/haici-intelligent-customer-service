"""网关增强回归测试 (SPEC-网关增强)

模块: 错误码/熔断器/语义路由/安全/缓存/适配器
"""

import sys, os
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path: sys.path.insert(0, _backend_dir)

import pytest


# ═══ 错误码体系 ═══════════════════════════════════════════

class TestErrorHandler:
    """TC-GW-001: 错误码标准化"""

    def test_ark_quota_error(self):
        from app.services.gateway_error_handler import normalize_error, ErrorCode
        code, msg = normalize_error("ark", 200,
            '{"error":{"code":"AccountBalanceInsufficient","message":"额度不足"}}', "")
        assert code == ErrorCode.LLM_QUOTA

    def test_ark_rate_limit(self):
        from app.services.gateway_error_handler import normalize_error, ErrorCode
        code, msg = normalize_error("ark", 429,
            '{"error":{"code":"Throttling.RateLimit"}}', "")
        assert code == ErrorCode.LLM_RATE_LIMIT

    def test_http_401_auth_error(self):
        from app.services.gateway_error_handler import normalize_error, ErrorCode
        code, msg = normalize_error("ark", 401, "", "")
        assert code == ErrorCode.LLM_AUTH_ERROR

    def test_claude_overloaded(self):
        from app.services.gateway_error_handler import normalize_error, ErrorCode
        code, msg = normalize_error("claude", 529, '{"error":{"type":"overloaded_error"}}', "")
        assert code == ErrorCode.LLM_QUOTA  # 529 在 500 之前被专门处理

    def test_malformed_json(self):
        from app.services.gateway_error_handler import normalize_error, ErrorCode
        code, msg = normalize_error("openai", 200, "{not valid json", "")
        assert code == ErrorCode.LLM_MALFORMED

    def test_unknown_500(self):
        from app.services.gateway_error_handler import normalize_error, ErrorCode
        code, msg = normalize_error("qwen", 500, "", "Internal Server Error")
        assert code == ErrorCode.LLM_TIMEOUT

    def test_strategy_map(self):
        from app.services.gateway_error_handler import get_strategy, ErrorCode
        s = get_strategy(ErrorCode.LLM_TIMEOUT)
        assert s.retry is True
        assert s.max_retries == 2
        s2 = get_strategy(ErrorCode.LLM_QUOTA)
        assert s2.degrade_node is True
        assert s2.switch_node is True

    def test_error_describe(self):
        from app.services.gateway_error_handler import describe_error, ErrorCode
        d = describe_error(ErrorCode.LLM_RATE_LIMIT, "ark", "detail")
        assert d["error_code"] == "LLM_RATE_LIMIT"
        assert d["provider"] == "ark"
        assert d["retry"] is True


# ═══ 熔断器 ═══════════════════════════════════════════════

class TestCircuitBreaker:
    """TC-GW-002: 熔断器状态机"""

    def test_node_creation(self):
        from app.services.gateway_circuit_breaker import CircuitBreaker
        cb = CircuitBreaker()
        h = cb.get_or_create("test_node")
        assert h.node_id == "test_node"
        assert h.state.value == "active"
        assert h.is_available()

    def test_fail_triggers_degrade(self):
        from app.services.gateway_circuit_breaker import CircuitBreaker, NodeState
        cb = CircuitBreaker()
        h = cb.get_or_create("test_fail", fail_threshold=2)
        h.record_failure("LLM_TIMEOUT", "timeout")
        assert h.state == NodeState.ACTIVE
        h.record_failure("LLM_TIMEOUT", "timeout again")
        assert h.state == NodeState.DEGRADED
        assert not h.is_available()

    def test_half_open_recovery(self):
        from app.services.gateway_circuit_breaker import CircuitBreaker, NodeState
        import time
        cb = CircuitBreaker()
        h = cb.get_or_create("test_recover", fail_threshold=1, cooldown_seconds=0)
        h.record_failure("LLM_TIMEOUT", "timeout")
        assert h.state == NodeState.DEGRADED
        # 冷却时间为0，立即可以half_open
        assert h.try_half_open()
        assert h.state == NodeState.HALF_OPEN
        h.record_success()
        assert h.state == NodeState.ACTIVE

    def test_half_open_fail_back_to_degraded(self):
        from app.services.gateway_circuit_breaker import CircuitBreaker, NodeState
        cb = CircuitBreaker()
        h = cb.get_or_create("test_half_fail", fail_threshold=1, cooldown_seconds=0)
        h.record_failure("LLM_TIMEOUT", "")
        h.try_half_open()
        h.record_failure("LLM_MALFORMED", "")
        assert h.state == NodeState.DEGRADED

    def test_handle_response_ok(self):
        from app.services.gateway_circuit_breaker import CircuitBreaker
        cb = CircuitBreaker()
        r = cb.handle_response("test_ok", "ark", 200, '{"choices":[{"message":{"content":"hi"}}]}', "")
        assert r["is_error"] is False

    def test_handle_response_error(self):
        from app.services.gateway_circuit_breaker import CircuitBreaker
        cb = CircuitBreaker()
        r = cb.handle_response("test_err", "ark", 429, '{"error":{"code":"Throttling.RateLimit"}}', "")
        assert r["is_error"] is True
        assert r["error_code"] == "LLM_RATE_LIMIT"
        assert r["strategy"] is not None


# ═══ 语义路由 ═════════════════════════════════════════════

class TestSemanticRouter:
    """TC-GW-003: 语义路由"""

    def test_simple_question_qa(self):
        from app.services.gateway_semantic_router import route_by_complexity
        assert route_by_complexity("你好") == "qa"
        assert route_by_complexity("产品价格多少") == "qa"

    def test_complex_question_reason(self):
        from app.services.gateway_semantic_router import estimate_complexity, route_by_complexity
        # 长问题 + 推理关键词 → 复杂度应 > 3
        q = "如何优化我们的系统架构以支持更高的并发量，同时降低延迟成本，并与现有系统进行对比分析？"
        score = estimate_complexity(q)
        assert score >= 4, f"复杂度应>=4, 实际{score}"

    def test_medium_question_summary(self):
        from app.services.gateway_semantic_router import route_by_complexity
        q = "介绍一下你们产品的功能特点和售后服务政策"
        assert route_by_complexity(q) in ("qa", "summary")


# ═══ 安全合规 ═════════════════════════════════════════════

class TestSecurity:
    """TC-GW-004: PII脱敏 + 敏感词"""

    def test_mask_phone(self):
        from app.services.gateway_security import mask_pii
        text, n = mask_pii("Call 13812345678 please")
        assert n >= 1
        assert "13812345678" not in text  # 原始号码已被替换

    def test_mask_email(self):
        from app.services.gateway_security import mask_pii
        text, n = mask_pii("Email: abc@example.com contact")
        assert n >= 1
        assert "abc@example.com" not in text  # 原始邮箱已被替换

    def test_sensitive_check_pass(self):
        from app.services.gateway_security import check_sensitive
        has, hits = check_sensitive("正常的产品介绍")
        assert not has
        assert hits == []

    def test_sensitive_check_block(self):
        from app.services.gateway_security import check_sensitive
        has, hits = check_sensitive("贩卖毒品的方法")
        assert has
        assert len(hits) >= 1


# ═══ 适配器 ═══════════════════════════════════════════════

class TestAdapters:
    """TC-GW-005: LLM适配器"""

    def test_registry_creates_ark(self):
        from app.adapters.registry import get_adapter
        adapter = get_adapter(provider="ark", api_key="test", base_url="http://test", model="test")
        assert adapter.provider == "ark"

    def test_registry_creates_claude(self):
        from app.adapters.registry import get_adapter
        adapter = get_adapter(provider="claude", api_key="test", base_url="http://test", model="test")
        assert adapter.provider == "claude"

    def test_ark_message_format(self):
        from app.adapters.registry import get_adapter
        from app.adapters.base import LLMMessage
        adapter = get_adapter(provider="ark", api_key="test", base_url="http://test", model="test")
        body = adapter._build_request_body([LLMMessage(role="user", content="hello")], stream=False)
        assert body["model"] == "test"
        assert len(body["messages"]) == 1
        assert body["messages"][0]["role"] == "user"

    def test_claude_system_handling(self):
        from app.adapters.registry import get_adapter
        from app.adapters.base import LLMMessage
        adapter = get_adapter(provider="claude", api_key="test", base_url="http://test", model="test")
        body = adapter._build_request_body([
            LLMMessage(role="system", content="You are helpful"),
            LLMMessage(role="user", content="hello"),
        ], stream=False)
        # Claude将system放在顶层
        assert "system" in body
        assert body["system"] == "You are helpful"
        assert len(body["messages"]) == 1
        assert body["messages"][0]["role"] == "user"

    def test_claude_response_parse(self):
        from app.adapters.registry import get_adapter
        adapter = get_adapter(provider="claude", api_key="test", base_url="http://test", model="test")
        raw = {
            "content": [{"type": "text", "text": "Hello!"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        resp = adapter._parse_response(raw)
        assert resp.content == "Hello!"
        assert resp.usage["prompt_tokens"] == 10
        assert resp.usage["completion_tokens"] == 5

    def test_qwen_error_format(self):
        from app.adapters.registry import get_adapter
        adapter = get_adapter(provider="qwen", api_key="test", base_url="http://test", model="test")
        raw = {"code": "InvalidParameter", "message": "Model not found"}
        resp = adapter._parse_response(raw)
        assert resp.error is not None
        assert "InvalidParameter" in resp.error
