# SPEC · AI 问答 Agent（RAG 核心模块）

> **模块**：AI 问答 Agent  
> **版本**：v0.2  
> **日期**：2026-06-12  
> **状态**：实施中  
> **产品需求文档**：`HaiCi笔试_AI 智能客服系统_PRD.md`（只读）  
> **全链路 SPEC（RAG + 反馈 + 追问 + 意图纠偏）**：`SPEC-RAG问答全链路.md`

---

## 0. 文档元数据、摘要与定位

### 一句话摘要

构建**无 LangGraph** 的轻量固定节点 Pipeline，完成 RAG 问答链路，并含意图识别、Query 改写、关键词提取、内部术语映射与向量检索；意图分解/增强本期不做。

### 分类路径

`产品研发` → `SPEC·PRD` → `HaiCiAgent/AI问答` → `agent_pipeline`

| 层级 | 值 |
|------|-----|
| L1 领域 | 产品研发 |
| L2 类型 | SPEC·实施规格 |
| L3 模块 | HaiCiAgent / AI 问答 Agent |
| L4 | `backend/app/services/agent_pipeline.py` |

### 版本与修订

| 字段 | 值 |
|------|-----|
| doc_version | v0.2 |
| status | 实施中 |
| updated_at | 2026-06-12T15:00:00+08:00 |
| 编排框架 | **禁止 LangGraph**；固定节点串行函数 |

---

## 目录

