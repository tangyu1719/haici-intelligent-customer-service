from datetime import date, datetime



from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func

from sqlalchemy.orm import Mapped, mapped_column



from app.database import Base





class User(Base):

    __tablename__ = "users"



    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_no: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)

    username: Mapped[str | None] = mapped_column(String(64), unique=True)

    email: Mapped[str | None] = mapped_column(String(128), unique=True)

    phone: Mapped[str | None] = mapped_column(String(20), unique=True)

    password_hash: Mapped[str | None] = mapped_column(String(255))

    nickname: Mapped[str] = mapped_column(String(64), default="")

    avatar_url: Mapped[str] = mapped_column(String(512), default="")

    status: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())





class RbacRole(Base):

    __tablename__ = "rbac_role"



    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    name: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[int] = mapped_column(Integer, default=1)





class RbacUserRole(Base):

    __tablename__ = "rbac_user_role"



    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("rbac_role.id", ondelete="CASCADE"), primary_key=True)





class RbacRefreshToken(Base):

    __tablename__ = "rbac_refresh_token"



    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    revoked: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)





class RbacVerifyCode(Base):

    __tablename__ = "rbac_verify_code"



    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    target: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    code: Mapped[str] = mapped_column(String(10), nullable=False)

    type: Mapped[str] = mapped_column(String(16), nullable=False)

    purpose: Mapped[str] = mapped_column(String(32), default="login")

    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    used: Mapped[int] = mapped_column(Integer, default=0)

    attempts: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())





class SysMenu(Base):

    __tablename__ = "sys_menu"



    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)

    name: Mapped[str] = mapped_column(String(64), nullable=False)

    menu_type: Mapped[str] = mapped_column(String(1), nullable=False)

    path: Mapped[str] = mapped_column(String(128), default="")

    component: Mapped[str] = mapped_column(String(128), default="")

    permission: Mapped[str | None] = mapped_column(String(128), unique=True)

    icon: Mapped[str] = mapped_column(String(64), default="")

    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    visible: Mapped[int] = mapped_column(Integer, default=1)

    status: Mapped[int] = mapped_column(Integer, default=1)

    platform: Mapped[str] = mapped_column(String(32), default="haici")





class SysRoleMenu(Base):

    __tablename__ = "sys_role_menu"



    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("rbac_role.id", ondelete="CASCADE"), primary_key=True)

    menu_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sys_menu.id", ondelete="CASCADE"), primary_key=True)





class ChatSession(Base):

    __tablename__ = "chat_sessions"



    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    context_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column(String(200), default="新对话")

    meta_json: Mapped[dict | None] = mapped_column(JSON, default=None)

    status: Mapped[int] = mapped_column(Integer, default=1)

    user_deleted: Mapped[int] = mapped_column(Integer, default=0, index=True)

    user_deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())





class ChatMessage(Base):

    __tablename__ = "chat_messages"



    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)

    role: Mapped[str] = mapped_column(Enum("user", "assistant", "system", name="message_role"))

    content: Mapped[str] = mapped_column(Text, nullable=False)

    intent_label: Mapped[str | None] = mapped_column(String(32))

    citations_json: Mapped[dict | list | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())





class MessageFeedback(Base):

    __tablename__ = "message_feedback"

    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uk_feedback_user_message"),)



    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    message_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chat_messages.id", ondelete="CASCADE"))

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))

    rating: Mapped[int] = mapped_column(Integer, nullable=False)

    intent_liked: Mapped[int | None] = mapped_column(Integer, nullable=True)

    context_snapshot_json: Mapped[dict | None] = mapped_column(JSON)

    comment: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())





class KnowledgeBase(Base):
    """多知识库管理 (PRD 加分项4)"""

    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    is_default: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class KnowledgeDocument(Base):

    __tablename__ = "knowledge_documents"



    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)

    kb_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="SET NULL"), index=True)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)

    status: Mapped[str] = mapped_column(Enum("processing", "ready", "failed", name="kb_status"), default="processing")

    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())





