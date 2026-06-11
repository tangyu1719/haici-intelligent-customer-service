# 前端启动说明

## 技术栈

- Vue 3 + TypeScript
- Vite 5
- Tailwind CSS（CDN）

## 开发模式

```bash
cd frontend
npm install
npm run dev
```

开发服务器默认 `http://127.0.0.1:5173`，API 通过 Vite 代理转发至后端 `8000` 端口。

## 生产构建

```bash
npm run build
```

构建产物输出至 `frontend/dist/`。后端启动后会优先托管 `dist` 目录（见 `backend/app/main.py`）。

## 功能模块

| 模块 | 说明 |
|------|------|
| 登录/注册 | JWT 鉴权，邮箱或手机号 |
| 智能对话 | SSE 流式问答、意图展示、引用溯源 |
| 知识库 | 文档上传/删除（txt/md/pdf） |
| 反馈 | 对助手消息点赞/点踩 |

## 目录结构

```
frontend/
├── src/
│   ├── api/          # HTTP 客户端
│   ├── styles/       # 全局样式
│   ├── types/        # TypeScript 类型
│   ├── App.vue       # 主应用组件
│   └── main.ts       # 入口
├── index.html
├── package.json
└── vite.config.ts
```
