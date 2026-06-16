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

DEFAULT_POOL_CEILING_MAP = "100:10,50:5,20:3"

DEFAULTS: dict[str, int | str | bool] = {
    "session_active_persist_interval_minutes": 10,
    # RAG 精筛落档：smart=按粗筛池比例+分数质量智能梯度；hard=按映射表硬配置
    "rag_pool_ceiling_mode": "smart",
    "rag_pool_ceiling_map": DEFAULT_POOL_CEILING_MAP,
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


def parse_pool_ceiling_map(raw: str) -> list[tuple[int, int]]:
    """解析 RAG 粗筛池→精筛上限映射，如 '100:10,50:5,20:3'。"""
    pairs: list[tuple[int, int]] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        left, right = part.split(":", 1)
        left, right = left.strip(), right.strip()
        if left.isdigit() and right.isdigit():
            pool_min, top_k = int(left), int(right)
            if pool_min > 0 and top_k > 0:
                pairs.append((pool_min, top_k))
    pairs.sort(key=lambda x: x[0], reverse=True)
    return pairs


def format_pool_ceiling_map(pairs: list[tuple[int, int]]) -> str:
    return ",".join(f"{p}:{k}" for p, k in sorted(pairs, key=lambda x: -x[0]))


def _normalize_pool_ceiling_mode(val: object) -> str:
    mode = str(val or "smart").strip().lower()
    return mode if mode in ("smart", "hard") else "smart"


def _normalize_pool_ceiling_map(val: object) -> str:
    raw = str(val or DEFAULT_POOL_CEILING_MAP).strip()
    pairs = parse_pool_ceiling_map(raw)
    if not pairs:
        return DEFAULT_POOL_CEILING_MAP
    return format_pool_ceiling_map(pairs)


def save_system_settings(patch: dict) -> dict:
    with _LOCK:
        current = load_system_settings()
        for key, val in patch.items():
            if key not in DEFAULTS:
                continue
            if key == "session_active_persist_interval_minutes":
                current[key] = max(1, min(120, int(val)))
            elif key == "rag_pool_ceiling_mode":
                current[key] = _normalize_pool_ceiling_mode(val)
            elif key == "rag_pool_ceiling_map":
                current[key] = _normalize_pool_ceiling_map(val)
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


def get_rag_pool_ceiling_mode() -> str:
    return _normalize_pool_ceiling_mode(load_system_settings().get("rag_pool_ceiling_mode"))


def get_rag_pool_ceiling_map_pairs() -> list[tuple[int, int]]:
    raw = load_system_settings().get("rag_pool_ceiling_map", DEFAULT_POOL_CEILING_MAP)
    pairs = parse_pool_ceiling_map(str(raw))
    return pairs or parse_pool_ceiling_map(DEFAULT_POOL_CEILING_MAP)
