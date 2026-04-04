# 知微多模态 Agent 电商智能客服中台

聚焦电商场景咨询意图杂、PDF 商品和规则手册信息提取难以及核心业务办理依赖人工等痛点，搭建全栈电商智能客服中台。系统采用"意图拦截分流 + Agent 工具调度"架构，构建起多模态文档解析与结构化入库、意图驱动的 Agent 自主调度业务工具与 RAG 知识检索并经混合召回与交叉编码器重排生成回答、四维自动化量化评测的完整闭环链路，显著提升复杂咨询环境下的响应速度与回复精度。

---

## 技术栈

| 层级 | 技术选型 |
|------|---------|
| **大模型推理** | Qwen2.5-72B-AWQ（vLLM 部署，4 卡张量并行） |
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
| **容器化** | Podman Compose 编排（MySQL / ChromaDB / ES / Redis） |

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
  命中FAQ  标签注入Agent ◄──┘
  直接返回     │
     │        ▼
     │   Agent（Qwen2.5-72B-AWQ）
     │   ReAct 循环，最多 5 轮
     │        │
     │   ┌────┴─────┐
     │   │          │
     │  业务工具   知识检索工具
     │  直连MySQL  search_knowledge
     │   │          │
     │   │     ┌────┴────────────────┐
     │   │     │ 查询扩展 → 双路召回   │
     │   │     │ RRF 融合 → Reranker  │
     │   │     │ Top3 生成回答        │
     │   │     └─────────────────────┘
     │   │          │
     ▼   ▼          ▼
┌─────────────────────────┐
│       返回结果            │
└─────────────────────────┘

  ┌─────────────────────────────────┐
  │  Redis 对话历史 & RAG 缓存       │
  │  · 滑动窗口 15 轮（30 条消息）     │
  │  · 会话 TTL 2 小时                │
  │  · RAG 缓存 TTL 10 分钟           │
  └─────────────────────────────────┘
