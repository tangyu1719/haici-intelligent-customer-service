# 通用插图描述 Agent（image_describe_general_agent）

## 输入变量

`{doc_context}` `{title_hint}` `{ocr_text}` `{image_type}`

## Prompt

请描述这张文档插图（类型参考：{image_type}，标题：{title_hint}）。

要求：
1. 简体中文，一段或数段连贯正文，作为 picture 块的 **description** 字段内容。
2. 覆盖画面中所有可读文字与关键物体/场景。
3. 结合文档上下文说明其在文档中的作用；无依据时不强行关联。
4. **只输出 description 正文**：不要输出 `{picture_id:...}` 外壳、不要 JSON、不要 Markdown 标题（不要 `### [图片理解]`）；看不清处写「不可辨」。

文档上下文：
{doc_context}

OCR 参考：
{ocr_text}

## 输出格式（由系统组装，Agent 勿重复输出）

系统会将你的正文写入 normalized.md，形如：

```
{picture_id:图N-img_NNNN;
url:F:\...\img_NNNN.png;
description:
<此处为你的正文>
}
```
