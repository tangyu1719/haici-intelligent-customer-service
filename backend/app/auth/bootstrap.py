"""启动时初始化 RBAC 种子与 user_no 回填。"""

import logging
from pathlib import Path

from sqlalchemy import text

from app.auth.seed import (
    backfill_user_no,
    ensure_admin_user,
    ensure_bootstrap_admin,
    ensure_roles,
    seed_menus,
    sync_agent_settings_menu,
    sync_knowledge_multimodal_menu,
    sync_profile_menu_group,
    sync_feedback_menu,
    sync_log_menu_group,
)
from app.auth.casbin_enforcer import seed_casbin_policies
from app.database import SessionLocal, engine
from app.models import Base

logger = logging.getLogger(__name__)

_USER_COLUMN_DDL = [
    ("user_no", "ADD COLUMN user_no VARCHAR(32) NULL UNIQUE COMMENT '对外Hash数字码' AFTER id"),
    ("username", "ADD COLUMN username VARCHAR(64) NULL UNIQUE COMMENT '登录名' AFTER user_no"),
    ("nickname", "ADD COLUMN nickname VARCHAR(64) NOT NULL DEFAULT '' AFTER phone"),
    ("avatar_url", "ADD COLUMN avatar_url VARCHAR(512) NOT NULL DEFAULT '' AFTER nickname"),
    ("status", "ADD COLUMN status TINYINT NOT NULL DEFAULT 1 COMMENT '1启用0禁用' AFTER avatar_url"),
    ("updated_at", "ADD COLUMN updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER created_at"),
]

_SESSION_COLUMN_DDL = [
    ("context_id", "ADD COLUMN context_id VARCHAR(36) NULL COMMENT '上下文UUID' AFTER id"),
    ("meta_json", "ADD COLUMN meta_json JSON NULL COMMENT '扩展元数据' AFTER title"),
    ("status", "ADD COLUMN status TINYINT NOT NULL DEFAULT 1 COMMENT '1正常0归档' AFTER meta_json"),
]

_FEEDBACK_COLUMN_DDL = [
    ("intent_liked", "ADD COLUMN intent_liked TINYINT NULL COMMENT '意图理解是否准确 1赞0踩' AFTER rating"),
    ("context_snapshot_json", "ADD COLUMN context_snapshot_json JSON NULL COMMENT '反馈上下文快照' AFTER intent_liked"),
]


def _ensure_users_columns(conn) -> None:
    rows = conn.execute(text("SHOW COLUMNS FROM users")).fetchall()
    existing = {r[0] for r in rows}
    for col, ddl in _USER_COLUMN_DDL:
        if col in existing:
            continue
        try:
            conn.execute(text(f"ALTER TABLE users {ddl}"))
        except Exception as exc:
            logger.warning("[登录模块-迁移|bootstrap|users.%s|硬编执行|跳过] err=%s", col, str(exc)[:120])
    try:
        conn.execute(text("ALTER TABLE users MODIFY password_hash VARCHAR(255) NULL"))
    except Exception:
        pass


def _ensure_message_feedback_columns(conn) -> None:
    try:
        rows = conn.execute(text("SHOW COLUMNS FROM message_feedback")).fetchall()
    except Exception:
        return
    existing = {r[0] for r in rows}
    for col, ddl in _FEEDBACK_COLUMN_DDL:
        if col in existing:
            continue
        try:
            conn.execute(text(f"ALTER TABLE message_feedback {ddl}"))
        except Exception as exc:
            logger.warning("[反馈模块-迁移|bootstrap|message_feedback.%s|硬编执行|跳过] err=%s", col, str(exc)[:120])


def _ensure_chat_sessions_columns(conn) -> None:
    try:
        rows = conn.execute(text("SHOW COLUMNS FROM chat_sessions")).fetchall()
    except Exception:
        return
    existing = {r[0] for r in rows}
    for col, ddl in _SESSION_COLUMN_DDL:
        if col in existing:
            continue
        try:
            conn.execute(text(f"ALTER TABLE chat_sessions {ddl}"))
        except Exception as exc:
            logger.warning("[会话持久化-迁移|bootstrap|chat_sessions.%s|硬编执行|跳过] err=%s", col, str(exc)[:120])
    try:
        conn.execute(text("UPDATE chat_sessions SET context_id = UUID() WHERE context_id IS NULL OR context_id = ''"))
    except Exception as exc:
        logger.warning("[会话持久化-迁移|bootstrap|backfill_context_id|硬编执行|跳过] err=%s", str(exc)[:120])
    try:
        conn.execute(text("ALTER TABLE chat_sessions MODIFY context_id VARCHAR(36) NOT NULL"))
    except Exception:
        pass
    try:
        conn.execute(text("CREATE UNIQUE INDEX uk_sessions_context ON chat_sessions (context_id)"))
    except Exception as exc:
        msg = str(exc)
        if "Duplicate" not in msg and "1061" not in msg and "already exists" not in msg:
            logger.warning("[会话持久化-迁移|bootstrap|uk_sessions_context|硬编执行|跳过] err=%s", msg[:120])


def _run_sql_migration() -> None:
    sql_path = Path(__file__).resolve().parents[2] / "数据库初始化脚本" / "migrate_rbac_v1.sql"
    if not sql_path.is_file():
        return
    raw = sql_path.read_text(encoding="utf-8")
    stmts = [s.strip() for s in raw.split(";") if s.strip() and not s.strip().startswith("--")]
    with engine.begin() as conn:
        _ensure_users_columns(conn)
        _ensure_chat_sessions_columns(conn)
        _ensure_message_feedback_columns(conn)
        for stmt in stmts:
            upper = stmt.upper()
            if upper.startswith("USE ") or "ALTER TABLE USERS" in upper:
                continue
            try:
                conn.execute(text(stmt))
            except Exception as exc:
                msg = str(exc)
                if any(x in msg for x in ("Duplicate column", "1060", "already exists", "1050")):
                    continue
                logger.warning("[登录模块-迁移|bootstrap|SQL|硬编执行|跳过] err=%s", msg[:120])


def ensure_auth_ready() -> None:
    Base.metadata.create_all(bind=engine)
    _run_sql_migration()
    db = SessionLocal()
    try:
        ensure_roles(db)
        seed_menus(db)
        sync_log_menu_group(db)
        sync_feedback_menu(db)
        sync_knowledge_multimodal_menu(db)
        sync_profile_menu_group(db)
        sync_agent_settings_menu(db)
        backfill_user_no(db)
        ensure_bootstrap_admin(db)
        ensure_admin_user(db)
        seed_casbin_policies()
        logger.info("[登录模块-认证|bootstrap|种子|硬编执行|完成] RBAC/菜单/Casbin/user_no 就绪")
    finally:
        db.close()
