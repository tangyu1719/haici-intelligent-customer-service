-- =============================================================================
-- HaiCi 智能客服 — 权威全量建表脚本 schema_full_v1.sql
-- 与 backend/app/models.py 一一对应；新环境优先执行本脚本。
-- 规约：不在数据库层建外键（阿里/MySQL 线上惯例），关联字段仅索引，引用完整性由应用层维护。
-- 命名规范见 docs/数据库设计.md
-- =============================================================================

CREATE DATABASE IF NOT EXISTS haici_cs
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE haici_cs;

-- -----------------------------------------------------------------------------
-- 1. 用户与认证
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
  id            BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
  user_no       VARCHAR(32)  NULL     COMMENT '对外用户编号（Hash）',
  username      VARCHAR(64)  NULL     COMMENT '登录名',
  email         VARCHAR(128) NULL     COMMENT '邮箱',
  phone         VARCHAR(20)  NULL     COMMENT '手机号',
  password_hash VARCHAR(255) NULL     COMMENT 'bcrypt 哈希，短信注册可为空',
  nickname      VARCHAR(64)  NOT NULL DEFAULT '' COMMENT '昵称',
  avatar_url    VARCHAR(512) NOT NULL DEFAULT '' COMMENT '头像 URL',
  status        TINYINT      NOT NULL DEFAULT 1 COMMENT '1=启用 0=禁用',
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NULL     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_users_user_no (user_no),
  UNIQUE KEY uk_users_username (username),
  UNIQUE KEY uk_users_email (email),
  UNIQUE KEY uk_users_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

