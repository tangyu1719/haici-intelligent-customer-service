-- 运维 SQL 日志 + 操作/异常日志扩展字段

CREATE TABLE IF NOT EXISTS sys_log_operation_sql (
  log_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  operation_log_id BIGINT NOT NULL DEFAULT 0,
  log_type TINYINT NOT NULL DEFAULT 1 COMMENT '1操作日志 2调度日志',
  cmd_table VARCHAR(128) DEFAULT '',
  cmd_statement TEXT,
  cmd_parameters TEXT,
  cmd_seq INT NOT NULL DEFAULT 0,
  trace_id VARCHAR(64) DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_op_sql_op (operation_log_id),
  INDEX idx_op_sql_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- operate_desc / prog_impl 由 bootstrap 按列检测增量添加
