"""
Prompt 段式指令模块：集中管理所有 LLM 指令段
=====================================================

本模块将散落在各文件中的硬编码 prompt 字符串提取为可复用的「段式变量」。
每段变量附带说明：是什么、起到什么作用、在哪些场景使用。
最终 prompt 由变量拼接而成，保证全链路一致性。

命名规范：
  ROLE_*    — 身份定义（你是谁）
  CNSTR_*   — 行为约束（你必须/不能做什么）
  RULE_*    — 执行规则（你怎么做）
  FMT_*     — 输出格式（你输出什么格式）
  TEMPL_*   — 模板片段（带占位符的拼接模板）

使用方式：
  from app.services.prompt_segments import build_rag_system_prompt
  system = build_rag_system_prompt(cite_instr="...引用格式...")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


# ============================================================
# 段式指令元数据容器
# ============================================================

@dataclass(frozen=True)
class PromptSegment:
    """一段完整的语义指令，附带说明文档。"""
    key: str        # 变量名标识
    text: str       # 指令原文
    desc: str       # 是什么（一句话描述）
    purpose: str    # 起到什么作用（为什么需要这段指令）


# ============================================================
# 一、身份定义 (ROLE_*)
# ============================================================
# 说明：定义 LLM 在特定场景下的身份/角色。
# 作用：角色锚定 - 让 LLM 知道"我是谁"，限缩行为边界，激活对应领域的知识模式。
# ============================================================

ROLE_ENTERPRISE_CS = PromptSegment(
    key="ROLE_ENTERPRISE_CS",
    text="你是企业智能客服。",
    desc="企业客服基础身份",
    purpose="锚定 RAG 回答场景的客服角色，限缩 LLM 行为在客服领域内",
)

ROLE_HAICI_ASSISTANT = PromptSegment(
    key="ROLE_HAICI_ASSISTANT",
    text="你是 HaiCi 企业智能客服助手。",
    desc="海驰品牌客服身份（闲聊场景）",
    purpose="闲聊场景的品牌客服身份，比 ROLE_ENTERPRISE_CS 更具体，用于自我介绍场景",
)

ROLE_QUERY_PREPROCESSOR = PromptSegment(
    key="ROLE_QUERY_PREPROCESSOR",
    text="你是企业智能客服的查询预处理模块。",
    desc="查询预处理模块身份",
    purpose="限定 LLM 只做查询改写与意图识别，不直接回答用户问题",
)

ROLE_KNOWLEDGE_REVIEWER = PromptSegment(
    key="ROLE_KNOWLEDGE_REVIEWER",
    text="你是企业知识库审核助手。",
    desc="知识库审核身份（防稀释场景）",
    purpose="用于防稀释机制中，让 LLM 以审核视角整理多文档检索结果，而非直接回答",
)

ROLE_INTENT_CORRECTOR = PromptSegment(
    key="ROLE_INTENT_CORRECTOR",
    text="你是智能客服意图纠偏助手。",
    desc="意图纠偏助手身份",
    purpose="限定 LLM 只做意图推测与纠偏，不参与实际对话回答",
)


# ============================================================
# 二、行为约束 (CNSTR_*)
# ============================================================
# 说明：定义 LLM 必须遵守的硬性约束。
# 作用：安全边界 - 防止幻觉、编造、越权回答，保证回答的可信度。
# ============================================================

CNSTR_ONLY_FROM_KB = PromptSegment(
    key="CNSTR_ONLY_FROM_KB",
    text="只能依据知识库片段回答，不得编造。",
    desc="知识库隔离约束",
    purpose="核心安全规则：防止 LLM 使用训练数据中的知识替代知识库，杜绝幻觉来源",
)

CNSTR_STATE_UNCERTAINTY = PromptSegment(
    key="CNSTR_STATE_UNCERTAINTY",
    text="若资料不足请明确说明无法回答。",
    desc="不确定性声明约束",
    purpose="防止 LLM 在知识不足时强行编造，要求明确告知用户不可答并引导换问法",
)

CNSTR_NO_SPECULATION = PromptSegment(
    key="CNSTR_NO_SPECULATION",
    text="不要编造具体产品参数或政策细节；不确定时建议用户换种问法或联系人工客服。",
    desc="闲聊防幻觉约束",
    purpose="闲聊场景的安全网：避免闲聊时随口编造不存在的产品参数或售后政策",
)

CNSTR_CONCISE_CHINESE = PromptSegment(
    key="CNSTR_CONCISE_CHINESE",
    text="用简洁中文回答用户。",
    desc="回答语言与风格约束",
    purpose="统一回答输出为简体中文，保持简洁不啰嗦",
)

CNSTR_SELF_INTRO_SCOPE = PromptSegment(
    key="CNSTR_SELF_INTRO_SCOPE",
    text="可介绍自己的身份与能力（产品咨询、售后政策、知识库问答）。",
    desc="自我介绍范围限定",
    purpose="闲聊场景允许自我介绍，但框定能力范围，防止夸大或编造",
)

CNSTR_JSON_ONLY = PromptSegment(
    key="CNSTR_JSON_ONLY",
    text="只输出 JSON，不要解释。",
    desc="纯 JSON 输出约束",
    purpose="预处理/分类等结构化输出场景：防止 JSON 前后混入解释文字导致解析失败",
)

CNSTR_NO_FABRICATE_MENU = PromptSegment(
    key="CNSTR_NO_FABRICATE_MENU",
    text="不得编造画面中未出现的菜单项、按钮或交互逻辑。",
    desc="VLM 图片描述：禁止编造 UI 元素",
    purpose="防止 VLM 在描述菜单截图时编造不存在的 UI 组件，污染知识库",
)


# ============================================================
# 三、预处理指令段 (PREPROC_*)
# ============================================================
# 说明：查询预处理模块（agent_pipeline）的指令段。
# 作用：指导 LLM 完成意图识别、查询改写、关键词提取、术语映射。
# ============================================================

PREPROC_TASK_DESC = PromptSegment(
    key="PREPROC_TASK_DESC",
    text="根据用户问题输出 JSON，字段：",
    desc="预处理任务总述",
    purpose="一句话告知预处理 LLM 它的输入（用户问题）和输出（JSON），锚定任务范围",
)

PREPROC_INTENT_FIELD = PromptSegment(
    key="PREPROC_INTENT_FIELD",
    text="intent 取值 product_consult|after_sale|chitchat|complaint；",
    desc="意图字段定义",
    purpose="定义 intent 字段的合法枚举值，确保 LLM 输出的意图能被下游路由识别",
)

PREPROC_REWRITE_FIELD = PromptSegment(
    key="PREPROC_REWRITE_FIELD",
    text="rewritten_query 为利于知识库检索的改写问句；",
    desc="改写问句字段定义",
    purpose="指导 LLM 输出语义更完整的改写问句，提升向量检索召回率",
)

PREPROC_KEYWORDS_FIELD = PromptSegment(
    key="PREPROC_KEYWORDS_FIELD",
    text="query_keywords 为原问实体/关键词数组；",
    desc="关键词字段定义",
    purpose="从原问中提取实体/关键词，用于术语映射和 BM25 关键字检索增强",
)

PREPROC_TERMS_FIELD = PromptSegment(
    key="PREPROC_TERMS_FIELD",
    text="retrieval_terms 为映射后的内部业务检索词数组。",
    desc="内部检索词字段定义",
    purpose="要求 LLM 将用户口语映射为内部业务术语，提升专业名词检索命中率",
)


# ============================================================
# 四、RAG 回答指令段 (RAG_*)
# ============================================================
# 说明：构建 RAG 回答 system prompt 的指令段。
# 作用：控制 LLM 在知识问答场景下的回答行为、插图选择、引用格式。
# ============================================================

RAG_CORE_RULES = PromptSegment(
    key="RAG_CORE_RULES",
    text=(
        "你是企业智能客服。只能依据知识库片段回答，不得编造。\n"
        "若资料不足请明确说明无法回答。"
    ),
    desc="RAG 回答核心约束（身份+知识隔离+不确定性声明）",
    purpose="RAG 回答的底线规则组合，是所有 RAG 链路共用的基础约束",
)

RAG_PICTURE_INLINE = PromptSegment(
    key="RAG_PICTURE_INLINE",
    text=(
        "回答中插图须紧扣用户问题：仅插入与问题相关的 picture 块（仅 url，不带 description），"
        "并用结合问题的简短说明点明图中关键位置（可引用 description 中的区块/标记编号）。"
    ),
    desc="RAG 插图关联规则",
    purpose="防止 LLM 随意插入无关图片；要求图文对齐，每张图要有解释其为何相关的文字说明",
)


# ============================================================
# 五、引用格式指令段 (CITE_*)
# ============================================================
# 说明：控制 LLM 输出的引用标注格式（句末编号、文献切片明细、注释逻辑链路）。
# 作用：让回答可溯源、可验证，同时为前端引用上标渲染提供结构化数据。
# ============================================================

CITE_HEADER = PromptSegment(
    key="CITE_HEADER",
    text="【回答格式 · 按句引用 + 逻辑注释（必须严格遵守）】",
    desc="引用格式总标题",
    purpose="告知 LLM 整个回答需要遵循引用格式规范，起醒目锚定作用",
)

CITE_BODY_RULES = PromptSegment(
    key="CITE_BODY_RULES",
    text=(
        "一、正文（按句为单位）\n"
        "  · 每一句依据知识库写出的论断，句末必须标注引用编号，格式为阿拉伯数字 1、2、3…（不用上标）。\n"
        "  · 同一句话可引用多个切片则写 1,2；编号对应下方预检索文献 [n]，禁止无编号的知识库论断。"
    ),
    desc="正文句末引用编号规则",
    purpose="逐句溯源：确保每句来自知识库的论断都有编号，方便人工核对和前端渲染引用上标",
)

CITE_SLICE_SECTION = PromptSegment(
    key="CITE_SLICE_SECTION",
    text=(
        "二、正文结束后依次输出两节（标题固定，不可省略）：\n"
        "  ## 文献切片明细\n"
        "  逐条列出本回答用到的切片（按 [n] 编号），每条须含：\n"
        "    - 切片[n]：所属父文档《父文档名》（父文档路径）\n"
        "    - 切片全文：（完整粘贴该切片正文，不可截断）\n"
        "    - 父文档全文：（写「见路径 xxx，前端可点击查看」）\n"
        "  ## 注释\n"
        "  按正文引用编号逐条写「处逻辑链路」（与正文句末编号一一对应，不可合并）：\n"
        "    1 处逻辑链路：摘录切片【1】原文「…关键句…」；因原文…，故正文第1句写成…。置信度：100\n"
        "  · 置信度为 0–100 整数。"
    ),
    desc="文献切片明细与注释节要求",
    purpose="强制 LLM 在回答末尾输出切片明细和逻辑注释，为前端提供结构化文献展示和可解释性",
)

CITE_NO_FABRICATION = PromptSegment(
    key="CITE_NO_FABRICATION",
    text="三、禁止编造未出现在切片中的事实。",
    desc="引用防编造约束",
    purpose="最后的兜底规则：引用格式的底线，确保切片中不存在的事实不会被写进回答",
)


# ============================================================
# 六、插图规则指令段 (PIC_*)
# ============================================================
# 说明：控制 LLM 如何处理 picture 块。
# 作用：防止 LLM 直接复制 description 原文、控制插图插入条件、要求区块标注逐条说明。
# ============================================================

PIC_SECTION_HEADER = PromptSegment(
    key="PIC_SECTION_HEADER",
    text="四、含图切片与正文插图（picture 块 · 必须遵守）",
    desc="插图规则节标题",
    purpose="醒目告知 LLM 下一段是关于 picture 块的特殊规则",
)

PIC_NO_RAW_DESCRIPTION = PromptSegment(
    key="PIC_NO_RAW_DESCRIPTION",
    text="  · 切片中的 {picture_id:…; url:…; description:…} 仅供你理解画面，禁止将 description 原文直接输出。",
    desc="禁止直接输出 description 原文",
    purpose="防止 LLM 偷懒把 description 字段直接粘贴到回答中（description 是给 LLM 理解的元数据，不应暴露给用户）",
)

PIC_INSERT_CONDITION = PromptSegment(
    key="PIC_INSERT_CONDITION",
    text=(
        "  · 仅当某张图与用户问题**直接相关**时，才插入插图，格式必须严格为：\n"
        "    {picture_id:图N-xxx; url:切片中的绝对路径;}\n"
        "    （不要带 description 字段，也不要在 url 后添加任何其他字段）"
    ),
    desc="插图插入条件与格式",
    purpose="控制插图仅在相关时出现，且格式纯净（仅 pic_id + url），防止 LLM 在 picture 块中添加多余字段污染前端解析",
)

PIC_ANNOTATION_MUST_LIST = PromptSegment(
    key="PIC_ANNOTATION_MUST_LIST",
    text=(
        "  · ★ 关键规则 ★ 图片上的红框/数字标记（如 ①②③ 或 区块(1)(2)(3)），"
        "你必须在正文中用文字逐条说明每个标记的含义：\n"
        "    「区块(1)：输入用户账号及密码」\n"
        "    「区块(2)：点击登录按钮进入系统」\n"
        "    「区块(3)：可修改密码」\n"
        "    这些区块说明是文档核心内容，必须保留，不得省略！"
    ),
    desc="图片标记逐条说明规则",
    purpose="强制 LLM 逐条解释图片中的红框/数字标记，这是文档核心内容，省略将导致关键操作步骤丢失",
)

PIC_NO_VAGUE_REF = PromptSegment(
    key="PIC_NO_VAGUE_REF",
    text="  · 无关图片一律不插；正文禁止「见下图」「如上图所示」等空泛表述。",
    desc="禁止空泛图片引用",
    purpose="防止 LLM 用「见下图」等模糊说法搪塞，要求每张插图必须有结合问题的具体文字说明",
)


# ============================================================
# 七、防稀释规则指令段 (ANTI_DILUTION_*)
# ============================================================
# 说明：大规模上下文防稀释机制的专用指令段。
# 作用：在多文档检索结果中防止注意力稀释，确保关键规则不被遗漏。
# ============================================================

ANTI_DILUTION_CITE_HEADER = PromptSegment(
    key="ANTI_DILUTION_CITE_HEADER",
    text="【防稀释引用规则】",
    desc="防稀释引用规则标题",
    purpose="醒目告知 LLM 引用规则来自防稀释上下文，与常规 RAG 引用区分",
)

ANTI_DILUTION_PRIORITY_RULES = PromptSegment(
    key="ANTI_DILUTION_PRIORITY_RULES",
    text=(
        "1. 优先引用上述「优先规则」列表中的条款\n"
        "2. 若多个文档存在冲突规则，明确指出差异并建议以最新/最权威的文档为准\n"
        "3. 每一步推断必须对应一个具体的切片编号\n"
        "4. 不要合并或混淆来自不同文档的规则"
    ),
    desc="防稀释场景引用优先级规则",
    purpose="在多文档场景中，引导 LLM 优先关注 LLM 提取的「优先规则」，遇到冲突时透明化差异，防止把不同文档的规则混为一谈",
)


# ============================================================
# 八、追问建议指令段 (FOLLOWUP_*)
# ============================================================
# 说明：生成追问建议的 prompt 段。
# 作用：引导 LLM 生成简短中文追问选项，提升用户交互体验。
# ============================================================

FOLLOWUP_TASK = PromptSegment(
    key="FOLLOWUP_TASK",
    text="根据用户问题与 AI 回答，生成 2～3 个简短中文追问建议，JSON 数组格式，每项不超过 20 字。",
    desc="追问建议生成任务描述",
    purpose="告知 LLM 如何根据问答上下文生成追问选项，限制数量（2-3个）和长度（20字），控制前端展示效果",
)


# ============================================================
# 九、意图纠偏指令段 (INTENT_FIX_*)
# ============================================================
# 说明：意图纠偏模块的 prompt 段。
# 作用：当系统意图识别有误时，由 LLM 推测更正确的意图。
# ============================================================

INTENT_FIX_TASK = PromptSegment(
    key="INTENT_FIX_TASK",
    text=(
        "系统误判了用户意图，请根据用户提问与 AI 回答，"
        "推测用户更可能属于哪种意图。只输出 JSON 数组，最多 2 项，每项字段：\n"
        "code（必须为 product_consult|after_sale|chitchat|complaint 之一或 unknown）、"
        "label（中文概括，不超过 16 字）、summary（一句话理由，不超过 40 字）。"
    ),
    desc="意图纠偏任务与输出格式",
    purpose="告知 LLM 纠偏任务的背景（系统误判）、输出格式（JSON数组）、字段约束（code枚举/字数限制）",
)


# ============================================================
# 十、防稀释 LLM 摘要指令段 (ANTI_SUMMARY_*)
# ============================================================
# 说明：防稀释模块调用 LLM 生成分层摘要时的 prompt 段。
# 作用：让 LLM 以审核视角整理多文档检索结果，生成结构化摘要 + 优先规则 + 置信度。
# ============================================================

ANTI_SUMMARY_TASK = PromptSegment(
    key="ANTI_SUMMARY_TASK",
    text="请阅读以下从多个文档检索到的信息，生成一个结构化摘要供客服使用。",
    desc="防稀释摘要任务描述",
    purpose="告知 LLM 它的任务是整合多文档信息生成摘要，输出目标是给客服使用（非直接给用户）",
)

ANTI_SUMMARY_OUTPUT_FORMAT = PromptSegment(
    key="ANTI_SUMMARY_OUTPUT_FORMAT",
    text=(
        "输出要求（JSON 格式）：\n"
        '{\n  "summary": "200字以内的综合摘要",\n'
        '  "priority_rules": ["规则1", "规则2"],\n'
        '  "confidence": 80,\n'
        '  "needs_clarification": false\n'
        "}"
    ),
    desc="防稀释摘要 JSON 输出格式定义",
    purpose="约束 LLM 输出标准化 JSON，包含摘要、优先规则、置信度、是否需要澄清四个维度",
)


# ============================================================
# 十一、文档结构化处理指令段 (DOC_*)
# ============================================================
# 说明：文档入库结构化处理（摘要/元数据/结构检查/语义分段）的 prompt 段。
# 作用：指导 LLM 完成文档摘要、结构检查、语义分段等入库预处理任务。
# ============================================================

ROLE_DOC_SUMMARY = PromptSegment(
    key="ROLE_DOC_SUMMARY",
    text="你是文档摘要整理助手。",
    desc="文档摘要助手身份（结构化处理）",
    purpose="知识库入库时，让 LLM 以摘要助手身份提炼文档主题，锚定摘要任务范围",
)

DOC_SUMMARY_INSTR = PromptSegment(
    key="DOC_SUMMARY_INSTR",
    text=(
        "请用200字以内的精简中文描述这份文档主要讲了哪些内容。\n"
        "注意：摘要描述的是'文档涉及了哪些方面/话题'，而不是列出具体数据或结论。\n"
        "例如：'本文档介绍了公司产品的功能特性、定价策略以及售后服务政策，并对比了竞品方案。'\n"
        "不要写：'该系统有35个功能，价格为999元。'\n\n"
        "只输出摘要文本，不要JSON、不要Markdown格式。"
    ),
    desc="文档摘要任务指令",
    purpose="约束 LLM 生成主题级摘要（非数据罗列），防止泄露不该出现在摘要中的具体数字/结论",
)

ROLE_DOC_STRUCTURE = PromptSegment(
    key="ROLE_DOC_STRUCTURE",
    text="你是文档结构检查助手。",
    desc="文档结构检查助手身份（结构化处理）",
    purpose="知识库入库时，让 LLM 判断文档是否有清晰结构，用于后续分段策略选择",
)

DOC_STRUCTURE_INSTR = PromptSegment(
    key="DOC_STRUCTURE_INSTR",
    text=(
        "分析以下文档内容，判断其是否已有清晰的结构（标题层级、段落分明、逻辑有序），"
        "还是属于杂乱无章的内容（如聊天记录、碎片笔记、无格式文本）。\n"
        "输出JSON：{\"has_structure\": true/false, \"structure_type\": \"md_headings/pure_paragraphs/chat_logs/mixed\", "
        "\"confidence\": 0-100, \"suggestion\": \"建议处理方式的简短说明\"}"
    ),
    desc="文档结构检查任务指令",
    purpose="指导 LLM 评估文档结构化程度并输出标准化 JSON，决定后续走 md_header 分段还是 AI 语义分段",
)

ROLE_SEMANTIC_SPLIT = PromptSegment(
    key="ROLE_SEMANTIC_SPLIT",
    text="你是文档语义分段助手。",
    desc="语义分段助手身份（知识库入库）",
    purpose="知识库入库时，让 LLM 以分段助手身份将长文档切分为语义自洽的独立片段",
)

DOC_SEMANTIC_SPLIT_INSTR = PromptSegment(
    key="DOC_SEMANTIC_SPLIT_INSTR",
    text="根据全文主题与逻辑，将文档切分为若干完整语义段。每段应可独立检索、语义自洽，禁止截断句子。",
    desc="语义分段任务指令",
    purpose="指导 LLM 按语义边界切分文档，确保每段可独立用于向量检索，不与前后文硬依赖",
)


# ============================================================
# 十二、组合函数：将段式变量拼接为完整 prompt
# ============================================================

def build_preprocess_prompt(history_text: str, query: str) -> str:
    """组装查询预处理 prompt（agent_pipeline 用）。

    使用段式变量拼接，替代原先两处硬编码重复字符串。
    """
    segments = [
        ROLE_QUERY_PREPROCESSOR.text,
        PREPROC_TASK_DESC.text,
        PREPROC_INTENT_FIELD.text,
        PREPROC_REWRITE_FIELD.text,
        PREPROC_KEYWORDS_FIELD.text,
        PREPROC_TERMS_FIELD.text,
        CNSTR_JSON_ONLY.text,
    ]
    header = "".join(segments)
    return f"{header}\n历史:\n{history_text or '无'}\n\n问题:{query}"


def build_rag_system_prompt(cite_instruction: str = "", *, include_picture_rule: bool = True) -> str:
    """组装 RAG system prompt（rag.py / context_anti_dilution.py 共用）。

    Args:
        cite_instruction: 引用格式指令（来自 _citation_format_block 或防稀释引用规则）
        include_picture_rule: 是否内联插图规则（rag.py 标准路径需要，防稀释路径可选）
    """
    parts = [RAG_CORE_RULES.text]
    if include_picture_rule:
        parts.append(RAG_PICTURE_INLINE.text)
    parts.append("")
    if cite_instruction:
        parts.append(cite_instruction)
    return "\n".join(parts)


def build_chitchat_system_prompt() -> str:
    """组装闲聊 system prompt（chat.py CHITCHAT_SYSTEM）。"""
    segments = [
        ROLE_HAICI_ASSISTANT.text,
        CNSTR_CONCISE_CHINESE.text,
        CNSTR_SELF_INTRO_SCOPE.text,
        CNSTR_NO_SPECULATION.text,
    ]
    return "".join(segments)


def build_citation_format_block() -> str:
    """组装完整引用格式指令块（rag_slice_utils 用）。"""
    return "\n".join([
        CITE_HEADER.text,
        CITE_BODY_RULES.text,
        CITE_SLICE_SECTION.text,
        CITE_NO_FABRICATION.text,
        build_picture_answer_rules(),
    ])


def build_picture_answer_rules() -> str:
    """组装插图规则指令块（rag_slice_utils、context_anti_dilution 共用）。"""
    return "\n".join([
        PIC_SECTION_HEADER.text,
        PIC_NO_RAW_DESCRIPTION.text,
        PIC_INSERT_CONDITION.text,
        PIC_ANNOTATION_MUST_LIST.text,
        PIC_NO_VAGUE_REF.text,
    ])


def build_anti_dilution_cite_instruction() -> str:
    """组装防稀释引用规则块（含插图规则）。"""
    return "\n".join([
        ANTI_DILUTION_CITE_HEADER.text,
        ANTI_DILUTION_PRIORITY_RULES.text,
        build_picture_answer_rules(),
    ])


def build_follow_up_prompt(intent: str, question: str, answer: str) -> str:
    """组装追问建议 prompt。"""
    return (
        f"{FOLLOWUP_TASK.text}"
        f"{CNSTR_JSON_ONLY.text}\n"
        f"意图:{intent}\n问题:{question[:200]}\n回答:{answer[:400]}"
    )


def build_intent_suggest_prompt(
    question: str, answer: str, detected_intent: str, detected_label: str, enum_text: str
) -> str:
    """组装意图纠偏 prompt。"""
    return (
        f"{ROLE_INTENT_CORRECTOR.text}"
        f"{INTENT_FIX_TASK.text}\n"
        f"标准意图：{enum_text}\n"
        f"系统识别：{detected_label}（{detected_intent}）\n"
        f"用户提问：{question[:300]}\n"
        f"AI 回答：{answer[:400]}\n"
        f"{CNSTR_JSON_ONLY.text}"
    )


def build_anti_dilution_summary_prompt(query: str, group_descriptions: list[str]) -> str:
    """组装防稀释 LLM 摘要 prompt。"""
    return (
        f"{ROLE_KNOWLEDGE_REVIEWER.text}"
        f"{ANTI_SUMMARY_TASK.text}\n\n"
        f"用户问题：{query}\n\n"
        "检索到的文档与规则：\n"
        + "\n\n".join(group_descriptions)
        + f"\n\n{ANTI_SUMMARY_OUTPUT_FORMAT.text}"
    )


def build_rag_user_prompt(intent: str, history_text: str, rag_context: str, query: str) -> str:
    """组装 RAG 回答的 user prompt（rag.py / context_anti_dilution.py 共用）。"""
    return f"意图:{intent}\n历史:\n{history_text or '无'}\n\n{rag_context}\n\n问题:{query}"


def build_doc_summary_default_prompt() -> str:
    """组装文档摘要默认 prompt（structured_processing 用，用户可覆盖）。"""
    return f"{ROLE_DOC_SUMMARY.text}{DOC_SUMMARY_INSTR.text}"


def build_doc_structure_check_default_prompt() -> str:
    """组装文档结构检查默认 prompt（structured_processing 用，用户可覆盖）。"""
    return f"{ROLE_DOC_STRUCTURE.text}{DOC_STRUCTURE_INSTR.text}"


def build_semantic_split_prompt(max_segments: int = 24) -> str:
    """组装语义分段 system prompt（kb_chunk_service 用）。"""
    return (
        f"{ROLE_SEMANTIC_SPLIT.text}"
        f"{DOC_SEMANTIC_SPLIT_INSTR.text}"
        f"输出 JSON 数组，长度不超过 {max_segments}，每项格式 {{\"text\":\"段落全文\"}}。"
        f"{CNSTR_JSON_ONLY.text}"
    )


# ============================================================
# 十三、段式指令清单（供前端 AgentConfigPanel 查询）
# ============================================================

def list_all_segments() -> list[dict]:
    """返回所有段式指令清单，供前端展示与管理。"""
    all_segments = [
        ROLE_ENTERPRISE_CS, ROLE_HAICI_ASSISTANT, ROLE_QUERY_PREPROCESSOR,
        ROLE_KNOWLEDGE_REVIEWER, ROLE_INTENT_CORRECTOR,
        ROLE_DOC_SUMMARY, ROLE_DOC_STRUCTURE, ROLE_SEMANTIC_SPLIT,
        CNSTR_ONLY_FROM_KB, CNSTR_STATE_UNCERTAINTY, CNSTR_NO_SPECULATION,
        CNSTR_CONCISE_CHINESE, CNSTR_SELF_INTRO_SCOPE, CNSTR_JSON_ONLY,
        CNSTR_NO_FABRICATE_MENU,
        PREPROC_TASK_DESC, PREPROC_INTENT_FIELD, PREPROC_REWRITE_FIELD,
        PREPROC_KEYWORDS_FIELD, PREPROC_TERMS_FIELD,
        RAG_CORE_RULES, RAG_PICTURE_INLINE,
        CITE_HEADER, CITE_BODY_RULES, CITE_SLICE_SECTION, CITE_NO_FABRICATION,
        PIC_SECTION_HEADER, PIC_NO_RAW_DESCRIPTION, PIC_INSERT_CONDITION,
        PIC_ANNOTATION_MUST_LIST, PIC_NO_VAGUE_REF,
        ANTI_DILUTION_CITE_HEADER, ANTI_DILUTION_PRIORITY_RULES,
        FOLLOWUP_TASK,
        INTENT_FIX_TASK,
        ANTI_SUMMARY_TASK, ANTI_SUMMARY_OUTPUT_FORMAT,
        DOC_SUMMARY_INSTR, DOC_STRUCTURE_INSTR, DOC_SEMANTIC_SPLIT_INSTR,
    ]
    result: list[dict] = []
    for s in all_segments:
        result.append({
            "key": s.key,
            "text": s.text,
            "desc": s.desc,
            "purpose": s.purpose,
        })
    return result
