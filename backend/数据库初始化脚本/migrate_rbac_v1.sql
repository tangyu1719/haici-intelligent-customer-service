-- 登录模块 RBAC / 菜单 / 日志 / Refresh Token 迁移 v1
-- 日期：2026-06-12
USE haici_cs;

-- 扩展 users（保留 id FK，新增对外 user_no 等）
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS user_no VARCHAR(32) NULL UNIQUE COMMENT '对外Hash数字码' AFTER id,
  ADD COLUMN IF NOT EXISTS username VARCHAR(64) NULL UNIQUE COMMENT '登录名' AFTER user_no,
  ADD COLUMN IF NOT EXISTS nickname VARCHAR(64) NOT NULL DEFAULT '' AFTER phone,
  ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(512) NOT NULL DEFAULT '' AFTER nickname,
  ADD COLUMN IF NOT EXISTS status TINYINT NOT NULL DEFAULT 1 COMMENT '1启用0禁用' AFTER avatar_url,
  ADD COLUMN IF NOT EXISTS updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER created_at;

-- MySQL 8.0.12 不支持 IF NOT EXISTS on ADD COLUMN，若报错请手工跳过已存在列
-- 允许短信静默注册暂无密码
ALTER TABLE users MODIFY password_hash VARCHAR(255) NULL;

CREATE TABLE IF NOT EXISTS rbac_role (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  code VARCHAR(32) NOT NULL UNIQUE,
  name VARCHAR(64) NOT NULL,
  status TINYINT NOT NULL DEFAULT 1,
  remark VARCHAR(255) DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rbac_user_role (
  user_id BIGINT NOT NULL,
  role_id BIGINT NOT NULL,
  PRIMARY KEY (user_id, role_id),
  CONSTRAINT fk_ur_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_ur_role FOREIGN KEY (role_id) REFERENCES rbac_role(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rbac_refresh_token (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  token_hash VARCHAR(64) NOT NULL,
  expires_at DATETIME NOT NULL,
  revoked TINYINT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at DATETIME NULL,
  INDEX idx_refresh_user (user_id),
  INDEX idx_refresh_hash (token_hash),
  CONSTRAINT fk_refresh_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rbac_verify_code (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  target VARCHAR(128) NOT NULL,
  code VARCHAR(10) NOT NULL,
  type VARCHAR(16) NOT NULL COMMENT 'sms|email',
  purpose VARCHAR(32) NOT NULL DEFAULT 'login',
  expires_at DATETIME NOT NULL,
  used TINYINT NOT NULL DEFAULT 0,
  attempts INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_verify_target (target, type, purpose)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sys_menu (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  parent_id BIGINT NOT NULL DEFAULT 0,
  name VARCHAR(64) NOT NULL,
  menu_type CHAR(1) NOT NULL COMMENT 'M目录 C菜单 F按钮',
  path VARCHAR(128) DEFAULT '',
  component VARCHAR(128) DEFAULT '',
  permission VARCHAR(128) NULL UNIQUE,
  icon VARCHAR(64) DEFAULT '',
  sort_order INT NOT NULL DEFAULT 0,
  visible TINYINT NOT NULL DEFAULT 1,
  status TINYINT NOT NULL DEFAULT 1,
  platform VARCHAR(32) NOT NULL DEFAULT 'haici',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sys_role_menu (
  role_id BIGINT NOT NULL,
  menu_id BIGINT NOT NULL,
  PRIMARY KEY (role_id, menu_id),
  CONSTRAINT fk_rm_role FOREIGN KEY (role_id) REFERENCES rbac_role(id) ON DELETE CASCADE,
  CONSTRAINT fk_rm_menu FOREIGN KEY (menu_id) REFERENCES sys_menu(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS casbin_rule (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  ptype VARCHAR(32) NOT NULL,
  v0 VARCHAR(255) DEFAULT '',
  v1 VARCHAR(255) DEFAULT '',
  v2 VARCHAR(255) DEFAULT '',
  v3 VARCHAR(255) DEFAULT '',
  v4 VARCHAR(255) DEFAULT '',
  v5 VARCHAR(255) DEFAULT '',
  INDEX idx_casbin_ptype (ptype)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sys_log_operation (
  log_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  operate_no VARCHAR(64) NOT NULL,
  user_id BIGINT NULL,
  user_no VARCHAR(32) NULL,
  module VARCHAR(64) DEFAULT '',
  menu_permission VARCHAR(128) DEFAULT '',
  url VARCHAR(512) DEFAULT '',
  method VARCHAR(16) DEFAULT '',
  input_value TEXT,
  return_value TEXT,
  client_ip VARCHAR(64) DEFAULT '',
  time_consume_ms INT DEFAULT 0,
  status TINYINT DEFAULT 1,
  trace_id VARCHAR(64) DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_op_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sys_log_error (
  log_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  operate_no VARCHAR(64) DEFAULT '',
  error_type TINYINT DEFAULT 1 COMMENT '1系统2操作3API',
  url VARCHAR(512) DEFAULT '',
  module VARCHAR(64) DEFAULT '',
  error_message TEXT,
  trace_id VARCHAR(64) DEFAULT '',
  client_ip VARCHAR(64) DEFAULT '',
  input_value TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_err_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sys_log_api_call (
  log_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  trace_id VARCHAR(64) DEFAULT '',
  api_type VARCHAR(32) DEFAULT 'llm',
  target_url VARCHAR(512) DEFAULT '',
  method VARCHAR(16) DEFAULT 'POST',
  request_summary TEXT,
  response_summary TEXT,
  status_code INT DEFAULT 0,
  time_consume_ms INT DEFAULT 0,
  success TINYINT DEFAULT 1,
  error_message TEXT,
  user_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_api_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sys_log_schedule (
  log_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  job_name VARCHAR(128) DEFAULT '',
  job_group VARCHAR(64) DEFAULT '',
  job_desc VARCHAR(255) DEFAULT '',
  start_time DATETIME NULL,
  end_time DATETIME NULL,
  execute_state TINYINT DEFAULT 0,
  job_info TEXT,
  error_msg TEXT,
  job_tag VARCHAR(128) DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO rbac_role (code, name) VALUES ('admin', '管理员'), ('viewer', '普通用户');
