# SPEC · 会话持久化与上下文标记

> **模块**：智能客服 / 会话管理  
> **版本**：v0.1  
> **日期**：2026-06-12  
> **状态**：已实施  

---

## 0. 文档元数据、摘要与定位

### 一句话摘要

在 MySQL 中为每条对话会话增加 **context_id（UUID）** 与 **meta_json（JSON 扩展元数据）**，前后端展示 **ID / 名称 / 创建时间 / 最后更新**，并支持 **重命名、备注、归档**；消息正文仍存 `chat_messages` 关系表。

### 分类路径

`产品研发` → `SPEC·PRD` → `HaiChiAgent/会话管理` → `chat_sessions`

| 层级 | 值 |
|------|-----|
| L1 领域 | 产品研发 |
| L2 类型 | SPEC·实施规格 |
| L3 模块 | HaiChiAgent / 会话持久化 |
| L4 | `backend/app/routers/sessions.py` |

### 版本与修订

| 字段 | 值 |
|------|-----|
| doc_version | v0.1 |
| status | 已实施 |
| created_at | 2026-06-12T18:00:00+08:00 |
| updated_at | 2026-06-12T18:00:00+08:00 |
| author | Cursor Agent |

---

## 目录

- [1. 背景与目标](#1-背景与目标)
- [2. 数据表设计](#2-数据表设计)
- [3. API 契约](#3-api-契约)
- [4. 前端展示与编辑](#4-前端展示与编辑)
- [5. 迁移与兼容](#5-迁移与兼容)
- [6. 验收清单](#6-验收清单)
- [待二次审阅（由 Owner 回填）](#待二次审阅由-owner-回填)

---

## 1. 背景与目标

| 诉求 | 方案 |
|------|------|
| 每条对话可持久化标记 | `chat_sessions` 行级持久化 + `chat_messages` 消息表 |
| 上下文 ID | `context_id` UUID，创建时生成，全局唯一 |
| 名称 | `title` 字段；首问自动截断 30 字；支持 PATCH 重命名 |
| 创建/更新时间 | `created_at` / `updated_at`；对话写入时刷新 `updated_at` |
| 扩展信息 | `meta_json`：`message_count`、`last_intent`、`note`、`pinned` |
| 编辑 | PATCH 重命名/备注；DELETE 软归档（`status=0`） |

**存储策略**：结构化字段走列；可变扩展走 MySQL JSON，避免频繁 ALTER。

---

## 2. 数据表设计

### chat_sessions（增强）

```sql
CREATE TABLE chat_sessions (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    context_id VARCHAR(36) NOT NULL COMMENT '上下文UUID',
    user_id BIGINT NOT NULL,
    title VARCHAR(200) NOT NULL DEFAULT '新对话',
    meta_json JSON NULL COMMENT '扩展元数据',
    status TINYINT NOT NULL DEFAULT 1 COMMENT '1正常0归档',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sessions_context (context_id),
    INDEX idx_sessions_user (user_id)
);
```

### meta_json 约定

```json
{
  "message_count": 12,
  "last_intent": "product",
  "note": "用户咨询售后",
  "pinned": false
}
```

### chat_messages（不变）

消息正文、意图、引用仍存关系表；`citations_json` 已为 JSON 列。

---

## 3. API 契约

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/sessions` | 创建会话，返回含 `context_id` |
| GET | `/api/v1/sessions` | 列表：id/context_id/title/时间/message_count/meta |
| GET | `/api/v1/sessions/{id}` | 详情 + 消息回放 |
| PATCH | `/api/v1/sessions/{id}` | 更新 `title` / `note` / `pinned` |
| DELETE | `/api/v1/sessions/{id}` | 归档（status=0） |

**列表项示例**：

```json
{
  "id": 11,
  "context_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "title": "你负责什么产品？",
  "created_at": "2026-06-12T10:00:00",
  "updated_at": "2026-06-12T10:05:00",
  "message_count": 4,
  "meta": { "last_intent": "product", "message_count": 4, "note": null, "pinned": false }
}
```

---

## 4. 前端展示与编辑

### 对话页左侧栏（`ChatPanel.vue`）

- 每条会话显示：**名称**、**ID**、**context_id 前 8 位**、**创建时间**、**最后更新**
- 悬停：**✎ 重命名**、**× 归档**
- 内联编辑：输入框 + 保存/取消

### 会话历史页（`/sessions`）

- 表格列：ID | 上下文 ID | 名称 | 创建时间 | 最后更新 | 消息数 | 操作
- 编辑：名称 + 备注；归档按钮
- 右侧详情：完整 context_id 与消息回放

---

## 5. 迁移与兼容

- 脚本：`backend/数据库初始化脚本/migrate_chat_sessions_v1.sql`
- 启动迁移：`bootstrap._ensure_chat_sessions_columns` 自动 ADD COLUMN + UUID 回填
- 旧会话无 `context_id` 时：`UPDATE ... SET context_id = UUID()`

### 5.1 异步持久化时机（v0.2）

| 阶段 | 行为 |
|------|------|
| 用户发问 | 同步读历史 + 跑 Pipeline；**用户消息/标题/meta 后台 `asyncio.create_task` 落库** |
| SSE 流式输出 | **不等待** DB commit，首 token 不被阻塞 |
| 回答完成 | 助手消息 **后台异步落库**；`done` 事件可带 `persist_async=true` |
| 失败 | 仅写日志，不阻断用户可见回复 |

实现：`app/services/chat_session_store.py` → `schedule_persist_user` / `schedule_persist_assistant`

### 5.2 上下文用量（v0.2）

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `MAX_QUESTION_LENGTH` | 500 | 单次输入字符上限 |
| `CHAT_MAX_CONTEXT_CHARS` | 262144 (256K) | 模型上下文窗口（字符） |
| `CHAT_CONTEXT_RESERVE_CHARS` | 32768 | 预留给 System/RAG/回答 |
| `CHAT_HISTORY_TURNS` | 50 | 历史轮数硬上限（双保险） |

历史选取：`chat_context.select_history_messages` 按字符预算从新到旧累加。  
配置 API：`GET /api/v1/chat/config`

---

## 6. 验收清单

- [x] MySQL 表含 `context_id` / `meta_json` / `status`
- [x] 创建会话自动生成 UUID
- [x] 列表/详情返回创建时间与更新时间
- [x] PATCH 重命名与备注
- [x] DELETE 软归档
- [x] 对话流式写入后刷新 `meta_json.message_count`（异步落库）
- [x] 用户/助手消息异步持久化，不阻塞 SSE
- [x] 上下文预算 256K + 单次输入 500 字
- [x] 对话页与会话历史页展示 ID/名称/时间
- [x] 回归脚本 `scripts/regression_chat_sessions.py`

---

## 待二次审阅（由 Owner 回填）

- [ ] 是否需要「置顶 pinned」在列表排序中优先
- [ ] 归档会话是否提供「回收站」恢复接口
- [ ] context_id 是否需对外 API（OpenAPI/Webhook）暴露

---

*实施文件：`models.py`、`routers/sessions.py`、`services/chat_session_store.py`、`ChatPanel.vue`、`MainShell.vue`*
