-- 对话 FAQ 缓存表（管理员在「系统管理 > 对话 FAQ」维护）
CREATE TABLE IF NOT EXISTS chat_faq (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  category VARCHAR(64) NOT NULL DEFAULT '通用',
  question VARCHAR(500) NOT NULL,
  answer TEXT NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  enabled TINYINT NOT NULL DEFAULT 1,
  updated_by BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_chat_faq_enabled (enabled),
  INDEX idx_chat_faq_category (category),
  CONSTRAINT fk_chat_faq_updated_by FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
