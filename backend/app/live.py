"""One live socket per trading account. Signals leave the Redis queue only after a successful push."""
from fastapi import WebSocket

from .engine import drain, restore

_rooms: dict[str, WebSocket] = {}


def attached(account: str) -> bool:
    return account in _rooms


async def connect(account: str, ws: WebSocket) -> None:
    previous = _rooms.get(account)
    _rooms[account] = ws
    if previous is not None and previous is not ws:
        try:
            await previous.close(code=4000)
        except Exception:
            pass


def disconnect(account: str, ws: WebSocket) -> None:
    if _rooms.get(account) is ws:
        _rooms.pop(account, None)


async def send(account: str, payload: dict) -> bool:
    ws = _rooms.get(account)
    if ws is None:
        return False
    try:
        await ws.send_json(payload)
        return True
    except Exception:
        disconnect(account, ws)
        return False


async def deliver(account: str) -> None:
    """Drain the queue onto the socket. If nobody is listening, the queue stays for HTTP polling."""
    if not attached(account):
        return
    signals = await drain(account)
    if signals and not await send(account, {"type": "signals", "signals": signals}):
        await restore(account, signals)