class DailyQuestionUsage(Base):

    __tablename__ = "daily_question_usage"

    __table_args__ = (UniqueConstraint("user_id", "usage_date", name="uk_usage_user_date"),)



    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))

    usage_date: Mapped[date] = mapped_column(Date, nullable=False)

    question_count: Mapped[int] = mapped_column(Integer, default=0)


class CasbinRule(Base):
    __tablename__ = "casbin_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ptype: Mapped[str] = mapped_column(String(32), nullable=False)
    v0: Mapped[str] = mapped_column(String(255), default="")
    v1: Mapped[str] = mapped_column(String(255), default="")
    v2: Mapped[str] = mapped_column(String(255), default="")
    v3: Mapped[str] = mapped_column(String(255), default="")
    v4: Mapped[str] = mapped_column(String(255), default="")
    v5: Mapped[str] = mapped_column(String(255), default="")


class SysLogOperation(Base):
    __tablename__ = "sys_log_operation"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operate_no: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    user_no: Mapped[str | None] = mapped_column(String(32))
    module: Mapped[str] = mapped_column(String(64), default="")
    menu_permission: Mapped[str] = mapped_column(String(128), default="")
    operate_desc: Mapped[str] = mapped_column(String(255), default="")
    url: Mapped[str] = mapped_column(String(512), default="")
    method: Mapped[str] = mapped_column(String(16), default="")
    input_value: Mapped[str | None] = mapped_column(Text)
    return_value: Mapped[str | None] = mapped_column(Text)
    client_ip: Mapped[str] = mapped_column(String(64), default="")
    time_consume_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=1)
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SysLogError(Base):
    __tablename__ = "sys_log_error"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operate_no: Mapped[str] = mapped_column(String(64), default="")
    error_type: Mapped[int] = mapped_column(Integer, default=1)
    url: Mapped[str] = mapped_column(String(512), default="")
    module: Mapped[str] = mapped_column(String(64), default="")
    error_message: Mapped[str | None] = mapped_column(Text)
    prog_impl: Mapped[str | None] = mapped_column(String(512), default="")
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    client_ip: Mapped[str] = mapped_column(String(64), default="")
    input_value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SysLogApiCall(Base):
    __tablename__ = "sys_log_api_call"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    api_type: Mapped[str] = mapped_column(String(32), default="llm")
    target_url: Mapped[str] = mapped_column(String(512), default="")
    method: Mapped[str] = mapped_column(String(16), default="POST")
    request_summary: Mapped[str | None] = mapped_column(Text)
    response_summary: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer, default=0)
    time_consume_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[int] = mapped_column(Integer, default=1)
    error_message: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SysLogSchedule(Base):
    __tablename__ = "sys_log_schedule"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(128), default="")
    job_group: Mapped[str] = mapped_column(String(64), default="")
    job_desc: Mapped[str] = mapped_column(String(255), default="")
    start_time: Mapped[datetime | None] = mapped_column(DateTime)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    execute_state: Mapped[int] = mapped_column(Integer, default=0)
    job_info: Mapped[str | None] = mapped_column(Text)
    error_msg: Mapped[str | None] = mapped_column(Text)
    job_tag: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SysLogOperationSql(Base):
    __tablename__ = "sys_log_operation_sql"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operation_log_id: Mapped[int] = mapped_column(BigInteger, index=True, default=0)
    log_type: Mapped[int] = mapped_column(Integer, default=1)
    cmd_table: Mapped[str] = mapped_column(String(128), default="")
    cmd_statement: Mapped[str | None] = mapped_column(Text)
    cmd_parameters: Mapped[str | None] = mapped_column(Text)
    cmd_seq: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ChatFaq(Base):
    """对话欢迎区 FAQ：管理员维护的标准问答缓存。"""

    __tablename__ = "chat_faq"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(64), default="通用", index=True)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[int] = mapped_column(Integer, default=1, index=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

