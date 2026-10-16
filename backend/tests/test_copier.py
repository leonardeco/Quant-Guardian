from app.copier import scale_volume
from conftest import activate


def test_scale_volume_floors_to_step():
    assert scale_volume(0.1, 100000, 50000) == 0.05
    assert scale_volume(1, 100000, 10000) == 0.1
    assert scale_volume(0.01, 100000, 10000) is None  # 0.001 must not round up to 0.01
    assert scale_volume(0.1, 0, 50000) is None


def test_copy_link_scales_volume_and_keeps_prices(client, customer):
    key, auth = customer["license_key"], customer["auth"]
    master = activate(client, key, "8100", 100000)
    follower = activate(client, key, "8101", 25000)
    body = {"master_account_id": master, "follower_account_id": follower}
    assert client.post("/api/v1/me/copies", headers=auth, json={"master_account_id": master, "follower_account_id": master}).status_code == 422
    link = client.post("/api/v1/me/copies", headers=auth, json=body)
    assert link.status_code == 201
    assert client.post("/api/v1/me/copies", headers=auth, json=body).status_code == 409
    other = client.post("/api/v1/auth/register", json={"email": "copy-intruder@test.io", "password": "secret123"}).json()
    assert client.post("/api/v1/me/copies", headers={"Authorization": f"Bearer {other['access_token']}"}, json=body).status_code == 404

    h = {"x-license-key": key}
    sig = {"license_key": key, "signal_uid": "c1", "account_number": "8100", "symbol": "EURUSD",
           "side": "BUY", "volume": 0.2, "sl_points": 15, "tp_points": 30}
    assert client.post("/api/v1/signals/ingest", json=sig).json()["status"] == "queued"
    own = client.get("/api/v1/terminal/pending?account_number=8100", headers=h).json()["signals"]
    copied = client.get("/api/v1/terminal/pending?account_number=8101", headers=h).json()["signals"]
    assert own[0]["volume"] == 0.2 and own[0]["sl_points"] == 15
    assert copied[0]["volume"] == 0.05 and copied[0]["sl_points"] == 15 and copied[0]["tp_points"] == 30
    assert copied[0]["account_number"] == "8101"

    client.post("/api/v1/signals/ingest", json={**sig, "signal_uid": "c2", "side": "CLOSE", "volume": None})
    closed = client.get("/api/v1/terminal/pending?account_number=8101", headers=h).json()["signals"]
    assert closed[0]["side"] == "CLOSE"

    assert client.delete(f"/api/v1/me/copies/{link.json()['id']}", headers=auth).status_code == 204
    client.post("/api/v1/signals/ingest", json={**sig, "signal_uid": "c3"})
    assert client.get("/api/v1/terminal/pending?account_number=8101", headers=h).json()["signals"] == []
