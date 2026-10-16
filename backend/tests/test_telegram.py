from datetime import datetime, timezone

from app.config import settings
from app.telegram import daily_text, next_ny_close
from conftest import activate


def test_next_ny_close_rolls_to_the_following_day():
    before = datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)  # 16:00 NY in January
    after = datetime(2026, 1, 5, 22, 30, tzinfo=timezone.utc)  # 17:30 NY
    assert next_ny_close(before).astimezone(timezone.utc) == datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc)
    assert next_ny_close(after).date() == datetime(2026, 1, 6, tzinfo=timezone.utc).date()


def test_daily_text_lists_balance_pnl_and_news():
    text = daily_text([("10001", 100500.0, 250.0, 2)], ["08:30"])
    assert "10001" in text and "100500.00" in text and "250.00" in text and "08:30" in text
    assert "sin eventos" in daily_text([], [])


def test_alerts_fire_once_per_level(client, customer, monkeypatch):
    sent = []

    async def capture(chat_id, text):
        sent.append((chat_id, text))

    monkeypatch.setattr(settings, "telegram_bot_token", "123:test")
    monkeypatch.setattr("app.telegram._post", capture)
    key, auth = customer["license_key"], customer["auth"]
    assert client.put("/api/v1/me/telegram", headers=auth, json={"chat_id": "abc"}).status_code == 422
    assert client.put("/api/v1/me/telegram", headers=auth, json={"chat_id": "998877"}).status_code == 200
    assert client.get("/api/v1/me", headers=auth).json()["telegram_chat_id"] == "998877"
    activate(client, key, "9100", 100000)
    h = {"x-license-key": key}

    def beat(equity):
        return client.post("/api/v1/telemetry/heartbeat", headers=h, json={
            "account_number": "9100", "balance": 100000, "equity": equity,
            "day_start_equity": 100000, "open_trades": 1})

    assert beat(99000).json()["level"] == "NORMAL" and sent == []
    assert beat(96700).json()["level"] == "ALERT" and len(sent) == 1 and "Alerta" in sent[0][1]
    assert beat(96600).json()["level"] == "ALERT" and len(sent) == 1
    assert beat(95000).json()["level"] == "KILL" and len(sent) == 2 and "Kill-switch" in sent[1][1]
    assert sent[0][0] == "998877"


def test_close_notifies_once(client, customer, monkeypatch):
    sent = []

    async def capture(chat_id, text):
        sent.append(text)

    monkeypatch.setattr(settings, "telegram_bot_token", "123:test")
    monkeypatch.setattr("app.telegram._post", capture)
    key, auth = customer["license_key"], customer["auth"]
    client.put("/api/v1/me/telegram", headers=auth, json={"chat_id": "1122"})
    activate(client, key, "9101")
    trade = {"account_number": "9101", "ticket": "9", "side": "BUY", "symbol": "EURUSD", "volume": 0.1,
             "open_price": 1.1, "close_price": 1.2, "pnl": 40, "opened_at": 1_767_225_600, "closed_at": 1_767_229_200}
    h = {"x-license-key": key}
    client.post("/api/v1/terminal/trades", headers=h, json=trade)
    client.post("/api/v1/terminal/trades", headers=h, json=trade)
    assert len(sent) == 1 and "Cierre" in sent[0] and "40.00" in sent[0]
