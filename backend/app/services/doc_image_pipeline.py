"""单图 OCR / VLM 分类 / 流程图管道 / RAG 描述块生成。"""

from __future__ import annotations



import json

import logging

import os

import re

import sys

from dataclasses import dataclass, field

from pathlib import Path

from typing import Any, Dict, List, Optional



from app.config import settings

from app.services.agent_prompt_registry import (

    describe_agent_for_image_type,

    extract_prompt_body,

    load_agent_prompt,

    render_agent_prompt,

)

from app.services.haici_output import abs_path_to_public_url



logger = logging.getLogger(__name__)



_AGENT_DIR: Optional[Path] = None

for _p in Path(__file__).resolve().parents:

    _c = _p / "src" / "agent"

    if _c.is_dir() and (_c / "mineru_processor.py").is_file():

        _AGENT_DIR = _c.resolve()

        break

if _AGENT_DIR and str(_AGENT_DIR) not in sys.path:

    sys.path.insert(0, str(_AGENT_DIR))





@dataclass

class ImageProcessResult:

    image_id: str

    file_name: str

    abs_path: str

    public_url: str

    image_type: str = "unknown"

    vlm_type_confidence: float = 0.0

    ocr_text: str = ""

    vlm_description: str = ""

    rag_block: str = ""

    pipeline: str = ""

    degraded: bool = False

    flowchart_report: Optional[str] = None

    overlay_url: Optional[str] = None

    extra: Dict[str, Any] = field(default_factory=dict)



    def to_manifest_entry(self, ordinal: int, source_format: str) -> Dict[str, Any]:

        return {

            "image_id": self.image_id,

            "source_format": source_format,

            "ordinal_in_doc": ordinal,

            "file_name": self.file_name,

            "public_url": self.public_url,

            "abs_path": self.abs_path,

            "picture_id": build_picture_id(self, ordinal=ordinal),

            "description": extract_description_body(self),

            "placeholder": f"{{picture_id:{build_picture_id(self, ordinal=ordinal)}; ...}}",

            "image_type": self.image_type,

            "vlm_type_confidence": self.vlm_type_confidence,

            "ocr_text": self.ocr_text[:2000],

            "vlm_description": self.vlm_description[:4000],

            "pipeline": self.pipeline,

            "degraded": self.degraded,

            "flowchart_report": self.flowchart_report,

            "overlay_url": self.overlay_url,
            "is_annotated": bool(
                self.image_type in ("ui_menu", "flowchart", "chart") or
                any(kw in (self.vlm_description or "").lower() for kw in
                    ["区块", "标记", "红框", "箭头", "标注", "编号", "①", "框选"])
            ),

        }





def _get_mineru():

    from mineru_processor import MinerUProcessor



    if settings.BAIDU_OCR_ENABLED:

        if settings.BAIDU_OCR_APP_ID:

            os.environ.setdefault("BAIDU_OCR_APP_ID", settings.BAIDU_OCR_APP_ID)

        if settings.BAIDU_OCR_API_KEY:

            os.environ.setdefault("BAIDU_OCR_API_KEY", settings.BAIDU_OCR_API_KEY)

        if settings.BAIDU_OCR_SECRET_KEY:

            os.environ.setdefault("BAIDU_OCR_SECRET_KEY", settings.BAIDU_OCR_SECRET_KEY)

    api_key = (settings.ARK_API_KEY or settings.QWEN_API_KEY or "").strip()

    return MinerUProcessor(vlm_api_key=api_key if settings.VLM_IMAGE_ENABLED else None)





def _get_vlm():

    if not settings.VLM_IMAGE_ENABLED:

        return None

    try:

        from vlm_image_understander import VLMImageUnderstander



        api_key = (settings.ARK_API_KEY or os.environ.get("ARK_API_KEY", "") or "").strip()

        if not api_key:

            return None

        return VLMImageUnderstander(api_key=api_key)

    except Exception as exc:

        logger.warning(

            "[智能客服-知识库|doc_image_pipeline|VLM|硬编执行|初始化] err=%s",

            str(exc)[:200],

        )

        return None





def _parse_json_from_text(raw: str) -> dict:

    text = (raw or "").strip()

    if text.startswith("```"):

        text = re.sub(r"^```(?:json)?\s*", "", text)

        text = re.sub(r"\s*```$", "", text)

    try:

        data = json.loads(text)

        return data if isinstance(data, dict) else {}

    except json.JSONDecodeError:

        return {}





