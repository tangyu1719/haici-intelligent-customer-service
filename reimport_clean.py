import os
import re
import uuid
import logging
import sys
import glob
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


def html_table_to_text(html: str) -> str:
    """将HTML表格转成结构化纯文本"""
    text = html
    text = re.sub(r'</tr>\s*<tr[^>]*>', '\n', text)
    text = re.sub(r'</td>\s*<td[^>]*>', ' | ', text)
    text = re.sub(r'</th>\s*<th[^>]*>', ' | ', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    text = re.sub(r'[ \t]+', ' ', text)
    lines = []
    for line in text.split('\n'):
        line = line.strip().strip('|').strip()
        if line and len(line) > 3:
            lines.append(line)
    return '\n'.join(lines)


def llm_convert_table(table_html: str, context_hint: str = "") -> str:
    """用LLM将HTML表格转成自然语言描述"""
    from llms import get_llm
    llm = get_llm()

    raw_text = html_table_to_text(table_html)
    # 如果表格内容太少，直接用纯文本版本
    if len(raw_text) < 30:
        return raw_text

    # 表格太大时截断，避免超出token限制
    if len(raw_text) > 3000:
        raw_text = raw_text[:3000]

    prompt = f"""请将以下表格内容转换为清晰的自然语言描述，要求：
1. 每个关键信息点单独一行
2. 保留所有数字、金额、时间等具体数据
3. 不要遗漏任何信息
4. 去掉无意义的水印文字如JD.COM

{f'表格上下文: {context_hint}' if context_hint else ''}
表格内容:
{raw_text}

自然语言描述:"""

    try:
        result = llm.call(prompt, temperature=0.1, max_tokens=1500)
        if result and len(result) > 20:
            return result
    except Exception as e:
        logger.warning("LLM表格转换失败: %s", str(e))

    return raw_text


def clean_markdown(text: str) -> str:
    """清洗MinerU提取的markdown内容"""
    # 提取表格前后的上下文作为hint
    def replace_table(match):
        table_html = match.group()
        # 获取表格前面的文字作为上下文
        start = max(0, match.start() - 200)
        context = text[start:match.start()].strip()
        context_hint = context[-100:] if len(context) > 100 else context
        return llm_convert_table(table_html, context_hint)

    # 用LLM转换HTML表格
    text = re.sub(r'<table[\s\S]*?</table>', replace_table, text)

    # 清除残留HTML标签
    text = re.sub(r'</?(?:tr|td|th|tbody|thead)[^>]*>', '', text)
    text = re.sub(r'rowspan=\d+\s*colspan=\d+>', '', text)
    # 去掉图片标签
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    # 去掉水印
    text = re.sub(r'JD\.COM', '', text)
    text = re.sub(r'JD\.CO[MN]?', '', text)
    text = re.sub(r'JD\.C\b', '', text)
    text = re.sub(r'\bD\.COM\b', '', text)
    text = re.sub(r'\)\.COM\b', '', text)
    text = re.sub(r'(?<!\w)COM(?!\w)', '', text)
    text = re.sub(r'(?<!\w)OM(?!\w)', '', text)
    # 清理空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            lines.append('')
            continue
        if len(re.sub(r'[\s\d\.\,\;\:\-\|\(\)\[\]\/]', '', line)) < 2:
            continue
        lines.append(line)
    return '\n'.join(lines).strip()


def split_document(markdown_content: str, filename: str, category: str) -> tuple:
    """切分文档为父块和子块"""
    parents = []
    children = []

    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[
        ("#", "H1"),
        ("##", "H2"),
        ("###", "H3"),
        ("####", "H4")
    ])
    parent_splits = md_splitter.split_text(markdown_content)

    if len(parent_splits) <= 1:
        fallback_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
        parent_splits = fallback_splitter.create_documents([markdown_content])

    child_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80)

    for p_doc in parent_splits:
        content = p_doc.page_content.strip()
        if len(content) < 15:
            continue

        parent_id = f"p_{uuid.uuid4().hex[:8]}"
        path = " > ".join([v for k, v in p_doc.metadata.items() if k.startswith("H")])
        enriched = f"[{path}]\n{content}" if path else content

        p_meta = {
            "source": filename,
            "category": category,
            "parent_id": parent_id,
            "doc_type": "parent"
        }

        parents.append(Document(page_content=enriched, metadata=p_meta))

        c_docs = child_splitter.split_documents([Document(page_content=enriched)])
        for c_doc in c_docs:
            if len(c_doc.page_content.strip()) < 15:
                continue
            c_meta = p_meta.copy()
            c_meta["doc_type"] = "child"
            children.append(Document(page_content=c_doc.page_content, metadata=c_meta))

    return parents, children


def main():
    from vectorstore import add_documents, reset_collection
    from es_client import bulk_index, get_client
    from config import settings

    es = get_client()
    if not es:
        logger.error("ES连接失败")
        return
    logger.info("ES连接正常")

    logger.info("清空ChromaDB...")
    reset_collection()

    logger.info("清空ES...")
    try:
        if es.indices.exists(index=settings.ES_INDEX):
            es.indices.delete(index=settings.ES_INDEX)
    except Exception as e:
        logger.warning("删除ES索引: %s", str(e))

    md_files = glob.glob("extracted_output/**/*.md", recursive=True)
    logger.info("发现 %d 个markdown文件", len(md_files))

    all_parents = []
    all_children = []

    for md_path in md_files:
        filename = os.path.basename(md_path)
        logger.info("处理: %s", md_path)

        with open(md_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        logger.info("  原始: %d 字符", len(raw_content))
        cleaned = clean_markdown(raw_content)
        logger.info("  清洗后: %d 字符", len(cleaned))

        if len(cleaned) < 30:
            logger.warning("  内容过少，跳过")
            continue

        if "DJI" in filename or "dji" in filename.lower():
            category = "dji_product"
        elif "help" in filename:
            category = "help_doc"
        else:
            category = "general"

        parents, children = split_document(cleaned, filename, category)
        logger.info("  父块: %d, 子块: %d", len(parents), len(children))

        all_parents.extend(parents)
        all_children.extend(children)

    logger.info("=" * 50)
    logger.info("汇总: 父块 %d, 子块 %d", len(all_parents), len(all_children))

    if all_children:
        logger.info("写入ChromaDB子块 %d 条...", len(all_children))
        for i in range(0, len(all_children), 100):
            add_documents(all_children[i:i+100])
        logger.info("ChromaDB完成")

    if all_parents:
        logger.info("写入ES父块 %d 条...", len(all_parents))
        bulk_index([{"content": d.page_content, **d.metadata} for d in all_parents])
        logger.info("ES父块完成")

    if all_children:
        logger.info("写入ES子块 %d 条...", len(all_children))
        for i in range(0, len(all_children), 100):
            bulk_index([{"content": d.page_content, **d.metadata} for d in all_children[i:i+100]])
        logger.info("ES子块完成")

    from vectorstore import get_collection
    col = get_collection()
    logger.info("ChromaDB: %d", col.count() if col else 0)
    try:
        logger.info("ES: %d", es.count(index=settings.ES_INDEX)['count'])
    except Exception as e:
        logger.warning("ES计数: %s", str(e))

    logger.info("完成")


if __name__ == "__main__":
    main()
