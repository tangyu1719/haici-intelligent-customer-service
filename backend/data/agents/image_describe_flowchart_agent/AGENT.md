# 流程图描述 Agent（image_describe_flowchart_agent）

## 身份与目标

- 理解流程图、架构图、泳道图；输出文字描述，并尽量给出 Mermaid（供可选下游使用）。
- CV 流程图解析失败时的 VLM 降级路径使用本模板。

## 输入变量

`{doc_context}` `{title_hint}` `{ocr_text}`

## Prompt

请分析这张**流程图/架构图/泳道图**（标题参考：{title_hint}）。

1. 用中文详细描述所有主要节点、分支条件与连接关系（按业务阅读顺序）。
2. 提取关键节点名称列表。
3. 若结构清晰，生成对应的 Mermaid `graph TD` 或 `flowchart` 代码（放在 JSON 的 mermaid 字段）。

**仅输出一个 JSON 对象**（可用 ```json 包裹），结构：
```json
{
  "description": "流程的详细中文描述，可直接写入 RAG 正文",
  "mermaid": "```mermaid\\nflowchart TD\\n...\\n```",
  "nodes": ["节点1", "节点2"],
  "edges": ["A --> B"]
}
```

若无法可靠还原 Mermaid，`mermaid` 可为空字符串，但 `description` 必须完整。

文档上下文：
{doc_context}

OCR 参考（辅助读字）：
{ocr_text}
