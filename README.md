# 知微多模态 Agent 电商智能客服中台

聚焦电商场景咨询意图杂、PDF 商品和规则手册信息提取难以及核心业务办理依赖人工等痛点，搭建全栈电商智能客服中台。系统采用"意图拦截分流 + Agent 工具调度"架构，构建起多模态文档解析与结构化入库、意图驱动的 Agent 多工具自主调度与混合检索重排、四维自动化量化评测的完整闭环链路，显著提升复杂咨询环境下的响应速度与回复精度。

---


## 技术栈

| 层级 | 技术选型 |
|------|---------|
| **大模型推理** | Qwen2.5-72B-AWQ（vLLM 部署，4 卡张量并行，意图推理 + 生成 + LLM-as-a-Judge 评测） |
| **意图识别** | Qwen2.5-1.5B-Instruct（本地 FP16 GPU 推理，三分类） |
| **Embedding** | BAAI/bge-large-zh-v1.5（本地部署，1024 维） |
| **Reranker** | BAAI/bge-reranker-base（本地 CrossEncoder，safetensors 加载） |
| **文档解析** | MinerU 3.0（pipeline 后端 + GPU 加速） |
| **OCR** | RapidOCR（ONNX Runtime 推理） |
| **向量库** | ChromaDB 0.4.24（HNSW + cosine 距离） |
| **全文检索** | Elasticsearch 8.11（BM25 + jieba 分词扩展） |
| **关系数据库** | MySQL 8.0（订单、商品、物流、用户数据） |
| **缓存 & 会话** | Redis 7（对话历史窗口 + RAG 结果缓存） |
| **后端框架** | FastAPI + Uvicorn |
| **前端** | Vue 3 + Tailwind CSS 单页应用（聊天界面 + 评测看板） |
| **Agent 框架** | LangChain + MCP 协议（ReAct 循环，最多 5 轮工具调用） |
| **容器化** | Docker Compose 编排（MySQL / ChromaDB / ES / Redis） |

---

## 系统架构

```
用户输入（文本 / 图片 / 语音）
   │
   ▼
┌────────────────────────┐
│  意图识别引擎（双层策略）  │
│  规则引擎 → Qwen2.5-1.5B │
└──────────┬─────────────┘
           │
     ┌─────┼──────────────┐
     │     │              │
  chitchat  tool_call/rag  未命中
     │     │              │
     ▼     ▼              ▼
  命中FAQ  RAG 检索 ◄──────┘
  直接返回  (查询扩展→双路召回→RRF→Reranker)
     │     │
     │     ▼
     │   检索结果注入上下文
     │     │
     │     ▼
     │   Agent（Qwen2.5-72B-AWQ）
     │     │
     │     ├─ 分析意图
     │     ├─ 选择 MCP 工具
     │     ├─ 执行调用（MySQL 实时数据）
     │     ├─ 整合结果（最多 5 轮）
     │     │
     ▼     ▼
┌─────────────────────────┐
│       返回结果            │
└─────────────────────────┘

┌─────────────────────────────────┐
│  Redis 对话历史                   │
│  · 滑动窗口 15 轮（30 条消息）     │
│  · 会话 TTL 2 小时                │
│  · RAG 缓存 TTL 10 分钟           │
└─────────────────────────────────┘
```

---

## 功能模块详解

### 1. 知识入库

**数据来源：** 大疆 DJI Mini 4 Pro 无人机 PDF 用户手册（约 100 页，图文混合版）和 4 份京东电商规则 PDF 文档（每份 1 页以内）。

**提取方式：** 使用 MinerU 3.0（pipeline 后端 + GPU 加速）将 PDF 转换为结构化 Markdown 文件，保留原始文档的标题层级、段落结构和表格信息。由于 PDF 中嵌有示意图和图表，提取后的 Markdown 中包含图片引用链接，系统通过 RapidOCR（ONNX 推理引擎）对嵌入图片逐一进行文字提取，将识别结果替换原图片链接，确保图片中的参数、标注等文字信息不丢失。此外，提取后的内容还经过清洗处理：HTML 表格通过 LLM 转换为自然语言描述（因 Markdown 原生表格语法不支持合并单元格等复杂结构，MinerU 以 HTML `<table>` 格式嵌入），水印文字、残留 HTML 标签和无效短行被自动过滤。

**切分入库：** 采用父子块两级切分策略：

- **父块：** 优先按 Markdown 标题层级（H1 → H4）进行语义切分，每个父块对应一个完整的章节段落，并在内容前拼接标题路径（如 `[产品概述 > 飞行参数]`）以保留上下文。若文档无明显标题结构，则退化为按 1500 字符滑动窗口切分（重叠 200 字符）。父块写入 Elasticsearch，用于关键词全文检索和父块回溯。
- **子块：** 将每个父块进一步按 500 字符（重叠 80 字符）切成更细粒度的子块，每个子块携带其所属父块的 parent_id。子块通过 BAAI/bge-large-zh-v1.5 向量模型编码后同时写入 ChromaDB（用于语义向量检索）和 Elasticsearch（用于关键词精确匹配），实现双路召回。

