# 数据库初始化脚本说明

## 新环境（推荐）

```powershell
# 在项目 backend/数据库初始化脚本 目录下
Get-Content schema_full_v1.sql | mysql -h127.0.0.1 -P3306 -uroot -p
```

创建库 `haici_cs`，含 **20 张表**，与 `app/models.py` 一致。

## 已有环境

直接启动后端即可；`app/auth/bootstrap.py` 会：

1. `Base.metadata.create_all` 补建新表
2. 按列检测 `ALTER TABLE` 补齐缺失字段
3. **移除历史数据库外键**（阿里规约）
4. 创建规范化索引（**不建 FK**）

也可手工参考 `migrate_schema_normalize_v1.sql`。

## 文件索引

| 文件 | 说明 |
|------|------|
| schema_full_v1.sql | **权威全量 DDL** |
| init.sql | 新环境入口说明 |
| migrate_*.sql | 历史增量脚本（供查阅/手工执行） |
| seed_kb/ | 样例 Markdown 知识库 |

详细设计见 `docxl/数据库设计.md`。
