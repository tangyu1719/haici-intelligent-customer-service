"""Agent 设置 API — Agent 配置 + Agent 网关

- /api/settings/gateway-nodes    网关节点 CRUD
- /api/settings/agent-routing     Agent 路由规则
- /api/settings/agents-md/{key}   Agent Prompt 编辑
- /api/settings/test-connection   连接测试
- /api/system/llm-gateway         网关快照（前端仪表盘用）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.services.agent_gateway import (
    GatewayNode,
    delete_gateway_node,
    list_agent_routing,
    list_gateway_nodes,
    load_gateway_config,
    reorder_gateway_nodes,
    save_agent_routing,
    test_connection,
    upsert_gateway_node,
)
from app.services.agent_prompt_registry import (
    AGENT_CATALOG,
    SUB_AGENT_CATALOG,
    get_agent_guide,
    load_agent_prompt,
    load_agent_routing,
    list_agent_catalog,
    save_agent_prompt,
    save_agent_routing as save_prompt_routing,
)

router = APIRouter(prefix="/settings", tags=["Agent 配置", "Agent 网关"])


# ── 请求体模型 ────────────────────────────────────────────


class GatewayNodeBody(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = ""
    provider: str = "ark"
    base_url: str = ""
    api_key: str = ""
    endpoint_id: str = ""
    model: str = ""
    priority: int = 10
    weight: int = 100
    status: str = "active"
    tags: list[str] = Field(default_factory=list)


class ReorderBody(BaseModel):
    node_ids: list[str]


class AgentRoutingSaveBody(BaseModel):
    rules: dict[str, Any] = Field(default_factory=dict)


class AgentMdSaveBody(BaseModel):
    content: str = ""


class TestConnectionBody(BaseModel):
    provider: str = "ark"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    endpoint_id: str = ""


# ── Agent 目录 ─────────────────────────────────────────────


@router.get("/agents/catalog")
def agents_catalog(_user=Depends(get_current_user)):
    """多模态 / RAG 相关 Agent 清单与元数据"""
    labels = {k: v.get("label", k) for k, v in AGENT_CATALOG.items()}
    return {
        "agents": list_agent_catalog(),
        "groups": {
            "multimodal_image": "多模态图片理解（VLM/OCR+LLM）",
            "doc_normalize": "文档标准化与摘要",
            "chat_agent": "AI 问答与运维",
        },
        "labels": labels,
    }


# ── Agent Prompt 编辑 ──────────────────────────────────────


@router.get("/agents-md/{agent_key}")
def get_agent_md(agent_key: str, _user=Depends(get_current_user)):
    content = load_agent_prompt(agent_key)
    meta = AGENT_CATALOG.get(agent_key) or SUB_AGENT_CATALOG.get(agent_key) or {}
    return {
        "agent_key": agent_key,
        "content": content,
        "label": meta.get("label", agent_key),
        "variables": meta.get("variables", []),
        "hint": meta.get("hint", ""),
        "guide": get_agent_guide(agent_key),
        "overview_only": bool(meta.get("overview_only")),
        "is_sub_agent": agent_key in SUB_AGENT_CATALOG,
        "parent_key": meta.get("parent_key"),
    }


@router.post("/agents-md/{agent_key}")
def post_agent_md(agent_key: str, body: AgentMdSaveBody, _user=Depends(get_current_user)):
    save_agent_prompt(agent_key, body.content or "")
    return {"ok": True, "agent_key": agent_key, "length": len(body.content or "")}


# ── Agent 路由规则 ─────────────────────────────────────────


@router.get("/agent-routing")
def get_agent_routing(_user=Depends(get_current_user)):
    """获取 Agent 路由规则（从 agent_gateway_config.json）"""
    return {"rules": list_agent_routing()}


@router.post("/agent-routing/save")
def post_agent_routing(body: AgentRoutingSaveBody, _user=Depends(get_current_user)):
    save_agent_routing(body.rules or {})
    save_prompt_routing(body.rules or {})
    return {"ok": True, "rules": list_agent_routing()}


# ── 网关节点 CRUD ──────────────────────────────────────────


@router.get("/gateway-nodes")
def get_gateway_nodes(_user=Depends(get_current_user)):
    """获取所有网关节点列表（密钥脱敏）"""
    nodes = list_gateway_nodes()
    return {"nodes": [n.to_public_dict() for n in nodes]}


@router.post("/gateway-nodes/upsert")
def post_gateway_node(body: GatewayNodeBody, _user=Depends(get_current_user)):
    """创建或更新网关节点"""
    node = upsert_gateway_node(body.model_dump())
    return {"ok": True, "node": node.to_public_dict()}


@router.delete("/gateway-nodes/{node_id}")
def delete_gateway_node_ep(node_id: str, _user=Depends(get_current_user)):
    """删除网关节点"""
    ok = delete_gateway_node(node_id)
    if not ok:
        raise HTTPException(status_code=404, detail="节点不存在")
    return {"ok": True}


@router.post("/gateway-nodes/reorder")
def reorder_gateway_nodes_ep(body: ReorderBody, _user=Depends(get_current_user)):
    """重新排序网关节点（priority 按顺序赋值）"""
    nodes = reorder_gateway_nodes(body.node_ids)
    return {"ok": True, "nodes": [n.to_public_dict() for n in nodes]}


# ── 连接测试 ───────────────────────────────────────────────


@router.post("/test-connection")
def test_llm_connection(body: TestConnectionBody, _user=Depends(get_current_user)):
    """测试 LLM 连接"""
    result = test_connection(
        provider=body.provider,
        api_key=body.api_key,
        base_url=body.base_url,
        model=body.model,
        endpoint_id=body.endpoint_id,
    )
    return {"ok": True, "result": result}


# ── LLM 网关快照（前端状态栏用） ────────────────────────────


@router.get("/gateway-snapshot")
def gateway_snapshot(_user=Depends(get_current_user)):
    """获取 LLM 网关运行快照（与运行时 llm_gateway 一致，密钥脱敏）"""
    from app.services.llm_gateway import get_llm_gateway

    return get_llm_gateway().public_snapshot()


# ── 熔断器与节点健康 ─────────────────────────────────────────


@router.get("/gateway-nodes/health")
def get_nodes_health(_user=Depends(get_current_user)):
    """获取所有节点的健康状态（熔断器视角）"""
    from app.services.gateway_circuit_breaker import breaker

    return {"ok": True, "nodes": breaker.list_all()}


@router.post("/gateway-nodes/{node_id}/health/recover")
def recover_node(node_id: str, _user=Depends(get_current_user)):
    """手动强制恢复节点"""
    from app.services.gateway_circuit_breaker import breaker

    health = breaker.get(node_id)
    if not health:
        return {"ok": False, "detail": "节点不存在"}
    health.force_recover()
    return {"ok": True, "node": health.to_dict()}


@router.post("/gateway-nodes/{node_id}/health/degrade")
def degrade_node(node_id: str, reason: str = "", _user=Depends(get_current_user)):
    """手动强制降级节点"""
    from app.services.gateway_circuit_breaker import breaker

    health = breaker.get(node_id)
    if not health:
        return {"ok": False, "detail": "节点不存在"}
    health.force_degrade(reason)
    return {"ok": True, "node": health.to_dict()}


# ── 语义路由测试 ─────────────────────────────────────────────


@router.get("/semantic-route/test")
def test_semantic_route(question: str, _user=Depends(get_current_user)):
    """测试语义路由：输入问题，返回复杂度评分和目标任务类型"""
    from app.services.gateway_semantic_router import estimate_complexity, route_by_complexity

    return {
        "ok": True,
        "question": question[:200],
        "complexity_score": estimate_complexity(question),
        "target_task_type": route_by_complexity(question),
    }


# ── Prompt 段式指令清单 ──────────────────────────────────────

@router.get("/prompt-segments")
def get_prompt_segments(_user=Depends(get_current_user)):
    """返回所有段式指令变量清单（供前端配置页展示与管理）。

    每个段包含：key（变量名）、text（指令原文）、desc（是什么）、purpose（起到什么作用）。
    """
    from app.services.prompt_segments import list_all_segments
    return {"ok": True, "segments": list_all_segments()}


# ── 缓存统计 ─────────────────────────────────────────────────


@router.get("/cache/stats")
def get_cache_stats(_user=Depends(get_current_user)):
    """获取缓存统计信息"""
    from app.services.gateway_cache import cache

    return {"ok": True, "stats": cache.stats()}


@router.post("/cache/invalidate")
def invalidate_cache(_user=Depends(get_current_user)):
    """清除所有缓存"""
    from app.services.gateway_cache import cache

    count = cache.invalidate()
    return {"ok": True, "cleared": count}


# ── 管道设置（意图识别模型选择） ──

@router.get("/pipeline-config")
def get_pipeline_config(_user=Depends(get_current_user)):
    """获取管道配置：意图识别使用的模型"""
    import os
    return {
        "ok": True,
        "ollama_available": os.path.exists(os.getenv("OLLAMA_BASE_URL", "")),
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        "ollama_model": os.getenv("OLLAMA_MODEL", "qwen2:0.5b"),
        "models": [
            {"key": "local_05b", "label": "本地 Qwen2 0.5B (最快, ~400MB)", "env_model": "qwen2:0.5b"},
            {"key": "local_15b", "label": "本地 Qwen2 1.5B (均衡, ~1GB)", "env_model": "qwen2:1.5b"},
            {"key": "api_gateway", "label": "API 网关模型 (ARK/豆包)", "env_model": ""},
        ],
    }


class PipelineConfigBody(BaseModel):
    intent_model: str = "local_05b"  # local_05b | local_15b | api_gateway


@router.put("/pipeline-config")
def update_pipeline_config(body: PipelineConfigBody, _user=Depends(get_current_user)):
    """更新管道意图识别模型选择"""
    model_map = {
        "local_05b": "qwen2:0.5b",
        "local_15b": "qwen2:1.5b",
        "api_gateway": "",
    }
    model = model_map.get(body.intent_model, "qwen2:0.5b")
    # 运行时更新环境变量
    import os
    if model:
        os.environ["OLLAMA_MODEL"] = model
    else:
        os.environ.pop("OLLAMA_MODEL", None)
    return {"ok": True, "intent_model": body.intent_model, "ollama_model": model}
