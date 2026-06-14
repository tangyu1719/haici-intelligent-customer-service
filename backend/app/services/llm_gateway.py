"""LLM API 网关：对齐 SuperBizAgent api_gateway_nodes + task_type 路由。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class GatewayNode:
    id: str
    name: str
    provider: str  # ark | qwen | openai_compatible
    base_url: str
    api_key: str
    model: str  # endpoint_id 或模型名
    priority: int = 100
    weight: int = 100
    status: str = "active"
    tags: list[str] = field(default_factory=list)


class LLMGateway:
    def __init__(self) -> None:
        self.route_mode = settings.GATEWAY_ROUTE_MODE
        self.nodes: dict[str, GatewayNode] = {}
        self.task_type_route: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        self.nodes.clear()
        self.task_type_route = dict(settings.gateway_task_type_route_map)

        # 1) 可选：从上级项目 config.json 加载节点池（与 web_rebuild_v2 一致）
        cfg_path = settings.resolved_gateway_config_path
        if cfg_path and cfg_path.is_file():
            try:
                raw = json.loads(cfg_path.read_text(encoding="utf-8"))
                self._merge_runtime_config(raw)
                if raw.get("gateway_route_mode"):
                    self.route_mode = str(raw["gateway_route_mode"]).strip().lower()
                logger.info(
                    "[智能客服-LLM|llm_gateway|配置|硬编执行|加载] 已合并上级 config.json; path=%s; nodes=%s",
                    cfg_path,
                    len(self.nodes),
                )
            except Exception as exc:
                logger.warning(
                    "[智能客服-LLM|llm_gateway|配置|硬编执行|加载] 上级 config 解析失败; error=%s",
                    exc,
                )

        # 2) 环境变量构建默认节点（通义 + 方舟双接入点）
        self._ensure_env_nodes()

        if not self.nodes:
            logger.warning("[智能客服-LLM|llm_gateway|配置|硬编执行|加载] 无可用网关节点，请检查 .env")

    def _merge_runtime_config(self, config: dict[str, Any]) -> None:
        if isinstance(config.get("gateway_task_type_route"), dict):
            for k, v in config["gateway_task_type_route"].items():
                if v:
                    self.task_type_route[str(k).lower()] = str(v).strip()

        nodes = config.get("api_gateway_nodes")
        if not isinstance(nodes, list):
            return

        fallback_key = (
            str(config.get("volcengine_api_key") or config.get("ARK_API_KEY") or settings.ARK_API_KEY or "")
        ).strip()
        fallback_base = (
            str(
                config.get("volcengine_base_url")
                or config.get("llm_base_url")
                or settings.ARK_BASE_URL
            )
        ).strip()

        for i, item in enumerate(nodes, 1):
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("id") or item.get("model_id") or "").strip()
            endpoint = str(item.get("endpoint_id") or item.get("model") or node_id).strip()
            if not node_id or not endpoint:
                continue
            provider = str(item.get("provider") or settings.GATEWAY_PROVIDER or "ark").strip().lower()
            if provider == "openai":
                provider = "openai_compatible"
            self.nodes[node_id] = GatewayNode(
                id=node_id,
                name=str(item.get("name") or node_id),
                provider=provider,
                base_url=str(item.get("base_url") or fallback_base).strip(),
                api_key=str(item.get("api_key") or fallback_key).strip(),
                model=endpoint,
                priority=int(item.get("priority", i * 10) or i * 10),
                weight=int(item.get("weight", 100) or 100),
                status=str(item.get("status") or "active").strip().lower(),
                tags=[str(t).lower() for t in (item.get("tags") or []) if str(t).strip()],
            )

    def _ensure_env_nodes(self) -> None:
        # 通义 DashScope（OpenAI 兼容模式）
        if settings.QWEN_API_KEY:
            qid = "node_qwen_dashscope"
            if qid not in self.nodes:
                self.nodes[qid] = GatewayNode(
                    id=qid,
                    name="通义千问 DashScope",
                    provider="qwen",
                    base_url=settings.QWEN_BASE_URL,
                    api_key=settings.QWEN_API_KEY,
                    model=settings.QWEN_MODEL,
                    priority=5,
                    weight=100,
                    tags=["qa", "summary", "chat"],
                )

        # 方舟 ARK — 问答接入点
        if settings.ARK_API_KEY and settings.LLM_MODEL_QA:
            qid = "node_ark_qa"
            if qid not in self.nodes:
                self.nodes[qid] = GatewayNode(
                    id=qid,
                    name="火山方舟 · 问答接入点",
                    provider="ark",
                    base_url=settings.ARK_BASE_URL,
                    api_key=settings.ARK_API_KEY,
                    model=settings.LLM_MODEL_QA,
                    priority=10,
                    weight=100,
                    tags=["qa", "chat"],
                )
            self.task_type_route.setdefault("qa", settings.LLM_MODEL_QA)
            self.task_type_route.setdefault("chat", settings.LLM_MODEL_QA)

        # 方舟 ARK — 推理/摘要接入点
        if settings.ARK_API_KEY and settings.LLM_MODEL_REASON:
            rid = "node_ark_reason"
            if rid not in self.nodes:
                self.nodes[rid] = GatewayNode(
                    id=rid,
                    name="火山方舟 · 推理接入点",
                    provider="ark",
                    base_url=settings.ARK_BASE_URL,
                    api_key=settings.ARK_API_KEY,
                    model=settings.LLM_MODEL_REASON,
                    priority=15,
                    weight=80,
                    tags=["summary", "reason"],
                )
            self.task_type_route.setdefault("summary", settings.LLM_MODEL_REASON)
            self.task_type_route.setdefault("reason", settings.LLM_MODEL_REASON)

        # 兼容旧版单 Key 配置
        if settings.LLM_API_KEY and settings.LLM_MODEL and "node_legacy_openai" not in self.nodes:
            self.nodes["node_legacy_openai"] = GatewayNode(
                id="node_legacy_openai",
                name="OpenAI 兼容默认",
                provider="openai_compatible",
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                model=settings.LLM_MODEL,
                priority=99,
                weight=50,
                tags=["qa", "chat"],
            )

    def choose(self, task_type: str = "qa") -> GatewayNode | None:
        task = (task_type or "qa").strip().lower()
        active = [n for n in self.nodes.values() if n.status == "active" and n.api_key and n.model]
        if not active:
            return None

        mode = (self.route_mode or "task_type").strip().lower()

        if mode in ("task_type", "task"):
            prefer = (self.task_type_route.get(task) or "").strip()
            if prefer:
                for n in active:
                    if n.model == prefer or n.id == prefer:
                        return n
                for n in active:
                    if prefer in n.tags or task in n.tags:
                        return n

        if mode == "priority":
            tagged = [n for n in active if task in n.tags or "qa" in n.tags and task == "chat"]
            if tagged:
                return sorted(tagged, key=lambda n: (n.priority, -n.weight, n.id))[0]
            return sorted(active, key=lambda n: (n.priority, -n.weight, n.id))[0]

        return sorted(active, key=lambda n: (n.priority, -n.weight, n.id))[0]

    def public_snapshot(self) -> dict[str, Any]:
        """供前端展示，不含完整密钥。"""
        nodes = []
        for n in sorted(self.nodes.values(), key=lambda x: (x.priority, x.id)):
            nodes.append(
                {
                    "id": n.id,
                    "name": n.name,
                    "provider": n.provider,
                    "base_url": n.base_url,
                    "model": n._mask_model(n.model),
                    "priority": n.priority,
                    "status": n.status,
                    "tags": n.tags,
                    "api_key_hint": n._mask_secret(n.api_key),
                }
            )
        chat_node = self.choose("qa")
        return {
            "route_mode": self.route_mode,
            "task_type_route": self.task_type_route,
            "active_chat": {
                "node_id": chat_node.id if chat_node else "",
                "name": chat_node.name if chat_node else "",
                "provider": chat_node.provider if chat_node else "",
                "model": chat_node._mask_model(chat_node.model) if chat_node else "",
                "base_url": chat_node.base_url if chat_node else "",
            },
            "nodes": nodes,
        }


def _mask_secret(value: str) -> str:
    v = (value or "").strip()
    if len(v) <= 8:
        return "***" if v else ""
    return f"{v[:4]}...{v[-4:]}"


def _mask_model(value: str) -> str:
    v = (value or "").strip()
    if len(v) <= 12:
        return v
    return f"{v[:8]}...{v[-4:]}"


GatewayNode._mask_secret = staticmethod(_mask_secret)  # type: ignore[attr-defined]
GatewayNode._mask_model = staticmethod(_mask_model)  # type: ignore[attr-defined]

_gateway: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
