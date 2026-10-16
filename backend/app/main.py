"""Terminal / billing / market API. Dashboard (JWT) endpoints live in dashboard.py."""
import asyncio
import hashlib
import hmac
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import models
from .config import settings
from .dashboard import router as dashboard_router
from .db import Base, engine, ensure_columns, get_db
from .copier import fanout
from .engine import add_candles, drain, enqueue, get_news, set_news, to_order
from .live import attached, connect, deliver, disconnect, send
from .risk import AccountState, RiskProfileData, drawdowns, evaluate, risk_level
from .strategies import run_strategy
from .newsfeed import news_loop
from .telegram import daily_loop, notify_order, notify_transition


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(ensure_columns)
    tasks = [asyncio.create_task(daily_loop()), asyncio.create_task(news_loop())]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Quant SaaS API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(dashboard_router)


# --- Auth helpers ---
def sign(body: bytes, secret: str | None = None) -> str:
    return hmac.new((secret or settings.webhook_secret).encode(), body, hashlib.sha256).hexdigest()


async def verify_signature(request: Request, x_signature: str = Header(...)) -> bytes:
    body = await request.body()
    if not hmac.compare_digest(sign(body), x_signature):
        raise HTTPException(401, "bad signature")
    return body


async def check_license(db: AsyncSession, key: str) -> models.License:
    """Valid, non-revoked license whose subscription is paid. 402 lets the EA tell the user to renew."""
    lic = (await db.execute(select(models.License).where(models.License.license_key == key))).scalar_one_or_none()
    if not lic or lic.status == "revoked":
        raise HTTPException(403, "invalid license")
    sub = await db.get(models.Subscription, lic.subscription_id)
    if sub.status not in ("active", "trialing"):
        raise HTTPException(402, "payment required")
    return lic


async def get_license(x_license_key: str = Header(...), db: AsyncSession = Depends(get_db)) -> models.License:
    return await check_license(db, x_license_key)


async def get_account(db: AsyncSession, lic: models.License, account_number: str) -> models.TradingAccount:
    acc = (await db.execute(select(models.TradingAccount).where(
        models.TradingAccount.license_id == lic.id,
        models.TradingAccount.account_number == account_number))).scalar_one_or_none()
    if not acc:
        raise HTTPException(404, "account not activated")
    return acc


async def risk_profile(db: AsyncSession, acc: models.TradingAccount) -> models.RiskProfile:
    return (await db.execute(select(models.RiskProfile).where(
        models.RiskProfile.trading_account_id == acc.id))).scalar_one()


async def last_snapshot(db: AsyncSession, acc: models.TradingAccount) -> models.EquitySnapshot | None:
    return (await db.execute(select(models.EquitySnapshot).where(models.EquitySnapshot.trading_account_id == acc.id)
                             .order_by(models.EquitySnapshot.id.desc()).limit(1))).scalar_one_or_none()


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Billing (payment provider webhook) ---
class BillingEvent(BaseModel):
    event: Literal["subscription.created", "subscription.updated"] = "subscription.created"
    user_id: str | None = None
    plan_id: str | None = None
    subscription_id: str | None = None
    status: Literal["active", "trialing", "past_due", "canceled"] | None = None


@app.post("/api/v1/webhooks/billing")
async def billing_webhook(body: bytes = Depends(verify_signature), db: AsyncSession = Depends(get_db)):
    """Payment provider event -> creates subscription + license (zero-friction flow) or updates its status."""
    ev = BillingEvent.model_validate_json(body)
    if ev.event == "subscription.created":
        if not ev.user_id or not ev.plan_id or not await db.get(models.User, ev.user_id):
            raise HTTPException(422, "valid user_id and plan_id required")
        sub = models.Subscription(user_id=ev.user_id, plan_id=ev.plan_id, status=ev.status or "active")
        db.add(sub)
        await db.flush()
        lic = models.License(subscription_id=sub.id, license_key=secrets.token_urlsafe(24))
        db.add(lic)
        await db.commit()
        return {"subscription_id": sub.id, "license_key": lic.license_key}
    sub = await db.get(models.Subscription, ev.subscription_id or "")
    if not sub or not ev.status:
        raise HTTPException(422, "valid subscription_id and status required")
    sub.status = ev.status
    if ev.status == "canceled":
        for lic in (await db.execute(select(models.License).where(
                models.License.subscription_id == sub.id))).scalars():
            lic.status = "revoked"
    await db.commit()
    return {"subscription_id": sub.id, "status": sub.status}


# --- Terminal (EA) ---
class ActivateIn(BaseModel):
    license_key: str
    account_number: str
    broker_server: str
    initial_balance: float = 0.0


class HeartbeatIn(BaseModel):
    account_number: str
    balance: float
    equity: float
    day_start_equity: float
    open_trades: int


