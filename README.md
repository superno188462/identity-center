# Identity Center

跨项目统一身份与用户资料服务。当前实现包含用户名密码注册/登录、可撤销服务端会话、最小通用资料 API 和 PostgreSQL 持久化。**OIDC/单点登录尚未实现**；跨不同站点部署时不能把当前 Cookie 接口当成完整 SSO。

## 目标

- 让语音、知识库等业务应用通过同一身份中心登录，并获得同一个稳定 `user_id`。
- 维护账号、登录凭据、统一用户 ID、最小通用资料和登录会话。
- 业务应用继续在各自数据库中维护自己的会话、文档、偏好和业务状态；用身份中心提供的 `sub` 作为关联键。
- 仅在明确授权后共享用户资料或记忆。身份中心不负责知识库文档和向量生命周期，也不持有业务项目的 Gateway Key。

## 当前可运行内容

```powershell
Copy-Item .env.example .env
# 修改 .env 中的 DATABASE_URL，指向 identity_center 专用 PostgreSQL 数据库
uv sync
uv run alembic upgrade head
uv run python main.py
```

默认监听 `127.0.0.1:8002`。需要更换端口时运行 `uv run python main.py --port 8010`。`GET /health` 检查 API 进程是否存活；`GET /ready` 会实际探测数据库（执行 `SELECT 1`），数据库不可用时返回 HTTP 503。打开 `http://127.0.0.1:8002/docs` 查看接口文档。

Swagger 的注册请求示例：

```json
{
  "username": "demo-user",
  "password": "replace-with-a-long-password"
}
```

首次使用前，需先创建 PostgreSQL 数据库并在 `.env` 配置 `DATABASE_URL`。身份中心应使用自己的数据库，不要直接复用语音或知识库项目的业务数据库。

登录接口可在 `http://127.0.0.1:8002/docs` 查看：`POST /api/auth/register`、`POST /api/auth/login`、`GET /api/auth/me`、`POST /api/auth/logout`。注册成功会自动登录；会话通过 `HttpOnly` Cookie 返回，浏览器调用需启用 credentials。通用资料通过 `GET/PATCH /api/auth/me/profile` 管理。

## 设计文档

- [系统边界、数据模型与演进步骤](docs/architecture.md)
- [OIDC 登录与 API 契约草案](docs/oidc-contract.md)

## 安全与实施状态

当前 MVP 沿用语音项目的服务端 opaque 会话方案：Cookie 只保存随机 token，数据库只保存 SHA-256 摘要，密码使用 `pwdlib` 推荐的 Argon2 哈希，登录失败按用户名/IP 哈希限流。部署在同一父域的子域时可配置 `AUTH_COOKIE_DOMAIN` 共享身份中心 Cookie；不同根域之间需要后续实现 OIDC Authorization Code + PKCE，不能通过 CORS 或复制 Cookie 获得可靠 SSO。

生产环境必须使用 HTTPS、独立数据库、强数据库凭据和正确的 `CORS_ALLOW_ORIGINS`；设置 `APP_ENV=production` 使 Cookie 默认启用 Secure。公开注册可通过 `AUTH_ALLOW_REGISTRATION=false` 关闭。身份中心尚未提供邮箱验证、密码重置、MFA、OIDC 或前端页面。

## 服务器 Docker 部署

当前 Compose 部署身份中心 API 容器，并连接 `DATABASE_URL` 指定的 PostgreSQL；不会自动创建 PostgreSQL 数据库。先在 PostgreSQL 中创建 `identity_center` 数据库和有权限的专用账号。

1. 将项目代码复制到服务器，并确认服务器已安装 Docker Engine 和 Docker Compose 插件。
2. 创建部署环境文件：

   ```bash
   cp docker/identity-center.env.example docker/identity-center.env
   ```

3. 编辑 `identity-center.env`：设置真实 `DATABASE_URL`、强数据库密码，以及浏览器实际访问的前端 Origin。模板默认使用 `host.docker.internal`，适用于 PostgreSQL 安装在同一台 Linux 宿主机的情况（Compose 已配置 host-gateway 映射）；远程数据库请改成服务器可达的私网地址或域名。密码中的特殊字符应 URL 编码；此文件已加入 Git 和 Docker 构建忽略规则，不要提交或放进镜像。
4. 确保 PostgreSQL 网络策略允许 Docker 容器访问数据库（包括 `listen_addresses`、`pg_hba.conf` 和服务器防火墙）；连接地址不能写 `localhost`，除非数据库确实在同一个容器中。
5. 通过 Nginx 反向代理到宿主机 `127.0.0.1:8002`，并启用 HTTPS。生产 Cookie 使用 `Secure`，因此浏览器应通过 HTTPS 访问。
6. 在项目目录启动：

   ```bash
   docker compose -f docker/compose.yaml up -d --build
   docker compose -f docker/compose.yaml ps
   docker compose -f docker/compose.yaml logs -f identity-center
   ```

容器启动命令会先执行 `uv run --no-sync alembic upgrade head`，再启动 API；迁移失败时容器不会开始接收请求。检查 `http://127.0.0.1:8002/health` 可确认进程存活，`/ready` 会检查数据库连接。首次部署还可从服务器本机执行 `curl -i http://127.0.0.1:8002/ready`。Nginx 对外提供 HTTPS 域名后，浏览器 Origin 必须与 `CORS_ALLOW_ORIGINS` 完全匹配。

更新代码后重新构建：

```bash
docker compose -f docker/compose.yaml up -d --build
```
