"""网关增强回归测试 (SPEC-网关增强)

模块: 错误码/熔断器/语义路由/安全/缓存/适配器
"""

import sys, os
import json
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


# ═══ LLM 错误恢复（规则 + 运维 Agent） ═══════════════════

class TestLLMErrorRecovery:
    """TC-GW-006: 错误恢复策略执行"""

    def test_plan_timeout_retry_then_switch(self):
        from app.services.gateway_error_handler import ErrorCode
        from app.services.llm_error_recovery import RecoveryAction, plan_recovery

        p1 = plan_recovery(ErrorCode.LLM_TIMEOUT, retries_used=0, switches_used=0)
        assert p1.action == RecoveryAction.RETRY
        p2 = plan_recovery(ErrorCode.LLM_TIMEOUT, retries_used=2, switches_used=0)
        assert p2.action == RecoveryAction.SWITCH_NODE
        p3 = plan_recovery(ErrorCode.LLM_TIMEOUT, retries_used=2, switches_used=1)
        assert p3.action == RecoveryAction.ABORT

    def test_plan_rate_limit_switch_node(self):
        from app.services.gateway_error_handler import ErrorCode
        from app.services.llm_error_recovery import RecoveryAction, plan_recovery

        p = plan_recovery(ErrorCode.LLM_RATE_LIMIT, switches_used=0)
        assert p.action == RecoveryAction.SWITCH_NODE
        assert p.backoff_seconds >= 0

    def test_plan_invalid_request_ops_agent(self):
        from app.services.gateway_error_handler import ErrorCode
        from app.services.llm_error_recovery import RecoveryAction, plan_recovery

        p1 = plan_recovery(ErrorCode.LLM_INVALID_REQUEST, ops_used=False)
        assert p1.action == RecoveryAction.OPS_AGENT
        p2 = plan_recovery(ErrorCode.LLM_INVALID_REQUEST, ops_used=True)
        assert p2.action == RecoveryAction.ABORT

    def test_plan_context_overflow_truncate(self):
        from app.services.gateway_error_handler import ErrorCode
        from app.services.llm_error_recovery import RecoveryAction, plan_recovery

        p = plan_recovery(ErrorCode.LLM_CONTEXT_OVERFLOW, retries_used=0)
        assert p.action == RecoveryAction.TRUNCATE_RETRY

    def test_plan_content_filter_abort(self):
        from app.services.gateway_error_handler import ErrorCode
        from app.services.llm_error_recovery import RecoveryAction, plan_recovery

        p = plan_recovery(ErrorCode.LLM_CONTENT_FILTER)
        assert p.action == RecoveryAction.ABORT

    def test_apply_param_patches(self):
        from app.services.llm_error_recovery import apply_param_patches

        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "x" * 5000},
        ]
        new_msgs, max_tok, temp = apply_param_patches(
            msgs,
            {"max_tokens": 256, "temperature": 0.05, "max_user_chars": 1000},
            max_tokens=1024,
            temperature=0.2,
        )
        assert max_tok == 256
        assert temp == 0.05
        assert len(new_msgs[-1]["content"]) <= 1000

    def test_parse_ops_agent_json(self):
        from app.services.llm_error_recovery import _parse_ops_json

        raw = (
            '诊断如下：{"fault_type":"参数错误","root_cause":"max_tokens过大",'
            '"fix_actions":["降低max_tokens"],"param_patches":{"max_tokens":512}}'
        )
        d = _parse_ops_json(raw)
        assert d.fault_type == "参数错误"
        assert d.param_patches.get("max_tokens") == 512

    def test_invoke_ops_agent_mock(self):
        from app.services.gateway_error_handler import ErrorCode
        from app.services.llm_error_recovery import invoke_ops_agent_diagnosis

        def _mock_llm(prompt: str, task_type: str) -> str:
            return json.dumps(
                {
                    "fault_type": "InvalidParameter",
                    "root_cause": "model字段缺失",
                    "fix_actions": ["补全model"],
                    "param_patches": {"max_tokens": 512, "temperature": 0.1},
                },
                ensure_ascii=False,
            )

        d = invoke_ops_agent_diagnosis(
            error_code=ErrorCode.LLM_INVALID_REQUEST,
            provider="ark",
            node_id="node_a",
            status_code=400,
            response_body='{"error":{"code":"InvalidParameter"}}',
            messages=[{"role": "user", "content": "hello"}],
            task_type="qa",
            llm_call=_mock_llm,
        )
        assert d.has_param_patches
        assert d.param_patches["max_tokens"] == 512

    def test_run_recovery_switch_node(self):
        from app.services.gateway_error_handler import ErrorCode, get_strategy
        from app.services.llm_error_recovery import (
            RecoveryAction,
            RecoveryPlan,
            RecoveryState,
            run_recovery_step,
        )
        from app.services.llm_gateway import GatewayNode, LLMGateway

        gw = LLMGateway()
        gw.nodes.clear()
        gw.nodes["n1"] = GatewayNode(
            id="n1", name="A", provider="ark", base_url="http://a", api_key="k", model="m1", priority=1
        )
        gw.nodes["n2"] = GatewayNode(
            id="n2", name="B", provider="qwen", base_url="http://b", api_key="k", model="m2", priority=2
        )
        import app.services.llm_gateway as lg_mod
        old = lg_mod._gateway
        lg_mod._gateway = gw
        try:
            plan = RecoveryPlan(
                action=RecoveryAction.SWITCH_NODE,
                error_code=ErrorCode.LLM_RATE_LIMIT,
                strategy=get_strategy(ErrorCode.LLM_RATE_LIMIT),
                message="switch",
            )
            state = RecoveryState()
            _, _, _, new_id = run_recovery_step(
                plan,
                state,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=512,
                temperature=0.2,
                task_type="qa",
                error_code=ErrorCode.LLM_RATE_LIMIT,
                provider="ark",
                node_id="n1",
                status_code=429,
                response_body="rate limit",
            )
            assert new_id == "n2"
            assert state.switches_used == 1
        finally:
            lg_mod._gateway = old

    def test_sync_chat_retry_on_timeout(self, monkeypatch):
        """模拟超时后规则重试成功"""
        import httpx
        from app.llms import LLMWrapper
        from app.services.llm_gateway import GatewayNode

        calls = {"n": 0}

        class _Resp:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 3}}

        class _Client:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, *a, **k):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise httpx.TimeoutException("timed out")
                return _Resp()

        monkeypatch.setattr(httpx, "Client", _Client)
        node = GatewayNode(
            id="t_node", name="T", provider="ark", base_url="http://t", api_key="k", model="m"
        )
        w = LLMWrapper()
        out = w._sync_chat(node, [{"role": "user", "content": "hi"}], 0.1, 64, task_type="qa")
        assert out == "ok"
        assert calls["n"] == 2


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
