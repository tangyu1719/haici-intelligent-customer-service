-- =============================================================================
-- 存量库：移除数据库层外键（对齐阿里规约 / schema_full_v1）
-- 幂等：约束不存在则跳过；启动时 bootstrap 也会自动执行
-- =============================================================================

USE haici_cs;

-- rbac
ALTER TABLE rbac_user_role DROP FOREIGN KEY fk_ur_user;
ALTER TABLE rbac_user_role DROP FOREIGN KEY fk_ur_role;
ALTER TABLE rbac_refresh_token DROP FOREIGN KEY fk_refresh_user;
ALTER TABLE sys_role_menu DROP FOREIGN KEY fk_rm_role;
ALTER TABLE sys_role_menu DROP FOREIGN KEY fk_rm_menu;

-- chat
ALTER TABLE chat_sessions DROP FOREIGN KEY fk_sessions_user;
ALTER TABLE chat_messages DROP FOREIGN KEY fk_messages_session;
ALTER TABLE message_feedback DROP FOREIGN KEY fk_feedback_message;
ALTER TABLE message_feedback DROP FOREIGN KEY fk_feedback_user;
ALTER TABLE chat_faq DROP FOREIGN KEY fk_chat_faq_updated_by;

-- knowledge
ALTER TABLE knowledge_bases DROP FOREIGN KEY fk_kb_bases_user;
ALTER TABLE knowledge_bases DROP FOREIGN KEY fk_kb_user;
ALTER TABLE knowledge_documents DROP FOREIGN KEY fk_kd_user;
ALTER TABLE knowledge_documents DROP FOREIGN KEY fk_kd_kb;

-- quota
ALTER TABLE daily_question_usage DROP FOREIGN KEY fk_usage_user;
