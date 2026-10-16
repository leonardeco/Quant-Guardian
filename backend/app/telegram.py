"""Telegram alerts. No-op unless TELEGRAM_BOT_TOKEN and a chat id are set."""
import asyncio
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import models
from .config import settings
from .db import SessionLocal
from .engine import get_news

NY = ZoneInfo("America/New_York")


def next_ny_close(now: datetime) -> datetime:
    """Next 17:00 America/New_York, which is when the daily note goes out."""
    local = now.astimezone(NY)
    target = local.replace(hour=17, minute=0, second=0, microsecond=0)
    if local >= target:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


async def chat_of(db: AsyncSession, acc: models.TradingAccount) -> str | None:
    lic = await db.get(models.License, acc.license_id)
    sub = await db.get(models.Subscription, lic.subscription_id) if lic else None
    user = await db.get(models.User, sub.user_id) if sub else None
    return user.telegram_chat_id if user else None


async def _post(chat_id: str, text: str) -> None:
    if not settings.telegram_bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        await asyncio.to_thread(urllib.request.urlopen, req, timeout=5)
    except Exception:
        print("telegram send failed")


async def deliver_text(chat_id: str | None, text: str) -> None:
    if chat_id and text:
        await _post(chat_id, text)


async def notify_transition(db: AsyncSession, acc: models.TradingAccount, previous: str | None,
                            level: str, daily_dd: float, limit: float) -> None:
    if level not in ("ALERT", "KILL") or level == previous:
        return
    if level == "KILL":
        text = (f"Kill-switch en la cuenta {acc.account_number}. "
                f"Drawdown diario {daily_dd:.2f}% (límite {limit:.2f}%).")
    else:
        text = (f"Alerta en la cuenta {acc.account_number}. "
                f"El drawdown diario va en {daily_dd:.2f}% y el límite es {limit:.2f}%.")
    await deliver_text(await chat_of(db, acc), text)


async def notify_order(db: AsyncSession, acc: models.TradingAccount, side: str, symbol: str,
                       volume: float | None = None, pnl: float | None = None) -> None:
    if side == "CLOSE" and pnl is None:
        text = f"Cierre de posiciones en {acc.account_number}."
    elif pnl is not None:
        text = f"Cierre {symbol} {side} en {acc.account_number}. PnL {pnl:.2f}."
    else:
        text = f"Apertura {symbol} {side} {volume:g} en {acc.account_number}."
    await deliver_text(await chat_of(db, acc), text)


def daily_text(rows: list[tuple[str, float | None, float, int]], news: list[str]) -> str:
    lines = ["Resumen de la jornada"]
    if not rows:
        lines.append("Sin cuentas vinculadas.")
    for number, balance, pnl, count in rows:
        bal = f"{balance:.2f}" if balance is not None else "sin dato"
        lines.append(f"{number}: balance {bal}, PnL {pnl:.2f}, operaciones {count}.")
    lines.append("Mañana: " + (", ".join(news) if news else "sin eventos de alto impacto cargados."))
    return "\n".join(lines)


async def report_text(db: AsyncSession, user: models.User, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(NY)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    accs = (await db.execute(
        select(models.TradingAccount)
        .join(models.License, models.License.id == models.TradingAccount.license_id)
        .join(models.Subscription, models.Subscription.id == models.License.subscription_id)
        .where(models.Subscription.user_id == user.id))).scalars().all()
    rows = []
    for acc in accs:
        snap = (await db.execute(select(models.EquitySnapshot).where(models.EquitySnapshot.trading_account_id == acc.id)
                                 .order_by(models.EquitySnapshot.id.desc()).limit(1))).scalar_one_or_none()
        trades = (await db.execute(select(models.TradeExecution).where(
            models.TradeExecution.trading_account_id == acc.id,
            models.TradeExecution.closed_at >= start,
            models.TradeExecution.closed_at <= now))).scalars().all()
        rows.append((acc.account_number, snap.balance if snap else None, sum(t.pnl or 0 for t in trades), len(trades)))
    tomorrow = (local + timedelta(days=1)).date()
    labels = []
    for event in await get_news():
        stamp = event.tz_convert(NY) if event.tzinfo else event.tz_localize("UTC").tz_convert(NY)
        if stamp.date() == tomorrow:
            labels.append(stamp.strftime("%H:%M"))
    return daily_text(rows, labels)


async def dispatch_daily_reports() -> None:
    async with SessionLocal() as db:
        users = (await db.execute(select(models.User).where(models.User.telegram_chat_id.is_not(None)))).scalars().all()
        for user in users:
            await deliver_text(user.telegram_chat_id, await report_text(db, user))


async def daily_loop() -> None:
    while True:
        delay = (next_ny_close(datetime.now(timezone.utc)) - datetime.now(timezone.utc)).total_seconds()
        await asyncio.sleep(max(delay, 1))
        try:
            await dispatch_daily_reports()
        except Exception:
            print("daily report failed")