def _vlm_prompt(agent_key: str, **variables: Any) -> str:

    """从 Agent 模板渲染 VLM 用户 Prompt（取 ## Prompt 段）。"""

    rendered = render_agent_prompt(agent_key, **variables)

    if not rendered:

        logger.warning(

            "[智能客服-知识库|doc_image_pipeline|_vlm_prompt|硬编执行|缺失模板] agent_key=%s",

            agent_key,

        )

        return ""

    return extract_prompt_body(rendered)





def _vlm_call(vlm, image_path: str, agent_key: str, *, max_tokens: int = 600, **variables: Any) -> str:

    prompt = _vlm_prompt(agent_key, **variables)

    if not prompt:

        return ""

    try:

        return str(vlm.understand_image(image_path, prompt, max_tokens=max_tokens)).strip()

    except Exception as exc:

        logger.warning(

            "[智能客服-知识库|doc_image_pipeline|_vlm_call|Agent执行|失败] agent=%s; err=%s",

            agent_key,

            str(exc)[:200],

        )

        return ""





def _description_from_json_agent(raw: str, *prefer_fields: str) -> str:

    obj = _parse_json_from_text(raw)

    if not obj:

        return (raw or "").strip()

    for key in prefer_fields:

        val = obj.get(key)

        if val and str(val).strip():

            return str(val).strip()

    return (raw or "").strip()





def classify_image_type(image_path: str, doc_context: str = "", *, image_id: str = "") -> Dict[str, Any]:

    """VLM 图片类型识别（真实 API + 可配置 Agent 模板）；失败返回 unknown。"""

    vlm = _get_vlm()

    if vlm is None:

        return {"type": "unknown", "confidence": 0.0, "title_hint": Path(image_path).stem}



    agent_key = "image_type_classifier_agent"

    variables = {

        "doc_context": (doc_context or "")[:800],

        "image_id": image_id or Path(image_path).stem,

        "file_name": Path(image_path).name,

    }

    try:

        raw = _vlm_call(vlm, image_path, agent_key, max_tokens=300, **variables)

        obj = _parse_json_from_text(raw)

        t = str(obj.get("type") or "unknown").strip().lower()

        if t not in {

            "ui_menu",

            "ui_design",

            "flowchart",

            "chart",

            "api_diagram",

            "photo",

            "unknown",

        }:

            t = "unknown"

        return {

            "type": t,

            "confidence": float(obj.get("confidence") or 0.5),

            "title_hint": str(obj.get("title_hint") or Path(image_path).stem)[:80],

            "agent_key": agent_key,

        }

    except Exception as exc:

        logger.warning(

            "[智能客服-知识库|doc_image_pipeline|classify_image_type|Agent执行|失败] err=%s",

            str(exc)[:200],

        )

        return {"type": "unknown", "confidence": 0.0, "title_hint": Path(image_path).stem}





def _ocr_image(image_path: str) -> str:

    try:

        mp = _get_mineru()

        if settings.BAIDU_OCR_ENABLED:

            r = mp._baidu_ocr(image_path)

            if r and r.get("success"):

                txt = str(r.get("text") or "").strip()

                if txt:

                    return txt

        return mp._local_ocr_fallback(image_path)

    except Exception as exc:

        logger.warning(

            "[智能客服-知识库|doc_image_pipeline|ocr|硬编执行|失败] err=%s",

            str(exc)[:200],

        )

        return ""





def _describe_with_agent(

    vlm,

    image_path: str,

    image_type: str,

    doc_context: str,

    title: str,

    ocr_text: str,

    image_id: str,

) -> tuple[str, str]:

    """按类型选择描述 Agent，返回 (description, agent_key)。"""

    agent_key = describe_agent_for_image_type(image_type)

    variables = {

        "doc_context": (doc_context or "")[:800],

        "title_hint": title,

        "ocr_text": (ocr_text or "")[:2000],

        "image_id": image_id,

        "image_type": image_type,

    }

    max_tokens = 800 if image_type in ("flowchart", "chart", "api_diagram") else 600

    raw = _vlm_call(vlm, image_path, agent_key, max_tokens=max_tokens, **variables)

    if image_type == "flowchart":

        desc = _description_from_json_agent(raw, "description", "mermaid")

    elif image_type == "chart":

        desc = _description_from_json_agent(raw, "description", "summary")

    elif image_type == "api_diagram":

        desc = _description_from_json_agent(raw, "description")

    else:

        desc = raw

    return desc.strip(), agent_key





