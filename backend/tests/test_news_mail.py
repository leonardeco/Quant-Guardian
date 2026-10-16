from app.config import settings
from app.newsfeed import select_events


SAMPLE = [
    {"title": "Non-Farm Employment Change", "impact": "High", "date": "2026-10-02T12:30:00-04:00"},
    {"title": "CPI y/y", "impact": "High", "date": "2026-10-15T08:30:00-04:00"},
    {"title": "FOMC Statement", "impact": "High", "date": "2026-10-29T14:00:00-04:00"},
    {"title": "ECB Interest Rate Decision", "impact": "High", "date": "2026-10-30T08:15:00-04:00"},
    {"title": "Retail Sales m/m", "impact": "High", "date": "2026-10-16T08:30:00-04:00"},
    {"title": "CPI m/m", "impact": "Medium", "date": "2026-10-15T08:30:00-04:00"},
    {"title": "Holiday", "impact": "High"},
]


def test_calendar_keeps_only_tracked_high_impact():
    times = select_events(SAMPLE)
    assert len(times) == 4
    assert all(t.tzinfo is not None for t in times)
    assert times[0].hour == 16  # 12:30 EDT is 16:30 UTC


def test_reset_email_hides_the_token(client, monkeypatch):
    from app.mail import reset_link

    sent = []

    async def capture(to, token):
        sent.append((to, token))
        return True

    monkeypatch.setattr(settings, "smtp_host", "smtp.example")
    monkeypatch.setattr("app.dashboard.send_reset_email", capture)
    client.post("/api/v1/auth/register", json={"email": "mail@test.io", "password": "secret123"})
    body = client.post("/api/v1/auth/forgot-password", json={"email": "mail@test.io"}).json()
    assert "reset_token" not in body
    assert sent[0][0] == "mail@test.io"
    assert reset_link(sent[0][1]).endswith(f"/restablecer?token={sent[0][1]}")
