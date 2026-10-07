"""统一账号、可撤销登录会话和登录失败计数的数据模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from services.auth.database import Base


class User(Base):
    """身份中心用户；`id` 是跨业务项目使用的稳定 UUID。"""

    __tablename__ = "identity_users"
    __table_args__ = (UniqueConstraint("username", name="uq_identity_users_username"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user", server_default="user")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    display_name: Mapped[str | None] = mapped_column(String(100))
    preferred_language: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthSession(Base):
    """保存 opaque Cookie 的哈希，不持久化可直接使用的原始令牌。"""

    __tablename__ = "identity_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("identity_users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="sessions")


class LoginAttempt(Base):
    """按用户名/IP 的哈希维护失败窗口，不保存原始用户名或 IP。"""

    __tablename__ = "identity_login_attempts"
    __table_args__ = (
        PrimaryKeyConstraint("scope", "key_hash", name="pk_identity_login_attempts"),
        Index("ix_identity_login_attempts_updated_at", "updated_at"),
    )

    scope: Mapped[str] = mapped_column(String(16), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
