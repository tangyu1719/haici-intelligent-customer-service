"""Agent Prompt 注册表：对齐 web_rebuild Agent 配置（routing + AGENT.md 模板）。

加载优先级（高 → 低）：
1. backend/data/agent_config.json 中的 agent_prompts 覆盖
2. 上级 src/agent/config.json 的 agent_prompts
3. backend/data/agents/{agent_key}/AGENT.md 内置模板
4. 上级 src/agent/agents/{subdir}/AGENT.md（legacy 映射）
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED_AGENTS_DIR = _BACKEND_ROOT / "data" / "agents"
_LOCAL_CONFIG_PATH = _BACKEND_ROOT / "data" / "agent_config.json"

# 上级 agents 目录（video_gui 同源）
_PARENT_AGENTS_DIR: Path | None = None
for _p in Path(__file__).resolve().parents:
    _c = _p / "src" / "agent" / "agents"
    if _c.is_dir():
        _PARENT_AGENTS_DIR = _c.resolve()
        break

_LEGACY_AGENT_SUBDIR: dict[str, str] = {
    "doc_standardize_agent": "doc_standardize",
    "summary_agent": "summary",
    "qa_orchestrator_agent": "qa_orchestrator",
    "ops_agent": "ops",
}

# 多模态 / RAG 文档标准化 Agent 目录（agent_key → 子目录名，默认同 key）
MULTIMODAL_AGENT_KEYS: tuple[str, ...] = (
    "image_type_classifier_agent",
    "image_describe_ui_menu_agent",
    "image_describe_ui_design_agent",
    "image_describe_flowchart_agent",
    "image_describe_chart_agent",
    "image_describe_api_diagram_agent",
    "image_describe_general_agent",
    "image_ocr_llm_enrich_agent",
    "doc_standardize_agent",
)

def _guide(
    *,
    role: str,
    trigger: str,
    impact: str,
    risks: list[str],
    can_edit: list[str],
    must_not_edit: list[str],
    variable_docs: dict[str, str],
    rollback: str,
    pipeline: str = "",
    warning: str = "",
    related_files: list[str] | None = None,
) -> dict[str, Any]:
    """构造 Agent 运维说明块（供配置页展示，与 AGENT.md 正文分离）。"""
    g: dict[str, Any] = {
        "role": role,
        "trigger": trigger,
        "impact": impact,
        "risks": risks,
        "can_edit": can_edit,
        "must_not_edit": must_not_edit,
        "variable_docs": variable_docs,
        "rollback": rollback,
    }
    if pipeline:
        g["pipeline"] = pipeline
    if warning:
        g["warning"] = warning
    if related_files:
        g["related_files"] = related_files
    return g


# VLM 子 Agent（实际参与 doc_image_pipeline 渲染；配置页可单独编辑）
SUB_AGENT_CATALOG: dict[str, dict[str, Any]] = {
    "image_type_classifier_agent": {
        "label": "图片类型分类",
        "group": "multimodal_image",
        "kind": "vlm",
        "task_type": "vlm",
        "parent_key": "vlm_image_agent",
        "variables": ["doc_context", "image_id", "file_name"],
        "hint": "入库时对每张插图做 VLM 分类，输出 JSON 供后续路由描述模板",
        "guide": _guide(
            role="判断文档插图属于菜单/流程图/图表等哪一类，决定后续使用哪套 VLM 描述 Prompt。",
            pipeline="知识库上传 → 文档解析抽图 → classify_image_type() → 本 Agent",
            trigger="每次向知识库上传含图文档（PDF/Word 等）且 VLM 网关可用时，对每张图调用一次。",
            impact="仅影响**新入库**文档的图片描述质量与 RAG 切片内容；已入库文档不会自动重跑。",
            risks=[
                "要求「只输出 JSON」被删掉 → 分类失败，图片类型恒为 unknown，描述走通用模板，检索精度下降。",
                "JSON 字段名 type/confidence/title_hint 被改 → 下游解析失败，confidence 丢失。",
                "类型定义 ui_menu/flowchart 等与代码 DESCRIBE_AGENT_BY_IMAGE_TYPE 不一致 → 路由到错误描述 Agent。",
            ],
            can_edit=[
                "各类型的判定口径说明（如「带箭头的逻辑图优先 flowchart」）。",
                "title_hint 长度与语言要求。",
                "结合 doc_context 的上下文提示语。",
            ],
            must_not_edit=[
                "JSON 结构及字段名：type、confidence、title_hint。",
                "type 枚举值必须与代码中 DESCRIBE_AGENT_BY_IMAGE_TYPE 的 key 一致。",
                "占位符 {doc_context}、{image_id}、{file_name} 不可删除或改名。",
                "「仅输出 JSON、不要其它文字」类硬约束。",
            ],
            variable_docs={
                "doc_context": "插图所在文档正文摘要（约 800 字内），帮助判断所属模块。",
                "image_id": "系统分配的图片 ID，如 img_0001，用于日志追踪。",
                "file_name": "原始图片文件名。",
            },
            rollback="删除 agent_config.json 中该 key 的覆盖，或从 Git 恢复 backend/data/agents/image_type_classifier_agent/AGENT.md，重启后端。",
            related_files=["backend/app/services/doc_image_pipeline.py → classify_image_type"],
        ),
    },
    "image_describe_ui_menu_agent": {
        "label": "菜单/界面截图描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "parent_key": "vlm_image_agent",
        "variables": ["doc_context", "title_hint", "ocr_text", "image_id"],
        "hint": "分类为 ui_menu 时：描述导航、菜单项、按钮等可见 UI 元素",
        "guide": _guide(
            role="为软件菜单/后台界面截图生成可检索的中文描述，写入 RAG 图片块。",
            pipeline="分类 type=ui_menu → describe_agent_for_image_type → 本 Agent → VLM 输出 description",
            trigger="图片被分类为 ui_menu 且 VLM 可用时。",
            impact="影响菜单类截图在问答中的召回与回答准确性；改错会导致编造菜单项或描述过空。",
            risks=["去掉「不要编造菜单」约束 → 幻觉菜单项污染知识库。", "要求输出 JSON → 与管道期望的纯文本 description 不兼容。"],
            can_edit=["描述粒度、段落结构、术语风格。", "对 OCR 噪声的处理说明。"],
            must_not_edit=["{doc_context}、{title_hint}、{ocr_text}、{image_id} 占位符。", "「只描述可见内容、不要编造」约束。", "## Prompt 段标题（系统用 extract_prompt_body 提取）。"],
            variable_docs={
                "doc_context": "文档上下文，用于推断所属产品/模块（须有依据）。",
                "title_hint": "分类阶段给出的短标题。",
                "ocr_text": "OCR 原文，供与画面交叉核对。",
                "image_id": "图片 ID。",
            },
            rollback="恢复 AGENT.md 或清除 agent_config.json 覆盖，重启后端；新上传文档才会用新模板。",
        ),
    },
    "image_describe_ui_design_agent": {
        "label": "UI 设计稿描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "parent_key": "vlm_image_agent",
        "variables": ["doc_context", "title_hint", "ocr_text", "image_id"],
        "hint": "分类为 ui_design 时：Banner、宣传稿等非功能性界面",
        "guide": _guide(
            role="描述 UI 装饰稿、宣传 Banner 等，强调视觉元素与文案，供 RAG 检索。",
            trigger="图片 type=ui_design 时。",
            impact="影响设计类插图的知识库描述；误改可能把功能界面与设计稿混淆。",
            risks=["与 ui_menu 模板混用口径 → 分类正确但描述风格不匹配。"],
            can_edit=["对色彩、布局、文案的描述要求。", "段落长度与语言。"],
            must_not_edit=["占位符与「勿编造」约束。", "## Prompt 段结构。"],
            variable_docs={
                "doc_context": "文档上下文。",
                "title_hint": "短标题参考。",
                "ocr_text": "OCR 参考。",
                "image_id": "图片 ID。",
            },
            rollback="同其它 describe Agent：恢复 AGENT.md 并重启。",
        ),
    },
    "image_describe_flowchart_agent": {
        "label": "流程图描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "parent_key": "vlm_image_agent",
        "variables": ["doc_context", "title_hint", "ocr_text", "image_id"],
        "hint": "分类为 flowchart 时：流程、泳道、架构连线图",
        "guide": _guide(
            role="将流程图/架构图转为按步骤或节点叙述的正文，便于「流程怎么走」类问答。",
            trigger="图片 type=flowchart 时。",
            impact="影响流程类问题的 RAG 命中；误改可能导致步骤顺序错乱或遗漏分支。",
            risks=["要求 Mermaid 输出 → 与 RAG 纯文本块格式不符。", "删除「按连线顺序描述」→ 逻辑关系丢失。"],
            can_edit=["步骤叙述风格、是否保留节点名称等细节要求。"],
            must_not_edit=["占位符。", "禁止 JSON/Mermaid 等若模板中已明确禁止的输出格式。"],
            variable_docs={"doc_context": "文档上下文。", "title_hint": "短标题。", "ocr_text": "OCR 节点文字。", "image_id": "图片 ID。"},
            rollback="恢复 AGENT.md 并重启。",
        ),
    },
    "image_describe_chart_agent": {
        "label": "数据图表描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "parent_key": "vlm_image_agent",
        "variables": ["doc_context", "title_hint", "ocr_text", "image_id"],
        "hint": "分类为 chart 时：柱状/折线/饼图等",
        "guide": _guide(
            role="描述数据图表的类型、轴含义、趋势与关键数值（仅画面可见部分）。",
            trigger="图片 type=chart 时。",
            impact="影响数据类问题的回答依据；误改可能编造不存在的数值。",
            risks=["允许「推测趋势」→ 无依据的数字幻觉。"],
            can_edit=["对图例、坐标轴、数据点的描述规范。"],
            must_not_edit=["「只描述可见数据」约束。", "占位符。"],
            variable_docs={"doc_context": "文档上下文。", "title_hint": "短标题。", "ocr_text": "OCR 轴标签/数值。", "image_id": "图片 ID。"},
            rollback="恢复 AGENT.md 并重启。",
        ),
    },
    "image_describe_api_diagram_agent": {
        "label": "接口/时序图描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "parent_key": "vlm_image_agent",
        "variables": ["doc_context", "title_hint", "ocr_text", "image_id"],
        "hint": "分类为 api_diagram 时：接口链路、时序、服务调用关系",
        "guide": _guide(
            role="描述 API/服务调用关系、时序步骤，支撑集成与接口类问答。",
            trigger="图片 type=api_diagram 时。",
            impact="影响接口文档类检索；误改可能混淆调用方向或虚构服务名。",
            risks=["删除「勿编造服务名」→ 幻觉接口。"],
            can_edit=["调用链叙述格式、是否列出 HTTP 方法等。"],
            must_not_edit=["占位符与可见性约束。"],
            variable_docs={"doc_context": "文档上下文。", "title_hint": "短标题。", "ocr_text": "OCR 接口名。", "image_id": "图片 ID。"},
            rollback="恢复 AGENT.md 并重启。",
        ),
    },
    "image_describe_general_agent": {
        "label": "通用/照片描述",
        "group": "multimodal_image",
        "kind": "vlm",
        "parent_key": "vlm_image_agent",
        "variables": ["doc_context", "title_hint", "ocr_text", "image_id"],
        "hint": "分类为 photo/unknown 时的兜底描述模板",
        "guide": _guide(
            role="对无法细分类的插图、产品照片等做通用视觉描述，作为兜底模板。",
            trigger="type 为 photo、unknown 或未命中专用模板时。",
            impact="兜底路径使用频率高；误改影响所有「分不准类」的图片质量。",
            risks=["过度具体化 → 对模糊图片产生幻觉细节。"],
            can_edit=["通用描述的结构与语气。", "信息不足时的兜底话术。"],
            must_not_edit=["占位符。", "与专用 Agent 冲突的类型判定（应在 classifier 改）。"],
            variable_docs={"doc_context": "文档上下文。", "title_hint": "短标题。", "ocr_text": "OCR 参考。", "image_id": "图片 ID。"},
            rollback="恢复 AGENT.md 并重启。",
        ),
    },
}

AGENT_CATALOG: dict[str, dict[str, Any]] = {
    # ── VLM 总览（仅说明用，运行时走 SUB_AGENT_CATALOG 中的子 Agent） ──
    "vlm_image_agent": {
        "label": "VLM 图片理解（总览）",
        "group": "multimodal_image",
        "kind": "vlm",
        "task_type": "vlm",
        "overview_only": True,
        "variables": [],
        "hint": "本项为链路说明入口；实际 Prompt 请在下方子 Agent 中编辑",
        "internal_agents": list(SUB_AGENT_CATALOG.keys()),
        "guide": _guide(
            role="多模态知识库入库中「VLM 看图」阶段的说明入口；**本 Key 的 Prompt 不会被 doc_image_pipeline 调用**。",
            pipeline="上传文档 → 抽图 → image_type_classifier_agent → 按类型选 image_describe_* → 写入 RAG 图片块",
            trigger="见各子 Agent；整体在「知识库上传/文档结构化」时触发，不在用户聊天时触发。",
            impact="子 Agent 模板决定新文档插图能否被正确检索；本总览页修改**不生效**。",
            risks=[
                "误以为改本页即可调整图片描述 → 实际无效，浪费排查时间。",
                "在 agent_config.json 为本 key 写入覆盖 → 仅占用配置位，不影响入库。",
            ],
            can_edit=["无需编辑本页；请切换到下方「图片类型分类」「菜单/界面截图描述」等子 Agent。"],
            must_not_edit=["N/A — 请编辑子 Agent 而非本总览项。"],
            variable_docs={},
            rollback="无需回滚本 key；若误保存，删除 agent_config.json 中 vlm_image_agent 条目即可。",
            warning="⚠ 运行时使用的是子 Agent（image_type_classifier_agent、image_describe_*），请点选下方芯片进入对应模板编辑。",
        ),
    },
    "image_ocr_llm_enrich_agent": {
        "label": "OCR+LLM 图片描述",
        "group": "multimodal_image",
        "kind": "llm",
        "task_type": "reason",
        "variables": ["doc_context", "ocr_text", "image_type", "title_hint", "vlm_draft"],
        "hint": "OCR 提取图片文字 → LLM 合成结构化描述（VLM 不可用或降级时的备选路径）",
        "guide": _guide(
            role="VLM 不可用或输出过短时的降级路径：用 OCR 原文 + 文档上下文，由 LLM 合成图片描述正文。",
            pipeline="抽图 → OCR →（VLM 失败或未配置）→ _enrich_ocr_with_llm() → 本 Agent",
            trigger="VLM 网关不可用、VLM 描述为空/过短、或管道显式走 OCR+LLM 降级时。",
            impact="仅**新入库**文档；降级路径下的 RAG 图片块质量依赖本模板。",
            risks=[
                "删除「只输出 description 正文」→ 输出带 JSON/外壳，污染 RAG 块。",
                "删除占位符 → doc_context/ocr_text 无法注入，描述与文档脱节。",
                "Prompt 为空 → 代码直接退回「OCR：」前缀截断，几乎无语义描述。",
            ],
            can_edit=[
                "正文段落数、语言风格、OCR 错字纠正说明。",
                "对 vlm_draft 与 OCR 的合并策略描述。",
            ],
            must_not_edit=[
                "{doc_context}、{ocr_text}、{image_type}、{title_hint}、{vlm_draft}。",
                "「只输出 description 正文、不要 JSON/picture_id 外壳」约束。",
                "## Prompt 段（extract_prompt_body 提取执行段）。",
            ],
            variable_docs={
                "doc_context": "文档上下文（约 1200 字内截断）。",
                "ocr_text": "OCR 全文或截断（约 3000 字内）。",
                "image_type": "分类结果，如 ui_menu、unknown。",
                "title_hint": "短标题参考。",
                "vlm_draft": "已有 VLM 草稿，可与 OCR 交叉补全；常为空。",
            },
            rollback="恢复 backend/data/agents/image_ocr_llm_enrich_agent/AGENT.md 或删除 agent_config.json 覆盖，重启后端。",
            related_files=["backend/app/services/doc_image_pipeline.py → _enrich_ocr_with_llm"],
        ),
    },
    "qa_orchestrator_agent": {
        "label": "AI 问答与调度",
        "group": "chat_agent",
        "kind": "llm",
        "task_type": "qa",
        "variables": ["question", "context", "history"],
        "hint": "预留：统一问答编排 Prompt（当前主链路尚未挂载）",
        "guide": _guide(
            role="设计意图：作为问答总编排 Agent，负责问题理解、检索调度与答案组织（对标 web_rebuild 同名 Agent）。",
            pipeline="用户提问 →（规划）本 Agent → RAG/工具 → 最终回答",
            trigger="**当前版本未接入**：实际问答走 agent_pipeline.py 内硬编码预处理 Prompt + RAG，不读取本模板。",
            impact="保存后**不影响现网对话**；若未来接入，将直接影响每次问答的检索词与回答结构。",
            risks=[
                "agent_config.json 中若存在「# test」等覆盖 → 会屏蔽 AGENT.md，未来接入时直接生效错误 Prompt。",
                "删除 {question}/{context}/{history} → 变量无法注入。",
                "误当作已生效而反复改 Prompt 排查对话问题 → 浪费时间。",
            ],
            can_edit=[
                "意图分流说明、检索策略、回答格式（在未接入前仅作预演）。",
                "业务术语与语气（接入前建议先在测试环境验证）。",
            ],
            must_not_edit=[
                "接入前请保持占位符完整；JSON/步骤标记若代码侧有解析则不可随意改结构。",
                "## Prompt 段标题规范。",
            ],
            variable_docs={
                "question": "用户当前问题。",
                "context": "RAG 检索到的知识片段。",
                "history": "近期对话历史。",
            },
            rollback="删除 agent_config.json → agent_prompts → qa_orchestrator_agent 条目（当前为「# test」），重启后加载 AGENT.md。",
            warning="⚠ 当前为占位/预留：主对话链路未调用本 Agent；改此处**不会**改变聊天行为。请先清理 agent_config.json 中的测试覆盖。",
            related_files=["backend/app/services/agent_pipeline.py（当前硬编码，未读本 Agent）"],
        ),
    },
    "ops_agent": {
        "label": "系统运维诊断",
        "group": "chat_agent",
        "kind": "llm",
        "task_type": "reason",
        "variables": ["error_log", "system_state", "context"],
        "hint": "失败链路定位、重试策略建议、节点路由补偿",
        "guide": _guide(
            role="根据日志与系统状态生成运维诊断报告：故障分类、根因假设、修复步骤。",
            pipeline="（规划）运维场景触发 → 本 Agent → 结构化诊断报告",
            trigger="**当前版本未自动挂载**；模板供运维 Copilot / 后续功能接入。日常对话不会调用。",
            impact="现网无影响；接入后影响运维建议质量与是否给出可执行修复步骤。",
            risks=[
                "去掉「不得凭空判断根因」→ 幻觉故障原因。",
                "删除 error_log 相关约束 → 建议与日志证据脱节。",
            ],
            can_edit=["报告章节结构、错误分类口径、重试/降级策略描述。"],
            must_not_edit=["{error_log}、{system_state}、{context} 占位符。", "证据一致性、不得省略关键日志等硬约束。"],
            variable_docs={
                "error_log": "错误堆栈或结构化日志片段。",
                "system_state": "节点健康、熔断、路由状态等。",
                "context": "补充上下文（接口、任务 ID 等）。",
            },
            rollback="恢复 backend/data/agents/ops_agent/AGENT.md，删除 agent_config.json 覆盖，重启。",
            warning="⚠ 当前主链路未自动调用；编辑仅影响未来接入或手动 invoke 场景。",
        ),
    },
}

DESCRIBE_AGENT_BY_IMAGE_TYPE: dict[str, str] = {
    "ui_menu": "image_describe_ui_menu_agent",
    "ui_design": "image_describe_ui_design_agent",
    "flowchart": "image_describe_flowchart_agent",
    "chart": "image_describe_chart_agent",
    "api_diagram": "image_describe_api_diagram_agent",
    "photo": "image_describe_general_agent",
    "unknown": "image_describe_general_agent",
}

_VAR_PATTERN = re.compile(r"\{(\w+)\}")


def _read_text(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning(
            "[智能客服-Agent配置|agent_prompt_registry|读取|硬编执行|失败] path=%s; err=%s",
            path,
            str(exc)[:120],
        )
    return ""


def _load_local_config() -> dict[str, Any]:
    if not _LOCAL_CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(_LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning(
            "[智能客服-Agent配置|agent_prompt_registry|本地配置|硬编执行|解析失败] err=%s",
            str(exc)[:120],
        )
        return {}


def _load_parent_config() -> dict[str, Any]:
    cfg_path = settings.resolved_gateway_config_path
    if not cfg_path or not cfg_path.is_file():
        return {}
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _bundled_agent_md(agent_key: str) -> str:
    p = _BUNDLED_AGENTS_DIR / agent_key / "AGENT.md"
    return _read_text(p)


def _legacy_agent_md(agent_key: str) -> str:
    if not _PARENT_AGENTS_DIR:
        return ""
    sub = _LEGACY_AGENT_SUBDIR.get(agent_key, agent_key.replace("_agent", ""))
    return _read_text(_PARENT_AGENTS_DIR / sub / "AGENT.md")


def _merged_prompt_overrides() -> dict[str, str]:
    merged: dict[str, str] = {}
    parent = _load_parent_config()
    parent_prompts = parent.get("agent_prompts")
    if isinstance(parent_prompts, dict):
        for k, v in parent_prompts.items():
            if v and str(v).strip():
                merged[str(k)] = str(v).strip()

    local = _load_local_config()
    local_prompts = local.get("agent_prompts")
    if isinstance(local_prompts, dict):
        for k, v in local_prompts.items():
            merged[str(k)] = str(v or "").strip()
    return merged


def _catalog_meta_for_key(key: str) -> dict[str, Any] | None:
    if key in AGENT_CATALOG:
        return AGENT_CATALOG[key]
    if key in SUB_AGENT_CATALOG:
        return SUB_AGENT_CATALOG[key]
    return None


def get_agent_guide(agent_key: str) -> dict[str, Any]:
    """返回 Agent 运维说明（配置页展示）。"""
    meta = _catalog_meta_for_key((agent_key or "").strip())
    if not meta:
        return {}
    guide = meta.get("guide")
    return dict(guide) if isinstance(guide, dict) else {}


def list_agent_catalog() -> list[dict[str, Any]]:
    """返回可配置 Agent 清单（含子 Agent 与运维说明）。"""
    overrides = _merged_prompt_overrides()
    out: list[dict[str, Any]] = []

    def _append_row(key: str, meta: dict[str, Any]) -> None:
        row = dict(meta)
        row["agent_key"] = key
        row["has_override"] = bool(overrides.get(key, "").strip())
        row["builtin_exists"] = (_BUNDLED_AGENTS_DIR / key / "AGENT.md").is_file()
        guide = meta.get("guide")
        if isinstance(guide, dict):
            row["guide"] = guide
        if key in SUB_AGENT_CATALOG:
            row["is_sub_agent"] = True
            row.setdefault("parent_key", "vlm_image_agent")
        if meta.get("overview_only"):
            row["overview_only"] = True
        out.append(row)

    for key, meta in AGENT_CATALOG.items():
        _append_row(key, meta)
    for key, meta in SUB_AGENT_CATALOG.items():
        _append_row(key, meta)
    return out


def load_agent_prompt(agent_key: str) -> str:
    """加载 Agent 完整 Prompt 文本（含 AGENT.md 正文）。"""
    key = (agent_key or "").strip()
    if not key:
        return ""

    overrides = _merged_prompt_overrides()
    if overrides.get(key, "").strip():
        return overrides[key].strip()

    bundled = _bundled_agent_md(key)
    if bundled:
        return bundled

    legacy = _legacy_agent_md(key)
    if legacy:
        return legacy

    return ""


def render_agent_prompt(agent_key: str, **variables: Any) -> str:
    """渲染 Prompt：替换 {doc_context} 等占位符；缺失变量置空。"""
    template = load_agent_prompt(agent_key)
    if not template:
        return ""

    str_vars = {k: str(v if v is not None else "") for k, v in variables.items()}

    def _repl(m: re.Match[str]) -> str:
        name = m.group(1)
        return str_vars.get(name, "")

    return _VAR_PATTERN.sub(_repl, template).strip()


def describe_agent_for_image_type(image_type: str) -> str:
    t = (image_type or "unknown").strip().lower()
    return DESCRIBE_AGENT_BY_IMAGE_TYPE.get(t, "image_describe_general_agent")


def load_agent_routing() -> dict[str, dict[str, Any]]:
    """合并上级 config 与本地 agent_config.json 的路由规则。"""
    rules: dict[str, dict[str, Any]] = {}
    parent = _load_parent_config()
    pr = parent.get("agent_route_rules")
    if isinstance(pr, dict):
        for k, v in pr.items():
            if isinstance(v, dict):
                rules[str(k)] = {
                    "mode": str(v.get("mode") or "system_compete"),
                    "nodes": list(v.get("nodes") or []),
                }

    local = _load_local_config()
    lr = local.get("agent_route_rules")
    if isinstance(lr, dict):
        for k, v in lr.items():
            if isinstance(v, dict):
                rules[str(k)] = {
                    "mode": str(v.get("mode") or "system_compete"),
                    "nodes": list(v.get("nodes") or []),
                }

    # 确保 catalog 中每个 Agent 至少有默认路由项
    for key in AGENT_CATALOG:
        rules.setdefault(key, {"mode": "system_compete", "nodes": []})
    return rules


def _persist_local_config(patch: dict[str, Any]) -> None:
    current = _load_local_config()
    current.update(patch)
    _LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOCAL_CONFIG_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def save_agent_prompt(agent_key: str, content: str) -> None:
    key = (agent_key or "").strip()
    if not key:
        raise ValueError("agent_key 不能为空")
    local = _load_local_config()
    prompts = dict(local.get("agent_prompts") or {})
    prompts[key] = str(content or "")
    local["agent_prompts"] = prompts
    _persist_local_config(local)

    # 同步写入 bundled AGENT.md，便于 diff 与导出
    md_dir = _BUNDLED_AGENTS_DIR / key
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / "AGENT.md"
    md_path.write_text((content or "").strip() + "\n", encoding="utf-8")
    logger.info(
        "[智能客服-Agent配置|agent_prompt_registry|save_agent_prompt|硬编执行|完成] agent_key=%s; len=%s",
        key,
        len(content or ""),
    )


def save_agent_routing(rules: dict[str, Any]) -> None:
    if not isinstance(rules, dict):
        raise ValueError("rules 必须为对象")
    normalized: dict[str, dict[str, Any]] = {}
    for k, v in rules.items():
        if not isinstance(v, dict):
            continue
        nodes = v.get("nodes")
        if isinstance(nodes, str):
            nodes = [x.strip() for x in nodes.split(",") if x.strip()]
        normalized[str(k)] = {
            "mode": str(v.get("mode") or "system_compete"),
            "nodes": list(nodes or []),
        }
    local = _load_local_config()
    local["agent_route_rules"] = normalized
    _persist_local_config(local)
    logger.info(
        "[智能客服-Agent配置|agent_prompt_registry|save_agent_routing|硬编执行|完成] count=%s",
        len(normalized),
    )


def extract_prompt_body(agent_md: str) -> str:
    """从 AGENT.md 提取「执行段」：优先 ## Prompt 之后的内容，否则全文。"""
    text = (agent_md or "").strip()
    if not text:
        return ""
    marker = "## Prompt"
    idx = text.find(marker)
    if idx >= 0:
        body = text[idx + len(marker) :].strip()
        if body.startswith("\n"):
            body = body.lstrip()
        return body
    return text
