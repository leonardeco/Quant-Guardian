from starlette.websockets import WebSocketDisconnect

from conftest import activate


def _sig(key: str, account: str, uid: str = "s1") -> dict:
    return {"license_key": key, "signal_uid": uid, "account_number": account, "symbol": "EURUSD",
            "side": "BUY", "volume": 0.1}


def test_socket_takes_the_queue(client, customer):
    key = customer["license_key"]
    activate(client, key, "5555")
    assert client.post("/api/v1/signals/ingest", json=_sig(key, "5555")).json()["status"] == "queued"
    with client.websocket_connect(f"/ws/v1/terminal/stream?license_key={key}&account_number=5555") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "signals" and msg["signals"][0]["symbol"] == "EURUSD"
        assert client.get("/api/v1/terminal/pending?account_number=5555",
                          headers={"x-license-key": key}).json()["signals"] == []
        client.post("/api/v1/signals/ingest", json=_sig(key, "5555", "s2"))
        live = ws.receive_json()
        assert live["signals"][0]["signal_uid"].endswith(":s2")
    # socket gone: polling works again
    assert client.post("/api/v1/signals/ingest", json=_sig(key, "5555", "s3")).json()["status"] == "queued"
    got = client.get("/api/v1/terminal/pending?account_number=5555", headers={"x-license-key": key}).json()["signals"]
    assert len(got) == 1 and got[0]["signal_uid"].endswith(":s3")


def test_socket_heartbeat_pushes_kill(client, customer):
    key = customer["license_key"]
    activate(client, key, "5556")
    with client.websocket_connect(f"/ws/v1/terminal/stream?license_key={key}&account_number=5556") as ws:
        ws.send_json({"type": "heartbeat", "balance": 100000, "equity": 95000,
                      "day_start_equity": 100000, "open_trades": 1})
        msg = ws.receive_json()
        assert msg["type"] == "risk" and msg["action"] == "FORCE_FLAT" and msg["level"] == "KILL"
        ws.send_json({"type": "heartbeat"})
        assert ws.receive_json()["type"] == "error"


def test_socket_rejects_foreign_account(client, customer):
    activate(client, customer["license_key"], "5557")
    try:
        with client.websocket_connect("/ws/v1/terminal/stream?license_key=nope&account_number=5557") as ws:
            ws.receive_json()
        raise AssertionError("socket should have closed")
    except WebSocketDisconnect as exc:
        assert exc.code == 1008
