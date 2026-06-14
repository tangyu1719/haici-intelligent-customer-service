-- chat_sessions 持久化增强：context_id + meta_json + status
-- 由 bootstrap 按列检测执行；本脚本供手工迁移参考

USE haici_cs;

ALTER TABLE chat_sessions
    ADD COLUMN context_id VARCHAR(36) NULL COMMENT '上下文UUID' AFTER id,
    ADD COLUMN meta_json JSON NULL COMMENT '扩展元数据' AFTER title,
    ADD COLUMN status TINYINT NOT NULL DEFAULT 1 COMMENT '1正常0归档' AFTER meta_json;

UPDATE chat_sessions SET context_id = UUID() WHERE context_id IS NULL OR context_id = '';

ALTER TABLE chat_sessions
    MODIFY context_id VARCHAR(36) NOT NULL,
    ADD UNIQUE KEY uk_sessions_context (context_id);