### 2. 意图识别与分流

意图识别采用规则优先 + 小模型兜底的双层策略。

**第一层规则引擎对输入做快速判断：**

- **chitchat（闲聊）：** 通过 FAQ 问答字典精确匹配，覆盖"你好"、"谢谢"、"再见"等 20 余条常见问候和简单反馈，命中后直接返回预设回答，不消耗大模型算力。同时对长度不超过 3 个字符且不包含订单号或商品编号的超短输入，也归为闲聊。
- **tool_call（工具调用）：** 通过正则表达式检测输入中是否包含订单号（OD 开头 + 10 位以上数字）或商品编号（P + 3 位数字），命中则直接标记为 tool_call，无需经过小模型推理即可进入工具调用流程。
- **rag（知识检索）：** 通过关键词列表子串匹配，检测输入中是否包含政策规则类词汇（如"运费"、"退款"、"售后"、"保修"等）或产品参数类词汇（如"续航"、"图传"、"避障"、"像素"等），命中且不包含具体订单号或商品编号时，直接标记为 rag，跳过小模型分类直接进入知识检索流程。
- **image_query（图片识别）：** 当用户上传图片时，直接标记为 image_query，通过 RapidOCR 提取图片中的文字内容，将识别结果拼入用户提问文本，交由 Agent 统一处理。

**第二层对规则未能覆盖的问题：** 调用本地部署的 Qwen2.5-1.5B（FP16，GPU 推理）进行三分类（chitchat / tool_call / rag），当模型输出不在合法标签范围内时，默认归为 rag 确保兜底。

**辅助功能：** 前端集成了 Web Speech API 语音识别功能，支持中文语音实时转文字。用户点击麦克风按钮后，浏览器端完成语音识别并自动填入输入框，不额外消耗服务端资源。

### 3. 上下文构建（RAG 检索管线）

闲聊命中 FAQ 时直接返回预设回答；其余情况均先启动 RAG 检索构建参考上下文：

1. **查询扩展：** 通过 LLM 生成 2 条语义改写，连同原始查询共 3 条 query 并发送入检索。
2. **双路召回：** ChromaDB 向量语义检索和 Elasticsearch 关键词检索各返回 15 条候选。ES 检索采用短语匹配（boost 5.0）、全词匹配（boost 3.0）和分词匹配（boost 1.5）三路 should 组合，并通过 jieba 分词优化中文召回。
3. **父块回溯：** 召回的子块通过其携带的 parent_id 回溯到 Elasticsearch 中对应的完整父块内容，恢复上下文完整性。
4. **RRF 融合排序：** 对所有候选文档进行 RRF（Reciprocal Rank Fusion，k=60）融合排序，取 Top 15。
5. **精排：** 送入 BAAI/bge-reranker-base 交叉编码器精排，最终取 Top 3 作为参考资料。
6. **上下文注入：** 当检索置信度高于 0.3 时，将参考资料注入 Agent 上下文。

### 4. Agent 统一推理

所有请求统一交由基于 Qwen2.5-72B-AWQ（vLLM 部署，4 卡张量并行）驱动的 Agent 处理。Agent 通过 MCP（Model Context Protocol）协议连接工具服务，可调用以下四个 skill 工具，工具后端直连 MySQL 数据库获取实时数据：

| 工具 | 功能 | 数据来源 |
|------|------|---------|
| query_order | 查询订单状态、金额和商品详情 | orders + order_items + products + logistics |
| cancel_order | 取消订单 | orders |
| query_logistics | 查询物流轨迹 | logistics + logistics_trace |
| check_stock | 查询商品库存和价格 | products + product_skus |

Agent 采用 ReAct 循环模式，最多迭代 5 轮工具调用，每轮根据工具返回结果决定是否继续调用或生成最终回答。若用户缺少订单号等必要参数，Agent 会主动追问。

### 5. 对话记忆与缓存

通过 Redis 维护会话上下文，滑动窗口保留最近 15 轮对话（30 条消息），会话有效期 2 小时，过期自动清除。Agent 推理时将历史对话注入 messages 列表，确保多轮对话中能理解代词指代和上下文承接。同时 RAG 查询结果缓存至 Redis（TTL 10 分钟，key 基于 query 的 MD5），相同问题短时间内重复提问直接返回缓存，避免重复检索和推理。

---

## 评测体系

系统内置自动化评测框架，基于 33 条覆盖闲聊、工具调用和知识问答三类场景的评测用例，从四个维度量化系统表现：

| 指标 | 数值 | 说明 |
|------|------|------|
| **意图准确率** | **93.9%** | 采用三分类评估（chitchat / tool_call / rag），计算预测标签与期望标签的匹配率 |
| **检索召回率** | **87.4%** | 每条用例预设 2-3 个核心关键词，计算命中关键词数 / 预设关键词总数 |
| **生成质量** | **92.12 / 100** | LLM-as-a-Judge，将问题和回答送入 Qwen2.5-72B 按 0-100 分评判相关性和准确性 |
| **平均延迟** | **3.991s** | 涵盖意图识别、检索召回、重排序、Agent 推理及工具调用的全链路耗时 |

