# SPEC · RAG 文档标准化（含 DOCX/PDF 图片处理）

> **模块**：知识库 / 多模态文档入库  
> **版本**：v0.1  
> **日期**：2026-06-12  
> **状态**：已批准 · 实施中（Owner 2026-06-12 裁决）  
> **产品需求文档**：`HaiCi笔试_AI 智能客服系统_PRD.md`（只读）  
> **关联 SPEC**：`SPEC-AI问答Agent.md`（分块策略已实施）、`docxl/AI架构设计.md`

---

## 0. 文档元数据、摘要与定位

### 一句话摘要

规定 HaiCi 知识库入库前的**文档标准化产物形态**：凡 DOCX/PDF 必须走**图片抽取 → 可引用链接占位 → 类型识别 → 分类型处理 → OCR/VLM 回插**流水线；DOCX 优先 `python-docx + 本地 OCR`，流程图走专用 CV 管道，其余图片走 VLM 分类与纯描述策略，最终输出可 RAG 分块的标准 Markdown/TXT。

### 分类路径

`产品研发` → `SPEC·实施规格` → `HaiCiAgent/知识库` → `document_normalization`

| 层级 | 值 |
|------|-----|
| L1 领域 | 产品研发 |
| L2 类型 | SPEC·实施规格 |
| L3 模块 | HaiCiAgent / RAG 知识库 |
| L4 | `backend/app/services/`（`knowledge_processor` · `document` · 新增 `doc_image_pipeline`） |

### 版本与修订（Git 式）

| 字段 | 值 |
|------|-----|
| doc_version | v0.2 |
| status | 已批准 · 实施中 |
| created_at | 2026-06-12T18:00:00+08:00 |
| updated_at | 2026-06-12T20:00:00+08:00 |
| author | Cursor Agent (draft) |
| reviewer | _待指派_ |
| git_branch | feature/haici-mvp |
| git_commit | N/A |

---

## 目录

