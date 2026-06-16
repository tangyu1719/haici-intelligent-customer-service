# API 文档

Base URL: `http://127.0.0.1:8000`

> RAG 链路与 SSE 事件语义见 [项目说明.md](../项目说明.md) 章节 2、[AI架构设计.md](./AI架构设计.md)。

## 1 认证

- `POST /api/v1/auth/register` 注册（邮箱或手机号 + 密码）
- `POST /api/v1/auth/send-code` 发送短信/邮箱验证码
- `POST /api/v1/auth/login` 登录（支持密码/短信验证码）
- `POST /api/v1/auth/refresh` 刷新 access_token
- `POST /api/v1/auth/logout` 登出（吊销 refresh_token）
- `GET /api/v1/auth/me` 当前用户信息（Bearer Token）
- `GET /api/v1/auth/menus` 当前用户菜单树
- `PATCH /api/v1/auth/profile` 更新个人资料

## 2 会话

- `POST /api/v1/sessions` 创建新会话
- `GET /api/v1/sessions` 会话列表（分页、排序、搜索）
- `GET /api/v1/sessions/{id}` 会话详情（含最近消息）
- `GET /api/v1/sessions/{id}/messages` 消息历史（分页）
- `PATCH /api/v1/sessions/{id}` 更新标题/备注/置顶
- `DELETE /api/v1/sessions/{id}` 归档（软删除）

## 3 知识库管理

- `GET /api/v1/knowledge` 文档列表（支持 kb_id 筛选、状态筛选）
- `POST /api/v1/knowledge/upload` 上传文档（支持 kb_id 参数关联知识库）
- `DELETE /api/v1/knowledge/{id}` 删除文档及向量数据
- `GET /api/v1/knowledge/{id}/manifest` 文档标准化产物清单
- `GET /api/v1/knowledge/{id}/normalized` 文档标准化 Markdown 内容
- `GET /api/v1/knowledge/{id}/assets` 文档图片资产列表
- `GET /api/v1/knowledge/config` 知识库配置（VLM/OCR/标准化开关）
- `GET /api/v1/knowledge/slice-methods` 支持的分块策略列表
- `POST /api/v1/knowledge/chunk-preview` 分块预览

## 4 多知识库路由

- `GET /api/v1/knowledge-bases` 知识库分页列表
- `GET /api/v1/knowledge-bases/all` 所有知识库简要列表（下拉用）
- `POST /api/v1/knowledge-bases` 创建知识库
- `GET /api/v1/knowledge-bases/{id}` 知识库详情
- `PUT /api/v1/knowledge-bases/{id}` 更新知识库
- `DELETE /api/v1/knowledge-bases/{id}` 删除知识库（仅解除关联，不删文档）
- `POST /api/v1/knowledge-bases/auto-route?question=` 自动路由到最相关知识库

## 5 流式问答（SSE）

`POST /api/v1/chat/stream`

请求：

```json
{
  "session_id": 1,
  "question": "退换货要几天？",
  "kb_id": null,
  "attachments": [
    {"type": "image", "name": "photo.png", "path": "/output/...", "preview": "data:..."}
  ]
}
```

SSE 事件流：

- `event: meta` → `{"intent":"after_sale","intent_label":"售后问题","kb_id":1,"anti_dilution":false,"pipeline":{...}}`
- `event: citations` → `{"items":[...],"slices":[...]}`
- `event: token` → `{"content":"退"}`
- `event: follow_ups` → `{"items":["追问1","追问2"]}`
- `event: done` → `{"assistant_message_id":12,"content":"完整回答","persist_async":false}`

- `GET /api/v1/chat/config` 对话配置（最大问题长度、上下文预算等）
- `GET /api/v1/chat/intent-alternatives` 意图纠偏备选方案

## 反馈

- `POST /api/v1/feedback/messages/{message_id}` 提交反馈

```json
{
  "rating": 4,
  "intent_liked": true,
  "comment": "回答准确",
  "context_snapshot": {
    "session_id": 1,
    "context_id": "uuid",
    "context_summary": "...",
    "user_question": "...",
    "assistant_answer": "...",
    "intent": "after_sale",
    "intent_label": "售后问题"
  }
}
```

- `GET /api/v1/feedback/my` 个人反馈历史

## 7 管理后台

### 7.1 反馈管理
- `GET /api/v1/admin/feedback` 反馈列表（管理视图，支持筛选）
- `GET /api/v1/admin/feedback/{id}` 反馈详情
- `GET /api/v1/admin/feedback/analytics` 反馈分析统计
- `GET /api/v1/admin/feedback/ai-analysis` AI 分析报告

### 7.2 EVAL 评测
- `GET /api/v1/admin/eval/overview` EVAL 评测概览

### 7.3 运维日志
- `GET /api/v1/admin/logs/operation` 操作日志
- `GET /api/v1/admin/logs/error` 异常日志
- `GET /api/v1/admin/logs/api-call` API 调用日志
- `GET /api/v1/admin/logs/schedule` 定时任务日志

## 8 系统

- `GET /api/v1/system/platform/health` 平台健康检查（MySQL/Chroma/Embedding/LLM网关）
- `GET /api/v1/system/llm-gateway` LLM 网关快照

## 9 多模态

- `POST /api/v1/multimodal/upload` 上传文件（图片/文档）
- `POST /api/v1/multimodal/text` 粘贴文本处理
- `POST /api/v1/multimodal/process` 文档处理
- `POST /api/v1/multimodal/flowchart/score` 流程图评分
- `GET /api/v1/multimodal/formats` 支持格式列表
- `GET /api/v1/multimodal/output-path` Output 目录信息
- `GET /api/v1/multimodal/browse` Output 目录浏览

## 10 Agent 配置

- `GET /api/v1/agent-settings/catalog` Agent 目录
- `GET /api/v1/agent-settings/prompt/{agent_id}` Agent Prompt
- `PUT /api/v1/agent-settings/prompt/{agent_id}` 更新 Prompt
- `GET /api/v1/agent-settings/routing` 路由配置
- `PUT /api/v1/agent-settings/routing` 更新路由配置
