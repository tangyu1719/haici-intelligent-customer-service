# SPEC — 网关增强（智能路由 + 安全合规 + 缓存 + 可观测性 + 错误码体系）

> 版本: v1.0 | 状态: 实施中 | 基于 PRD 加分项扩展

---

## 一、智能路由与负载均衡

### 1.1 语义路由

**目标**: 简单问题走小模型省成本，复杂问题走大模型保质量。

**实现方案**:
```
用户问题 → 复杂度判定(快速LLM调用) → 
  ├─ 复杂度≤3: 路由到 qa 标签节点(小模型)
  ├─ 复杂度4-6: 路由到 summary 标签节点(中模型)  
  └─ 复杂度≥7: 路由到 reason 标签节点(大模型)
```

**复杂度判定规则**:
| 维度 | 低(1-3) | 中(4-6) | 高(7-10) |
|------|---------|---------|----------|
| 问题长度 | <20字 | 20-100字 | >100字 |
| 是否多问 | 单问 | 2问 | 3问+ |
| 是否需要推理 | 否(FAQ/闲聊) | 需要检索 | 需要多步推理 |
| 领域专业度 | 通用 | 业务相关 | 跨系统/多领域 |

**前端暴露**:
- Agent网关页面：每个节点显示复杂度范围标签
- 路由测试工具：输入问题 → 显示判定结果和目标节点

### 1.2 加权轮询 + 最少连接数

**数据结构**:
```json
{
  "node_id": "node_primary",
  "weight": 100,
  "current_connections": 0,
  "max_connections": 10,
  "healthy": true
}
```

**算法**:
1. 过滤 healthy=true 的节点
2. 按 current_connections/max_connections 升序（最少连接优先）
3. 同连接数按 weight 降序（加权轮询）
4. 调用前 `current_connections++`，调用后 `current_connections--`

**前端暴露**:
- 网关面板显示每个节点当前连接数/最大连接数
- 实时刷新

### 1.3 故障自动转移 + 熔断

**状态机**:
```
active → (连续失败N次) → degraded → (冷却时间T后) → half_open →
  ├─ 测试请求成功 → active
  └─ 测试请求失败 → degraded(重置冷却)
```

**配置项**（每个节点可独立设置）:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| fail_threshold | 3 | 连续失败N次触发降级 |
| cooldown_seconds | 60 | 冷却时间 |
| half_open_probe | 1 | 半开状态探测请求数 |
| max_retries | 2 | 单次请求最大重试次数 |

**前端暴露**:
- 网关面板节点列表：实时状态指示灯(绿/黄/红)
- 点击节点查看熔断历史（失败原因、时间线）
- 手动强制恢复/降级按钮

---

## 二、安全与合规

### 2.1 API Key 轮换管理

**方案**: 
- 每个节点支持配置主Key + 备用Key
- 支持手动触发轮换
- 记录轮换历史

**API**:
```
POST /api/v1/settings/gateway-nodes/{id}/rotate-key
  → 将当前 api_key 写入 api_key_backup，提示输入新Key
  
GET  /api/v1/settings/gateway-nodes/{id}/key-history
  → 返回轮换历史列表
```

### 2.2 敏感词过滤 + PII 脱敏

**请求阶段**（发往LLM前）:
- 手机号: `138****1234`
- 身份证: `310***********1234`
- 邮箱: `abc***@example.com`
- 银行卡: `6222****1234`

**响应阶段**（LLM返回后）:
- 可选开关：是否对响应也做脱敏
- 敏感词检测: 政治/色情/暴力 → 标记 + 拦截

**前端暴露**:
- GW面板增加"安全合规"Tab
- PII脱敏规则开关（可配置脱敏类型）
- 敏感词词库管理（增删）

---

## 三、缓存层

### 3.1 语义缓存

**方案**: 
- 问题 Embedding → 向量相似度 > 0.92 → 命中缓存
- 缓存值: {question, answer, citations, model, timestamp, ttl}

**存储**: ChromaDB 新建 `cache` collection

**流程**:
```
用户问题 → Embedding → 查缓存collection →
  ├─ 命中(similarity>0.92) → 直接返回缓存答案
  └─ 未命中 → 正常RAG流程 → 结果写入缓存
```

### 3.2 TTL去重

- 完全相同问题(字符串hash) → TTL内(默认5分钟) → 返回缓存
- 防止用户短时间内重复提问消耗Token

---

## 四、可观测性（集成到 EVAL 评测）

### 4.1 实时指标面板

**新增指标**:
| 指标 | 说明 | 计算方式 |
|------|------|---------|
| QPS | 每秒请求数 | 滑动窗口(1min) |
| 延迟P50/P95/P99 | 响应时间分布 | 近100次请求 |
| 错误率 | 失败/总请求 | 滑动窗口(5min) |
| 模型分布 | 各模型调用占比 | 饼图 |
| Token用量 | 按模型/用户 | 柱状图 |

**API**: 扩展现有 `GET /api/v1/admin/eval/overview`

### 4.2 Token用量统计

**数据存储**: 扩展 `sys_log_api_call` 表
```sql
ALTER TABLE sys_log_api_call ADD COLUMN token_in INT DEFAULT 0;
ALTER TABLE sys_log_api_call ADD COLUMN token_out INT DEFAULT 0;
ALTER TABLE sys_log_api_call ADD COLUMN model VARCHAR(64);
ALTER TABLE sys_log_api_call ADD COLUMN cost_estimate DECIMAL(10,6);
```

### 4.3 全链路Trace

每个请求生成 `trace_id`，所有关联日志打上相同 trace_id。
现有 `set_agent_trace` 已有基础，增强为贯穿整个请求生命周期。