CREATE TABLE IF NOT EXISTS rbac_role (
  id         BIGINT      NOT NULL AUTO_INCREMENT,
  code       VARCHAR(32) NOT NULL COMMENT '角色编码 admin/viewer',
  name       VARCHAR(64) NOT NULL COMMENT '角色名称',
  status     TINYINT     NOT NULL DEFAULT 1 COMMENT '1=启用 0=禁用',
  remark     VARCHAR(255) NOT NULL DEFAULT '' COMMENT '备注',
  created_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_rbac_role_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='RBAC 角色';

CREATE TABLE IF NOT EXISTS rbac_user_role (
  user_id BIGINT NOT NULL,
  role_id BIGINT NOT NULL,
  PRIMARY KEY (user_id, role_id),
  INDEX idx_ur_user (user_id),
  INDEX idx_ur_role (role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户-角色关联';

CREATE TABLE IF NOT EXISTS rbac_refresh_token (
  id           BIGINT      NOT NULL AUTO_INCREMENT,
  user_id      BIGINT      NOT NULL,
  token_hash   VARCHAR(64) NOT NULL,
  expires_at   DATETIME    NOT NULL,
  revoked      TINYINT     NOT NULL DEFAULT 0 COMMENT '1=已吊销',
  created_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at DATETIME    NULL,
  PRIMARY KEY (id),
  INDEX idx_refresh_user (user_id),
  INDEX idx_refresh_hash (token_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Refresh Token';

CREATE TABLE IF NOT EXISTS rbac_verify_code (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  target     VARCHAR(128) NOT NULL COMMENT '手机/邮箱',
  code       VARCHAR(10)  NOT NULL,
  type       VARCHAR(16)  NOT NULL COMMENT 'sms|email',
  purpose    VARCHAR(32)  NOT NULL DEFAULT 'login',
  expires_at DATETIME     NOT NULL,
  used       TINYINT      NOT NULL DEFAULT 0,
  attempts   INT          NOT NULL DEFAULT 0,
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_verify_target (target, type, purpose)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='验证码';

-- -----------------------------------------------------------------------------
-- 2. 菜单与 Casbin
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sys_menu (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  parent_id  BIGINT       NOT NULL DEFAULT 0,
  name       VARCHAR(64)  NOT NULL,
  menu_type  CHAR(1)      NOT NULL COMMENT 'M=目录 C=菜单 F=按钮',
  path       VARCHAR(128) NOT NULL DEFAULT '',
  component  VARCHAR(128) NOT NULL DEFAULT '',
  permission VARCHAR(128) NULL COMMENT '权限标识',
  icon       VARCHAR(64)  NOT NULL DEFAULT '',
  sort_order INT          NOT NULL DEFAULT 0,
  visible    TINYINT      NOT NULL DEFAULT 1,
  status     TINYINT      NOT NULL DEFAULT 1,
  platform   VARCHAR(32)  NOT NULL DEFAULT 'haici',
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sys_menu_permission (permission)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统菜单';

CREATE TABLE IF NOT EXISTS sys_role_menu (
  role_id BIGINT NOT NULL,
  menu_id BIGINT NOT NULL,
  PRIMARY KEY (role_id, menu_id),
  INDEX idx_rm_role (role_id),
  INDEX idx_rm_menu (menu_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='角色-菜单关联';

CREATE TABLE IF NOT EXISTS casbin_rule (
  id    BIGINT       NOT NULL AUTO_INCREMENT,
  ptype VARCHAR(32)  NOT NULL,
  v0    VARCHAR(255) NOT NULL DEFAULT '',
  v1    VARCHAR(255) NOT NULL DEFAULT '',
  v2    VARCHAR(255) NOT NULL DEFAULT '',
  v3    VARCHAR(255) NOT NULL DEFAULT '',
  v4    VARCHAR(255) NOT NULL DEFAULT '',
  v5    VARCHAR(255) NOT NULL DEFAULT '',
  PRIMARY KEY (id),
  INDEX idx_casbin_ptype (ptype)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Casbin 策略';

-- -----------------------------------------------------------------------------
-- 3. 对话与反馈
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS chat_sessions (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  context_id      VARCHAR(36)  NOT NULL COMMENT '上下文 UUID，链路追踪',
  user_id         BIGINT       NOT NULL,
  title           VARCHAR(200) NOT NULL DEFAULT '新对话',
  meta_json       JSON         NULL COMMENT '扩展：message_count/last_intent/note/pinned',
  status          TINYINT      NOT NULL DEFAULT 1 COMMENT '1=正常 0=归档',
  user_deleted    TINYINT      NOT NULL DEFAULT 0 COMMENT '用户侧软删 1=是',
  user_deleted_at DATETIME     NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sessions_context (context_id),
  INDEX idx_sessions_user (user_id),
  INDEX idx_sessions_user_deleted (user_id, user_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天会话';

CREATE TABLE IF NOT EXISTS chat_messages (
  id              BIGINT NOT NULL AUTO_INCREMENT,
  session_id      BIGINT NOT NULL,
  role            ENUM('user','assistant','system') NOT NULL,
  content         TEXT   NOT NULL,
  intent_label    VARCHAR(32) NULL,
  citations_json  JSON   NULL COMMENT 'RAG 引用切片',
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_messages_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天消息';

CREATE TABLE IF NOT EXISTS message_feedback (
  id                    BIGINT NOT NULL AUTO_INCREMENT,
  message_id            BIGINT NOT NULL,
  user_id               BIGINT NOT NULL,
  rating                TINYINT NOT NULL COMMENT '1-5 星',
  intent_liked          TINYINT NULL COMMENT '意图理解 1=赞 0=踩',
  context_snapshot_json JSON   NULL COMMENT '反馈上下文快照',
  comment               VARCHAR(500) NULL,
  created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_feedback_user_message (message_id, user_id),
  INDEX idx_feedback_message (message_id),
  INDEX idx_feedback_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='消息反馈';

CREATE TABLE IF NOT EXISTS chat_faq (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  category   VARCHAR(64)  NOT NULL DEFAULT '通用',
  question   VARCHAR(500) NOT NULL,
  answer     TEXT         NOT NULL,
  sort_order INT          NOT NULL DEFAULT 0,
  enabled    TINYINT      NOT NULL DEFAULT 1,
  updated_by BIGINT       NULL,
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_chat_faq_enabled (enabled),
  INDEX idx_chat_faq_category (category),
  INDEX idx_chat_faq_updated_by (updated_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='对话 FAQ 缓存';

-- -----------------------------------------------------------------------------
-- 4. 知识库
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS knowledge_bases (
  id          BIGINT       NOT NULL AUTO_INCREMENT,
  user_id     BIGINT       NOT NULL,
  name        VARCHAR(128) NOT NULL,
  description VARCHAR(512) NULL,
  is_default  TINYINT      NOT NULL DEFAULT 0 COMMENT '1=默认库',
  status      TINYINT      NOT NULL DEFAULT 1 COMMENT '1=启用 0=禁用',
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_kb_bases_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库';

CREATE TABLE IF NOT EXISTS knowledge_documents (
  id            BIGINT       NOT NULL AUTO_INCREMENT,
  user_id       BIGINT       NOT NULL,
  kb_id         BIGINT       NULL COMMENT '所属知识库',
  filename      VARCHAR(255) NOT NULL,
  storage_path  VARCHAR(512) NOT NULL,
  status        ENUM('processing','ready','failed') NOT NULL DEFAULT 'processing',
  chunk_count   INT          NOT NULL DEFAULT 0,
  error_message VARCHAR(500) NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_kd_user (user_id),
  INDEX idx_kd_kb (kb_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库文档';

-- -----------------------------------------------------------------------------
-- 5. 配额
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS daily_question_usage (
  id             BIGINT NOT NULL AUTO_INCREMENT,
  user_id        BIGINT NOT NULL,
  usage_date     DATE   NOT NULL,
  question_count INT    NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uk_usage_user_date (user_id, usage_date),
  INDEX idx_usage_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='每日提问配额';

-- -----------------------------------------------------------------------------
-- 6. 审计与运维日志（主键统一 log_id）
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sys_log_operation (
  log_id          BIGINT       NOT NULL AUTO_INCREMENT,
  operate_no      VARCHAR(64)  NOT NULL,
  user_id         BIGINT       NULL,
  user_no         VARCHAR(32)  NULL,
  module          VARCHAR(64)  NOT NULL DEFAULT '',
  menu_permission VARCHAR(128) NOT NULL DEFAULT '',
  operate_desc    VARCHAR(255) NOT NULL DEFAULT '' COMMENT '操作描述',
  url             VARCHAR(512) NOT NULL DEFAULT '',
  method          VARCHAR(16)  NOT NULL DEFAULT '',
  input_value     TEXT         NULL,
  return_value    TEXT         NULL,
  client_ip       VARCHAR(64)  NOT NULL DEFAULT '',
  time_consume_ms INT          NOT NULL DEFAULT 0,
  status          TINYINT      NOT NULL DEFAULT 1 COMMENT '1=成功 0=失败',
  trace_id        VARCHAR(64)  NOT NULL DEFAULT '',
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (log_id),
  INDEX idx_op_created (created_at),
  INDEX idx_op_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='操作审计日志';

CREATE TABLE IF NOT EXISTS sys_log_error (
  log_id        BIGINT       NOT NULL AUTO_INCREMENT,
  operate_no    VARCHAR(64)  NOT NULL DEFAULT '',
  error_type    TINYINT      NOT NULL DEFAULT 1 COMMENT '1=系统 2=操作 3=API',
  url           VARCHAR(512) NOT NULL DEFAULT '',
  module        VARCHAR(64)  NOT NULL DEFAULT '',
  error_message TEXT         NULL,
  prog_impl     VARCHAR(512) NULL DEFAULT '' COMMENT '代码定位',
  trace_id      VARCHAR(64)  NOT NULL DEFAULT '',
  client_ip     VARCHAR(64)  NOT NULL DEFAULT '',
  input_value   TEXT         NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (log_id),
  INDEX idx_err_created (created_at),
  INDEX idx_err_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='异常日志';

CREATE TABLE IF NOT EXISTS sys_log_api_call (
  log_id            BIGINT       NOT NULL AUTO_INCREMENT,
  trace_id          VARCHAR(64)  NOT NULL DEFAULT '',
  api_type          VARCHAR(32)  NOT NULL DEFAULT 'llm',
  target_url        VARCHAR(512) NOT NULL DEFAULT '',
  method            VARCHAR(16)  NOT NULL DEFAULT 'POST',
  request_summary   TEXT         NULL,
  response_summary  TEXT         NULL,
  status_code       INT          NOT NULL DEFAULT 0,
  time_consume_ms   INT          NOT NULL DEFAULT 0,
  success           TINYINT      NOT NULL DEFAULT 1,
  error_message     TEXT         NULL,
  user_id           BIGINT       NULL,
  created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (log_id),
  INDEX idx_api_created (created_at),
  INDEX idx_api_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='外部 API 调用日志';

CREATE TABLE IF NOT EXISTS sys_log_schedule (
  log_id        BIGINT       NOT NULL AUTO_INCREMENT,
  job_name      VARCHAR(128) NOT NULL DEFAULT '',
  job_group     VARCHAR(64)  NOT NULL DEFAULT '',
  job_desc      VARCHAR(255) NOT NULL DEFAULT '',
  start_time    DATETIME     NULL,
  end_time      DATETIME     NULL,
  execute_state TINYINT      NOT NULL DEFAULT 0,
  job_info      TEXT         NULL,
  error_msg     TEXT         NULL,
  job_tag       VARCHAR(128) NOT NULL DEFAULT '',
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (log_id),
  INDEX idx_sched_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='定时任务日志';

CREATE TABLE IF NOT EXISTS sys_log_operation_sql (
  log_id           BIGINT NOT NULL AUTO_INCREMENT,
  operation_log_id BIGINT NOT NULL DEFAULT 0,
  log_type         TINYINT NOT NULL DEFAULT 1 COMMENT '1=操作 2=调度',
  cmd_table        VARCHAR(128) NOT NULL DEFAULT '',
  cmd_statement    TEXT NULL,
  cmd_parameters   TEXT NULL,
  cmd_seq          INT NOT NULL DEFAULT 0,
  trace_id         VARCHAR(64) NOT NULL DEFAULT '',
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (log_id),
  INDEX idx_op_sql_op (operation_log_id),
  INDEX idx_op_sql_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='SQL 追踪日志';

-- -----------------------------------------------------------------------------
-- 7. 种子数据（幂等）
-- -----------------------------------------------------------------------------

INSERT IGNORE INTO rbac_role (code, name) VALUES
  ('admin', '管理员'),
  ('viewer', '普通用户');