- [1. PRD 必达需求提取](#1-prd-必达需求提取)
- [2. PRD 加分项映射](#2-prd-加分项映射)
- [3. 固定节点 Pipeline（本期）](#3-固定节点-pipeline本期)
- [4. 本期不做](#4-本期不做)
- [5. 技术选型](#5-技术选型)
- [6. SSE 事件](#6-sse-事件)
- [7. 验收清单](#7-验收清单)
- [8. 对话页 UX 与健康检查（v0.2）](#8-对话页-ux-与健康检查v02)
- [待二次审阅（由 Owner 回填）](#待二次审阅由-owner-回填)

---

## 1. PRD 必达需求提取

| PRD 条目 | 要求 | 实现 |
|----------|------|------|
| 知识库上传 | txt/md/pdf 解析向量化 | `knowledge_processor` + Chroma |
| RAG 流程 | 检索 → Prompt → LLM → 流式 | `chat.py` + `rag.py` |
| 引用来源 | 文档名 + 片段摘要 | SSE `citations` |
| 多轮对话 | 最近 N 轮上下文 | `CHAT_HISTORY_TURNS` |
| 500 字限制 | 前后端校验 | `MAX_QUESTION_LENGTH` |
| 空检索兜底 | 标准话术，不编造 | `FALLBACK_NO_CONTEXT` |
| 每日 100 次 | 可配置限额 | `rate_limit.py` |
| SSE 流式 | 逐字输出 | `event: token` |
| 意图标注 | 会话记录标注分类 | `intent_label` 字段 + SSE meta |
| 前后端分离 | 前端不直连 LLM | 网关 `llm_gateway` |

---

## 2. PRD 加分项映射

| 加分项 | 策略 | 状态 |
|--------|------|------|
| 流式体验 | SSE token 直出 | ✅ |
| 意图识别 | 规则 + LLM JSON 预处理 | ✅ |
| Prompt 抗幻觉 | 仅依据片段 + 空检索兜底 | ✅ |
| 知识库增量 | 按文档 ID 分 tenant 写入 Chroma | ✅ 已有 |
| 大规模上下文防稀释 | Top-K + 片段截断 + 多路合并检索 + System 约束 | ✅ 初版 |
| 追问引导 | 回答后 LLM 生成 2～3 条 | ✅ `follow_up.py` |
| 管理后台 | 运维日志 + 会话历史 | ✅ 登录模块 |
| 多知识库路由 | 按 user_id tenant | 🔲 后续 |
| Agent 任务拆解 | PRD 终极挑战 | 🔲 文档/后续 |

---

## 3. 固定节点 Pipeline（本期）

**不用 LangGraph**，`run_agent_pipeline()` 串行执行：

```text
用户问题
  → [1] 意图识别     intent.py 规则 + LLM JSON（product/after_sale/chitchat/complaint）
  → [2] Query 改写   rewritten_query（指代消解/检索友好表述）
  → [3] 关键词提取   query_keywords
  → [4] 内部术语映射 retrieval_terms（term_dictionary.py）
  → [5] RAG 检索     retrieve_merged(rag_query)
  → [6] Prompt 拼接  build_prompt_messages
  → [7] LLM 流式生成 stream_chat
  → [8] 追问建议     generate_follow_ups（可选）
```

节点，**不含**：意图分解（decompose）、意图增强（enhance）。

实现文件：

- `app/services/agent_pipeline.py`
- `app/services/term_dictionary.py`
- `app/services/follow_up.py`
- `app/routers/chat.py`

---

## 4. 本期不做

- LangGraph / Plan-Execute 编排
- 意图分解、意图增强
- 多知识库自动路由（预留 tenant）
- Agent 跨微服务任务拆解（PRD 终极挑战，仅 SPEC 占位）

---

## 5. 技术选型

| 组件 | 选型 |
|------|------|
| LLM | 火山方舟 ARK + 通义（`llm_gateway` 双接入点） |
| Embedding | BGE-large-zh 本地快照 |
| 向量库 | Chroma |
| 框架 | 直调 SDK + 自研 Pipeline（无 LangChain Chain 编排） |

---

## 6. SSE 事件

| event | 说明 |
|-------|------|
| `meta` | intent、pipeline 节点输出、LLM 接入点 |
| `citations` | 引用来源 |
| `token` | 流式正文 |
| `follow_ups` | 追问建议（加分项） |
| `done` | 消息 ID |

---

## 7. 验收清单

- [x] 固定 5 节点 Pipeline（意图/改写/关键词/术语/RAG）
- [x] 无 LangGraph
- [x] SSE 流式 + 引用 + 意图标注
- [x] 空检索兜底
- [x] 追问建议 SSE
- [ ] 人工 RAG 质量回归（需知识库样例文档）
- [ ] 多知识库路由
- [x] 对话页健康检查条
- [x] 对话页左侧会话栏（无任务结构）
- [x] 会话持久化：context_id + meta_json + 编辑/归档（见 `SPEC-会话持久化.md`）
- [x] 加载态单一 wave-loader（无竖线空泡）
- [x] SSE DetachedInstanceError 修复

---

## 8. 对话页 UX 与健康检查（v0.2）

> 实施说明见 `docs/PLAN-对话页健康与会话栏.md`。

### 8.1 对话页布局

| 区域 | 行为 |
|------|------|
| 顶栏左 | 当前会话上下文名称（首问截断标题或「会话 #id」），**不**显示「智能客服会话」 |
| 顶栏右 | 健康检查摘要 + 展开明细 + 刷新 |
| 左侧栏 | 竖向会话列表、`+ 新对话`，**不含** 外部任务历史/子任务链 |
| 主区 | 消息流 + 单一加载动画 |

### 8.2 平台健康检查 API

- 路径：`GET /api/v1/system/platform/health`
- 探测项：`mysql`、`chroma`、`embedding`、`llm_gateway`
- 响应：`{ ready, all_ok, summary:{ok,warn,error}, items:[{id,label,status,latency_ms,error,detail}] }`
- 与 `/api/v1/system/platform/health` 字段一致，供对话页健康条消费。

### 8.3 流式加载规范

- 发送后 **不** 预插入空 `assistant` 气泡。
- `isWaiting=true` 时仅渲染 **一个** wave-loader 卡片。
- 收到首个 `token` 事件后创建助手消息并追加内容。

### 8.4 SSE 会话绑定

- HTTP 依赖注入的 `db` / `current_user` **不得**在 `StreamingResponse` 生成器内继续使用。
- 生成器内使用 `SessionLocal()`；`user_id`、`session_id` 在入口固化为标量。

---

## 待二次审阅（由 Owner 回填）

- [ ] RAG_TOP_K / SCORE_THRESHOLD 调参目标值
- [ ] 术语表是否接入业务方词库文件
- [ ] 是否启用独立 LLM 节点（每步一次调用）vs 当前合并预处理

---

*实施清单：`backend/app/services/agent_pipeline.py`、`backend/app/routers/chat.py`*