@app.post("/api/v1/license/activate")
async def activate(p: ActivateIn, db: AsyncSession = Depends(get_db)):
    lic = await check_license(db, p.license_key)
    acc = (await db.execute(select(models.TradingAccount).where(
        models.TradingAccount.license_id == lic.id,
        models.TradingAccount.account_number == p.account_number))).scalar_one_or_none()
    if not acc:
        acc = models.TradingAccount(license_id=lic.id, account_number=p.account_number,
                                    broker_server=p.broker_server, initial_balance=p.initial_balance)
        db.add(acc)
        await db.flush()
        db.add(models.RiskProfile(trading_account_id=acc.id))
    await db.commit()
    return {"status": "active", "account_id": acc.id}


async def record_heartbeat(db: AsyncSession, lic: models.License, account_number: str,
                           balance: float, equity: float, day_start_equity: float, open_trades: int) -> dict:
    acc = await get_account(db, lic, account_number)
    rp = await risk_profile(db, acc)
    prev = await last_snapshot(db, acc)
    hwm = max(equity, balance, prev.high_water_mark if prev else 0.0)
    lic.last_heartbeat_at = datetime.now(timezone.utc)
    db.add(models.EquitySnapshot(trading_account_id=acc.id, balance=balance, equity=equity,
                                 floating_pnl=equity - balance, high_water_mark=hwm,
                                 day_start_equity=day_start_equity, open_trades=open_trades))
    await db.commit()
    profile = RiskProfileData(rp.max_daily_dd_pct, rp.max_total_dd_pct, rp.max_open_trades)
    base = acc.initial_balance or balance
    state = AccountState(base, day_start_equity, equity, open_trades)
    previous = None
    if prev and prev.day_start_equity:
        previous = risk_level(profile, AccountState(base, prev.day_start_equity, prev.equity, prev.open_trades))
    result = {"action": evaluate(profile, state), "level": risk_level(profile, state)}
    await notify_transition(db, acc, previous, result["level"], drawdowns(state)[0], profile.max_daily_dd_pct)
    return result


@app.post("/api/v1/telemetry/heartbeat")
async def heartbeat(p: HeartbeatIn, lic: models.License = Depends(get_license), db: AsyncSession = Depends(get_db)):
    result = await record_heartbeat(db, lic, p.account_number, p.balance, p.equity, p.day_start_equity, p.open_trades)
    await send(p.account_number, {"type": "risk", **result})
    return result


@app.websocket("/ws/v1/terminal/stream")
async def terminal_stream(ws: WebSocket, license_key: str, account_number: str, db: AsyncSession = Depends(get_db)):
    """Live orders and risk. Query auth because the MT5 bridge cannot set headers on the upgrade."""
    await ws.accept()
    try:
        lic = await check_license(db, license_key)
        await get_account(db, lic, account_number)
    except HTTPException as exc:
        reason = exc.detail if isinstance(exc.detail, str) else "rejected"
        await ws.close(code=1008, reason=reason[:120])
        return
    await connect(account_number, ws)
    try:
        await deliver(account_number)
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict) or msg.get("type") != "heartbeat":
                continue
            try:
                lic = await check_license(db, license_key)
                beat = HeartbeatIn(account_number=account_number, balance=msg["balance"], equity=msg["equity"],
                                   day_start_equity=msg["day_start_equity"], open_trades=msg["open_trades"])
            except HTTPException as exc:
                await ws.close(code=1008, reason=str(exc.detail)[:120])
                break
            except (KeyError, TypeError, ValueError, ValidationError):
                await ws.send_json({"type": "error", "detail": "bad heartbeat"})
                continue
            result = await record_heartbeat(db, lic, account_number, beat.balance, beat.equity,
                                            beat.day_start_equity, beat.open_trades)
            await send(account_number, {"type": "risk", **result})
    except WebSocketDisconnect:
        pass
    finally:
        disconnect(account_number, ws)


class TradeIn(BaseModel):
    account_number: str
    ticket: str
    side: Literal["BUY", "SELL"]
    symbol: str
    volume: float
    open_price: float
    close_price: float
    pnl: float
    opened_at: int  # epoch seconds, broker server time
    closed_at: int
    utc_offset: int = 0


@app.post("/api/v1/terminal/trades")
async def report_trade(p: TradeIn, lic: models.License = Depends(get_license), db: AsyncSession = Depends(get_db)):
    """Closed position reported by the EA. Upsert by (account, ticket) so retries are safe."""
    acc = await get_account(db, lic, p.account_number)
    t = (await db.execute(select(models.TradeExecution).where(
        models.TradeExecution.trading_account_id == acc.id,
        models.TradeExecution.ticket == p.ticket))).scalar_one_or_none()
    created = t is None
    if not t:
        t = models.TradeExecution(trading_account_id=acc.id, ticket=p.ticket)
        db.add(t)
    ts = lambda s: datetime.fromtimestamp(s - p.utc_offset, tz=timezone.utc)  # noqa: E731
    t.side, t.symbol, t.volume = p.side, p.symbol, p.volume
    t.open_price, t.close_price, t.pnl = p.open_price, p.close_price, p.pnl
    t.opened_at, t.closed_at = ts(p.opened_at), ts(p.closed_at)
    await db.commit()
    if created:
        await notify_order(db, acc, p.side, p.symbol, p.volume, p.pnl)
    return {"id": t.id}