def _enrich_ocr_with_llm(

    ocr_text: str,

    doc_context: str,

    image_type: str,

    title: str,

    vlm_draft: str = "",

) -> str:

    """OCR + LLM 描述合成（真实 LLM；无网关时返回 OCR 前缀文本）。"""

    if not (ocr_text or vlm_draft):

        return ""

    agent_key = "image_ocr_llm_enrich_agent"

    if not load_agent_prompt(agent_key):

        return f"OCR：{(ocr_text or vlm_draft)[:1500]}"



    prompt = extract_prompt_body(

        render_agent_prompt(

            agent_key,

            doc_context=(doc_context or "")[:1200],

            ocr_text=(ocr_text or "")[:3000],

            image_type=image_type or "unknown",

            title_hint=title or "插图",

            vlm_draft=(vlm_draft or "")[:1500],

        )

    )

    if not prompt:

        return f"OCR：{ocr_text[:1500]}"



    try:

        from app.llms import get_llm



        llm = get_llm()

        out = llm.call(prompt, temperature=0.2, max_tokens=900, task_type="reason")

        if out and not out.startswith("【配置错误】"):

            return out.strip()

    except Exception as exc:

        logger.warning(

            "[智能客服-知识库|doc_image_pipeline|_enrich_ocr_with_llm|Agent执行|失败] err=%s",

            str(exc)[:200],

        )

    return f"OCR：{ocr_text[:1500]}"





def _run_flowchart_cv(image_path: str, image_id: str) -> Dict[str, Any]:

    try:

        from app.services.flowchart_scoring_service import run_flowchart_score



        rep = run_flowchart_score(image_path, artifact_subdir=f"kb_{image_id}")

        if not rep.get("ok"):

            return {"ok": False, "error": rep.get("error"), "degraded": True}

        summary = rep.get("summary") or {}

        blocks = int(summary.get("final_block_count") or rep.get("final_block_count") or 0)

        desc = f"流程图 CV 解析：共 {blocks} 个逻辑块。"

        geom = summary.get("geometry_score") or rep.get("geometry_score") or {}

        if isinstance(geom, dict) and geom.get("total_score") is not None:

            desc += f" 几何得分 {geom.get('total_score')}。"

        return {

            "ok": True,

            "description": desc,

            "report_path": rep.get("report_path"),

            "overlay_url": rep.get("overlay_url"),

        }

    except Exception as exc:

        return {"ok": False, "error": str(exc), "degraded": True}





def extract_description_body(result: ImageProcessResult) -> str:
    """从 VLM/OCR 结果提取可写入 picture 块的 description 正文。"""
    body = (result.vlm_description or "").strip()
    body = re.sub(r"^###\s*\[图片理解\]\s*[^\n]*\n?", "", body, count=1).strip()
    if not body and result.ocr_text:
        body = f"OCR：{result.ocr_text[:1500]}"
    return body


def build_picture_id(result: ImageProcessResult, *, ordinal: int = 0) -> str:
    title = result.extra.get("title_hint") or result.image_id
    ord_num = ordinal
    if ord_num <= 0 and "_" in result.image_id:
        try:
            ord_num = int(result.image_id.rsplit("_", 1)[-1])
        except ValueError:
            ord_num = 0
    if ord_num > 0:
        return f"图{ord_num}-{result.image_id}"
    return f"图-{title}"


def _detect_annotations(result: ImageProcessResult) -> bool:
    """检测图片是否包含标记/红框/编号等，用于提示LLM逐条解释。"""
    combined = (
        (result.vlm_description or "") + " " +
        (result.ocr_text or "") + " " +
        (extract_description_body(result) or "")
    ).lower()
    markers = ["区块(", "标记", "红框", "箭头", "标注", "编号", "①", "②", "③", "④", "⑤",
               "「", "」", "框选", "高亮", "箭头指向", "注明", "备注"]
    return any(m in combined for m in markers)


