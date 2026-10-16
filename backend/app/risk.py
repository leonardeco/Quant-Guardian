"""Risk Guardian: pure decision logic (no I/O) so it is easy to test."""
import math
from dataclasses import dataclass


@dataclass
class RiskProfileData:
    max_daily_dd_pct: float = 4.0
    max_total_dd_pct: float = 8.0
    max_open_trades: int = 5


@dataclass
class AccountState:
    initial_balance: float
    day_start_equity: float
    equity: float
    open_trades: int


def drawdowns(s: AccountState) -> tuple[float, float]:
    daily = (s.day_start_equity - s.equity) / s.day_start_equity * 100 if s.day_start_equity else 0.0
    total = (s.initial_balance - s.equity) / s.initial_balance * 100 if s.initial_balance else 0.0
    return daily, total


def evaluate(profile: RiskProfileData, s: AccountState) -> str:
    """Return ALLOW, BLOCK_NEW (anti-overtrading) or FORCE_FLAT (kill-switch)."""
    daily_dd, total_dd = drawdowns(s)
    if daily_dd >= profile.max_daily_dd_pct or total_dd >= profile.max_total_dd_pct:
        return "FORCE_FLAT"
    if s.open_trades >= profile.max_open_trades:
        return "BLOCK_NEW"
    return "ALLOW"


def risk_level(profile: RiskProfileData, s: AccountState) -> str:
    """NORMAL, ALERT (80% of a drawdown limit) or KILL. Does not change the EA action."""
    if evaluate(profile, s) == "FORCE_FLAT":
        return "KILL"
    daily_dd, total_dd = drawdowns(s)
    if daily_dd >= profile.max_daily_dd_pct * 0.8 or total_dd >= profile.max_total_dd_pct * 0.8:
        return "ALERT"
    return "NORMAL"


def position_size(equity: float, risk_pct: float, sl_distance: float, value_per_unit: float,
                  step: float = 0.01) -> float:
    """Dynamic lot sizing: risk_pct of equity divided by SL cost per lot.
    Floors to `step` so the real risk never exceeds risk_pct."""
    if sl_distance <= 0 or value_per_unit <= 0:
        raise ValueError("sl_distance and value_per_unit must be > 0")
    raw = equity * risk_pct / 100 / (sl_distance * value_per_unit)
    return round(math.floor(raw / step + 1e-9) * step, 8)
