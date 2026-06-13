"""Agent Prompt 注册表：对齐 web_rebuild Agent 配置（routing + AGENT.md 模板）。

加载优先级（高 → 低）：
1. backend/data/agent_config.json 中的 agent_prompts 覆盖
2. 上级 src/agent/config.json 的 agent_prompts
3. backend/data/agents/{agent_key}/AGENT.md 内置模板
4. 上级 src/agent/agents/{subdir}/AGENT.md（legacy 映射）
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED_AGENTS_DIR = _BACKEND_ROOT / "data" / "agents"
_LOCAL_CONFIG_PATH = _BACKEND_ROOT / "data" / "agent_config.json"

# 上级 agents 目录（video_gui 同源）
_PARENT_AGENTS_DIR: Path | None = None
for _p in Path(__file__).resolve().parents:
    _c = _p / "src" / "agent" / "agents"
    if _c.is_dir():
        _PARENT_AGENTS_DIR = _c.resolve()
        break

_LEGACY_AGENT_SUBDIR: dict[str, str] = {
    "doc_standardize_agent": "doc_standardize",
    "summary_agent": "summary",
    "qa_orchestrator_agent": "qa_orchestrator",
    "ops_agent": "ops",
}

# 多模态 / RAG 文档标准化 Agent 目录（agent_key → 子目录名，默认同 key）
MULTIMODAL_AGENT_KEYS: tuple[str, ...] = (
    "image_type_classifier_agent",
    "image_describe_ui_menu_agent",
    "image_describe_ui_design_agent",
    "image_describe_flowchart_agent",
    "image_describe_chart_agent",
    "image_describe_api_diagram_agent",
    "image_describe_general_agent",
    "image_ocr_llm_enrich_agent",
    "doc_standardize_agent",
)

AGENT_CATALOG: dict[str, dict[str, Any]] = {
    "image_type_classifier_agent": {
        "label": "图片类型识别",
        "group": "multimodal_image",
        "kind": "vlm",
        "task_type": "vlm",
        "variables": ["doc_context", "image_id", "file_name"],
        "hint": "VLM 输出 JSON：type/confidence/title_hint",
    },
    "image_describe_ui_menu_agent": {
        "label": "UI 菜单截图描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "task_type": "vlm",
        "variables": ["doc_context", "title_hint", "ocr_text", "image_id"],
        "hint": "软件界面/菜单截图的结构化纯描述",
    },
    "image_describe_ui_design_agent": {
        "label": "UI 设计插图描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "task_type": "vlm",
        "variables": ["doc_context", "title_hint", "ocr_text", "image_id"],
        "hint": "Banner/装饰/UI 稿与文档主题的关联描述",
    },
    "image_describe_flowchart_agent": {
        "label": "流程图描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "task_type": "vlm",
        "variables": ["doc_context", "title_hint", "ocr_text"],
        "hint": "流程/架构/泳道图；可输出 JSON（description/mermaid/nodes/edges）",
    },
    "image_describe_chart_agent": {
        "label": "图表描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "task_type": "vlm",
        "variables": ["doc_context", "title_hint", "ocr_text"],
        "hint": "柱状/折线/饼图等；可输出 JSON（chart_type/data/insights）",
    },
    "image_describe_api_diagram_agent": {
        "label": "接口链路图描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "task_type": "vlm",
        "variables": ["doc_context", "title_hint", "ocr_text"],
        "hint": "时序/链路图；可输出 JSON（apis/services/sequence_diagram）",
    },
    "image_describe_general_agent": {
        "label": "通用插图描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "task_type": "vlm",
        "variables": ["doc_context", "title_hint", "ocr_text", "image_type"],
        "hint": "photo/unknown 等兜底 VLM 描述",
    },
    "image_ocr_llm_enrich_agent": {
        "label": "OCR+LLM 描述合成",
        "group": "multimodal_image",
        "kind": "llm",
        "task_type": "reason",
        "variables": ["doc_context", "ocr_text", "image_type", "title_hint", "vlm_draft"],
        "hint": "OCR 原文 + 文档上下文 → 结构化 RAG 描述（无 VLM 或降级时）",
    },
    "doc_standardize_agent": {
        "label": "原文整理",
        "group": "doc_normalize",
        "kind": "llm",
        "task_type": "summary",
        "variables": ["transcript", "article"],
        "hint": "转 MD 前的正文去噪、分段、繁简转换",
    },
    "summary_agent": {
        "label": "文档摘要",
        "group": "doc_normalize",
        "kind": "llm",
        "task_type": "summary",
        "variables": ["transcript", "article"],
        "hint": "提取核心主题、关键数据点与适用场景的结构化摘要",
    },
    "qa_orchestrator_agent": {
        "label": "AI 问答与调度",
        "group": "chat_agent",
        "kind": "llm",
        "task_type": "qa",
        "variables": ["question", "context", "history"],
        "hint": "统一问答入口：问题理解、检索调度、答案编排、异常兜底",
    },
    "ops_agent": {
        "label": "系统运维诊断",
        "group": "chat_agent",
        "kind": "llm",
        "task_type": "reason",
        "variables": ["error_log", "system_state", "context"],
        "hint": "失败链路定位、重试策略建议、节点路由补偿",
    },
}

DESCRIBE_AGENT_BY_IMAGE_TYPE: dict[str, str] = {
    "ui_menu": "image_describe_ui_menu_agent",
    "ui_design": "image_describe_ui_design_agent",
    "flowchart": "image_describe_flowchart_agent",
    "chart": "image_describe_chart_agent",
    "api_diagram": "image_describe_api_diagram_agent",
    "photo": "image_describe_general_agent",
    "unknown": "image_describe_general_agent",
}

_VAR_PATTERN = re.compile(r"\{(\w+)\}")


def _read_text(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning(
            "[智能客服-Agent配置|agent_prompt_registry|读取|硬编执行|失败] path=%s; err=%s",
            path,
            str(exc)[:120],
        )
    return ""


def _load_local_config() -> dict[str, Any]:
    if not _LOCAL_CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(_LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning(
            "[智能客服-Agent配置|agent_prompt_registry|本地配置|硬编执行|解析失败] err=%s",
            str(exc)[:120],
        )
        return {}


def _load_parent_config() -> dict[str, Any]:
    cfg_path = settings.resolved_gateway_config_path
    if not cfg_path or not cfg_path.is_file():
        return {}
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _bundled_agent_md(agent_key: str) -> str:
    p = _BUNDLED_AGENTS_DIR / agent_key / "AGENT.md"
    return _read_text(p)


def _legacy_agent_md(agent_key: str) -> str:
    if not _PARENT_AGENTS_DIR:
        return ""
    sub = _LEGACY_AGENT_SUBDIR.get(agent_key, agent_key.replace("_agent", ""))
    return _read_text(_PARENT_AGENTS_DIR / sub / "AGENT.md")


def _merged_prompt_overrides() -> dict[str, str]:
    merged: dict[str, str] = {}
    parent = _load_parent_config()
    parent_prompts = parent.get("agent_prompts")
    if isinstance(parent_prompts, dict):
        for k, v in parent_prompts.items():
            if v and str(v).strip():
                merged[str(k)] = str(v).strip()

    local = _load_local_config()
    local_prompts = local.get("agent_prompts")
    if isinstance(local_prompts, dict):
        for k, v in local_prompts.items():
            merged[str(k)] = str(v or "").strip()
    return merged


def list_agent_catalog() -> list[dict[str, Any]]:
    """返回可配置 Agent 清单（含是否已有自定义覆盖）。"""
    overrides = _merged_prompt_overrides()
    out: list[dict[str, Any]] = []
    for key, meta in AGENT_CATALOG.items():
        row = dict(meta)
        row["agent_key"] = key
        row["has_override"] = bool(overrides.get(key, "").strip())
        row["builtin_exists"] = (_BUNDLED_AGENTS_DIR / key / "AGENT.md").is_file()
        out.append(row)
    return out


def load_agent_prompt(agent_key: str) -> str:
    """加载 Agent 完整 Prompt 文本（含 AGENT.md 正文）。"""
    key = (agent_key or "").strip()
    if not key:
        return ""

    overrides = _merged_prompt_overrides()
    if overrides.get(key, "").strip():
        return overrides[key].strip()

    bundled = _bundled_agent_md(key)
    if bundled:
        return bundled

    legacy = _legacy_agent_md(key)
    if legacy:
        return legacy

    return ""


def render_agent_prompt(agent_key: str, **variables: Any) -> str:
    """渲染 Prompt：替换 {doc_context} 等占位符；缺失变量置空。"""
    template = load_agent_prompt(agent_key)
    if not template:
        return ""

    str_vars = {k: str(v if v is not None else "") for k, v in variables.items()}

    def _repl(m: re.Match[str]) -> str:
        name = m.group(1)
        return str_vars.get(name, "")

    return _VAR_PATTERN.sub(_repl, template).strip()


def describe_agent_for_image_type(image_type: str) -> str:
    t = (image_type or "unknown").strip().lower()
    return DESCRIBE_AGENT_BY_IMAGE_TYPE.get(t, "image_describe_general_agent")


def load_agent_routing() -> dict[str, dict[str, Any]]:
    """合并上级 config 与本地 agent_config.json 的路由规则。"""
    rules: dict[str, dict[str, Any]] = {}
    parent = _load_parent_config()
    pr = parent.get("agent_route_rules")
    if isinstance(pr, dict):
        for k, v in pr.items():
            if isinstance(v, dict):
                rules[str(k)] = {
                    "mode": str(v.get("mode") or "system_compete"),
                    "nodes": list(v.get("nodes") or []),
                }

    local = _load_local_config()
    lr = local.get("agent_route_rules")
    if isinstance(lr, dict):
        for k, v in lr.items():
            if isinstance(v, dict):
                rules[str(k)] = {
                    "mode": str(v.get("mode") or "system_compete"),
                    "nodes": list(v.get("nodes") or []),
                }

    # 确保 catalog 中每个 Agent 至少有默认路由项
    for key in AGENT_CATALOG:
        rules.setdefault(key, {"mode": "system_compete", "nodes": []})
    return rules


def _persist_local_config(patch: dict[str, Any]) -> None:
    current = _load_local_config()
    current.update(patch)
    _LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOCAL_CONFIG_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def save_agent_prompt(agent_key: str, content: str) -> None:
    key = (agent_key or "").strip()
    if not key:
        raise ValueError("agent_key 不能为空")
    local = _load_local_config()
    prompts = dict(local.get("agent_prompts") or {})
    prompts[key] = str(content or "")
    local["agent_prompts"] = prompts
    _persist_local_config(local)

    # 同步写入 bundled AGENT.md，便于 diff 与导出
    md_dir = _BUNDLED_AGENTS_DIR / key
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / "AGENT.md"
    md_path.write_text((content or "").strip() + "\n", encoding="utf-8")
    logger.info(
        "[智能客服-Agent配置|agent_prompt_registry|save_agent_prompt|硬编执行|完成] agent_key=%s; len=%s",
        key,
        len(content or ""),
    )


def save_agent_routing(rules: dict[str, Any]) -> None:
    if not isinstance(rules, dict):
        raise ValueError("rules 必须为对象")
    normalized: dict[str, dict[str, Any]] = {}
    for k, v in rules.items():
        if not isinstance(v, dict):
            continue
        nodes = v.get("nodes")
        if isinstance(nodes, str):
            nodes = [x.strip() for x in nodes.split(",") if x.strip()]
        normalized[str(k)] = {
            "mode": str(v.get("mode") or "system_compete"),
            "nodes": list(nodes or []),
        }
    local = _load_local_config()
    local["agent_route_rules"] = normalized
    _persist_local_config(local)
    logger.info(
        "[智能客服-Agent配置|agent_prompt_registry|save_agent_routing|硬编执行|完成] count=%s",
        len(normalized),
    )


def extract_prompt_body(agent_md: str) -> str:
    """从 AGENT.md 提取「执行段」：优先 ## Prompt 之后的内容，否则全文。"""
    text = (agent_md or "").strip()
    if not text:
        return ""
    marker = "## Prompt"
    idx = text.find(marker)
    if idx >= 0:
        body = text[idx + len(marker) :].strip()
        if body.startswith("\n"):
            body = body.lstrip()
        return body
    return text
