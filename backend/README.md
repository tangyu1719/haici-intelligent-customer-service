# 后端启动说明

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

环境变量见项目根目录 `.env.example`。必须配置 `LLM_API_KEY`。
