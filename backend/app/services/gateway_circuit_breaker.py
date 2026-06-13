"""网关熔断器 (SPEC §1.3)

状态机: active → degraded → half_open → active/degraded
每个节点独立维护熔断状态。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .gateway_error_handler import (
    ErrorCode,
    ErrorStrategy,
    get_strategy,
    normalize_error,
)

logger = logging.getLogger(__name__)


class NodeState(str, Enum):
    ACTIVE = "active"        # 正常
    DEGRADED = "degraded"    # 熔断中
    HALF_OPEN = "half_open"  # 半开探测


@dataclass
class NodeHealth:
    """节点健康状态"""
    node_id: str
    state: NodeState = NodeState.ACTIVE
    fail_count: int = 0                # 连续失败次数
    fail_threshold: int = 3            # 触发熔断的阈值
    cooldown_seconds: int = 60         # 冷却时间（秒）
    half_open_probe: int = 1           # 半开探测请求数
    max_retries: int = 2               # 单次请求最大重试
    last_fail_time: float = 0.0        # 最后一次失败时间戳
    last_fail_reason: str = ""         # 最后失败原因
    total_requests: int = 0            # 总请求数
    total_failures: int = 0            # 总失败数
    degrade_count: int = 0             # 累计熔断次数
    history: list[dict] = field(default_factory=list)  # 最近10条事件

    def record_success(self) -> None:
        self.total_requests += 1
        self.fail_count = 0
        if self.state == NodeState.HALF_OPEN:
            self.state = NodeState.ACTIVE
            self._add_event("半开探测成功，恢复为active")

    def record_failure(self, error_code, detail: str = "") -> None:
        code_val = error_code.value if isinstance(error_code, ErrorCode) else str(error_code)
        self.total_requests += 1
        self.total_failures += 1
        self.fail_count += 1
        self.last_fail_time = time.time()
        self.last_fail_reason = f"{code_val}: {detail[:100]}"
        self._add_event(f"失败 [{code_val}]: {detail[:100]}")

        if self.state == NodeState.ACTIVE and self.fail_count >= self.fail_threshold:
            self.state = NodeState.DEGRADED
            self.degrade_count += 1
            self._add_event(f"触发熔断，连续失败{self.fail_count}次")

        elif self.state == NodeState.HALF_OPEN:
            self.state = NodeState.DEGRADED
            self._add_event("半开探测失败，重回degraded")

    def try_half_open(self) -> bool:
        """检查是否可以进入半开状态"""
        if self.state != NodeState.DEGRADED:
            return False
        if time.time() - self.last_fail_time >= self.cooldown_seconds:
            self.state = NodeState.HALF_OPEN
            self._add_event("冷却期满，进入half_open探测")
            return True
        return False

    def force_recover(self) -> None:
        """手动强制恢复"""
        self.state = NodeState.ACTIVE
        self.fail_count = 0
        self._add_event("手动强制恢复")

    def force_degrade(self, reason: str = "") -> None:
        """手动强制降级"""
        self.state = NodeState.DEGRADED
        self._add_event(f"手动降级: {reason}")

    def is_available(self) -> bool:
        """节点是否可用于接收新请求"""
        return self.state in (NodeState.ACTIVE, NodeState.HALF_OPEN)

    def _add_event(self, msg: str) -> None:
        self.history.insert(0, {
            "time": time.strftime("%H:%M:%S"),
            "state": self.state.value,
            "message": msg,
        })
        if len(self.history) > 10:
            self.history = self.history[:10]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "state": self.state.value,
            "fail_count": self.fail_count,
            "fail_threshold": self.fail_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "is_available": self.is_available(),
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "degrade_count": self.degrade_count,
            "failure_rate": round(self.total_failures / max(self.total_requests, 1), 4),
            "last_fail_reason": self.last_fail_reason,
            "last_fail_time": time.strftime("%H:%M:%S", time.localtime(self.last_fail_time)) if self.last_fail_time else "",
            "history": self.history[:5],
        }


class CircuitBreaker:
    """熔断器管理器，维护所有节点的健康状态"""

    def __init__(self):
        self._nodes: dict[str, NodeHealth] = {}
        self._lock = threading.Lock()

    def get_or_create(self, node_id: str, **kwargs: Any) -> NodeHealth:
        with self._lock:
            if node_id not in self._nodes:
                self._nodes[node_id] = NodeHealth(node_id=node_id, **kwargs)
            return self._nodes[node_id]

    def get(self, node_id: str) -> NodeHealth | None:
        return self._nodes.get(node_id)

    def remove(self, node_id: str) -> None:
        with self._lock:
            self._nodes.pop(node_id, None)

    def get_available_nodes(self, node_ids: list[str]) -> list[str]:
        """返回可用的节点ID列表"""
        return [nid for nid in node_ids if self.get(nid) is None or self.get(nid).is_available()]

    def list_all(self) -> list[dict[str, Any]]:
        return [n.to_dict() for n in self._nodes.values()]

    def handle_response(
        self,
        node_id: str,
        provider: str,
        status_code: int,
        response_body: str,
        exception_msg: str = "",
    ) -> dict[str, Any]:
        """处理一次LLM调用的响应，更新节点健康状态。

        返回: {"is_error": bool, "error_code": str, "strategy": ErrorStrategy, "node_state": str}
        """
        health = self.get_or_create(node_id)

        if status_code < 400:
            health.record_success()
            return {
                "is_error": False,
                "error_code": "",
                "strategy": None,
                "node_state": health.state.value,
            }

        error_code, message = normalize_error(provider, status_code, response_body, exception_msg)
        health.record_failure(error_code, detail=message)
        strategy = get_strategy(error_code)

        logger.warning(
            "[网关-熔断|circuit_breaker|handle_response] node=%s; error=%s; state=%s; retry=%s",
            node_id, error_code.value, health.state.value, strategy.retry,
        )

        return {
            "is_error": True,
            "error_code": error_code.value,
            "strategy": strategy,
            "node_state": health.state.value,
            "node_available": health.is_available(),
            "message": message,
        }


# 全局单例
breaker = CircuitBreaker()