---

## 项目结构

```
zhiwei-agent/
├── main.py              # FastAPI 入口，/chat/sync、/eval/run 接口，启动时预加载 Reranker
├── config.py            # Pydantic Settings 统一配置，读取 .env 环境变量
├── dialog.py            # 对话管理器，协调意图识别、图片处理、RAG 检索、Agent 调用
├── agent.py             # ReAct Agent，SystemPrompt + 历史注入 + MCP 工具绑定 + 循环执行
├── intent.py            # 双层意图识别：规则引擎（FAQ/正则/关键词）+ Qwen2.5-1.5B 分类
├── mcp_server.py        # MCP 工具服务，4 个 skill 直连 MySQL 获取实时数据
├── rag.py               # RAG 管线：查询扩展 → 双路并行召回 → RRF 融合 → Reranker 精排 → LLM 生成
├── llms.py              # LLM / Embedder / Reranker 封装，含响应缓存
├── vectorstore.py       # ChromaDB 向量库：去重写入、cosine 检索、集合管理
├── es_client.py         # Elasticsearch：索引管理、jieba 分词、三路混合查询、父块回溯
├── memory.py            # Redis 对话历史，滑动窗口 15 轮 + 自动过期
├── multimodal.py        # RapidOCR 图片文字提取
├── evaluation.py        # 评测引擎：意图匹配 + 关键词召回 + LLM-as-a-Judge 打分
├── run_eval.py          # 命令行评测脚本
├── reimport_clean.py    # 知识库清洗重导：HTML 表格 LLM 转换 + 水印去除 + 父子块切分入库
├── import_kb.py         # JSON 知识库导入，双写 ChromaDB + ES
├── clean_kb.py          # 数据清理，重置 ChromaDB / ES / Redis
├── docker-compose.yml   # 容器编排：MySQL / ChromaDB / ES / Redis
├── init.sql             # MySQL 建表 DDL
├── init_data.sql        # MySQL 初始数据：5 款商品、3 笔订单、物流轨迹
├── frontend/
│   └── index.html       # Vue 3 + Tailwind CSS 聊天界面 + 评测看板 + 语音输入 + 图片上传
├── qwen/
│   └── Qwen2.5-1.5B-Instruct/  # 本地意图识别小模型
└── test_data/
    ├── eval_cases.json          # 33 条评测用例
    ├── knowledge_base.json      # 结构化知识条目（运费/售后/DJI 参数等）
    └── *.pdf                    # DJI 用户手册 + 4 份电商规则文档
```

---

## 快速开始

### 1. 环境准备

```bash
cd zhiwei-agent
cp .env.example .env   # 按需修改 API Key 和数据库连接
```

### 2. 启动基础服务

```bash
docker-compose up -d   # 启动 MySQL / ChromaDB / ES / Redis
```

### 3. 启动 vLLM 推理服务

```bash
CUDA_VISIBLE_DEVICES=4,5,6,7 nohup vllm serve ~/qwen2.5-72b-awq \
  --served-model-name qwen2.5-72b-awq \
  --host 0.0.0.0 --port 8900 \
  --tensor-parallel-size 4 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  > /tmp/vllm_72b.log 2>&1 &
```

### 4. 导入知识库

```bash
# 导入 JSON 结构化知识
python import_kb.py

# 导入 PDF 文档（需先通过 MinerU 解析产出 Markdown）
python reimport_clean.py
```

### 5. 启动应用

```bash
CUDA_VISIBLE_DEVICES=0 uvicorn main:app --host 0.0.0.0 --port 5050
```

### 6. 访问服务

- 聊天界面：http://localhost:5050
- API 文档：http://localhost:5050/docs

### 7. 运行评测

```bash
python run_eval.py
```
<img width="1916" height="909" alt="6b2ac24ad127e30a85be2fc2ee7cfa07" src="https://github.com/user-attachments/assets/547b5571-e889-4795-ba6f-8013fcacef1a" />
<img width="1916" height="909" alt="6b2ac24ad127e30a85be2fc2ee7cfa07" src="https://github.com/user-attachments/assets/ae5b97aa-462d-4fc4-aa79-09d137a794bb" />
<img width="1919" height="907" alt="5613a776fee92bc6057fa0691d4e2147" src="https://github.com/user-attachments/assets/2c6e2a46-ae3a-4abf-8b86-bace6e38ec77" />
<img width="1919" height="908" alt="c79a48a64c63ea1793ba182ed0cf4537" src="https://github.com/user-attachments/assets/ffe3bb63-0829-4dca-917e-d5eb980a2558" />
<img width="1914" height="893" alt="536725672352a1e97859a4c4357ff4be" src="https://github.com/user-attachments/assets/cce41098-75f6-4af0-b909-e33b1f4fc68e" />




