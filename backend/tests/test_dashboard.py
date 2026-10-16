from datetime import datetime, timezone

from app.analytics import compute_metrics, max_drawdown_pct
from conftest import activate


def test_metrics():
    m = compute_metrics([100, -50, 200, -50], [10000, 10100, 10050, 10250, 10200])
    assert m["trades"] == 4 and m["win_rate"] == 50.0 and m["profit_factor"] == 3.0 and m["expectancy"] == 50.0
    assert compute_metrics([], [])["win_rate"] is None
    assert max_drawdown_pct([100, 120, 90, 130]) == 25.0


def test_auth(client):
    r = client.post("/api/v1/auth/register", json={"email": "dup@test.io", "password": "secret123"})
    assert r.status_code == 201
    assert client.post("/api/v1/auth/register", json={"email": "dup@test.io", "password": "secret123"}).status_code == 409
    assert client.post("/api/v1/auth/login", json={"email": "dup@test.io", "password": "wrongpass"}).status_code == 401
    tok = client.post("/api/v1/auth/login", json={"email": "dup@test.io", "password": "secret123"}).json()["access_token"]
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {tok}"}).json()["email"] == "dup@test.io"
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert client.get("/api/v1/me").status_code == 401


def test_password_reset(client):
    client.post("/api/v1/auth/register", json={"email": "reset@test.io", "password": "secret123"})
    missing = client.post("/api/v1/auth/forgot-password", json={"email": "nobody@test.io"})
    assert missing.status_code == 200 and "reset_token" not in missing.json()
    token = client.post("/api/v1/auth/forgot-password", json={"email": "reset@test.io"}).json()["reset_token"]
    assert client.post("/api/v1/auth/reset-password", json={"token": "x" * 20, "password": "newsecret1"}).status_code == 400
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "password": "newsecret1"}).status_code == 200
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "password": "newsecret1"}).status_code == 400
    assert client.post("/api/v1/auth/login", json={"email": "reset@test.io", "password": "secret123"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "reset@test.io", "password": "newsecret1"}).status_code == 200


def test_risk_profile_edit_and_isolation(client, customer):
    acc_id = activate(client, customer["license_key"], "888")
    url = f"/api/v1/me/accounts/{acc_id}/risk"
    body = {"max_daily_dd_pct": 3, "max_total_dd_pct": 6, "max_open_trades": 2, "risk_per_trade_pct": 0.5}
    assert client.put(url, headers=customer["auth"], json={**body, "max_daily_dd_pct": 9}).status_code == 422
    assert client.put(url, headers=customer["auth"], json=body).status_code == 200
    assert client.get(url, headers=customer["auth"]).json()["max_open_trades"] == 2
    # another user can't touch it
    tok = client.post("/api/v1/auth/register", json={"email": "intruder@test.io", "password": "secret123"}).json()
    assert client.get(url, headers={"Authorization": f"Bearer {tok['access_token']}"}).status_code == 404


def test_trade_report_and_performance(client, customer):
    key, auth = customer["license_key"], customer["auth"]
    h = {"x-license-key": key}
    acc_id = activate(client, key, "444")
    for eq in (100000, 101000, 100500):
        client.post("/api/v1/telemetry/heartbeat", headers=h, json={
            "account_number": "444", "balance": eq, "equity": eq, "day_start_equity": 100000, "open_trades": 0})
    t0 = int(datetime(2026, 1, 5, 10, tzinfo=timezone.utc).timestamp())
    trade = {"account_number": "444", "ticket": "1", "side": "BUY", "symbol": "EURUSD", "volume": 0.5,
             "open_price": 1.1, "close_price": 1.102, "pnl": 1000, "opened_at": t0, "closed_at": t0 + 3600}
    client.post("/api/v1/terminal/trades", headers=h, json=trade)
    client.post("/api/v1/terminal/trades", headers=h, json=trade)  # retry must not duplicate
    client.post("/api/v1/terminal/trades", headers=h, json={**trade, "ticket": "2", "pnl": -500})
    perf = client.get(f"/api/v1/analytics/performance?account_id={acc_id}", headers=auth).json()
    m = perf["metrics"]
    assert m["trades"] == 2 and m["net_pnl"] == 500 and m["profit_factor"] == 2.0
    assert len(perf["equity_curve"]) == 3 and m["max_drawdown_pct"] > 0
    accounts = client.get("/api/v1/me/accounts", headers=auth).json()
    row = next(a for a in accounts if a["id"] == acc_id)
    assert row["equity"] == 100500 and row["level"] == "NORMAL" and row["daily_dd_pct"] == -0.5
    page = client.get(f"/api/v1/analytics/performance?account_id={acc_id}&limit=1&offset=1", headers=auth).json()
    assert page["trades_total"] == 2 and len(page["trades"]) == 1 and page["metrics"]["trades"] == 2


def test_account_alert_level(client, customer):
    key, auth = customer["license_key"], customer["auth"]
    acc_id = activate(client, key, "555")
    client.post("/api/v1/telemetry/heartbeat", headers={"x-license-key": key}, json={
        "account_number": "555", "balance": 100000, "equity": 96700, "day_start_equity": 100000, "open_trades": 1})
    row = next(a for a in client.get("/api/v1/me/accounts", headers=auth).json() if a["id"] == acc_id)
    assert row["action"] == "ALLOW" and row["level"] == "ALERT" and row["daily_dd_pct"] == 3.3
    assert row["max_daily_dd_pct"] == 4.0
