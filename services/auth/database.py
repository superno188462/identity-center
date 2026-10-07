"""异步数据库连接与 ORM 基类。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """身份中心 ORM 模型基类。"""


def _database_url() -> str:
    """读取仅服务端使用的 PostgreSQL async URL，并拒绝错误驱动。"""
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL_REQUIRED")
    if not url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("DATABASE_URL must use postgresql+asyncpg")
    return url


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """创建共享连接池；配置在进程生命周期内固定。"""
    return async_sessionmaker(
        create_async_engine(
            _database_url(),
            pool_pre_ping=True,
            pool_size=int(os.getenv("DATABASE_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("DATABASE_MAX_OVERFLOW", "10")),
        ),
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """为单个 API 请求提供数据库会话，并在请求后释放连接。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session
