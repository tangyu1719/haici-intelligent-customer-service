# HaiCi 智能客服系统

基于开源电商客服 Agent 减重改造的企业级 RAG 智能客服 MVP，目录结构与交付物对齐 HaiCi 笔试 PRD。

## 技术栈

- **后端**：FastAPI + MySQL + ChromaDB
- **前端**：Vue 3 + TypeScript + Vite
- **LLM**：OpenAI 兼容 API（通义千问 / Ollama 等）
- **Embedding**：BAAI/bge-small-zh-v1.5（CPU）

## 目录结构

```
├── backend/                    # 后端代码
│   ├── app/                    # FastAPI 应用模块
│   ├── 数据库初始化脚本/         # 建表语句 + 样例知识库
│   ├── requirements.txt
│   └── README.md               # 后端启动说明
├── frontend/                   # 前端代码
│   ├── src/
│   ├── package.json
│   └── README.md               # 前端启动说明
├── docs/                       # 设计文档
│   ├── API文档.md
│   ├── 数据库设计.md
│   ├── AI架构设计.md
│   └── 业务流程说明.md
├── 项目说明.md
├── 运行指南.md
├── docker-compose.yml
└── .env.example
```

## 快速启动

```bash
# 1. 中间件
docker compose up -d

# 2. 配置
cp .env.example .env
# 填写 LLM_API_KEY

# 3. 后端
cd backend && pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. 前端（可选，开发模式）
cd frontend && npm install && npm run dev

# 5. 生产前端构建（后端托管 dist）
cd frontend && npm run build
```

浏览器访问：`http://127.0.0.1:8000`（或 Vite 开发端口 5173）

## 文档索引

- [项目说明](./项目说明.md)
- [运行指南](./运行指南.md)
- [API 文档](./docs/API文档.md)
- [数据库设计](./docs/数据库设计.md)
- [AI 架构设计](./docs/AI架构设计.md)
- [业务流程说明](./docs/业务流程说明.md)

## 分支

| 分支 | 说明 |
|------|------|
| `main` | 上游完整克隆快照 |
| `feature/haici-mvp` | PRD MVP 改造交付分支 |
