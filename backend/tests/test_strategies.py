import numpy as np
import pandas as pd

from app.strategies import in_news_blackout, run_strategy, zscore_reversion


def _df(closes, start="2026-01-05 00:00", freq="1h"):
    idx = pd.date_range(start, periods=len(closes), freq=freq, tz="UTC")
    c = pd.Series(closes, index=idx)
    return pd.DataFrame({"open": c, "high": c + 0.1, "low": c - 0.1, "close": c})


def test_session_breakout_up():
    closes = [1.0] * 8 + [1.5]  # flat Asian range, breakout at 08:00
    sig = run_strategy("session_breakout", _df(closes))
    assert sig and sig.side == "BUY" and sig.tp_dist == sig.sl_dist * 2


def test_session_outside_window():
    assert run_strategy("session_breakout", _df([1.0] * 8 + [1.5] + [1.5] * 6)) is None


def test_zscore_reversion():
    rng = np.random.default_rng(1)
    closes = list(100 + rng.normal(0, 0.1, 60)) + [105]
    sig = zscore_reversion(_df(closes))
    assert sig and sig.side == "SELL" and sig.tp_dist > 0


def test_news_blackout():
    ev = pd.Timestamp("2026-01-05 13:30", tz="UTC")
    assert in_news_blackout(pd.Timestamp("2026-01-05 13:20", tz="UTC"), [ev])
    assert not in_news_blackout(pd.Timestamp("2026-01-05 14:00", tz="UTC"), [ev])
    df = _df([100.0] * 59 + [110])
    assert run_strategy("zscore_reversion", df) is not None
    assert run_strategy("zscore_reversion", df, news_events=[df.index[-1]]) is None