```

---

## 一、知识入库

### 1.1 数据来源

大疆 DJI Mini 4 Pro 无人机 PDF 说明书（约 100 页）和 4 份电商规则 PDF 说明书（每份 1 页以内）。

### 1.2 提取方式

使用 MinerU 将 PDF 转换为结构化 Markdown 文件。对于 Markdown 中的嵌入图片，调用 RapidOCR 提取图片内容。提取后的 Markdown 还经过清洗处理，HTML 表格通过 LLM 转换为自然语言描述，去除水印、残留标签和无效内容。

### 1.3 切分入库

采用父子块两级切分策略：

- **父块：** 优先按 Markdown 标题层级（H1 → H4）进行语义切分，每个父块对应一个完整的章节段落，并在内容前拼接标题路径以保留上下文。若文档无明显标题结构，则退化为按 1500 字符滑动窗口切分（重叠 200 字符）。父块写入 Elasticsearch，用于关键词全文检索和父块回溯。

- **子块：** 将每个父块进一步按 500 字符（重叠 80 字符）切成更细粒度的子块，每个子块携带其所属父块的 parent_id。子块经 BAAI/bge-large-zh-v1.5 向量模型编码后写入 ChromaDB 用于语义向量检索，同时原文写入 Elasticsearch 用于关键词精确匹配，实现双路召回。

---

## 二、数据检索

用户提问后，系统采用意图识别分流 → Agent 统一推理的两阶段架构。

### 2.1 意图识别与分流

意图识别采用规则优先 + 小模型兜底的双层策略。

**第一层规则引擎对输入做快速判断：**

- 通过字典精确匹配 FAQ 预设问答对返回；
- 包含订单号（OD 开头）或商品编号（P001 等）的问题直接标记为 tool_call；
- 通过关键词匹配检测输入中是否包含政策规则类词汇或产品参数类词汇，命中且不包含具体订单号或商品编号时，直接标记为 rag；

**第二层对规则未能覆盖的问题：**

调用本地部署的 Qwen2.5-1.5B 进行三分类（chitchat / tool_call / rag），当模型输出不在合法标签范围内时，让 Agent 自己判断。

**辅助功能：**

- 上传图片的请求标记为 image_query 并通过 RapidOCR 提取图片文字拼入提问。
- 前端集成了 Web Speech API 语音识别功能，支持中文语音实时转文字。用户点击麦克风按钮后，浏览器端完成语音识别并自动填入输入框，不额外消耗服务端资源。

### 2.2 Agent 统一推理

闲聊命中 FAQ 直接返回预设回答。其余问题将意图标签作为路由提示注入 Qwen2.5-72B-AWQ（vLLM 部署，4 卡张量并行）驱动的 Agent，Agent 采用 ReAct 循环模式，最多迭代 5 轮，根据标签自主选择调用对应工具。工具启动时通过 MCP 协议加载描述注册，共 5 个工具：query_order（订单查询）、cancel_order（取消订单）、query_logistics（物流追踪）、check_stock（库存查询）直连 MySQL 获取实时数据，search_knowledge（知识检索）触发 RAG 检索管线。若用户缺少订单号等必要参数，Agent 会主动追问。

### 2.3 工具执行与 RAG 检索管线

Agent 根据标签自主调用对应工具：业务工具（query_order、cancel_order、query_logistics、check_stock、compare_products）直连 MySQL 查询实时订单、物流与库存数据，即时返回结果。知识检索工具（search_knowledge）触发 RAG 检索管线：首先对用户原始提问通过 LLM 生成 2 条语义改写（查询扩展），连同原始查询共 3 条 query 并行启动 Chroma 向量检索和 ES 关键词检索各返回 15 条候选。ES 检索采用短语匹配（boost 5.0）、全词匹配（boost 3.0）和分词匹配（boost 1.5）三路 should 组合，并通过 jieba 分词优化中文召回。召回的子块通过其携带的 parent_id 回溯到 Elasticsearch 中对应的完整父块内容，恢复上下文完整性。随后对所有候选文档进行 RRF 融合排序，取 Top 15 送入 BAAI/bge-reranker-base 交叉编码器精排，最终取 Top 3 作为参考资料生成回答。

### 2.4 对话记忆与缓存

通过 Redis 维护会话上下文，滑动窗口保留最近 15 轮对话（30 条消息），会话有效期 2 小时，过期自动清除。Agent 推理时将历史对话注入 messages 列表，确保多轮对话中能理解代词指代和上下文承接。同时 RAG 查询结果缓存至 Redis（TTL 10 分钟，key 基于 query 的 MD5），相同问题短时间内重复提问直接返回缓存，避免重复检索和推理。

---

## 三、效果评测

系统内置自动化评测框架，基于 33 条覆盖闲聊、工具调用和知识问答三类场景的评测用例，从四个维度量化系统表现：

- **意图识别准确率：** 采用三分类评估（chitchat / tool_call / rag），计算预测标签与期望标签的匹配率。
- **检索召回率：** 每条评测用例预设 2-3 个核心关键词，计算公式为：命中关键词数 / 预设关键词总数。
- **生成质量：** 采用大模型自评方式，将用户问题和系统回答送入 Qwen2.5-72B，按 0-100 分评判回答的相关性和准确性。评分标准为：0 分完全不相关或错误，50 分部分回答但不完整，80 分准确但略显冗余，100 分准确且简洁。对于包含"无法"、"抱歉"等拒答词或长度不足 5 字的回答，直接赋 10 分。
- **平均延迟：** 记录每条评测从发起提问到返回完整回答的端到端耗时，涵盖意图识别、检索召回、重排序、Agent 推理及工具调用的全链路时间。

---

## 四、评测结果

| 指标 | 数值 | 说明 |
|------|------|------|
| **意图准确率** | **97%** | 33 条样本意图识别正确率 |
| **检索召回率** | **85.9%** | 基于关键词命中率衡量文档召回质量 |
| **生成质量** | **90.3 / 100** | LLM-as-a-Judge 对回答相关性和准确性打分 |
| **平均延迟** | **2.8s** | 含意图识别 + 工具调用 + 检索 + 生成全链路耗时 |

---

## 五、效果展示

### 聊天界面

<!-- 在此粘贴聊天界面截图 -->

### 评测看板

<!-- 在此粘贴评测看板截图 -->

### 对话示例

<!-- 在此粘贴对话示例截图 -->

---

## 项目结构

```
zhiwei-agent/
├── main.py              # FastAPI 入口，/chat/sync、/eval/run 接口，启动时预加载 Reranker
├── config.py            # Pydantic Settings 统一配置，读取 .env 环境变量
├── dialog.py            # 对话管理器，协调意图识别、图片处理、标签注入、Agent 调用
├── agent.py             # ReAct Agent，启动时 MCP 加载工具 schema，运行时本地调用工具函数
├── intent.py            # 双层意图识别：规则引擎（FAQ/正则/关键词）+ Qwen2.5-1.5B 分类
├── mcp_server.py        # MCP 工具服务，5 个工具（4 业务 + 1 知识检索）直连 MySQL 和 RAG
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
podman-compose up -d   # 启动 MySQL / ChromaDB / ES / Redis
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
