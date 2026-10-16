"""Dashboard API (JWT): auth, accounts, risk profiles, strategies, analytics."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import inspect
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import models
from .analytics import compute_metrics
from .config import settings
from .db import get_db
from .mail import send_reset_email
from .risk import AccountState, RiskProfileData, drawdowns, evaluate, risk_level
from .security import create_token, get_current_user, hash_password, verify_password
from .strategies import STRATEGIES

router = APIRouter(prefix="/api/v1")
CurrentUser = Depends(get_current_user)


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


@router.post("/auth/register", status_code=201)
async def register(p: Credentials, db: AsyncSession = Depends(get_db)):
    if (await db.execute(select(models.User).where(models.User.email == p.email))).scalar_one_or_none():
        raise HTTPException(409, "email already registered")
    user = models.User(email=p.email, password_hash=hash_password(p.password))
    db.add(user)
    await db.commit()
    return {"id": user.id, "access_token": create_token(user.id)}


@router.post("/auth/login")
async def login(p: Credentials, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(models.User).where(models.User.email == p.email))).scalar_one_or_none()
    if not user or not verify_password(p.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
    return {"access_token": create_token(user.id), "token_type": "bearer"}


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=128)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/auth/forgot-password")
async def forgot_password(p: ForgotIn, db: AsyncSession = Depends(get_db)):
    """Always 200 so the endpoint does not reveal which emails exist.
    The raw token is returned only when expose_reset_tokens is on and the mail was not sent."""
    user = (await db.execute(select(models.User).where(models.User.email == p.email))).scalar_one_or_none()
    token = secrets.token_urlsafe(32)
    if not user:
        return {"status": "ok"}
    user.reset_token_hash = _token_hash(token)
    user.reset_token_expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    await db.commit()
    sent = await send_reset_email(user.email, token)
    if settings.expose_reset_tokens and not sent:
        return {"status": "ok", "reset_token": token}
    return {"status": "ok"}


@router.post("/auth/reset-password")
async def reset_password(p: ResetIn, db: AsyncSession = Depends(get_db)):
    digest = _token_hash(p.token)
    user = (await db.execute(select(models.User).where(models.User.reset_token_hash == digest))).scalar_one_or_none()
    expires = user.reset_token_expires if user else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not user or not expires or expires < datetime.now(timezone.utc) or not hmac.compare_digest(user.reset_token_hash or "", digest):
        raise HTTPException(400, "invalid or expired token")
    user.password_hash = hash_password(p.password)
    user.reset_token_hash = None
    user.reset_token_expires = None
    await db.commit()
    return {"status": "ok"}


async def owned_account(db: AsyncSession, user: models.User, account_id: str) -> models.TradingAccount:
    acc = (await db.execute(
        select(models.TradingAccount)
        .join(models.License, models.License.id == models.TradingAccount.license_id)
        .join(models.Subscription, models.Subscription.id == models.License.subscription_id)
        .where(models.TradingAccount.id == account_id, models.Subscription.user_id == user.id))).scalar_one_or_none()
    if not acc:
        raise HTTPException(404, "account not found")
    return acc


@router.get("/me")
async def me(user: models.User = CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(models.Subscription, models.License)
        .join(models.License, models.License.subscription_id == models.Subscription.id)
        .where(models.Subscription.user_id == user.id))).all()
    return {"id": user.id, "email": user.email, "telegram_chat_id": user.telegram_chat_id,
            "licenses": [{"license_key": l.license_key, "status": l.status, "plan_id": s.plan_id,
                          "subscription_status": s.status, "last_heartbeat_at": l.last_heartbeat_at}
                         for s, l in rows]}


class TelegramIn(BaseModel):
    chat_id: str | None = None


@router.put("/me/telegram")
async def put_telegram(p: TelegramIn, user: models.User = CurrentUser, db: AsyncSession = Depends(get_db)):
    if p.chat_id and not re.fullmatch(r"-?\d{1,20}", p.chat_id):
        raise HTTPException(422, "invalid chat id")
    user.telegram_chat_id = p.chat_id or None
    await db.commit()
    return {"telegram_chat_id": user.telegram_chat_id}


@router.get("/me/accounts")
async def my_accounts(user: models.User = CurrentUser, db: AsyncSession = Depends(get_db)):
    accs = (await db.execute(
        select(models.TradingAccount)
        .join(models.License, models.License.id == models.TradingAccount.license_id)
        .join(models.Subscription, models.Subscription.id == models.License.subscription_id)
        .where(models.Subscription.user_id == user.id))).scalars().all()
    out = []
    for a in accs:
        snap = (await db.execute(select(models.EquitySnapshot).where(models.EquitySnapshot.trading_account_id == a.id)
                                 .order_by(models.EquitySnapshot.id.desc()).limit(1))).scalar_one_or_none()
        rp = (await db.execute(select(models.RiskProfile).where(
            models.RiskProfile.trading_account_id == a.id))).scalar_one_or_none()
        out.append({"id": a.id, "account_number": a.account_number, "broker_server": a.broker_server,
                    "initial_balance": a.initial_balance,
                    "balance": snap.balance if snap else None, "equity": snap.equity if snap else None,
                    "last_update": snap.ts if snap else None, **_risk_view(a, snap, rp)})
    return out


def _risk_view(acc: models.TradingAccount, snap: models.EquitySnapshot | None,
               rp: models.RiskProfile | None) -> dict:
    view = {"floating_pnl": snap.floating_pnl if snap else None,
            "day_start_equity": snap.day_start_equity if snap else None,
            "open_trades": snap.open_trades if snap else None,
            "daily_dd_pct": None, "total_dd_pct": None, "action": None, "level": None,
            "max_daily_dd_pct": rp.max_daily_dd_pct if rp else None,
            "max_total_dd_pct": rp.max_total_dd_pct if rp else None,
            "max_open_trades": rp.max_open_trades if rp else None}
    if not snap or not rp or not snap.day_start_equity or not acc.initial_balance:
        return view
    state = AccountState(acc.initial_balance, snap.day_start_equity, snap.equity, snap.open_trades)
    profile = RiskProfileData(rp.max_daily_dd_pct, rp.max_total_dd_pct, rp.max_open_trades)
    daily, total = drawdowns(state)
    view.update(daily_dd_pct=round(daily, 2), total_dd_pct=round(total, 2),
                action=evaluate(profile, state), level=risk_level(profile, state))
    return view


class RiskIn(BaseModel):
    max_daily_dd_pct: float = Field(gt=0, le=100)
    max_total_dd_pct: float = Field(gt=0, le=100)
    max_open_trades: int = Field(ge=1, le=200)
    risk_per_trade_pct: float = Field(gt=0, le=10)
    news_filter: bool = True


@router.get("/me/accounts/{account_id}/risk")
async def get_risk(account_id: str, user: models.User = CurrentUser, db: AsyncSession = Depends(get_db)):
    acc = await owned_account(db, user, account_id)
    rp = (await db.execute(select(models.RiskProfile).where(models.RiskProfile.trading_account_id == acc.id))).scalar_one()
    return RiskIn.model_validate(rp, from_attributes=True)


@router.put("/me/accounts/{account_id}/risk")
async def put_risk(account_id: str, p: RiskIn, user: models.User = CurrentUser, db: AsyncSession = Depends(get_db)):
    if p.max_daily_dd_pct > p.max_total_dd_pct:
        raise HTTPException(422, "daily drawdown cannot exceed total drawdown")
    acc = await owned_account(db, user, account_id)
    rp = (await db.execute(select(models.RiskProfile).where(models.RiskProfile.trading_account_id == acc.id))).scalar_one()
    for k, v in p.model_dump().items():
        setattr(rp, k, v)
    await db.commit()
    return p


class StrategyIn(BaseModel):
    strategy: str
    symbol: str
    params: dict = {}


class StrategyPatch(BaseModel):
    enabled: bool | None = None
    params: dict | None = None


def _validate_params(strategy: str, params: dict) -> None:
    fn = STRATEGIES.get(strategy)
    if not fn:
        raise HTTPException(422, f"unknown strategy, options: {list(STRATEGIES)}")
    try:
        inspect.signature(fn).bind(None, **params)
    except TypeError as e:
        raise HTTPException(422, f"invalid params: {e}")


def _strategy_out(r: models.StrategyConfig) -> dict:
    return {"id": r.id, "strategy": r.strategy, "symbol": r.symbol, "params": r.params, "enabled": r.enabled}


@router.post("/me/accounts/{account_id}/strategies", status_code=201)
async def create_strategy(account_id: str, p: StrategyIn, user: models.User = CurrentUser,
                          db: AsyncSession = Depends(get_db)):
    _validate_params(p.strategy, p.params)
    acc = await owned_account(db, user, account_id)
    cfg = models.StrategyConfig(trading_account_id=acc.id, strategy=p.strategy, symbol=p.symbol, params=p.params)
    db.add(cfg)
    await db.commit()
    return _strategy_out(cfg)


@router.get("/me/accounts/{account_id}/strategies")
async def list_strategies(account_id: str, user: models.User = CurrentUser, db: AsyncSession = Depends(get_db)):
    acc = await owned_account(db, user, account_id)
    rows = (await db.execute(select(models.StrategyConfig).where(
        models.StrategyConfig.trading_account_id == acc.id))).scalars().all()
    return [_strategy_out(r) for r in rows]


@router.patch("/me/accounts/{account_id}/strategies/{strategy_id}")
async def patch_strategy(account_id: str, strategy_id: str, p: StrategyPatch, user: models.User = CurrentUser,
                         db: AsyncSession = Depends(get_db)):
    acc = await owned_account(db, user, account_id)
    cfg = await db.get(models.StrategyConfig, strategy_id)
    if not cfg or cfg.trading_account_id != acc.id:
        raise HTTPException(404, "strategy not found")
    if p.params is not None:
        _validate_params(cfg.strategy, p.params)
        cfg.params = p.params
    if p.enabled is not None:
        cfg.enabled = p.enabled
    await db.commit()
    return _strategy_out(cfg)


class CopyIn(BaseModel):
    master_account_id: str
    follower_account_id: str


def _copy_out(link: models.CopyLink, master: models.TradingAccount, follower: models.TradingAccount) -> dict:
    return {"id": link.id, "enabled": link.enabled,
            "master_account_id": master.id, "master_account_number": master.account_number,
            "follower_account_id": follower.id, "follower_account_number": follower.account_number}


@router.get("/me/copies")
async def list_copies(user: models.User = CurrentUser, db: AsyncSession = Depends(get_db)):
    ids = [a.id for a in (await db.execute(
        select(models.TradingAccount)
        .join(models.License, models.License.id == models.TradingAccount.license_id)
        .join(models.Subscription, models.Subscription.id == models.License.subscription_id)
        .where(models.Subscription.user_id == user.id))).scalars().all()]
    if not ids:
        return []
    links = (await db.execute(select(models.CopyLink).where(models.CopyLink.master_account_id.in_(ids)))).scalars().all()
    out = []
    for link in links:
        master = await db.get(models.TradingAccount, link.master_account_id)
        follower = await db.get(models.TradingAccount, link.follower_account_id)
        if master and follower:
            out.append(_copy_out(link, master, follower))
    return out


@router.post("/me/copies", status_code=201)
async def create_copy(p: CopyIn, user: models.User = CurrentUser, db: AsyncSession = Depends(get_db)):
    if p.master_account_id == p.follower_account_id:
        raise HTTPException(422, "account cannot copy itself")
    master = await owned_account(db, user, p.master_account_id)
    follower = await owned_account(db, user, p.follower_account_id)
    exists = (await db.execute(select(models.CopyLink).where(
        models.CopyLink.follower_account_id == follower.id))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "follower already linked")
    link = models.CopyLink(master_account_id=master.id, follower_account_id=follower.id)
    db.add(link)
    await db.commit()
    return _copy_out(link, master, follower)


@router.delete("/me/copies/{link_id}", status_code=204)
async def delete_copy(link_id: str, user: models.User = CurrentUser, db: AsyncSession = Depends(get_db)):
    link = await db.get(models.CopyLink, link_id)
    if not link:
        raise HTTPException(404, "copy link not found")
    await owned_account(db, user, link.master_account_id)
    await db.delete(link)
    await db.commit()


@router.get("/analytics/performance")
async def performance(account_id: str, date_from: datetime | None = None, date_to: datetime | None = None,
                      limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
                      user: models.User = CurrentUser, db: AsyncSession = Depends(get_db)):
    acc = await owned_account(db, user, account_id)
    tq = select(models.TradeExecution).where(models.TradeExecution.trading_account_id == acc.id,
                                             models.TradeExecution.closed_at.is_not(None))
    eq = select(models.EquitySnapshot).where(models.EquitySnapshot.trading_account_id == acc.id)
    if date_from:
        tq, eq = tq.where(models.TradeExecution.closed_at >= date_from), eq.where(models.EquitySnapshot.ts >= date_from)
    if date_to:
        tq, eq = tq.where(models.TradeExecution.closed_at <= date_to), eq.where(models.EquitySnapshot.ts <= date_to)
    trades = (await db.execute(tq.order_by(models.TradeExecution.closed_at))).scalars().all()
    snaps = (await db.execute(eq.order_by(models.EquitySnapshot.id))).scalars().all()
    return {
        "metrics": compute_metrics([t.pnl or 0.0 for t in trades], [s.equity for s in snaps]),
        "equity_curve": [{"ts": s.ts, "equity": s.equity, "balance": s.balance} for s in snaps],
        "trades_total": len(trades),
        "trades": [{"ticket": t.ticket, "symbol": t.symbol, "side": t.side, "volume": t.volume,
                    "open_price": t.open_price, "close_price": t.close_price, "pnl": t.pnl,
                    "opened_at": t.opened_at, "closed_at": t.closed_at} for t in trades[offset:offset + limit]],
    }
