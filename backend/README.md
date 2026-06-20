# 后端启动说明

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

环境变量见项目根目录 `.env.example`。必须配置 `ARK_API_KEY` 与 `LLM_MODEL_QA`（DeepSeek-V4-flash 接入点）。

- **网关配置**：运行时读写 `backend/data/agent_gateway_config.json`（含密钥，已 gitignore）。首次可复制 `backend/data/agent_gateway_config.example.json`；管理 API 保存后会热重载 `llm_gateway`。
- **Embedding**：默认在 `backend/data/models` 查找本地 BGE 快照；也可设置 `EMBEDDING_MODEL_PATH` / `EMBEDDING_MODEL_CACHE_DIR`。
