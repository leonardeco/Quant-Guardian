"""Quant engine: vectorised strategies over OHLC DataFrames.

Input df: DatetimeIndex (UTC) with columns open, high, low, close.
Each strategy returns the latest Signal or None. No I/O here.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Signal:
    side: str  # BUY | SELL
    sl_dist: float  # distance in price units (converted to broker points in engine.py)
    tp_dist: float
    reason: str


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def zscore(close: pd.Series, window: int = 50) -> pd.Series:
    m, s = close.rolling(window).mean(), close.rolling(window).std()
    return (close - m) / s.replace(0, np.nan)


def session_breakout(df: pd.DataFrame, range_start: int = 0, range_end: int = 7,
                     trade_end: int = 12, sl_atr: float = 1.5, rr: float = 2.0) -> Signal | None:
    """Break of the Asian-session range (UTC hours) during the London window.
    Also detects a liquidity sweep: wick beyond the range that closes back inside is faded."""
    last = df.iloc[-1]
    ts = df.index[-1]
    if not (range_end <= ts.hour < trade_end):
        return None
    day = df[df.index.normalize() == ts.normalize()]
    rng = day[(day.index.hour >= range_start) & (day.index.hour < range_end)]
    if rng.empty:
        return None
    hi, lo = rng["high"].max(), rng["low"].min()
    a = atr(df).iloc[-1]
    if np.isnan(a):
        return None
    sl = a * sl_atr
    if last["high"] > hi and last["close"] < hi:
        return Signal("SELL", sl, sl * rr, "sweep_high")
    if last["low"] < lo and last["close"] > lo:
        return Signal("BUY", sl, sl * rr, "sweep_low")
    if last["close"] > hi:
        return Signal("BUY", sl, sl * rr, "breakout_up")
    if last["close"] < lo:
        return Signal("SELL", sl, sl * rr, "breakout_down")
    return None


def zscore_reversion(df: pd.DataFrame, window: int = 50, entry_z: float = 2.0,
                     sl_atr: float = 2.0) -> Signal | None:
    """Mean reversion: fade price when it is entry_z std-devs from the rolling mean.
    TP is the mean itself."""
    z = zscore(df["close"], window)
    if len(z) < window or np.isnan(z.iloc[-1]):
        return None
    a = atr(df).iloc[-1]
    mean = df["close"].rolling(window).mean().iloc[-1]
    price = df["close"].iloc[-1]
    tp = abs(price - mean)
    if z.iloc[-1] >= entry_z:
        return Signal("SELL", a * sl_atr, tp, f"z={z.iloc[-1]:.2f}")
    if z.iloc[-1] <= -entry_z:
        return Signal("BUY", a * sl_atr, tp, f"z={z.iloc[-1]:.2f}")
    return None


def in_news_blackout(ts: pd.Timestamp, events: list[pd.Timestamp], before_min: int = 15, after_min: int = 15) -> bool:
    """True if ts falls within the blackout window around any high-impact event."""
    return any(e - pd.Timedelta(minutes=before_min) <= ts <= e + pd.Timedelta(minutes=after_min) for e in events)


STRATEGIES = {"session_breakout": session_breakout, "zscore_reversion": zscore_reversion}


def run_strategy(name: str, df: pd.DataFrame, params: dict | None = None,
                 news_events: list[pd.Timestamp] | None = None) -> Signal | None:
    if news_events and in_news_blackout(df.index[-1], news_events):
        return None
    return STRATEGIES[name](df, **(params or {}))
