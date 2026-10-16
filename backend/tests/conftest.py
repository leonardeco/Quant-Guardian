import json
import os
import uuid

# must be set before the app (and its settings) are imported
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["REDIS_URL"] = "memory://"
os.environ["JWT_SECRET"] = "test-secret-at-least-32-bytes-long-xxxxxxxx"
os.environ["EXPOSE_RESET_TOKENS"] = "true"
os.environ["NEWS_FEED_URL"] = ""
if os.path.exists("test.db"):
    os.remove("test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, sign  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def billing(c, payload: dict):
    body = json.dumps(payload).encode()
    return c.post("/api/v1/webhooks/billing", content=body, headers={"x-signature": sign(body)})


@pytest.fixture
def customer(client):
    """Registered user with a paid subscription. Returns dict(token, auth, license_key, subscription_id)."""
    r = client.post("/api/v1/auth/register", json={"email": f"{uuid.uuid4().hex[:8]}@test.io", "password": "secret123"})
    user_id, token = r.json()["id"], r.json()["access_token"]
    sub = billing(client, {"user_id": user_id, "plan_id": "quant_pro"}).json()
    return {"token": token, "auth": {"Authorization": f"Bearer {token}"}, **sub}


def activate(c, key: str, account: str, balance: float = 100000) -> str:
    r = c.post("/api/v1/license/activate", json={"license_key": key, "account_number": account,
                                                 "broker_server": "Demo", "initial_balance": balance})
    assert r.status_code == 200, r.text
    return r.json()["account_id"]