- [0. 文档元数据、摘要与定位](#0-文档元数据摘要与定位)
- [1. 背景与范围](#1-背景与范围)
- [2. 标准化产物定义](#2-标准化产物定义)
- [3. 图片处理总则（DOCX / PDF 强制）](#3-图片处理总则docx--pdf-强制)
- [4. DOCX 解析策略](#4-docx-解析策略)
- [5. PDF 解析策略](#5-pdf-解析策略)
- [6. 图片链接与占位标记规范](#6-图片链接与占位标记规范)
- [7. VLM 图片类型识别与分路由处理](#7-vlm-图片类型识别与分路由处理)
- [8. 流程图专用管道](#8-流程图专用管道)
- [9. OCR 回插与 RAG 分块衔接](#9-ocr-回插与-rag-分块衔接)
- [10. 模块映射与 API](#10-模块映射与-api)
- [11. 执行抉择与 WARNING](#11-执行抉择与-warning)
- [12. 验收清单](#12-验收清单)
- [13. Open Questions（实施前须裁决）](#13-open-questions实施前须裁决)
- [待二次审阅（由 Owner 回填）](#待二次审阅由-owner-回填)

---

## 1. 背景与范围

### 1.1 背景

- PRD 要求知识库支持 **txt / md / pdf** 上传并向量化；HaiCi 已扩展 docx、图片等多模态入口。
- 已实施 **RAG 分块策略模块化**（`kb_chunk_service.py`），但入库前 **文档正文标准化** 仍不足：DOCX/PDF 内嵌图未统一抽链、未分类、未保证链接可引用。
- 上级工程 `src/agent` 已有能力可复用：
  - `mineru_processor.py`：DOCX 混排解析、PDF pipeline、百度 OCR + 本地 pytesseract、VLM 理解
  - `vlm_image_understander.py`：Doubao-Seed vision（流程图 / 接口图 / 图表 / 通用描述）
  - `flowchart_scoring_pipeline.py`：流程图 CV 分块（HaiCi 已通过 `flowchart_scoring_service.py` 封装）

### 1.2 范围内

| 项 | 说明 |
|----|------|
| 输入 | 知识库上传、多模态队列中的 **凡含图文档**：DOCX、PDF、**XLS/XLSX**、PPT、独立图片等 |
| 输出 | 标准 **Markdown + TXT**（`output/mm_exports` 或 `output/kb_assets/{doc_id}/`），含可点击/可 fetch 的图片链接与 OCR/VLM 回插正文 |
| 图片 | 全部内嵌/页内图必须：落盘 → 链接占位 → 标记 ID → 类型识别 → 分路由 → 回插 |
| 分块 | 标准化 MD 再交给 `kb_chunk_service`（见 `SPEC-AI问答Agent.md`） |

### 1.3 范围外（本期 SPEC 不强制）

- 纯 txt/md 无图文档（沿用现有 `read_document_text`）
- 视频/音频转写（已有 DocumentProcessor 能力，不在本 SPEC 扩展）
- Milvus 多库路由、Agent 任务拆解

---

## 2. 标准化产物定义

入库前每份 DOCX/PDF 必须生成如下**最小产物集**：

| 产物 | 路径约定 | 用途 |
|------|----------|------|
| `normalized.md` | `output/kb_assets/{tenant}/{doc_id}/normalized.md` | RAG 分块主文本 |
| `normalized.txt` | 同上 `.txt` | 检索/调试纯文本 |
| `images/` | `.../images/img_{seq:04d}.{ext}` | 抽出的图片实体 |
| `manifest.json` | 同目录 | 图片元数据、占位符、类型、处理结果摘要 |
| `flowchart/`（条件） | `.../flowchart/{img_id}/` | 流程图管道产物（report、overlay 等） |

**manifest.json 单图条目（示意）**：

```json
{
  "image_id": "img_0003",
  "source_format": "docx",
  "ordinal_in_doc": 3,
  "file_name": "img_0003.png",
  "public_url": "/output/kb_assets/1/42/images/img_0003.png",
  "placeholder": "<!-- IMG:img_0003 -->",
  "markdown_link": "![图3-售后菜单]( /output/kb_assets/1/42/images/img_0003.png )",
  "image_type": "ui_menu",
  "vlm_type_confidence": 0.91,
  "ocr_text": "...",
  "vlm_description": "...",
  "pipeline": "vlm_describe_only",
  "flowchart_report": null
}
```

---

## 3. 图片处理总则（DOCX / PDF 强制）

**硬性要求（违反则视为入库失败或 `status=failed`）：**

1. **必须抽取**：文档内每一张可见图片保存为独立文件，禁止仅在 MD 中写「见原 Word」而不落盘。
2. **必须打链接**：在 `normalized.md` 对应位置插入 **Markdown 图片语法**，`src` 为**可解析的 HTTP 路径**（见 章节 6）。
3. **必须打标记**：每张图在 MD 中紧邻链接处插入 **HTML 注释占位符** `<!-- IMG:{image_id} -->`，供 OCR/VLM 完成后**原位回插**扩展段落（不破坏链接）。
4. **必须分类**：每张图经 VLM **类型识别** 后走路由（章节 7）；禁止未分类直接入库。
5. **必须可验证**：提供 `GET /api/v1/knowledge/documents/{id}/assets` 或静态 `/output/...` 访问，前端/ curl 可 200 打开图片链接。

---

## 4. DOCX 解析策略

### 4.1 优先级（Owner 已口头确认方向）

| 优先级 | 路径 | 条件 |
|--------|------|------|
| **P0 默认** | `python-docx` + ZIP 内嵌图抽取 + **本地 OCR** | 结构清晰、内嵌图可枚举 |
| **P1 降级** | `mineru_processor._process_word` | python-docx 失败、复杂排版、高版本 OOXML 特性 |
| **P2 兜底** | DocumentProcessor DOCXParser（仅文本） | 前两者均失败；须 `error` 可见，不得静默冒充完整解析 |

### 4.2 P0 流程（目标实现）

```text
DOCX
 → 解析 body 顺序（段落 / 表格 / 内嵌图）
 → 每遇内嵌图：写出 images/img_N.ext
 → MD 中写入：<!-- IMG:img_N --> + ![alt](public_url)
 → 本地 OCR（pytesseract / MinerU._local_ocr_fallback，与本系统一致）
 → VLM 分类 + 分路由（章节 7）
 → 回插 OCR/VLM/流程图文本块至占位符下方
 → normalized.md / manifest.json
```

### 4.3 与 MinerU 的关系

- **OCR 引擎**：百度 OCR **默认开启**（`BAIDU_OCR_ENABLED=true`，须配置 `BAIDU_OCR_*`）；本地 pytesseract 为兜底。
- **MinerU DOCX**：高版本/复杂 docx **不作为默认**，仅 P1 显式降级并打日志 `pipeline=mineru_docx_fallback`。

---

## 5. PDF 解析策略

| 优先级 | 路径 | 适用 |
|--------|------|------|
| **P0** | MinerU PDF pipeline（`process_pdf`） | 扫描件、复杂版式、图文混排 |
| **P1** | PyMuPDF 文本 + 页图 OCR 兜底 | 纯文本 PDF、MinerU 不可用 |
| **P2** | 页级 rasterize + OCR | 整页长图/扫描页 |

PDF 内 `images/` 目录与 MD 链接规则 **同 DOCX**（章节 6）。MinerU 产出的 `![](images/xxx.png)` 须 **重写为** HaiCi 统一 `public_url`（禁止相对路径直接入库而不映射）。

---

## 6. 图片链接与占位标记规范

### 6.1 URL 规则

| 场景 | public_url 形式 | 要求 |
|------|-----------------|------|
| 后端静态托管（**采纳**） | `/output/kb_assets/{tenant}/{doc_id}/images/{file}` | FastAPI `/output` 挂载；**回答界面可直接渲染** |
| 前端同源访问 | 浏览器 fetch `/output/...` 与 API 同源即可 | 不要求 CDN；后续可扩展 |
| 禁止 | `file://`、`C:\...`、仅 `{relative}` 无映射 | 一律拒绝入库或 rewrite |

实现参考：`flowchart_scoring_service.abs_path_to_output_url()`。

### 6.2 占位标记

```markdown
<!-- IMG:img_0003 -->
![图3-系统设置-菜单截图](/output/kb_assets/1/42/images/img_0003.png)

<!-- IMG:img_0003:BODY -->
（OCR/VLM/流程图结构化结果回插于此，可多次追加段落）
```

- `IMG:{id}`：锚点，解析器保留顺序。
- `IMG:{id}:BODY`：可选，专门承载回插正文；若无则回插在链接下一行。

### 6.3 alt 文本规范

`![{序号}-{简述}](url)`，简述来自 VLM 分类后的短标题（如「售后政策-菜单页」）。

---

## 7. VLM 图片类型识别与分路由处理

### 7.1 类型枚举（VLM 首判）

| `image_type` | 含义 | 处理策略 |
|--------------|------|----------|
| `ui_menu` | 文档内的**软件界面/菜单截图**（与 HaiCi 产品 Casbin 菜单无关） | **纯描述**：哪个系统/哪个菜单或模块、可见元素；**结合**文档上下文，禁止编造 |
| `ui_design` | 装饰性 UI、banner、图标墙、营销图 | **纯描述**：是什么、与什么功能/模块相关；不 OCR 逐字除非 OCR 已高置信 |
| `flowchart` | 流程图、泳道图、架构连线图 | **走 章节 8 专用管道**；RAG 正文以结构化结果（块列表/Mermaid 摘要）为主 |
| `chart` | 统计图、表格截图 | VLM `understand_chart` + OCR 互补 |
| `api_diagram` | 接口/时序图 | VLM `understand_api_diagram` |
| `photo` | 照片/实物 | 通用 `understand_image` 摘要 |
| `unknown` | 无法判断 | 通用描述 + OCR；日志 `degraded=true` |

### 7.2 VLM 接入

- 复用 `vlm_image_understander.py` 或 HaiCi `llm_gateway` / `ARK_API_KEY` —— **哪个可用用哪个**。
- **第一步**：新增 `classify_image_type(image_path, doc_context)` → JSON `{ "type", "confidence", "title_hint" }`（真实 VLM 调用，禁止规则假判）。
- **第二步**：按上表路由；菜单/设计类 prompt 必须注入 **doc_context**（当前章节标题 + 前后 500 字）。

### 7.3 菜单页 / 设计图描述模板（写入 RAG）

**菜单页示例结构**：

```markdown
### [图片理解] 系统设置 - 账户安全菜单
- 所属模块：个人中心 / 账户安全
- 可见元素：修改密码、绑定手机、登录设备管理
- 上下文关联：上文说明「可在设置中管理账户安全」
- 来源图：![...](url)
```

**设计图**：仅保留「是什么 + 关联功能」，不做逐步操作指南。

---

## 8. 流程图专用管道

### 8.1 现状

HaiCi 已封装：

- `backend/app/services/flowchart_scoring_service.py` → `src/agent/tools/flowchart_scoring_pipeline.py`
- 多模态页 `/api/v1/multimodal/flowchart/score` 可独立调用
- 产物：`flowchart_scoring_report.json`、overlay 图、`/output/flowchart_scoring_web/{job_id}/...`

### 8.2 入库集成要求

当 VLM 判定 `image_type=flowchart`：

1. 对该 **`images/img_N.ext`** 调用 `run_flowchart_score`（非单独人工点按钮）。
2. 将 **几何分块摘要 + 关键节点文本** 写入 `IMG:img_N:BODY`（可附 Mermaid 若管道产出）。
3. `manifest.json.flowchart_report` 指向 report 路径；overlay 可选写入 `public_url` 供前端预览。
4. **流程图 CV 失败**：**降级**为 VLM/ OCR 描述，打 `degraded=true`，**不阻断**入库。

---

## 9. OCR 回插与 RAG 分块衔接

```text
标准化 normalized.md
  → knowledge_processor.read_document_text（读 normalized 而非原始 docx/pdf）
  → kb_chunk_service.split_to_documents(slice_method=用户选择)
  → Chroma 向量入库
```

- RAG chunk 写入 **图片描述 + 可选图片链接**（`![alt](/output/...)`）；以语义检索友好为准，链接主要用于回答界面渲染。
- 分块策略默认建议：`md_header`（结构化 MD）或 `dynamic_semantic`（长文档）；见 `SPEC-AI问答Agent.md`。
- chunk metadata 增加：`image_ids[]`、`normalization_manifest` 路径。

---

## 10. 模块映射与 API

### 10.1 新增/改造模块（实施 PLAN 用）

| 模块 | 职责 |
|------|------|
| `doc_normalizer.py`（新） | 统一 DOCX/PDF → normalized.md + manifest |
| `doc_image_pipeline.py`（新） | 抽图、URL 生成、占位、OCR、VLM 分类、回插 |
| `knowledge_processor.py` | 上传后先调 normalizer，再分块 |
| `document.py` | 多模态预览同样走 normalizer |
| `haici_output.py` | 增加 `kb_assets_dir(tenant, doc_id)` |
| `main.py` / `knowledge.py` | 静态资源校验 API、入库进度 SSE（可选） |

### 10.2 API（草案）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/knowledge/slice-methods` | 已有 |
| GET | `/api/v1/knowledge/documents/{id}/manifest` | 返回 manifest.json |
| GET | `/api/v1/knowledge/documents/{id}/normalized` | 返回 standardized md |
| POST | `/api/v1/knowledge/upload` | 增加 `normalize=true`（默认 true for pdf/docx） |

---

## 11. 执行抉择与 WARNING

### 11.1 备选：图片 URL 托管

| 备选 | 说明 |
|------|------|
| A | 仅 `/output/kb_assets/...` 后端静态 |
| B | 前端 `public/` + 构建期同步 |
| C | 对象存储 CDN |

**采纳（草案）**：**A** — 与现有 `flowchart_scoring_service`、`/output` 挂载一致，实现成本最低。

**顾虑**：B 需双写；C 超 PRD MVP 范围。

### 11.2 备选：DOCX 默认解析器

| 备选 | 说明 |
|------|------|
| A | python-docx + 本地 OCR（Owner 要求优先） |
| B | MinerU `_process_word` 默认 |
| C | 仅 DocumentProcessor 文本 |

**采纳（草案）**：**A**，B/C 为显式降级链。

### 11.3 WARNING

1. **链接失效**：若未挂载 `/output` 或路径未 `resolve` 到 `get_output_dir()` 下，前端图片全部 404 — 入库前须 `assert_public_url_reachable`。
2. **VLM 成本**：整本 PDF 多图会多次调用 ARK；需 `.env` 开关 `VLM_IMAGE_ENABLED` 与单文档上限 `MAX_IMAGES_PER_DOC`。
3. **流程图耗时**：CV 管道秒级~分钟级；知识库上传应异步 `status=processing`（已有字段）。
4. **假 Agent 违规**：类型识别、描述生成必须真实 VLM；失败写 `degraded` 而非模板冒充。
5. **百度 OCR**：默认开启；密钥不得写入日志。

---

## 12. 验收清单

- [ ] DOCX/XLS/PDF 含图：内嵌图落盘，`manifest.json` 条数一致
- [ ] 列表展示：**文件类型、大小、图片数、VLM 上限**（`GET /knowledge` 扩展字段）
- [ ] MD 中每张图：`<!-- IMG:* -->` + 描述 + 可访问 `/output/...` 链接
- [ ] 菜单截图：VLM 纯描述 + 文档上下文，不编造
- [ ] 流程图：优先 CV 管道；失败 degraded 降级
- [ ] 超 30 张图：`truncated=true` 可见
- [ ] 扫描 PDF：MinerU 失败时 PyMuPDF+OCR 兜底

---

## 13. Owner 裁决记录（2026-06-12）

| 编号 | 裁决 |
|------|------|
| Q1 | **凡含图文档均纳入**，含 DOCX、PDF、**XLS/XLSX** 等，不仅 PRD 列举的 txt/md/pdf |
| Q2 | **百度 OCR 默认开启**，须配置密钥 |
| Q3 | VLM 上限 **30**，UI **展示**；导入后展示类型/大小/含图数 |
| Q4 | RAG：**图片描述 + 图片本身**进 chunk；链接可进可不进，以实现为准 |
| Q5 | `ui_menu` 指**文档内软件截图**，与产品 Casbin 菜单 **无关** |
| Q6 | 专用目录 **`output/kb_assets/{tenant}/{doc_id}/`** |
| Q7 | MinerU 失败允许 **PyMuPDF + OCR** 兜底 |
| 附加 | 流程图 CV 失败 → **降级**，不阻断；VLM **哪个可用用哪个**；图片 URL 以 `/output` 可渲染为准 |

---

## 待二次审阅（由 Owner 回填）

- [x] Q1～Q7 已裁决（见 章节 13）
- [x] DOCX P0 = python-docx + 百度 OCR + 本地兜底
- [x] 流程图 CV 失败 = 降级入库
- [ ] 百度 OCR 密钥已在 `.env` 配置并验通
- [ ] 实际上传含图 DOCX/PDF/XLS 回归通过
- [ ] 接口冻结责任人：
- [ ] 上线窗口：
