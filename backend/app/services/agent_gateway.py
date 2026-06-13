"""Agent 网关服务 — LLM 网关节点管理 + 路由 + 连接测试。

从 web_rebuild_v2 迁移，支持:
- 多 LLM 提供商网关节点 CRUD
- 三种路由模式: system_compete / custom_order / strict_priority
- 按任务类型路由 (task_type: qa / summary / reason)
- API 连接测试
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GATEWAY_CONFIG = PROJECT_ROOT / "src" / "agent" / "config.json"
LOCAL_GATEWAY_CONFIG = PROJECT_ROOT / "backend" / "data" / "agent_gateway_config.json"


@dataclass
class GatewayNode:
    """网关节点"""
    id: str
    name: str = ""
    provider: str = "ark"
    base_url: str = ""
    api_key: str = ""
    endpoint_id: str = ""
    model: str = ""
    priority: int = 10
    weight: int = 100
    status: str = "active"  # active / disabled / degraded
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "endpoint_id": self.endpoint_id,
            "model": self.model,
            "priority": self.priority,
            "weight": self.weight,
            "status": self.status,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GatewayNode":
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            provider=str(d.get("provider", "ark")),
            base_url=str(d.get("base_url", "")),
            api_key=str(d.get("api_key", "")),
            endpoint_id=str(d.get("endpoint_id", "")),
            model=str(d.get("model", "")),
            priority=int(d.get("priority", 10)),
            weight=int(d.get("weight", 100)),
            status=str(d.get("status", "active")),
            tags=list(d.get("tags") or []),
        )


@dataclass
class AgentRouteRule:
    """Agent 路由规则"""
    agent_id: str
    mode: str = "system_compete"  # system_compete / custom_order / strict_priority
    nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "nodes": self.nodes,
        }

    @classmethod
    def from_dict(cls, agent_id: str, d: dict[str, Any]) -> "AgentRouteRule":
        return cls(
            agent_id=agent_id,
            mode=str(d.get("mode", "system_compete")),
            nodes=list(d.get("nodes") or []),
        )


@dataclass
class GatewayConfig:
    """完整网关配置"""
    route_mode: str = "task_type"  # task_type / weighted / priority
    task_type_route: dict[str, str] = field(default_factory=dict)
    nodes: list[GatewayNode] = field(default_factory=list)
    agent_rules: dict[str, AgentRouteRule] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gateway_route_mode": self.route_mode,
            "gateway_task_type_route": self.task_type_route,
            "api_gateway_nodes": [n.to_dict() for n in self.nodes],
            "agent_route_rules": {
                k: v.to_dict() for k, v in self.agent_rules.items()
            },
        }


def _load_config_file() -> dict[str, Any]:
    """加载网关配置文件（本地优先，其次上级项目）"""
    for path in (LOCAL_GATEWAY_CONFIG, DEFAULT_GATEWAY_CONFIG):
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def _save_config_file(data: dict[str, Any]) -> None:
    LOCAL_GATEWAY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_GATEWAY_CONFIG.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_gateway_config() -> GatewayConfig:
    """加载完整网关配置"""
    raw = _load_config_file()
    nodes = [GatewayNode.from_dict(n) for n in (raw.get("api_gateway_nodes") or [])]
    rules = raw.get("agent_route_rules") or {}
    agent_rules = {
        k: AgentRouteRule.from_dict(k, v) for k, v in rules.items()
    }
    return GatewayConfig(
        route_mode=raw.get("gateway_route_mode", "task_type"),
        task_type_route=raw.get("gateway_task_type_route") or {},
        nodes=nodes,
        agent_rules=agent_rules,
    )


def save_gateway_config(cfg: GatewayConfig) -> None:
    _save_config_file(cfg.to_dict())


def list_gateway_nodes() -> list[GatewayNode]:
    cfg = load_gateway_config()
    return sorted(cfg.nodes, key=lambda n: n.priority)


def upsert_gateway_node(node_dict: dict[str, Any]) -> GatewayNode:
    cfg = load_gateway_config()
    new_node = GatewayNode.from_dict(node_dict)
    found = False
    for i, n in enumerate(cfg.nodes):
        if n.id == new_node.id:
            cfg.nodes[i] = new_node
            found = True
            break
    if not found:
        cfg.nodes.append(new_node)
    save_gateway_config(cfg)
    return new_node


def delete_gateway_node(node_id: str) -> bool:
    cfg = load_gateway_config()
    before = len(cfg.nodes)
    cfg.nodes = [n for n in cfg.nodes if n.id != node_id]
    if len(cfg.nodes) < before:
        save_gateway_config(cfg)
        return True
    return False


def reorder_gateway_nodes(node_ids: list[str]) -> list[GatewayNode]:
    cfg = load_gateway_config()
    id_map = {n.id: n for n in cfg.nodes}
    reordered: list[GatewayNode] = []
    for i, nid in enumerate(node_ids):
        if nid in id_map:
            node = id_map[nid]
            node.priority = i + 1
            reordered.append(node)
    # 添加未在列表中的节点
    for n in cfg.nodes:
        if n.id not in node_ids:
            reordered.append(n)
    cfg.nodes = reordered
    save_gateway_config(cfg)
    return reordered


def list_agent_routing() -> dict[str, dict[str, Any]]:
    cfg = load_gateway_config()
    return {k: v.to_dict() for k, v in cfg.agent_rules.items()}


def save_agent_routing(rules: dict[str, dict[str, Any]]) -> None:
    cfg = load_gateway_config()
    cfg.agent_rules = {
        k: AgentRouteRule.from_dict(k, v) for k, v in rules.items()
    }
    save_gateway_config(cfg)


def choose_node(
    task_type: str = "qa",
    agent_id: str | None = None,
) -> GatewayNode | None:
    """根据任务类型和 Agent ID 选择最优网关节点。

    路由逻辑:
    1. 如果有 agent_id 且配置了 agent_route_rules → 按 agent 规则
    2. 如果有 task_type_route → 按任务类型匹配
    3. 否则选优先级最高的节点
    """
    cfg = load_gateway_config()

    active_nodes = [n for n in cfg.nodes if n.status == "active"]
    if not active_nodes:
        return None

    # Agent 级别路由
    if agent_id and agent_id in cfg.agent_rules:
        rule = cfg.agent_rules[agent_id]
        if rule.mode == "strict_priority" and rule.nodes:
            for nid in rule.nodes:
                node = next((n for n in active_nodes if n.id == nid), None)
                if node:
                    return node
        elif rule.mode == "custom_order" and rule.nodes:
            return next((n for n in active_nodes if n.id == rule.nodes[0]), active_nodes[0])

    # 任务类型路由
    if cfg.task_type_route:
        node_id = cfg.task_type_route.get(task_type)
        if node_id:
            node = next((n for n in active_nodes if n.id == node_id or n.name == node_id), None)
            if node:
                return node

    # 默认：最高优先级
    return sorted(active_nodes, key=lambda n: n.priority)[0]


def test_connection(
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    """测试 LLM 连接"""
    from app.adapters.registry import get_adapter

    try:
        adapter = get_adapter(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            max_tokens=10,
        )
        result = adapter.health_check()
        return result
    except Exception as exc:
        return {
            "provider": provider,
            "model": model,
            "ok": False,
            "error": str(exc)[:300],
        }
