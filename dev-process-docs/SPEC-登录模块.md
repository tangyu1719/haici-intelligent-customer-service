# SPEC · 登录模块（认证 / RBAC / 菜单 / 运维日志）

> **模块**：登录与认证授权  
> **版本**：v0.4  
> **日期**：2026-06-12  
> **状态**：已裁决 · 实施中  
> **产品需求文档**：`HaiCi笔试_AI 智能客服系统_PRD.md`（只读）

**最高原则**：一切需求 **PRD 优先**；SPEC 可迭代，PRD 不可改。

---

## 1. 用户对外标识 `user_no`（Hash，非自增）

自增 ID 易泄露业务量，**禁止**对外使用 `id`。采用 **不可逆 Hash 映射** 生成 10 位数字对外码（比裸 UUID 更贴近企业用户编号习惯，且不可推测下一号）。

### 1.1 算法（实现见 `app/auth/user_no.py`）

```text
raw = uuid7_bytes || server_secret || nanotime || random(16B)
digest = SHA-256(raw)
user_no = str(1_000_000_000 + (int(digest[:8], 16) % 9_000_000_000))  # 固定 10 位，首位非 0
冲突则重算（最多 5 次）
```

- **内部** `users.id`：BIGINT，仅 FK / JWT `sub`
- **对外** `user_no`：10 位数字串，API/界面展示
- **短信静默注册默认昵称**：`小鱼儿_{user_no}`

---

## 2. 登录逻辑（定稿 2026-06-12）

### 2.1 方式 A：手机号 + 短信验证码

| 步骤 | 行为 |
|------|------|
| 1 | 用户输入手机号，获取验证码 `POST /auth/send-code`（purpose=login） |
| 2 | `POST /auth/login` `{ login_type:"sms", identifier:手机号, credential:验证码 }` |
| 3 | **手机号已存在** → 校验验证码 → 直接登录，签发 access + refresh |
| 4 | **手机号不存在** → 校验验证码通过 → **静默注册**：仅写 phone、user_no、nickname=`小鱼儿_{user_no}`，email/密码为空占位 → 直接登录 |
| 5 | 前端可 Toast：「已为您创建账号」 |

> 不在白名单也走静默注册（Owner：不在库即自动开户，字段默认）。

### 2.2 方式 B：手机号 / 邮箱 / 用户名 + 密码（主登录入口，v0.5）

| 步骤 | 行为 |
|------|------|
| 1 | 登录页默认：**手机号 / 邮箱 / 用户名 + 密码** |
| 2 | `POST /auth/login` `{ login_type:"password", identifier, credential }` |
| 3 | 底部链接：**手机号验证码免注册登录**（跳转短信子流程，逻辑同 2.1） |
| 4 | 独立按钮 **「注册账号」** → 注册页（邮箱必填） |

### 2.3 内置管理员（开发/演示，v0.5）

| 字段 | 值 |
|------|-----|
| 用户名 | `admin` |
| 密码 | `admin` |
| 角色 | `admin` |
| 种子 | `ensure_bootstrap_admin()` 启动时写入/重置 |

> 生产环境须修改或禁用默认账密。

### 2.4 Token

- access：30 分钟；refresh：30 天；`POST /auth/refresh` 轮换 refresh（滑动续期）

---

## 3. 注册逻辑（定稿）

### 3.1 邮箱 + 验证码 + 密码（主注册入口）

| 字段 | 必填 |
|------|------|
| email | ✅ |
| password | ✅ |
| code | ✅ 邮箱验证码 |
| nickname / username | ❌ 可选，可空 |

`POST /auth/register` → 默认角色 `viewer` → 返回 token 或引导登录。

### 3.2 手机号

- **不在注册页强制绑定**；登录后可于 **个人中心** `PATCH /auth/profile` 绑定手机（+ 验证码）。

---

## 4. PRD 菜单树（父级 · sys_menu 种子）

见 v0.3 章节 4：智能客服（对话/会话历史）· 知识库 · 个人中心 · 运维管理（admin）。

---

## 5. RBAC · 双轨 · 权限 UI

- UI：`sys_menu` + `sys_role_menu`；无权限 **不显示**；直链 **弹窗**「无权限，请向管理员申请权限」
- API：Casbin；`/api/v1/system/llm-gateway` 需登录

---

## 6. 运维四类日志（对标 WMS）

`sys_log_operation` · `sys_log_error` · `sys_log_api_call` · `sys_log_schedule`（预留）

---

## 7. 前端

- 独立 **`/login`** 路由页（非弹窗）
- Vue Router + `beforeEach` 权限守卫
- 侧栏菜单来自 `GET /auth/menus`

---

## 8. 验收要点

- [x] 手机验证码：老用户直登；新用户静默注册 `小鱼儿_{user_no}`（TestClient 已验）
- [x] 邮箱验证码注册；手机个人中心后绑（API 已验）
- [x] 邮箱/手机 + 密码登录
- [x] user_no 为 Hash 10 位，非自增暴露
- [x] refresh 滑动续期 30 天（实现于 `security.py`）
- [x] 独立 `/login` + Vue Router + `/auth/menus` 侧栏
- [ ] PRD 会话历史页（路由已有，待增强详情）
- [ ] 运维四类日志中间件 + admin 页
- [x] Casbin 正式接入（`casbin_rule` + 原生 Enforcer；pycasbin 可用时自动切换）
- [x] 运维四类日志中间件 + admin 只读 API/页面
- [x] 会话历史详情 + 消息回放（`GET /sessions/{id}`）

---

*实施清单见仓库 `backend/app/auth/`、`backend/数据库初始化脚本/migrate_rbac_v1.sql`*
