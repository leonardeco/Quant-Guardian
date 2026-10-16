"""Signal engine: candle buffers, signal queue (Redis) + conversion of strategy Signals into broker orders."""
import json

import pandas as pd

from .risk import position_size
from .store import get_redis
from .strategies import Signal

MAX_BARS = 500
SEEN_TTL = 7 * 24 * 3600
QUEUE_TTL = 3600  # undelivered signals expire; a stale signal must never fire hours later


async def add_candles(account: str, symbol: str, candles: list[dict], utc_offset: int = 0) -> pd.DataFrame:
    """Upsert closed bars (broker-server time -> UTC) and return the OHLC frame, oldest first."""
    r = get_redis()
    key = f"candles:{account}:{symbol}"
    await r.hset(key, mapping={str(int(c["t"]) - utc_offset): json.dumps([c["o"], c["h"], c["l"], c["c"]])
                               for c in candles})
    data = await r.hgetall(key)
    keys = sorted(int(k) for k in data)
    if len(keys) > MAX_BARS:
        await r.hdel(key, *[str(k) for k in keys[:-MAX_BARS]])
        keys = keys[-MAX_BARS:]
    rows = [json.loads(data[str(k)]) for k in keys]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"],
                        index=pd.to_datetime(keys, unit="s", utc=True))


async def enqueue(account_number: str, uid: str, payload: dict) -> bool:
    """Idempotent push: returns False if uid was already seen."""
    r = get_redis()
    if not await r.set(f"seen:{uid}", 1, nx=True, ex=SEEN_TTL):
        return False
    qkey = f"queue:{account_number}"
    await r.rpush(qkey, json.dumps({"signal_uid": uid, **payload}))
    await r.expire(qkey, QUEUE_TTL)
    return True


async def drain(account_number: str) -> list[dict]:
    """Atomically take every pending signal for the account."""
    r = get_redis()
    async with r.pipeline(transaction=True) as pipe:
        items, _ = await pipe.lrange(f"queue:{account_number}", 0, -1).delete(f"queue:{account_number}").execute()
    return [json.loads(i) for i in items]


async def restore(account_number: str, signals: list[dict]) -> None:
    """Put signals back when a live push could not be delivered. Skips the seen-key so they are not dropped."""
    if not signals:
        return
    r = get_redis()
    qkey = f"queue:{account_number}"
    await r.rpush(qkey, *[json.dumps(s) for s in signals])
    await r.expire(qkey, QUEUE_TTL)


async def set_news(events: list[pd.Timestamp]) -> None:
    await get_redis().set("news:events", json.dumps([e.isoformat() for e in events]))


async def get_news() -> list[pd.Timestamp]:
    raw = await get_redis().get("news:events")
    return [pd.Timestamp(e) for e in json.loads(raw)] if raw else []


def to_order(sig: Signal, *, equity: float, risk_pct: float, point: float, tick_size: float,
             tick_value: float, vol_min: float, vol_step: float, vol_max: float) -> dict | None:
    """Size the trade by risk and convert price distances to broker points.
    Returns None when the minimum lot would exceed the allowed risk."""
    value_per_unit = tick_value / tick_size  # account currency per 1.0 price move per lot
    lots = min(position_size(equity, risk_pct, sig.sl_dist, value_per_unit, vol_step), vol_max)
    if lots < vol_min:
        return None
    return {"side": sig.side, "volume": lots, "sl_points": round(sig.sl_dist / point),
            "tp_points": round(sig.tp_dist / point), "reason": sig.reason}
