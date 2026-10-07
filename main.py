"""Identity Center API entry point for account authentication and profiles."""

import argparse
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import uvicorn

from services.auth.database import get_db_session, get_session_factory
from services.auth.models import User
from services.auth.service import (
    LoginRateLimited,
    create_auth_session,
    get_user_by_token,
    login_user,
    register_user,
    revoke_token,
    session_ttl,
)

APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR / ".env")

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]

app = FastAPI(
    title="Identity Center",
    description="跨项目统一身份与用户资料服务。",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class AuthCredentials(BaseModel):
    """注册或登录凭据；密码只用于当前请求，禁止记录或回显。"""

    username: str = Field(
        min_length=1,
        max_length=64,
        description="用户名，服务端会去除首尾空格并忽略大小写",
    )
    password: str = Field(min_length=1, max_length=128, description="注册密码至少 8 个字符")


class ProfilePatch(BaseModel):
    """允许用户修改的少量跨项目通用资料。"""

    display_name: str | None = Field(default=None, max_length=100, description="显示名称；传 null 可清空")
    preferred_language: str | None = Field(
        default=None, max_length=20, description="语言偏好，例如 zh-CN；传 null 可清空"
    )


def _user_payload(user: User) -> dict[str, Any]:
    """构造兼容现有语音登录客户端的用户响应。"""
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "permissions": [],
        "display_name": user.display_name,
        "preferred_language": user.preferred_language,
    }


def _validate_request_origin(request: Request) -> None:
    """对浏览器写操作施加 Origin allowlist；CORS 负责同源策略头部。"""
    origin = request.headers.get("origin")
    if origin and origin not in allowed_origins:
        raise HTTPException(status_code=403, detail={"code": "ORIGIN_NOT_ALLOWED"})


def _cookie_settings() -> tuple[bool, str, str | None]:
    """根据部署环境配置 Cookie；跨站 Cookie 必须使用 Secure。"""
    secure_value = os.getenv("AUTH_COOKIE_SECURE")
    secure = (
        secure_value.strip().lower() == "true"
        if secure_value is not None
        else os.getenv("APP_ENV", "development").strip().lower() == "production"
    )
    same_site = os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
    domain = os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None
    if same_site not in {"lax", "strict", "none"} or (same_site == "none" and not secure):
        raise RuntimeError("AUTH_COOKIE_SAMESITE_NONE_REQUIRES_SECURE_COOKIE")
    return secure, same_site, domain


async def require_current_user(
    request: Request, db: AsyncSession = Depends(get_db_session)
) -> User:
    """以身份中心 Cookie 验证用户，用户 ID 只来自服务端有效会话。"""
    _validate_request_origin(request)
    user = await get_user_by_token(db, request.cookies.get("identity_session"))
    if not user:
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})
    return user


def _set_auth_cookie(response: JSONResponse, token: str) -> None:
    secure, same_site, domain = _cookie_settings()
    response.set_cookie(
        key="identity_session",
        value=token,
        max_age=session_ttl(),
        httponly=True,
        secure=secure,
        samesite=same_site,
        domain=domain,
        path="/",
    )


@app.get("/health", tags=["health"], summary="检查服务进程是否正常")
async def health() -> dict[str, str]:
    """Return process health without exposing dependency or secret details."""
    return {"status": "ok", "service": "identity-center"}


@app.get("/ready", tags=["health"], summary="检查服务是否已准备好处理请求")
async def ready() -> JSONResponse:
    """检查数据库连接是否可用；失败时返回通用状态，不暴露连接信息。"""
    try:
        factory = get_session_factory()
        async with factory() as db:
            await db.execute(text("SELECT 1"))
    except (SQLAlchemyError, RuntimeError, ValueError):
        return JSONResponse(
            {"status": "not_ready", "dependencies": {"database": "unavailable"}},
            status_code=503,
        )
    return JSONResponse(
        {"status": "ready", "dependencies": {"database": "ok"}},
        status_code=200,
    )


