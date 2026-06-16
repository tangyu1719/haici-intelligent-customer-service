# PRD 功能对照与验收清单

> **来源文档**：[产品需求文档（AI 智能客服系统）](./HaiCi笔试_AI%20智能客服系统_PRD.md)  
> **验收日期**：2026-06-16  
> **验收方式**：代码走查 + `pytest tests/` 全量回归（159 passed）  
> **说明**：不含 PRD「终极挑战·微服务 Agent 拆解」项（按交付范围排除）

---

## 一、必做功能（PRD §功能需求）

### 1. 用户与会话模块

| # | PRD 要求 | 实现状态 | 代码/接口 | 验证 |
|---|----------|----------|-----------|------|
| 1.1 | 用户注册/登录（手机号+密码 或 邮箱+密码） | ✅ 已实现 | `POST /api/v1/auth/register`、`/login`；支持短信验证码登录 | `test_regression_auth.py`、`test_regression_login_module.py` |
| 1.2 | 发起独立 Session 对话 | ✅ 已实现 | `POST /api/v1/sessions` | `test_regression_sessions.py` |
| 1.3 | 历史会话列表与会话详情（含完整对话） | ✅ 已实现 | `GET /api/v1/sessions`、`/sessions/{id}/messages` | `test_regression_sessions.py` |
| 1.4 | 对 AI 回答反馈（赞/踩 + 可选文字） | ✅ 已实现 | `POST /api/v1/feedback/messages/{id}` | `test_regression_feedback.py` |

### 2. 核心 AI 对话模块 · 知识库管理

| # | PRD 要求 | 实现状态 | 代码/接口 | 验证 |
|---|----------|----------|-----------|------|
| 2.1 | 上传 .txt / .md / .pdf，解析并向量化 | ✅ 已实现 | `POST /api/v1/knowledge/upload`；`doc_normalizer.py` + `knowledge_processor.py` | `test_regression_knowledge.py`、`test_regression_rag_normalize.py` |
| 2.2 | 知识库列表（名称、上传时间、处理中/就绪/失败） | ✅ 已实现 | `GET /api/v1/knowledge` | `test_regression_knowledge_base.py` |
| 2.3 | 删除文档并同步清除向量 | ✅ 已实现 | `DELETE /api/v1/knowledge/{id}` | `test_regression_knowledge.py` |

### 3. 核心 AI 对话模块 · 智能问答（RAG）

| # | PRD 要求 | 实现状态 | 代码/接口 | 验证 |
|---|----------|----------|-----------|------|
| 3.1 | 提问 → 向量检索 → Prompt 拼接 → LLM → 流式返回 | ✅ 已实现 | `POST /api/v1/chat/stream`；`rag.py` → `chat.py` | `test_regression_chat.py` |
| 3.2 | 展示引用来源（文档名 + 片段摘要） | ✅ 已实现 | SSE `event:citations`；`ChatAssistantMessage.vue` | `test_regression_chat.py` |
| 3.3 | 多轮对话（携带最近 N 轮历史） | ✅ 已实现 | `session_context_manager.py`、`chat_context.py` | `test_chat_context_manager.py` |

### 4. 业务规则

| # | PRD 要求 | 实现状态 | 配置/代码 | 验证 |
|---|----------|----------|-----------|------|
| 4.1 | 单次提问 ≤ 500 字 | ✅ 已实现 | `MAX_QUESTION_LENGTH=500` | `test_regression_rate_limit.py` |
| 4.2 | 检索为空 → 标准兜底话术，不编造 | ✅ 已实现 | `FALLBACK_NO_CONTEXT`；空检索短路 LLM | `test_regression_chat.py` |
| 4.3 | 每用户每日提问上限 100（可配置） | ✅ 已实现 | `DAILY_QUESTION_LIMIT=100` | `test_regression_rate_limit.py` |
| 4.4 | SSE 流式逐字输出 | ✅ 已实现 | `event:token` 逐 delta 推送 | `test_regression_chat.py` |

---

## 二、加分项（PRD §可选扩展 / §加分项）

