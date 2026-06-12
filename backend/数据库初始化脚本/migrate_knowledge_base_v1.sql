-- 多知识库管理 (PRD 加分项4)
-- 创建时间: 2026-06-13

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    name        VARCHAR(128) NOT NULL COMMENT '知识库名称',
    description VARCHAR(512) DEFAULT NULL COMMENT '知识库描述',
    is_default  TINYINT DEFAULT 0 COMMENT '是否默认知识库 1=是 0=否',
    status      TINYINT DEFAULT 1 COMMENT '状态 1=启用 0=禁用',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_kb_user (user_id),
    CONSTRAINT fk_kb_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库表';

-- 为 knowledge_documents 添加 kb_id 外键（如果不存在）
SET @col_exists = 0;
SELECT COUNT(*) INTO @col_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'knowledge_documents'
  AND COLUMN_NAME = 'kb_id';

SET @sql = IF(@col_exists = 0,
    'ALTER TABLE knowledge_documents ADD COLUMN kb_id BIGINT DEFAULT NULL AFTER user_id, ADD INDEX idx_kd_kb (kb_id)',
    'SELECT "kb_id column already exists" AS msg');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 为管理员用户创建默认知识库
INSERT IGNORE INTO knowledge_bases (user_id, name, description, is_default, status)
SELECT id, '默认知识库', '系统自动创建的默认知识库', 1, 1
FROM users
WHERE username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM knowledge_bases
    WHERE user_id = users.id AND name = '默认知识库'
  );
