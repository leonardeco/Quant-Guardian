"""Copy a master's order to its followers. One hop, same prices, volume scaled by equity."""
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import models
from .engine import enqueue
from .live import deliver
from .telegram import notify_order


def scale_volume(master_volume: float, master_equity: float, follower_equity: float, step: float = 0.01) -> float | None:
    """Floor the follower lot so it never rounds up past the equity ratio."""
    if master_volume <= 0 or master_equity <= 0 or follower_equity <= 0 or step <= 0:
        return None
    raw = master_volume * follower_equity / master_equity
    lots = round(math.floor(raw / step + 1e-9) * step, 8)
    return lots or None


async def _equity(db: AsyncSession, acc: models.TradingAccount) -> float:
    snap = (await db.execute(select(models.EquitySnapshot).where(models.EquitySnapshot.trading_account_id == acc.id)
                             .order_by(models.EquitySnapshot.id.desc()).limit(1))).scalar_one_or_none()
    if snap is not None:
        return snap.equity
    return acc.initial_balance or 0.0


async def fanout(db: AsyncSession, master: models.TradingAccount, uid: str, payload: dict) -> None:
    links = (await db.execute(select(models.CopyLink).where(
        models.CopyLink.master_account_id == master.id, models.CopyLink.enabled.is_(True)))).scalars().all()
    if not links:
        return
    master_equity = await _equity(db, master)
    for link in links:
        follower = await db.get(models.TradingAccount, link.follower_account_id)
        if follower is None:
            continue
        body = {k: v for k, v in payload.items() if v is not None}
        body["account_number"] = follower.account_number
        if body.get("side") != "CLOSE":
            scaled = scale_volume(float(body.get("volume") or 0), master_equity, await _equity(db, follower))
            if scaled is None:
                continue
            body["volume"] = scaled
        if await enqueue(follower.account_number, f"copy:{link.id}:{uid}", body):
            await notify_order(db, follower, str(body.get("side") or ""), str(body.get("symbol") or ""), body.get("volume"))
            await deliver(follower.account_number)
