"""系统管理设置（JSON 持久化，启动时自动创建）。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock

from app.config import settings

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(settings.UPLOAD_DIR).resolve().parent / "system_settings.json"
_LOCK = Lock()

DEFAULTS: dict[str, int | str | bool] = {
    "session_active_persist_interval_minutes": 10,
}


def _ensure_file() -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _SETTINGS_PATH.is_file():
        _SETTINGS_PATH.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")


def load_system_settings() -> dict:
    with _LOCK:
        _ensure_file()
        try:
            raw = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "[系统管理-设置|system_settings.load|system_settings.json|硬编执行|降级] error_type=%s",
                type(exc).__name__,
            )
            raw = {}
        merged = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
        return merged


def save_system_settings(patch: dict) -> dict:
    with _LOCK:
        current = load_system_settings()
        for key, val in patch.items():
            if key not in DEFAULTS:
                continue
            if key == "session_active_persist_interval_minutes":
                current[key] = max(1, min(120, int(val)))
            else:
                current[key] = val
        _SETTINGS_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "[系统管理-设置|system_settings.save|system_settings.json|硬编执行|完成] keys=%s",
            ",".join(patch.keys()),
        )
        return current


def get_session_persist_interval_minutes() -> int:
    val = load_system_settings().get("session_active_persist_interval_minutes", 10)
    try:
        return max(1, min(120, int(val)))
    except (TypeError, ValueError):
        return 10
