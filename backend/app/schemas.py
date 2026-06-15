from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    email: str | None = None
    phone: str | None = None
    password: str = Field(min_length=6, max_length=64)

    def model_post_init(self, __context) -> None:
        if not self.email and not self.phone:
            raise ValueError("邮箱或手机号至少填写一项")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str | None
    phone: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class SessionMetaSummary(BaseModel):
    last_intent: str | None = None
    message_count: int = 0
    note: str | None = None
    pinned: bool = False


class SessionListItem(BaseModel):
    id: int
    context_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    meta: SessionMetaSummary | None = None

    class Config:
        from_attributes = True


class SessionPageResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[SessionListItem]


class MessagePageResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list["MessageItem"]


class SessionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def trim_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        t = v.strip()
        if not t:
            raise ValueError("标题不能为空")
        return t


class SessionDetailResponse(SessionListItem):
    status: int = 1
    user_id: int | None = None
    messages: list["MessageItem"] = []


class MessageItem(BaseModel):
    id: int
    role: str
    content: str
    intent_label: str | None = None
    citations: list[dict] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class FeedbackContextSnapshot(BaseModel):
    session_id: int
    context_id: str = ""
    context_summary: str = ""
    user_question: str = ""
    assistant_answer: str = ""
    intent: str | None = None
    intent_label: str | None = None
    detected_intent: str | None = None
    detected_intent_label: str | None = None
    corrected_intent: str | None = None
    corrected_intent_label: str | None = None
    intent_suggestions_shown: list[str] | None = None


class FeedbackRequest(BaseModel):
    """反馈提交：新建时至少含 rating；更新时可分次提交星级/意图/补充说明。"""

    rating: int | None = Field(default=None, ge=1, le=5, description="回答满意度 1-5 星")
    intent_liked: bool | None = None
    comment: str | None = Field(default=None, max_length=500)
    context_snapshot: FeedbackContextSnapshot | None = None


class FeedbackAdminItem(BaseModel):
    id: int
    message_id: int
    user_id: int
    username: str | None = None
    nickname: str | None = None
    rating: int
    intent_liked: bool | None = None
    comment: str | None = None
    context_snapshot: dict | None = None
    created_at: datetime
    # 详情字段（列表/详情均返回，缺失时由后端从会话回填）
    session_id: int | None = None
    context_id: str = ""
    user_question: str = ""
    assistant_answer: str = ""
    context_summary: str = ""
    intent: str = ""
    intent_label: str = ""
    corrected_intent: str = ""
    corrected_intent_label: str = ""
    session_title: str = ""

    class Config:
        from_attributes = True


class FeedbackAdminDetailResponse(BaseModel):
    item: FeedbackAdminItem


class FeedbackAdminListResponse(BaseModel):
    total: int
    page: int = 1
    size: int = 20
    items: list[FeedbackAdminItem]


class KnowledgePageResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list["KnowledgeDocumentItem"]


class KnowledgeDocumentItem(BaseModel):
    id: int
    filename: str
    status: str
    chunk_count: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    file_type: str | None = None
    file_size_bytes: int | None = None
    file_size_human: str | None = None
    image_count: int | None = None
    vlm_limit: int | None = None
    truncated: bool | None = None
    assets_dir: str | None = None
    kb_id: int | None = None
    kb_name: str | None = None

    class Config:
        from_attributes = True


class ChatAttachmentItem(BaseModel):
    """对话附件（图片/文件，path 为 multimodal/upload 返回的服务端路径）。"""

    type: str = Field(..., pattern="^(image|file)$")
    name: str = Field(..., min_length=1, max_length=260)
    path: str = Field(..., min_length=1, max_length=1024)
    preview: str | None = Field(None, max_length=512_000, description="图片 data URL，仅前端展示用")


class ChatStreamRequest(BaseModel):
    session_id: int
    question: str
    kb_id: int | None = None
    attachments: list[ChatAttachmentItem] | None = None

    @field_validator("question")
    @classmethod
    def trim_question(cls, v: str) -> str:
        return v.strip()
