import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    reset_token_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    reset_token_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[str] = mapped_column(String)  # starter | quant_pro | institutional
    provider_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="trialing")  # active|past_due|canceled|trialing
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class License(Base):
    __tablename__ = "licenses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    subscription_id: Mapped[str] = mapped_column(ForeignKey("subscriptions.id"))
    license_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active|grace|revoked
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TradingAccount(Base):
    __tablename__ = "trading_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    license_id: Mapped[str] = mapped_column(ForeignKey("licenses.id"), index=True)
    account_number: Mapped[str] = mapped_column(String, index=True)
    broker_server: Mapped[str] = mapped_column(String)
    initial_balance: Mapped[float] = mapped_column(Float)


class RiskProfile(Base):
    __tablename__ = "risk_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    trading_account_id: Mapped[str] = mapped_column(ForeignKey("trading_accounts.id"), unique=True)
    max_daily_dd_pct: Mapped[float] = mapped_column(Float, default=4.0)
    max_total_dd_pct: Mapped[float] = mapped_column(Float, default=8.0)
    max_open_trades: Mapped[int] = mapped_column(Integer, default=5)
    risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=1.0)
    news_filter: Mapped[bool] = mapped_column(Boolean, default=True)


class StrategyConfig(Base):
    __tablename__ = "strategy_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    trading_account_id: Mapped[str] = mapped_column(ForeignKey("trading_accounts.id"), index=True)
    strategy: Mapped[str] = mapped_column(String)  # session_breakout|zscore_reversion
    symbol: Mapped[str] = mapped_column(String)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CopyLink(Base):
    __tablename__ = "copy_links"
    __table_args__ = (UniqueConstraint("master_account_id", "follower_account_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    master_account_id: Mapped[str] = mapped_column(ForeignKey("trading_accounts.id"), index=True)
    follower_account_id: Mapped[str] = mapped_column(ForeignKey("trading_accounts.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class TradeExecution(Base):
    __tablename__ = "trade_executions"
    __table_args__ = (UniqueConstraint("trading_account_id", "ticket"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    trading_account_id: Mapped[str] = mapped_column(ForeignKey("trading_accounts.id"), index=True)
    ticket: Mapped[str] = mapped_column(String, index=True)  # MT5 position id
    side: Mapped[str] = mapped_column(String)
    symbol: Mapped[str] = mapped_column(String)
    volume: Mapped[float] = mapped_column(Float)
    open_price: Mapped[float] = mapped_column(Float)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)  # net: profit + swap + commission
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trading_account_id: Mapped[str] = mapped_column(ForeignKey("trading_accounts.id"), index=True)
    balance: Mapped[float] = mapped_column(Float)
    equity: Mapped[float] = mapped_column(Float)
    floating_pnl: Mapped[float] = mapped_column(Float)
    high_water_mark: Mapped[float] = mapped_column(Float)
    day_start_equity: Mapped[float] = mapped_column(Float, default=0)
    open_trades: Mapped[int] = mapped_column(Integer, default=0)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
