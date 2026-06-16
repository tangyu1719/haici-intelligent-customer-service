-- =============================================================================
-- 存量库结构规范化 migrate_schema_normalize_v1.sql
-- 幂等：可重复执行；与 schema_full_v1.sql / models.py 对齐
-- 规约：不新增数据库外键，仅补索引；外键清理见 migrate_drop_db_foreign_keys_v1.sql
-- =============================================================================

USE haici_cs;

CREATE INDEX idx_sessions_user_deleted ON chat_sessions (user_id, user_deleted);
CREATE INDEX idx_feedback_message ON message_feedback (message_id);
CREATE INDEX idx_feedback_user ON message_feedback (user_id);
CREATE INDEX idx_op_trace ON sys_log_operation (trace_id);
CREATE INDEX idx_err_trace ON sys_log_error (trace_id);
CREATE INDEX idx_api_trace ON sys_log_api_call (trace_id);
CREATE INDEX idx_kd_kb ON knowledge_documents (kb_id);
CREATE INDEX idx_chat_faq_updated_by ON chat_faq (updated_by);
CREATE INDEX idx_ur_user ON rbac_user_role (user_id);
CREATE INDEX idx_ur_role ON rbac_user_role (role_id);
CREATE INDEX idx_rm_role ON sys_role_menu (role_id);
CREATE INDEX idx_rm_menu ON sys_role_menu (menu_id);
CREATE INDEX idx_usage_user ON daily_question_usage (user_id);