# --- Signal bridge (TradingView/Python -> MT5 terminal) ---
class SignalIn(BaseModel):
    """TradingView alerts can't set headers, so the license key travels in the JSON body."""
    license_key: str
    signal_uid: str
    account_number: str
    symbol: str
    side: Literal["BUY", "SELL", "CLOSE"]
    volume: float | None = None
    sl_points: float | None = None
    tp_points: float | None = None


@app.post("/api/v1/signals/ingest", status_code=202)
async def ingest_signal(p: SignalIn, db: AsyncSession = Depends(get_db)):
    lic = await check_license(db, p.license_key)
    acc = await get_account(db, lic, p.account_number)
    payload = p.model_dump(exclude={"license_key", "signal_uid"})
    # uid is namespaced by license so one customer can't burn another's ids
    uid = f"{lic.id}:{p.signal_uid}"
    queued = await enqueue(p.account_number, uid, payload)
    if queued:
        await notify_order(db, acc, p.side, p.symbol, p.volume)
        await fanout(db, acc, uid, payload)
    await deliver(p.account_number)
    return {"status": "queued" if queued else "duplicate"}


@app.get("/api/v1/terminal/pending")
async def pending_signals(account_number: str, lic: models.License = Depends(get_license),
                          db: AsyncSession = Depends(get_db)):
    await get_account(db, lic, account_number)  # license must own this account
    if attached(account_number):
        return {"signals": []}  # the live socket owns the queue; polling must not double-fire
    return {"signals": await drain(account_number)}


# --- Market data -> strategies -> signal queue ---
class NewsIn(BaseModel):
    events: list[datetime]


@app.post("/api/v1/market/news")
async def market_news(body: bytes = Depends(verify_signature)):
    events = [pd.Timestamp(e) for e in NewsIn.model_validate_json(body).events]
    events = [e.tz_convert("UTC") if e.tzinfo else e.tz_localize("UTC") for e in events]
    await set_news(events)
    return {"count": len(events)}


class CandleIn(BaseModel):
    t: int  # bar open time, broker server epoch seconds
    o: float
    h: float
    l: float
    c: float


class CandlesIn(BaseModel):
    account_number: str
    symbol: str
    utc_offset: int = 0  # broker server time - UTC, seconds
    point: float = Field(gt=0)
    tick_size: float = Field(gt=0)
    tick_value: float = Field(gt=0)
    vol_min: float = 0.01
    vol_step: float = 0.01
    vol_max: float = 100.0
    candles: list[CandleIn] = Field(min_length=1)  # closed bars only


@app.post("/api/v1/market/candles")
async def market_candles(p: CandlesIn, lic: models.License = Depends(get_license), db: AsyncSession = Depends(get_db)):
    acc = await get_account(db, lic, p.account_number)
    df = await add_candles(p.account_number, p.symbol, [c.model_dump() for c in p.candles], p.utc_offset)
    configs = (await db.execute(select(models.StrategyConfig).where(
        models.StrategyConfig.trading_account_id == acc.id,
        models.StrategyConfig.symbol == p.symbol,
        models.StrategyConfig.enabled.is_(True)))).scalars().all()
    if not configs:
        return {"queued": []}
    rp = await risk_profile(db, acc)
    snap = await last_snapshot(db, acc)
    equity = snap.equity if snap else acc.initial_balance
    news = await get_news() if rp.news_filter else None
    bar_ts = int(df.index[-1].timestamp())
    queued = []
    for cfg in configs:
        sig = run_strategy(cfg.strategy, df, cfg.params, news)
        if not sig:
            continue
        order = to_order(sig, equity=equity, risk_pct=rp.risk_per_trade_pct, point=p.point, tick_size=p.tick_size,
                         tick_value=p.tick_value, vol_min=p.vol_min, vol_step=p.vol_step, vol_max=p.vol_max)
        uid = f"{cfg.id}:{bar_ts}"  # one signal per strategy per bar
        payload = {"account_number": p.account_number, "symbol": p.symbol, **order} if order else None
        if payload and await enqueue(p.account_number, uid, payload):
            queued.append(uid)
            await notify_order(db, acc, order["side"], p.symbol, order["volume"])
            await fanout(db, acc, uid, payload)
    if queued:
        await deliver(p.account_number)
    return {"queued": queued}
