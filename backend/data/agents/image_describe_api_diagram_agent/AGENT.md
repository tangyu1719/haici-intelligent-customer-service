# 接口链路图描述 Agent（image_describe_api_diagram_agent）

## 输入变量

`{doc_context}` `{title_hint}` `{ocr_text}`

## Prompt

请分析这张**接口链路图/时序图/服务调用图**（标题参考：{title_hint}）。

**仅输出一个 JSON 对象**：
```json
{
  "description": "链路的中文叙述，按调用顺序说明",
  "sequence_diagram": "```mermaid\\nsequenceDiagram\\n...\\n```",
  "apis": [{"name": "接口名", "from": "调用方", "to": "被调用方", "method": "GET|POST|..."}],
  "services": ["服务A", "服务B"]
}
```

`description` 字段将直接写入 RAG Markdown；必须准确、不编造未出现的接口。

文档上下文：
{doc_context}

OCR 参考：
{ocr_text}
