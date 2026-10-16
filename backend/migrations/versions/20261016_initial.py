"""initial schema

Revision ID: 20261016_initial
Revises:
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261016_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("reset_token_hash", sa.String(), nullable=True),
        sa.Column("reset_token_expires", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_chat_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("provider_customer_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])

    op.create_table(
        "licenses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subscription_id", sa.String(36), sa.ForeignKey("subscriptions.id"), nullable=False),
        sa.Column("license_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_licenses_license_key", "licenses", ["license_key"], unique=True)

    op.create_table(
        "trading_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("license_id", sa.String(36), sa.ForeignKey("licenses.id"), nullable=False),
        sa.Column("account_number", sa.String(), nullable=False),
        sa.Column("broker_server", sa.String(), nullable=False),
        sa.Column("initial_balance", sa.Float(), nullable=False),
    )
    op.create_index("ix_trading_accounts_license_id", "trading_accounts", ["license_id"])
    op.create_index("ix_trading_accounts_account_number", "trading_accounts", ["account_number"])

    op.create_table(
        "risk_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trading_account_id", sa.String(36), sa.ForeignKey("trading_accounts.id"), nullable=False),
        sa.Column("max_daily_dd_pct", sa.Float(), nullable=False),
        sa.Column("max_total_dd_pct", sa.Float(), nullable=False),
        sa.Column("max_open_trades", sa.Integer(), nullable=False),
        sa.Column("risk_per_trade_pct", sa.Float(), nullable=False),
        sa.Column("news_filter", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_risk_profiles_trading_account_id", "risk_profiles", ["trading_account_id"], unique=True)

    op.create_table(
        "strategy_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trading_account_id", sa.String(36), sa.ForeignKey("trading_accounts.id"), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_strategy_configs_trading_account_id", "strategy_configs", ["trading_account_id"])

    op.create_table(
        "copy_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("master_account_id", sa.String(36), sa.ForeignKey("trading_accounts.id"), nullable=False),
        sa.Column("follower_account_id", sa.String(36), sa.ForeignKey("trading_accounts.id"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("master_account_id", "follower_account_id"),
    )
    op.create_index("ix_copy_links_master_account_id", "copy_links", ["master_account_id"])
    op.create_index("ix_copy_links_follower_account_id", "copy_links", ["follower_account_id"], unique=True)

    op.create_table(
        "trade_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trading_account_id", sa.String(36), sa.ForeignKey("trading_accounts.id"), nullable=False),
        sa.Column("ticket", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=False),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("trading_account_id", "ticket"),
    )
    op.create_index("ix_trade_executions_trading_account_id", "trade_executions", ["trading_account_id"])
    op.create_index("ix_trade_executions_ticket", "trade_executions", ["ticket"])
    op.create_index("ix_trade_executions_closed_at", "trade_executions", ["closed_at"])

    op.create_table(
        "equity_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trading_account_id", sa.String(36), sa.ForeignKey("trading_accounts.id"), nullable=False),
        sa.Column("balance", sa.Float(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("floating_pnl", sa.Float(), nullable=False),
        sa.Column("high_water_mark", sa.Float(), nullable=False),
        sa.Column("day_start_equity", sa.Float(), nullable=False),
        sa.Column("open_trades", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_equity_snapshots_trading_account_id", "equity_snapshots", ["trading_account_id"])
    op.create_index("ix_equity_snapshots_ts", "equity_snapshots", ["ts"])


def downgrade() -> None:
    op.drop_table("equity_snapshots")
    op.drop_table("trade_executions")
    op.drop_table("copy_links")
    op.drop_table("strategy_configs")
    op.drop_table("risk_profiles")
    op.drop_table("trading_accounts")
    op.drop_table("licenses")
    op.drop_table("subscriptions")
    op.drop_table("users")
