# 后端启动说明

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

环境变量见项目根目录 `.env.example`。必须配置 `ARK_API_KEY` 与 `LLM_MODEL_QA`（DeepSeek-V4-flash 接入点）；Embedding 使用本地 `EMBEDDING_MODEL_PATH` 快照。
