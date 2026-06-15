-- 用户侧会话软删除字段
-- 由 bootstrap 按列检测执行；本脚本供手工迁移参考

USE haici_cs;

ALTER TABLE chat_sessions
    ADD COLUMN user_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '用户侧软删除1是0否' AFTER status,
    ADD COLUMN user_deleted_at DATETIME NULL COMMENT '用户删除时间' AFTER user_deleted;

-- 历史「归档删除」迁移为用户软删除
UPDATE chat_sessions
SET user_deleted = 1,
    user_deleted_at = COALESCE(user_deleted_at, updated_at, NOW()),
    status = 1
WHERE status = 0 AND user_deleted = 0;
