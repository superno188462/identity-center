# 身份中心架构与数据模型

## 1. 目标与边界

身份中心回答“这个用户是谁、是否完成认证、允许哪个应用登录”。业务应用回答“这个用户在本应用拥有什么资源”。共享数据服务回答“哪些明确授权的数据可跨应用检索”。

身份中心负责：

- 统一账号与稳定、不含业务语义的 UUID `user_id`；
- 登录凭据、账号状态、会话/授权撤销；
- OIDC Issuer、客户端注册与授权；
- 最少量的通用用户资料与跨应用共享同意记录。

业务应用继续负责：

- `rtc-voice`：语音会话、Agent 记忆、语音偏好及其生命周期；
- `knowledge-platform`：目录、文档、权限、切片关系和 Gateway 向量同步状态；
- 各业务自己的授权规则和用户扩展设置。

身份中心不持有 Gateway API Key，也不直接管理 Gateway 向量数据。业务应用用经过验证的 OIDC `sub` 作为统一 `user_id`，而不是从浏览器请求参数信任任意用户 ID。

## 2. 核心关系

```text
Identity Center (OIDC issuer)
  users(user_id)
     ├── RTC database: voice_conversations(user_id), agent_memory(user_id)
     └── Knowledge database: documents(owner_user_id), access_grants(...)

Gateway
  vector records(owner_user_id, app_id, record_type, sharing_scope, ...)
```

业务数据库可以保存 `user_id` 字段，不复制密码或身份凭据。业务数据必须同时使用本项目的访问控制校验；知道用户 ID 不代表有权访问其数据。

## 3. 建议的数据模型

### Identity Center

- `users`: `id UUID PK`, `status`, `created_at`, `updated_at`, `deleted_at`。
- `user_identities`: `id`, `user_id FK`, `issuer/provider`, `subject`, `normalized_login`, `verified_at`；支持一个账号绑定多种登录方式。
- `password_credentials`: `user_id FK`, `password_hash`, `changed_at`；只保存 Argon2id 等安全哈希，不保存明文密码。若使用外部 IdP，此表可不存在。
- `oidc_clients`: `client_id`, `redirect_uris`, `allowed_scopes`, `status`；客户端密钥仅对有机密能力的服务端客户端使用并安全存放。
- `auth_sessions` / `authorization_codes`: 会话与短时授权状态，存储可撤销的哈希/摘要，不记录原始令牌。
- `user_profiles`: 最少量的通用资料，例如显示名、首选语言；不要把各业务画像揉进此表。
- `profile_consents`: 用户授权的资料范围、用途、授予/撤销时间和来源应用。

### 业务项目数据库

业务表以身份中心 `user_id` 为归属键，例如 `voice_conversations(user_id, ...)`、`knowledge_documents(owner_user_id, ...)`。同一 `user_id` 在不同数据库中是同一自然人，但数据仍由各业务的应用权限控制。

### Gateway 向量 metadata

每条向量记录由写入方提供至少这些归属字段：

```json
{
  "owner_user_id": "identity-center UUID",
  "app_id": "rtc-voice",
  "record_type": "long_term_memory",
  "sharing_scope": "app_private",
  "schema_version": 1
}
```

跨应用共享时，`sharing_scope` 应由明确的授权规则控制，例如 `user_shared`；默认应是 `app_private`。知识文档可使用 `app_id=knowledge-platform`, `record_type=knowledge_chunk`。metadata 用于召回约束和来源追踪，不应被误认为 Gateway 已提供行级授权。

## 4. 重要隔离限制

根据当前 Gateway 项目级 API Key 契约，同一 Gateway 项目下的 Key 具有项目级访问范围，调用者传入 metadata 过滤不等于服务端强制行级 ACL。因此：

1. 每个应用服务端必须从已验证的令牌读取 `sub`，并自行强制添加 `owner_user_id`、`app_id` 和 `sharing_scope` 过滤；不得接受浏览器自由指定这些安全过滤字段。
2. 同一 Gateway 项目适用于可信业务后端之间的逻辑隔离，不适用于需要抵抗某个应用 Key 泄露后的强隔离。
3. 若要求应用间强隔离，应使用独立 Gateway 项目/凭据，或先让 Gateway 支持应用级权限、collection ACL 或行级 ACL；共享资料通过受控服务显式提供。
4. 同一用户 ID 只解决身份关联，不自动产生共享授权。

## 5. 逐步实施

1. 当前已实现本地用户名/密码、opaque session Cookie、限流、通用资料字段和 PostgreSQL schema migration；当前项目仍未实现 OIDC。
2. 确定正式域名、TLS 和客户端清单后实现 Authorization Code + PKCE、Discovery、JWKS、token、userinfo、logout/revocation，供不同根域的应用完成 SSO。
3. 先让一个业务应用接入，保持旧登录只读兼容窗口；为原有账号建立可审计的身份映射。只有经过验证的账号绑定/迁移流程才能合并账户，不能只按用户名猜测。
4. 需要保留业务数据关联时，可以迁移旧账号 UUID 为 canonical `user_id`；两项目已有同一用户但 ID 不同的情况需建立显式账户映射并审核冲突。
5. 验证会话撤销、CSRF/CORS、redirect URI allowlist 和跨应用授权后，再迁移另一个项目。长期记忆的共享必须另有授权策略。
