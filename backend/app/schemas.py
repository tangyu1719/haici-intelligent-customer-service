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


class SessionListItem(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageItem(BaseModel):
    id: int
    role: str
    content: str
    intent_label: str | None = None
    citations: list[dict] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=0, le=1)
    comment: str | None = Field(default=None, max_length=500)


class KnowledgeDocumentItem(BaseModel):
    id: int
    filename: str
    status: str
    chunk_count: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatStreamRequest(BaseModel):
    session_id: int
    question: str

    @field_validator("question")
    @classmethod
    def trim_question(cls, v: str) -> str:
        return v.strip()
