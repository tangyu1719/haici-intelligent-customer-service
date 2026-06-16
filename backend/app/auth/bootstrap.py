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
    sync_knowledge_menu_group,
    sync_profile_menu_group,
    sync_feedback_menu,
    sync_log_menu_group,
    sync_system_rbac_menu,
    sync_chat_faq_menu,
    sync_user_profile_menu,
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
    ("user_deleted", "ADD COLUMN user_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '用户侧软删除1是0否' AFTER status"),
    ("user_deleted_at", "ADD COLUMN user_deleted_at DATETIME NULL COMMENT '用户删除时间' AFTER user_deleted"),
]

_FEEDBACK_COLUMN_DDL = [
    ("intent_liked", "ADD COLUMN intent_liked TINYINT NULL COMMENT '意图理解是否准确 1赞0踩' AFTER rating"),
    ("context_snapshot_json", "ADD COLUMN context_snapshot_json JSON NULL COMMENT '反馈上下文快照' AFTER intent_liked"),
]

_LOG_OPERATION_COLUMN_DDL = [
    ("operate_desc", "ADD COLUMN operate_desc VARCHAR(255) NOT NULL DEFAULT '' COMMENT '操作描述' AFTER menu_permission"),
]

_LOG_ERROR_COLUMN_DDL = [
    ("prog_impl", "ADD COLUMN prog_impl VARCHAR(512) NULL DEFAULT '' COMMENT '代码定位' AFTER error_message"),
]

_RBAC_ROLE_COLUMN_DDL = [
    ("remark", "ADD COLUMN remark VARCHAR(255) NOT NULL DEFAULT '' COMMENT '备注' AFTER status"),
    ("created_at", "ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER remark"),
]

_SYS_MENU_COLUMN_DDL = [
    ("created_at", "ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER platform"),
]

_KD_COLUMN_DDL = [
    ("kb_id", "ADD COLUMN kb_id BIGINT NULL COMMENT '所属知识库' AFTER user_id"),
]

_NORMALIZE_INDEXES = [
    ("rbac_user_role", "idx_ur_user", "CREATE INDEX idx_ur_user ON rbac_user_role (user_id)"),
    ("rbac_user_role", "idx_ur_role", "CREATE INDEX idx_ur_role ON rbac_user_role (role_id)"),
    ("sys_role_menu", "idx_rm_role", "CREATE INDEX idx_rm_role ON sys_role_menu (role_id)"),
    ("sys_role_menu", "idx_rm_menu", "CREATE INDEX idx_rm_menu ON sys_role_menu (menu_id)"),
    ("chat_sessions", "idx_sessions_user_deleted", "CREATE INDEX idx_sessions_user_deleted ON chat_sessions (user_id, user_deleted)"),
    ("message_feedback", "idx_feedback_message", "CREATE INDEX idx_feedback_message ON message_feedback (message_id)"),
    ("message_feedback", "idx_feedback_user", "CREATE INDEX idx_feedback_user ON message_feedback (user_id)"),
    ("chat_faq", "idx_chat_faq_updated_by", "CREATE INDEX idx_chat_faq_updated_by ON chat_faq (updated_by)"),
    ("daily_question_usage", "idx_usage_user", "CREATE INDEX idx_usage_user ON daily_question_usage (user_id)"),
    ("sys_log_operation", "idx_op_trace", "CREATE INDEX idx_op_trace ON sys_log_operation (trace_id)"),
    ("sys_log_error", "idx_err_trace", "CREATE INDEX idx_err_trace ON sys_log_error (trace_id)"),
    ("sys_log_api_call", "idx_api_trace", "CREATE INDEX idx_api_trace ON sys_log_api_call (trace_id)"),
]

# 历史脚本曾建数据库外键，按阿里规约启动时幂等移除
_LEGACY_DB_FOREIGN_KEYS: list[tuple[str, str]] = [
    ("rbac_user_role", "fk_ur_user"),
    ("rbac_user_role", "fk_ur_role"),
    ("rbac_refresh_token", "fk_refresh_user"),
    ("sys_role_menu", "fk_rm_role"),
    ("sys_role_menu", "fk_rm_menu"),
    ("chat_sessions", "fk_sessions_user"),
    ("chat_messages", "fk_messages_session"),
    ("message_feedback", "fk_feedback_message"),
    ("message_feedback", "fk_feedback_user"),
    ("chat_faq", "fk_chat_faq_updated_by"),
    ("knowledge_bases", "fk_kb_bases_user"),
    ("knowledge_bases", "fk_kb_user"),
    ("knowledge_documents", "fk_kd_user"),
    ("knowledge_documents", "fk_kd_kb"),
    ("knowledge_documents", "fk_kb_user"),
    ("daily_question_usage", "fk_usage_user"),
]


def _ensure_table_columns(conn, table: str, ddl_list: list[tuple[str, str]], log_prefix: str) -> None:
    try:
        rows = conn.execute(text(f"SHOW COLUMNS FROM {table}")).fetchall()
    except Exception:
        return
    existing = {r[0] for r in rows}
    for col, ddl in ddl_list:
        if col in existing:
            continue
        try:
            conn.execute(text(f"ALTER TABLE {table} {ddl}"))
        except Exception as exc:
            logger.warning("[%s|bootstrap|%s.%s|硬编执行|跳过] err=%s", log_prefix, table, col, str(exc)[:120])


def _ensure_rbac_role_columns(conn) -> None:
    _ensure_table_columns(conn, "rbac_role", _RBAC_ROLE_COLUMN_DDL, "RBAC-迁移")


def _ensure_sys_menu_columns(conn) -> None:
    _ensure_table_columns(conn, "sys_menu", _SYS_MENU_COLUMN_DDL, "RBAC-迁移")


