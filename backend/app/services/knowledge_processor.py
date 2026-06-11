from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter


def read_document_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        import fitz

        doc = fitz.open(file_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    raise ValueError(f"不支持的文件格式: {suffix}")


def split_to_documents(text: str, document_id: int, document_name: str):
    from langchain_core.documents import Document

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80)
    chunks = [c.strip() for c in splitter.split_text(text) if c.strip()]
    return [
        Document(
            page_content=chunk,
            metadata={"document_id": document_id, "document_name": document_name},
        )
        for chunk in chunks
    ]