| # | PRD 加分项 | 实现状态 | 设计要点 | 验证 |
|---|------------|----------|----------|------|
| B1 | 意图识别并在会话记录标注 | ✅ 已实现 | 规则 + LLM 混合；SSE `meta.intent` 落库 `chat_messages.intent` | `test_regression_intent.py` |
| B2 | 追问引导 2–3 条 | ✅ 已实现 | `follow_up.py`；SSE `event:follow_ups` | `test_regression_chat.py` |
| B3 | 管理后台：全量会话、反馈统计、日均问答折线图 | ✅ 已实现 | `FeedbackDashboard.vue` + `feedback_analytics.py` | `test_feedback_analytics.py`、`test_regression_admin.py` |
| B4 | 多知识库路由 | ✅ 已实现 | `knowledge_bases` 表 + `auto-route` API | `test_regression_knowledge_base.py` |
| B5 | 大规模检索防注意力稀释 | ✅ 已实现 | `context_anti_dilution.py` + `rag_gradient_filter.py` | `test_regression_anti_dilution.py` |
| B6 | 流式输出体验流畅 | ✅ 已实现 | 真 LLM token 流 + 前端 ReadableStream | 人工 + SSE 回归 |
| B7 | Prompt 优化减幻觉 | ✅ 已实现 | `prompt_segments.py` 硬约束 + 引用溯源 UI | 见 [面试问答-RAG与Agent.md](./面试问答-RAG与Agent.md) §3 |
| B8 | 知识库增量更新 | ✅ 已实现 | 按 `document_id` upsert/delete，删文档不影响其他向量 | `test_regression_knowledge.py` |
| — | **终极挑战：微服务 Agent 拆解** | ⏭ 不在范围 | 设计思路见面试文档 §6，未要求实现 | — |

---

## 三、技术要求对照（PRD §技术栈 / §技术要求）

| # | 要求 | 状态 | 说明 |
|---|------|------|------|
| T1 | 前后端分离 + RESTful / SSE | ✅ | Vue3 + FastAPI |
| T2 | RAG 自行实现（可借助框架但需理解） | ✅ | 手写检索/Prompt/流式，未黑盒 LangChain Chain |
| T3 | 向量检索与 LLM 在后端 | ✅ | 前端仅调 `/chat/stream` |
| T4 | AI 模块异常处理（超时/限流） | ✅ | `llm_error_recovery.py`、`llm_gateway.py` |
| T5 | SSE 流式输出 | ✅ | 见 [API文档.md](./API文档.md) |
| T6 | MySQL 存元数据 | ✅ | 见 [数据库设计.md](./数据库设计.md) |
| T7 | Chroma 向量库 | ✅ | `vectorstore.py` |
| T8 | OpenAI 兼容 LLM API | ✅ | 通义千问等，见 `.env.example` |
| T9 | Embedding（bge 等） | ✅ | `bge-small-zh-v1.5` CPU |
| T10 | `.env.example` 不含真实 Key | ✅ | 根目录已提供 |

---

## 四、提交物目录对照（PRD §提交要求）

| PRD 要求路径 | 状态 | 实际路径 |
|--------------|------|----------|
| `backend/` + README | ✅ | [backend/README.md](../backend/README.md) |
| `数据库初始化脚本/` | ✅ | [backend/数据库初始化脚本/](../backend/数据库初始化脚本/) |
| `frontend/` + README | ✅ | [frontend/README.md](../frontend/README.md) |
| `docs/API文档.md` | ✅ | [API文档.md](./API文档.md) |
| `docs/数据库设计.md` | ✅ | [数据库设计.md](./数据库设计.md) |
| `docs/AI架构设计.md` | ✅（已更新） | [AI架构设计.md](./AI架构设计.md) |
| `docs/业务流程说明.md` | ✅ | [业务流程说明.md](./业务流程说明.md) |
| `项目说明.md` | ✅（已更新） | [项目说明.md](../项目说明.md) |
| `运行指南.md` | ✅ | [运行指南.md](../运行指南.md) |

---

## 五、验收结论

| 维度 | 结论 |
|------|------|
| 必做功能 | **14/14 全部覆盖** |
| 加分项（不含终极挑战） | **8/8 已实现** |
| 自动化回归 | **159 passed / 0 failed**（2026-06-16） |
| 文档完整性 | 见 [项目交付总览.md](./项目交付总览.md) 文档清单 |

**总体判定：PRD 范围内功能验收通过，可进入代码审查与演示环节。**
