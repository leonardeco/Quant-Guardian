from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def ensure_columns(sync_conn) -> None:
    """create_all does not alter existing tables. Add columns introduced after the first boot."""
    insp = inspect(sync_conn)
    tables = set(insp.get_table_names())
    statements: list[str] = []
    if "users" in tables:
        have = {c["name"] for c in insp.get_columns("users")}
        if "reset_token_hash" not in have:
            statements.append("ALTER TABLE users ADD COLUMN reset_token_hash VARCHAR")
        if "reset_token_expires" not in have:
            statements.append("ALTER TABLE users ADD COLUMN reset_token_expires TIMESTAMP")
        if "telegram_chat_id" not in have:
            statements.append("ALTER TABLE users ADD COLUMN telegram_chat_id VARCHAR")
    if "equity_snapshots" in tables:
        have = {c["name"] for c in insp.get_columns("equity_snapshots")}
        if "day_start_equity" not in have:
            statements.append("ALTER TABLE equity_snapshots ADD COLUMN day_start_equity FLOAT")
        if "open_trades" not in have:
            statements.append("ALTER TABLE equity_snapshots ADD COLUMN open_trades INTEGER")
    for sql in statements:
        sync_conn.execute(text(sql))


async def get_db():
    async with SessionLocal() as session:
        yield session