---

## 五、错误码体系（核心）

### 5.1 LLM 失败模式分类

| 错误码 | 类别 | 典型表现 | ARK表现 | Claude表现 | Qwen表现 | OpenAI表现 |
|--------|------|---------|---------|-----------|---------|-----------|
| `LLM_TIMEOUT` | 连接超时 | 请求超时无响应 | `ReadTimeout` | `RequestTimeout` | `GatewayTimeout` | `timeout` |
| `LLM_QUOTA` | 额度耗尽 | API Key无可用额度 | `AccountBalanceInsufficient` | `overloaded_error`/529 | `InvalidApiKey` | `insufficient_quota` |
| `LLM_RATE_LIMIT` | 限流 | 请求频率过高 | `Throttling.RateLimit`/`TooManyRequests` | `rate_limit_error`/429 | `Throttling` | `rate_limit_exceeded` |
| `LLM_MALFORMED` | 响应乱码 | JSON解析失败/内容异常 | HTTP200但JSON非法 | 同左 | 同左 | 同左 |
| `LLM_INVALID_REQUEST` | 入参错误 | 模型名错误/参数非法 | `InvalidParameter`/400 | `invalid_request_error`/400 | `InvalidParameter` | `invalid_request_error`/400 |
| `LLM_CONTENT_FILTER` | 内容审查 | 触发安全审查 | `ContentFilter` | `content_policy` | `OutputExceeded` | `content_filter` |
| `LLM_QUALITY_LOW` | 质量偏差 | 回答与预期相差大 | 回答过短/无关 | 同左 | 同左 | 同左 |
| `LLM_CONTEXT_OVERFLOW` | 上下文溢出 | Token超过模型上限 | `ContextLengthExceeded`/400 | 400 context_window | `Maximum token` | `context_length_exceeded` |
| `LLM_UNKNOWN` | 未知错误 | 其他未分类 | — | — | — | — |

### 5.2 错误码标准化函数

```python
def normalize_error(provider: str, response_or_error: Any) -> tuple[str, str]:
    """
    将不同LLM的原生错误统一转换为标准错误码。
    
    返回: (error_code, human_readable_message)
    """
    # 1. 先匹配 HTTP 状态码
    # 2. 再匹配响应体中的错误消息
    # 3. 回退到 LLM_UNKNOWN
```

### 5.3 错误码→重试/降级策略

| 错误码 | 重试 | 降级策略 |
|--------|------|---------|
| `LLM_TIMEOUT` | ✅ 最多2次，指数退避(1s→3s) | 切换到备用节点 |
| `LLM_QUOTA` | ❌ 不重试 | 立即切换备用节点+标记节点degraded |
| `LLM_RATE_LIMIT` | ✅ 最多1次，退避5s | 切换到备用节点+标记节点degraded |
| `LLM_MALFORMED` | ✅ 最多1次 | 重试后仍失败→切换节点 |
| `LLM_INVALID_REQUEST` | ❌ 不重试 | 返回明确错误给用户 |
| `LLM_CONTENT_FILTER` | ❌ 不重试 | 返回兜底话术 |
| `LLM_QUALITY_LOW` | ❌ 不重试 | 标记该问题+人工审核队列 |
| `LLM_CONTEXT_OVERFLOW` | ❌ 不重试 | 自动截断上下文后重试1次 |
| `LLM_UNKNOWN` | ✅ 最多1次 | 切换备用节点 |

### 5.4 错误码捕获实现（ARK优先）

```python
class GatewayErrorHandler:
    def handle_response(self, provider: str, response) -> tuple[bool, str, str]:
        """
        返回: (is_error, error_code, message)
        """
        # ARK: 检查 status_code + response body
        # 示例: {"error":{"code":"AccountBalanceInsufficient","message":"..."}}
```

---

## 六、实现计划

### Phase 1: 错误码体系 + 熔断 (1h)
- `backend/app/services/gateway_error_handler.py` — 错误码标准化
- `backend/app/services/gateway_circuit_breaker.py` — 熔断器
- 更新 `agent_gateway.py` — 集成错误处理和熔断
- 测试: ARK节点模拟各种失败场景

### Phase 2: 智能路由 (1h)
- `backend/app/services/gateway_semantic_router.py` — 语义路由
- 更新 GatewayPanel 前端 — 复杂度标签
- 更新 `llm_gateway.py` — 集成路由

### Phase 3: 安全合规 + 缓存 (1h)
- `backend/app/services/gateway_security.py` — PII脱敏 + 敏感词
- `backend/app/services/gateway_cache.py` — 语义缓存
- 前端安全Tab

### Phase 4: 可观测性 (0.5h)
- 扩展 `admin_eval.py` — 新增指标
- 扩展 `eval_service.py` — Token统计
- 前端 EvalDashboard 更新

### 文件清单

| 文件 | Phase | 说明 |
|------|-------|------|
| `services/gateway_error_handler.py` | 1 | 错误码标准化 |
| `services/gateway_circuit_breaker.py` | 1 | 熔断器 |
| `services/gateway_semantic_router.py` | 2 | 语义路由 |
| `services/gateway_security.py` | 3 | 安全合规 |
| `services/gateway_cache.py` | 3 | 缓存层 |
| `routers/admin_eval.py` (改) | 4 | 可观测性API |
| `services/eval_service.py` (改) | 4 | 指标计算 |
| `services/agent_gateway.py` (改) | 1-2 | 集成 |
| `services/llm_gateway.py` (改) | 1-2 | 集成 |
| `components/GatewayPanel.vue` (改) | 1-3 | 前端面板 |
| `components/EvalDashboard.vue` (改) | 4 | 可观测面板 |
