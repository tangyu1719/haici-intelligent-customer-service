"""对话上下文管理单元测试。"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.chat_context import (
    count_history_chars,
    select_history_messages,
    select_sliding_window_messages,
    trim_messages_to_budget,
)
from app.services.model_context_registry import lookup_context_chars, register_model_context
from app.services.session_context_manager import should_compress


def _msg(role: str, content: str, mid: int = 1):
    return SimpleNamespace(role=role, content=content, id=mid)


def test_lookup_context_chars_known_model():
    chars = lookup_context_chars("qwen-turbo")
    assert chars >= 128_000


def test_register_custom_model():
    register_model_context("custom-model-x", 8000)
    assert lookup_context_chars("custom-model-x") == 8000 * 2


def test_count_history_chars():
    rows = [_msg("user", "你好"), _msg("assistant", "您好")]
    assert count_history_chars(rows) == 4


def test_select_sliding_window_limits_turns():
    rows = [_msg("user", f"q{i}", i) for i in range(1, 25)]
    picked = select_sliding_window_messages(rows, budget_chars=100_000)
    assert len(picked) <= 20  # 10 轮 * 2


def test_should_compress_by_ratio():
    rows = [_msg("user", "x" * 5000, i) for i in range(1, 6)]
    compress, ratio = should_compress(rows, budget_chars=10_000, turn_count=5)
    assert compress is True
    assert ratio >= 0.8


def test_should_compress_by_turns():
    rows = [_msg("user", "短", i) for i in range(1, 30)]
    compress, _ = should_compress(rows, budget_chars=1_000_000, turn_count=15)
    assert compress is True


def test_full_mode_when_ample():
    rows = [_msg("user", "你好", 1), _msg("assistant", "您好", 2)]
    compress, _ = should_compress(rows, budget_chars=50_000, turn_count=1)
    assert compress is False
    picked = select_history_messages(rows, budget_chars=50_000)
    assert len(picked) == 2


def test_trim_messages_to_budget():
    msgs = [{"role": "user", "content": "a" * 100}, {"role": "assistant", "content": "b" * 100}]
    trimmed = trim_messages_to_budget(msgs, 120)
    total = sum(len(m["content"]) for m in trimmed)
    assert total <= 120
