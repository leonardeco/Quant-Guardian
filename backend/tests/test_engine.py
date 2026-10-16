import json

import pandas as pd

from app.engine import to_order
from app.strategies import Signal
from conftest import activate, sign


def test_to_order_sizing():
    # EURUSD: 1% of 10k = $100 risk; SL 0.0050 * $100k per lot per 1.0 move = $500/lot -> 0.20 lots
    o = to_order(Signal("BUY", 0.005, 0.01, "t"), equity=10000, risk_pct=1, point=0.00001, tick_size=0.00001,
                 tick_value=1.0, vol_min=0.01, vol_step=0.01, vol_max=100)
    assert o == {"side": "BUY", "volume": 0.2, "sl_points": 500, "tp_points": 1000, "reason": "t"}


def test_to_order_skips_when_min_lot_over_risks():
    assert to_order(Signal("BUY", 0.05, 0.1, "t"), equity=100, risk_pct=1, point=0.00001, tick_size=0.00001,
                    tick_value=1.0, vol_min=0.01, vol_step=0.01, vol_max=100) is None


def _candles(closes, utc_offset=0):
    idx = pd.date_range("2026-01-05 00:00", periods=len(closes), freq="1h", tz="UTC")
    return [{"t": int(t.timestamp()) + utc_offset, "o": c, "h": c + 0.1, "l": c - 0.1, "c": c}
            for t, c in zip(idx, closes)]


def test_candles_to_signal_end_to_end(client, customer):
    key, auth = customer["license_key"], customer["auth"]
    h = {"x-license-key": key}
    acc_id = activate(client, key, "555")
    url = f"/api/v1/me/accounts/{acc_id}/strategies"
    assert client.post(url, headers=auth, json={"strategy": "session_breakout", "symbol": "EURUSD",
                                                "params": {"bogus": 1}}).status_code == 422
    assert client.post(url, headers=auth, json={"strategy": "session_breakout", "symbol": "EURUSD",
                                                "params": {"rr": 2.0}}).status_code == 201
    # broker at UTC+2: bars arrive shifted, engine must normalise to UTC hours
    payload = {"account_number": "555", "symbol": "EURUSD", "utc_offset": 7200, "point": 0.00001,
               "tick_size": 0.00001, "tick_value": 1.0, "candles": _candles([1.0] * 8 + [1.5], 7200)}
    assert len(client.post("/api/v1/market/candles", headers=h, json=payload).json()["queued"]) == 1
    # resending the same closed bar must not duplicate the signal
    assert client.post("/api/v1/market/candles", headers=h, json=payload).json()["queued"] == []
    sigs = client.get("/api/v1/terminal/pending?account_number=555", headers=h).json()["signals"]
    assert len(sigs) == 1 and sigs[0]["side"] == "BUY" and sigs[0]["volume"] > 0 and sigs[0]["sl_points"] > 0


def test_disabled_strategy_and_news_blackout(client, customer):
    key, auth = customer["license_key"], customer["auth"]
    h = {"x-license-key": key}
    acc_id = activate(client, key, "556")
    sid = client.post(f"/api/v1/me/accounts/{acc_id}/strategies", headers=auth,
                      json={"strategy": "session_breakout", "symbol": "EURUSD"}).json()["id"]
    candles = _candles([1.0] * 8 + [1.5])
    payload = {"account_number": "556", "symbol": "EURUSD", "point": 0.00001, "tick_size": 0.00001,
               "tick_value": 1.0, "candles": candles}
    news = json.dumps({"events": ["2026-01-05T08:05:00Z"]}).encode()
    assert client.post("/api/v1/market/news", content=news, headers={"x-signature": sign(news)}).json()["count"] == 1
    assert client.post("/api/v1/market/candles", headers=h, json=payload).json()["queued"] == []
    client.post("/api/v1/market/news", content=b'{"events": []}', headers={"x-signature": sign(b'{"events": []}')})
    client.patch(f"/api/v1/me/accounts/{acc_id}/strategies/{sid}", headers=auth, json={"enabled": False})
    assert client.post("/api/v1/market/candles", headers=h, json=payload).json()["queued"] == []
