"""Performance metrics. Pure functions, no I/O."""
import math


def max_drawdown_pct(equity: list[float]) -> float:
    peak, mdd = -math.inf, 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak * 100)
    return round(mdd, 4)


def compute_metrics(pnls: list[float], equity: list[float]) -> dict:
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    n = len(pnls)
    return {
        "trades": n,
        "net_pnl": round(sum(pnls), 2),
        "win_rate": round(len(wins) / n * 100, 2) if n else None,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else None,
        "expectancy": round(sum(pnls) / n, 2) if n else None,
        "avg_win": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else None,
        "max_drawdown_pct": max_drawdown_pct(equity),
    }
