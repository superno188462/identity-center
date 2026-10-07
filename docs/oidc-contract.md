# OIDC 登录/API 契约草案

本文件区分当前已经实现的本地账号接口和下一阶段的 OIDC 契约。当前 API 使用服务端 opaque Cookie 会话；OIDC Authorization Code + PKCE 尚未实现。

## 当前已实现的账号接口

所有路径前缀为 `/api/auth`。注册成功自动建立会话；注册仅创建普通用户，不允许客户端指定角色。跨域浏览器请求必须启用 credentials，并将前端 origin 加入 `CORS_ALLOW_ORIGINS`。

| Method / path | 行为 |
| --- | --- |
| `POST /register` | `{ "username": "...", "password": "..." }`；成功返回 201、`user` 对象并设置 `identity_session` HttpOnly Cookie |
| `POST /login` | 同一凭据结构；成功返回 `user` 并设置会话 Cookie |
| `GET /me` | 校验 Cookie 后返回 canonical `user.id` |
| `POST /logout` | 撤销当前服务端会话并清除 Cookie |
| `GET /me/profile` | 读取最小通用资料 |
| `PATCH /me/profile` | 更新 `display_name` 和/或 `preferred_language` |

错误以 FastAPI `detail.code` 表示，包括 `USERNAME_TAKEN`、`USERNAME_LENGTH`、`USERNAME_FORMAT`、`PASSWORD_TOO_SHORT`、`PASSWORD_TOO_LONG`、`INVALID_CREDENTIALS`、`LOGIN_RATE_LIMITED`、`REGISTRATION_DISABLED` 和 `AUTH_REQUIRED`。用户名长度 3–64；密码长度 8–128。重复账号返回 409，验证失败返回 422，登录失败返回相同的 401 错误，限流返回 429 和 `Retry-After`。

当前 Cookie 名为 `identity_session`，由身份中心自己校验。若语音与知识库前端部署于同一父域子域，可在 HTTPS 下配置共享父域 Cookie；若应用位于不同根域，浏览器不会将该 Cookie 自动共享给各应用，必须接入下面规划的 OIDC 流程。

## 下一阶段 OIDC 契约

以下 OIDC 端点仍是规划，不会出现在当前 OpenAPI 中。浏览器应用不持有 client secret。

## 浏览器登录流程

1. 应用把浏览器重定向到身份中心 `/authorize`，携带已注册的 `client_id`、精确匹配的 `redirect_uri`、`response_type=code`、`scope=openid profile`、随机 `state`、`nonce` 和 PKCE `code_challenge`。
2. 身份中心认证用户并征求所需授权，随后仅重定向到注册的 URI，返回短时、单次使用的 `code` 和原样 `state`。
3. 应用后端使用 `code_verifier` 在 `/token` 兑换令牌；服务端校验签名、issuer、audience、expiry、nonce 和 state。
4. 应用以令牌 `sub` 作为本项目稳定 `user_id`。应用 API 从已验证令牌提取身份，不接受客户端传入的 `user_id` 作为权限依据。

## 目标端点

| Endpoint | 目的 |
| --- | --- |
| `GET /.well-known/openid-configuration` | 发布 issuer、端点、支持的 grant/response type、签名算法 |
| `GET /.well-known/jwks.json` | 发布可轮换的公钥集合；绝不发布私钥 |
| `GET /authorize` | 校验 client、redirect URI、scope、state、PKCE 并建立用户授权 |
| `POST /token` | 兑换授权码；验证 PKCE、单次使用、过期和 client |
| `GET /userinfo` | 根据 scope 返回最小用户 claims |
| `POST /revoke` | 撤销支持的 token/session |
| `POST /logout` | 结束身份中心会话并清理身份中心自己的 Cookie |
| `GET /api/v1/me/profile` | 获取当前用户允许共享的通用资料 |
| `PATCH /api/v1/me/profile` | 更新用户可编辑的通用资料 |
| `GET /api/v1/me/consents` | 查看当前用户授权给应用的资料范围 |
| `DELETE /api/v1/me/consents/{client_id}` | 撤销应用的资料授权 |

## Token / Claims

ID Token 至少包含 `iss`, `sub`, `aud`, `exp`, `iat`, `nonce`。`sub` 是稳定 UUID；应用私有资料不放在 ID Token 中。访问令牌采用短有效期，并绑定 audience/scope；不要把长期 refresh token 放入浏览器 localStorage。

应用客户端分别注册。例如 `rtc-voice-web` 与 `knowledge-web` 使用各自 allowlisted redirect URI 和所需 scopes。token 的 `aud` 必须匹配具体业务 API；一个应用不可拿另一个应用的 audience token 调用其 API。

## 错误约定

错误 JSON 使用机器可读 `error` 和非敏感 `error_description`。至少覆盖 `invalid_request`, `unauthorized_client`, `invalid_grant`, `invalid_scope`, `access_denied`, `temporarily_unavailable`。不得返回密码校验细节、授权码、令牌、原始凭据或堆栈。

## 未决配置（真实登录实现前必须确定）

- 正式 issuer 域名与 TLS/反向代理可信配置；
- 账号标识与验证方式（邮箱、用户名或外部身份提供方）；
- 邮件验证、密码重置、MFA 和账号恢复；
- 每个应用的 client、redirect URI、scope、audience 与 logout URI；
- 私钥/KMS、密钥轮换、访问审计、限流和备份策略；
- 业务应用现有账号到 canonical `sub` 的安全迁移规则。
