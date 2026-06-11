# API 文档

Base URL: `http://127.0.0.1:8000`

## 认证

- `POST /api/v1/auth/register` 注册（邮箱或手机号 + 密码）
- `POST /api/v1/auth/login` 登录（OAuth2 表单：`username` + `password`）
- `GET /api/v1/auth/me` 当前用户（Bearer Token）

## 会话

- `POST /api/v1/sessions` 创建会话
- `GET /api/v1/sessions` 会话列表
- `GET /api/v1/sessions/{id}/messages` 消息历史

## 知识库

- `GET /api/v1/knowledge` 文档列表
- `POST /api/v1/knowledge/upload` 上传 txt/md/pdf
- `DELETE /api/v1/knowledge/{id}` 删除文档及向量

## 流式问答（SSE）

`POST /api/v1/chat/stream`

请求：

```json
{ "session_id": 1, "question": "退换货要几天？" }
```

SSE 事件：

- `event: meta` → `{"intent":"after_sale",...}`
- `event: citations` → `{"items":[{"document_name":"...","snippet":"..."}]}`
- `event: token` → `{"content":"退"}`
- `event: done` → `{"assistant_message_id":12,"content":"..."}`

## 反馈

- `POST /api/v1/feedback/messages/{message_id}`

```json
{ "rating": 1, "comment": "回答准确" }
```
