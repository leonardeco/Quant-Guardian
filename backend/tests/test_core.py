import pytest

from app.risk import AccountState, RiskProfileData, evaluate, position_size, risk_level
from conftest import activate, billing


def test_risk_rules():
    p = RiskProfileData()
    assert evaluate(p, AccountState(100000, 100000, 99000, 1)) == "ALLOW"
    assert evaluate(p, AccountState(100000, 100000, 95900, 1)) == "FORCE_FLAT"
    assert evaluate(p, AccountState(100000, 100000, 99900, 5)) == "BLOCK_NEW"


def test_risk_level_warns_before_kill():
    p = RiskProfileData()  # 4% daily, 8% total; alert at 80%
    assert evaluate(p, AccountState(100000, 100000, 96700, 1)) == "ALLOW"
    assert risk_level(p, AccountState(100000, 100000, 96700, 1)) == "ALERT"
    assert risk_level(p, AccountState(100000, 100000, 99000, 1)) == "NORMAL"
    assert risk_level(p, AccountState(100000, 100000, 95900, 1)) == "KILL"


def test_position_size():
    assert position_size(100000, 1, 50, 10) == 2.0
    assert position_size(10000, 1, 0.0033, 100000) == 0.3  # 0.303 floors, never rounds up
    with pytest.raises(ValueError):
        position_size(1000, 1, 0, 10)


def test_billing_rejects_bad_signature_and_unknown_user(client):
    assert client.post("/api/v1/webhooks/billing", content=b"{}", headers={"x-signature": "bad"}).status_code == 401
    assert billing(client, {"user_id": "nope", "plan_id": "starter"}).status_code == 422


def test_license_and_kill_switch(client, customer):
    key = customer["license_key"]
    activate(client, key, "123")
    hb = {"account_number": "123", "balance": 100000, "equity": 95000, "day_start_equity": 100000, "open_trades": 1}
    r = client.post("/api/v1/telemetry/heartbeat", json=hb, headers={"x-license-key": key})
    assert r.json()["action"] == "FORCE_FLAT"


def test_unpaid_and_canceled_subscriptions(client, customer):
    key, sub = customer["license_key"], customer["subscription_id"]
    activate(client, key, "321")
    h = {"x-license-key": key}
    billing(client, {"event": "subscription.updated", "subscription_id": sub, "status": "past_due"})
    assert client.get("/api/v1/terminal/pending?account_number=321", headers=h).status_code == 402
    billing(client, {"event": "subscription.updated", "subscription_id": sub, "status": "canceled"})
    assert client.get("/api/v1/terminal/pending?account_number=321", headers=h).status_code == 403


def test_signal_bridge(client, customer):
    key = customer["license_key"]
    activate(client, key, "999")
    sig = {"license_key": key, "signal_uid": "s1", "account_number": "999", "symbol": "EURUSD",
           "side": "BUY", "volume": 0.1}
    assert client.post("/api/v1/signals/ingest", json={**sig, "license_key": "bad"}).status_code == 403
    assert client.post("/api/v1/signals/ingest", json={**sig, "side": "HOLD"}).status_code == 422
    assert client.post("/api/v1/signals/ingest", json=sig).json()["status"] == "queued"
    assert client.post("/api/v1/signals/ingest", json=sig).json()["status"] == "duplicate"
    h = {"x-license-key": key}
    got = client.get("/api/v1/terminal/pending?account_number=999", headers=h).json()["signals"]
    assert len(got) == 1 and got[0]["symbol"] == "EURUSD" and "license_key" not in got[0]
    assert client.get("/api/v1/terminal/pending?account_number=999", headers=h).json()["signals"] == []


def test_license_cannot_read_foreign_account(client, customer):
    activate(client, customer["license_key"], "777")
    other = billing(client, {"user_id": client.get("/api/v1/me", headers=customer["auth"]).json()["id"],
                             "plan_id": "starter"}).json()["license_key"]
    assert client.get("/api/v1/terminal/pending?account_number=777",
                      headers={"x-license-key": other}).status_code == 404
