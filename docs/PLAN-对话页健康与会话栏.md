# PLAN · 对话页健康检查与会话侧栏

## 0. 文档元数据、摘要与定位

### 一句话摘要

在对话页引入 web_rebuild 同源的平台健康探测条、左侧竖向会话列表，并修复 SSE 流式期间的空气泡/竖线闪烁与 `DetachedInstanceError` 导致的「对话服务异常」。

### 分类路径

`产品研发` → `PLAN·实施计划` → `HaiChiAgent/对话页` → `ChatPanel + platform_health`

| 层级 | 值 |
|------|-----|
| L1 领域 | 产品研发 |
| L2 类型 | PLAN·实施计划 |
| L3 模块 | HaiChiAgent / 智能对话 |
| L4 | `ChatPanel.vue`、`platform_health.py` |

### 版本与修订

| 字段 | 值 |
|------|-----|
| doc_version | v0.1 |
| status | 已实施 |
| created_at | 2026-06-12T15:00:00+08:00 |
| updated_at | 2026-06-12T15:00:00+08:00 |
| author | Cursor Agent (draft) |
| reviewer | _待指派_ |

---

## 目录

- [1. 背景与问题](#1-背景与问题)
- [2. 实现范围](#2-实现范围)
- [3. 文件清单](#3-文件清单)
- [4. 验证步骤](#4-验证步骤)
- [待二次审阅（由 Owner 回填）](#待二次审阅由-owner-回填)

---

## 1. 背景与问题

| 问题 | 根因 | 处理 |
|------|------|------|
| 加载时出现空气泡 + 竖线 | 发送即插入空 `assistant` 消息并叠加光标 + 独立 wave-loader | 等待期仅显示 wave-loader；首 token 再创建助手气泡 |
| 「对话服务异常」 | SSE 生成器内访问 `current_user.id`，请求 Session 已关闭 → `DetachedInstanceError` | 生成器使用独立 `SessionLocal`，入口固化 `user_id` |
| 无健康状态 | 未移植 web_rebuild 健康条 | 新增 `/api/v1/system/platform/health` |
| 无会话切换 | 对话页无侧栏 | `ChatPanel` 左侧会话列表，不引用任务结构 |

---

## 2. 实现范围

### 后端

- `platform_health.py`：探测 MySQL、Chroma、嵌入模型路径、LLM 网关（轻量 ping）。
- `GET /api/v1/system/platform/health`：返回 `{ ready, all_ok, summary, items[] }`，字段对齐 web_rebuild 前端。
- `chat.py`：SSE 生成器独立 DB Session。

### 前端

- 新建 `ChatPanel.vue`：
  - 顶栏：当前会话标题（上下文名称）+ 健康检查折叠条。
  - 左侧：竖向会话列表 +「新对话」。
  - 对话区：单一加载动画（三点 wave），无竖线光标。
- `MainShell.vue`：`/chat` 路由嵌入 `ChatPanel`，隐藏全局「智能客服会话」顶栏。

---

## 3. 文件清单

| 路径 | 变更 |
|------|------|
| `backend/app/services/platform_health.py` | 新增 |
| `backend/app/routers/system.py` | 健康 API |
| `backend/app/routers/chat.py` | SSE Session 修复 |
| `backend/app/auth/casbin_policies.py` | 健康路由授权 |
| `frontend/src/components/ChatPanel.vue` | 新增 |
| `frontend/src/views/MainShell.vue` | 接入 ChatPanel |
| `frontend/src/styles/main.css` | 健康条样式 |

---

## 4. 验证步骤

1. 登录 → 智能对话。
2. 顶栏显示当前会话名 +「健康检查」摘要；点击展开各依赖状态。
3. 左侧可切换历史会话、新建对话。
4. 发送问题：等待期仅见三点加载框，无竖线空泡。
5. 产品类问题应正常流式回复，不再出现「对话服务异常」。

---

## 待二次审阅（由 Owner 回填）

- [ ] 健康检查是否默认跳过 LLM ping（省 token）改为仅配置检测
- [ ] 会话侧栏是否需要删除/重命名会话
- [ ] Chroma 异常时是否在健康条显示「RAG 降级」引导文案
