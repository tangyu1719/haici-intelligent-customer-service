"""日志脱敏辅助。"""

from app.logging_utils import mask_secret, sanitize_log_text


def test_mask_secret():
    assert mask_secret("abcdefghijklmnop") == "abcd...mnop"
    assert mask_secret("short") == "***"


def test_sanitize_log_text():
    raw = "Authorization: Bearer sk-live-secret-key-12345"
    out = sanitize_log_text(raw)
    assert "sk-live-secret-key-12345" not in out