def build_rag_image_block(
    result: ImageProcessResult,
    *,
    ordinal: int = 0,
    include_link: bool = True,
) -> str:
    """RAG 切片友好 picture 块：picture_id + url + description + is_annotated。"""
    _ = include_link
    picture_id = build_picture_id(result, ordinal=ordinal)
    url = str(Path(result.abs_path).resolve()) if result.abs_path else ""
    description = extract_description_body(result)
    is_annotated = _detect_annotations(result)
    lines = [
        "{picture_id:" + picture_id + ";",
        "url:" + url + ";",
    ]
    if is_annotated:
        lines.append("is_annotated:true;")
    lines.append("description:")
    if description:
        lines.append(description)
    lines.append("}")
    return "\n".join(lines)





def process_image(

    image_path: str,

    *,

    image_id: str,

    doc_context: str = "",

    source_format: str = "unknown",

) -> ImageProcessResult:

    p = Path(image_path).resolve()

    public_url = abs_path_to_public_url(p)

    res = ImageProcessResult(

        image_id=image_id,

        file_name=p.name,

        abs_path=str(p),

        public_url=public_url,

    )



    res.ocr_text = _ocr_image(str(p))

    if settings.IMAGE_CLASSIFY_ENABLED:
        cls = classify_image_type(str(p), doc_context, image_id=image_id)
    else:
        cls = {
            "type": "unknown",
            "confidence": 0.5,
            "title_hint": image_id,
            "agent_key": "skipped",
        }
    res.image_type = cls["type"]

    res.vlm_type_confidence = float(cls.get("confidence") or 0)

    res.extra["title_hint"] = cls.get("title_hint") or image_id

    res.extra["classifier_agent"] = cls.get("agent_key", "image_type_classifier_agent")



    vlm = _get_vlm()

    title = res.extra["title_hint"]



    if res.image_type == "flowchart":

        cv = _run_flowchart_cv(str(p), image_id)

        if cv.get("ok"):

            res.vlm_description = str(cv.get("description") or "")

            res.flowchart_report = cv.get("report_path")

            res.overlay_url = cv.get("overlay_url")

            res.pipeline = "flowchart_cv"

        else:

            res.degraded = True

            res.pipeline = "flowchart_cv_degraded"

            if vlm:

                desc, dk = _describe_with_agent(

                    vlm, str(p), "flowchart", doc_context, title, res.ocr_text, image_id

                )

                res.extra["describe_agent"] = dk

                res.vlm_description = desc

            if not res.vlm_description and res.ocr_text:

                res.vlm_description = _enrich_ocr_with_llm(

                    res.ocr_text, doc_context, res.image_type, title

                )

                res.pipeline = "ocr_llm_enrich"

    elif vlm:

        desc, dk = _describe_with_agent(

            vlm, str(p), res.image_type, doc_context, title, res.ocr_text, image_id

        )

        res.vlm_description = desc

        res.extra["describe_agent"] = dk

        res.pipeline = f"vlm_{dk}"

        # VLM 过短且 OCR 有内容 → OCR+LLM 补全

        if len(desc) < 40 and len(res.ocr_text) > 80:

            enriched = _enrich_ocr_with_llm(

                res.ocr_text, doc_context, res.image_type, title, vlm_draft=desc

            )

            if enriched and len(enriched) > len(desc):

                res.vlm_description = enriched

                res.pipeline = "vlm+ocr_llm_enrich"

    else:

        res.degraded = True

        res.vlm_description = _enrich_ocr_with_llm(

            res.ocr_text, doc_context, res.image_type, title

        )

        res.pipeline = "ocr_llm_enrich" if res.vlm_description else "ocr_only"



    if not res.vlm_description and res.ocr_text:

        res.vlm_description = _enrich_ocr_with_llm(

            res.ocr_text, doc_context, res.image_type, title

        )

        if res.pipeline == "ocr_only":

            res.pipeline = "ocr_llm_enrich"



    res.rag_block = build_rag_image_block(

        res, ordinal=int(image_id.split("_")[-1]) if "_" in image_id else 0, include_link=True

    )

    logger.info(

        "[智能客服-知识库|doc_image_pipeline|process_image|Agent执行|完成] id=%s; type=%s; pipeline=%s; degraded=%s; describe_agent=%s",

        image_id,

        res.image_type,

        res.pipeline,

        res.degraded,

        res.extra.get("describe_agent", ""),

    )

    return res


