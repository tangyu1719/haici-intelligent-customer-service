"""SSE 缓存事件与 LLM token 流分离。"""

import asyncio
import os
import sys

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tests_dir = os.path.join(_backend_dir, "tests")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)


class TestChatSseCachedEvents:
    def test_emit_cached_answer_event_type(self):
        from app.routers.chat import _emit_cached_answer

        async def _run():
            events = []
            async for chunk in _emit_cached_answer("标准答案", "faq_cache"):
                events.append(chunk)
            return events

        chunks = asyncio.run(_run())
        assert len(chunks) == 1
        assert chunks[0].startswith("event: cached")
        assert "标准答案" in chunks[0]
        assert "faq_cache" in chunks[0]
        assert "event: token" not in chunks[0]

    def test_collect_sse_text_includes_cached(self):
        from http_regression_helpers import collect_sse_text

        class _FakeResp:
            def iter_lines(self, decode_unicode=True):
                yield "event: cached"
                yield 'data: {"content":"兜底话术","source":"rule_fallback"}'
                yield ""
                yield "event: done"
                yield 'data: {"assistant_message_id":1}'
                yield ""

        text = collect_sse_text(_FakeResp())
        assert "兜底话术" in text