def _ensure_knowledge_documents_columns(conn) -> None:
    _ensure_table_columns(conn, "knowledge_documents", _KD_COLUMN_DDL, "知识库-迁移")
    try:
        conn.execute(text("CREATE INDEX idx_kd_kb ON knowledge_documents (kb_id)"))
    except Exception as exc:
        msg = str(exc)
        if "Duplicate" not in msg and "1061" not in msg:
            logger.warning("[知识库-迁移|bootstrap|idx_kd_kb|硬编执行|跳过] err=%s", msg[:120])


def _drop_legacy_db_foreign_keys(conn) -> None:
    """移除历史数据库外键（阿里规约：不在 DB 层建 FK，引用完整性由应用层维护）。"""
    for table, fk_name in _LEGACY_DB_FOREIGN_KEYS:
        try:
            conn.execute(text(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{fk_name}`"))
            logger.info("[结构规范化|bootstrap|drop_fk|硬编执行|完成] table=%s; fk=%s", table, fk_name)
        except Exception as exc:
            msg = str(exc)
            if "1091" in msg or "check that column/key exists" in msg.lower():
                continue
            logger.warning("[结构规范化|bootstrap|drop_fk|硬编执行|跳过] table=%s; fk=%s; err=%s", table, fk_name, msg[:120])


def _ensure_normalize_indexes(conn) -> None:
    for table, idx_name, ddl in _NORMALIZE_INDEXES:
        try:
            rows = conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.statistics "
                    "WHERE table_schema = DATABASE() AND table_name = :t AND index_name = :i"
                ),
                {"t": table, "i": idx_name},
            ).scalar()
            if rows and int(rows) > 0:
                continue
            conn.execute(text(ddl))
        except Exception as exc:
            logger.warning("[结构规范化|bootstrap|%s|硬编执行|跳过] err=%s", idx_name, str(exc)[:120])


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


def _ensure_log_sql_schema(conn) -> None:
    try:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS sys_log_operation_sql (
                  log_id BIGINT PRIMARY KEY AUTO_INCREMENT,
                  operation_log_id BIGINT NOT NULL DEFAULT 0,
                  log_type TINYINT NOT NULL DEFAULT 1 COMMENT '1操作 2调度',
                  cmd_table VARCHAR(128) DEFAULT '',
                  cmd_statement TEXT,
                  cmd_parameters TEXT,
                  cmd_seq INT NOT NULL DEFAULT 0,
                  trace_id VARCHAR(64) DEFAULT '',
                  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  INDEX idx_op_sql_op (operation_log_id),
                  INDEX idx_op_sql_trace (trace_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )
    except Exception as exc:
        logger.warning("[登录模块-迁移|bootstrap|sys_log_operation_sql|硬编执行|跳过] err=%s", str(exc)[:120])


def _ensure_sys_log_operation_columns(conn) -> None:
    try:
        rows = conn.execute(text("SHOW COLUMNS FROM sys_log_operation")).fetchall()
    except Exception:
        return
    existing = {r[0] for r in rows}
    for col, ddl in _LOG_OPERATION_COLUMN_DDL:
        if col in existing:
            continue
        try:
            conn.execute(text(f"ALTER TABLE sys_log_operation {ddl}"))
        except Exception as exc:
            logger.warning("[登录模块-迁移|bootstrap|sys_log_operation.%s|硬编执行|跳过] err=%s", col, str(exc)[:120])


def _ensure_sys_log_error_columns(conn) -> None:
    try:
        rows = conn.execute(text("SHOW COLUMNS FROM sys_log_error")).fetchall()
    except Exception:
        return
    existing = {r[0] for r in rows}
    for col, ddl in _LOG_ERROR_COLUMN_DDL:
        if col in existing:
            continue
        try:
            conn.execute(text(f"ALTER TABLE sys_log_error {ddl}"))
        except Exception as exc:
            logger.warning("[登录模块-迁移|bootstrap|sys_log_error.%s|硬编执行|跳过] err=%s", col, str(exc)[:120])


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
    # 历史「归档删除」→ 用户软删除，管理员审计仍可见
    try:
        conn.execute(
            text(
                """
                UPDATE chat_sessions
                SET user_deleted = 1,
                    user_deleted_at = COALESCE(user_deleted_at, updated_at, NOW()),
                    status = 1
                WHERE status = 0 AND (user_deleted IS NULL OR user_deleted = 0)
                """
            )
        )
    except Exception as exc:
        logger.warning("[会话持久化-迁移|bootstrap|backfill_user_deleted|硬编执行|跳过] err=%s", str(exc)[:120])


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
        _ensure_rbac_role_columns(conn)
        _ensure_sys_menu_columns(conn)
        _ensure_knowledge_documents_columns(conn)
        _drop_legacy_db_foreign_keys(conn)
        _ensure_log_sql_schema(conn)
        _ensure_sys_log_operation_columns(conn)
        _ensure_sys_log_error_columns(conn)
        _ensure_normalize_indexes(conn)
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
        sync_knowledge_menu_group(db)
        sync_profile_menu_group(db)
        sync_agent_settings_menu(db)
        sync_system_rbac_menu(db)
        sync_chat_faq_menu(db)
        sync_user_profile_menu(db)
        backfill_user_no(db)
        from app.services.chat_faq import seed_default_chat_faq

        seed_default_chat_faq(db)
        ensure_bootstrap_admin(db)
        ensure_admin_user(db)
        seed_casbin_policies()
        logger.info("[登录模块-认证|bootstrap|种子|硬编执行|完成] RBAC/菜单/Casbin/user_no 就绪")
    finally:
        db.close()
