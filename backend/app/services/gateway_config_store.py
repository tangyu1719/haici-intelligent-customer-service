"""LLM 网关配置单一读写入口（agent_gateway_config.json，本地文件 gitignore）。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCAL_GATEWAY_CONFIG = PROJECT_ROOT / "backend" / "data" / "agent_gateway_config.json"
LOCAL_GATEWAY_EXAMPLE = PROJECT_ROOT / "backend" / "data" / "agent_gateway_config.example.json"


def load_raw_gateway_config() -> dict[str, Any]:
    """加载网关 JSON：本地 data 文件优先，其次可选 monorepo 路径（.env LLM_GATEWAY_CONFIG）。"""
    if LOCAL_GATEWAY_CONFIG.is_file():
        try:
            raw = json.loads(LOCAL_GATEWAY_CONFIG.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "[智能客服-LLM|gateway_config_store|本地配置|硬编执行|解析失败] error=%s",
                exc,
            )

    optional = settings.resolved_gateway_config_path
    if optional and optional.is_file() and optional.resolve() != LOCAL_GATEWAY_CONFIG.resolve():
        try:
            raw = json.loads(optional.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                logger.info(
                    "[智能客服-LLM|gateway_config_store|上级配置|硬编执行|加载] path=%s",
                    optional,
                )
                return raw
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "[智能客服-LLM|gateway_config_store|上级配置|硬编执行|解析失败] path=%s; error=%s",
                optional,
                exc,
            )
    return {}


def save_raw_gateway_config(data: dict[str, Any]) -> None:
    LOCAL_GATEWAY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_GATEWAY_CONFIG.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    from app.services.llm_gateway import reload_llm_gateway

    reload_llm_gateway()
    logger.info(
        "[智能客服-LLM|gateway_config_store|本地配置|硬编执行|已保存] path=%s; nodes=%s",
        LOCAL_GATEWAY_CONFIG,
        len(data.get("api_gateway_nodes") or []),
    )


def ensure_local_gateway_file_from_example() -> None:
    """首次启动：若本地配置不存在，从 example 复制（不覆盖已有本地文件）。"""
    if LOCAL_GATEWAY_CONFIG.is_file():
        return
    if not LOCAL_GATEWAY_EXAMPLE.is_file():
        return
    LOCAL_GATEWAY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_GATEWAY_CONFIG.write_text(
        LOCAL_GATEWAY_EXAMPLE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    logger.info(
        "[智能客服-LLM|gateway_config_store|本地配置|硬编执行|已从 example 初始化]",
    )