@app.post("/api/auth/register", status_code=201, summary="注册统一身份账号")
async def auth_register(
    credentials: AuthCredentials,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """创建普通用户并自动建立登录会话；新账号不能自行成为管理员。"""
    _validate_request_origin(request)
    if os.getenv("AUTH_ALLOW_REGISTRATION", "true").strip().lower() != "true":
        raise HTTPException(status_code=403, detail={"code": "REGISTRATION_DISABLED"})
    try:
        user = await register_user(db, credentials.username, credentials.password)
    except ValueError as exc:
        code = str(exc)
        status = 409 if code == "USERNAME_TAKEN" else 422
        raise HTTPException(status_code=status, detail={"code": code}) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "USERNAME_TAKEN"}) from exc

    token, _ = await create_auth_session(db, user)
    response = JSONResponse({"user": _user_payload(user)}, status_code=201)
    _set_auth_cookie(response, token)
    return response


@app.post("/api/auth/login", summary="登录统一身份账号")
async def auth_login(
    credentials: AuthCredentials,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """验证凭据并设置 HttpOnly 会话 Cookie。"""
    _validate_request_origin(request)
    client_ip = request.client.host if request.client else "unknown"
    try:
        result = await login_user(db, credentials.username, credentials.password, client_ip)
    except LoginRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": "LOGIN_RATE_LIMITED", "message": "登录尝试过于频繁，请稍后重试"},
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail={"code": "INVALID_CREDENTIALS"}) from exc
    if not result:
        raise HTTPException(status_code=401, detail={"code": "INVALID_CREDENTIALS"})
    user, token, _ = result
    response = JSONResponse({"user": _user_payload(user)})
    _set_auth_cookie(response, token)
    return response


@app.get("/api/auth/me", summary="获取当前登录用户")
async def auth_me(user: User = Depends(require_current_user)) -> dict[str, Any]:
    """返回当前会话对应的 canonical user ID 和公开账号字段。"""
    return {"user": _user_payload(user)}


@app.post("/api/auth/logout", summary="退出当前身份中心会话")
async def auth_logout(
    request: Request, db: AsyncSession = Depends(get_db_session)
) -> JSONResponse:
    """撤销当前服务端会话并清除身份中心 Cookie。"""
    _validate_request_origin(request)
    await revoke_token(db, request.cookies.get("identity_session"))
    secure, same_site, domain = _cookie_settings()
    response = JSONResponse({"logged_out": True})
    response.delete_cookie(
        "identity_session",
        path="/",
        domain=domain,
        httponly=True,
        secure=secure,
        samesite=same_site,
    )
    return response


@app.get("/api/auth/me/profile", summary="读取当前用户的通用资料")
async def read_profile(user: User = Depends(require_current_user)) -> dict[str, Any]:
    """读取身份中心维护的少量通用资料，不包含业务项目画像。"""
    return {
        "profile": {
            "user_id": user.id,
            "display_name": user.display_name,
            "preferred_language": user.preferred_language,
        }
    }


@app.patch("/api/auth/me/profile", summary="更新当前用户的通用资料")
async def update_profile(
    payload: ProfilePatch,
    user: User = Depends(require_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """只更新请求显式提交的通用字段，业务项目专属资料由业务项目维护。"""
    for field in payload.model_fields_set:
        setattr(user, field, getattr(payload, field))
    await db.commit()
    await db.refresh(user)
    return {
        "profile": {
            "user_id": user.id,
            "display_name": user.display_name,
            "preferred_language": user.preferred_language,
        }
    }


def main() -> None:
    """Start the local API server; accepts an optional listening port."""
    parser = argparse.ArgumentParser(description="启动 Identity Center API")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "8002")),
        help="HTTP 监听端口，默认读取 PORT 或使用 8002",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port 必须在 1 到 65535 之间")
    uvicorn.run("main:app", host=os.getenv("HOST", "127.0.0.1"), port=args.port)


if __name__ == "__main__":
    main()
