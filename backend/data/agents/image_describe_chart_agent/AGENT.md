# 图表描述 Agent（image_describe_chart_agent）

## 输入变量

`{doc_context}` `{title_hint}` `{ocr_text}`

## Prompt

请分析这张**数据图表**（标题参考：{title_hint}）。

**仅输出一个 JSON 对象**：
```json
{
  "chart_type": "柱状图|折线图|饼图|散点图|其他",
  "title": "图表标题",
  "description": "图表内容与趋势的详细中文描述，可直接用于 RAG",
  "data": {"类别A": 0, "类别B": 0},
  "insights": ["关键洞察1"]
}
```

规则：
- `description` 必须自洽可读，即使 OCR 缺失也能独立理解。
- 数值看不清时写「不可辨」，不要猜测。
- `data` 中只包含能从图中读出的键值。

文档上下文：
{doc_context}

OCR 参考：
{ocr_text}
