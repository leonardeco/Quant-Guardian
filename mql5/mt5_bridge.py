"""Local MT5 bridge. One process per terminal; do not run it together with QuantGuardian.mq5 on the same account.

Usage:
  python mt5_bridge.py --api http://127.0.0.1:8000 --license <key> --account <login>

Requires the MetaTrader 5 terminal on this Windows machine (`pip install MetaTrader5`) and `websockets`.
Without the terminal it connects anyway and prints orders instead of sending them.
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit

MAGIC = 770077

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

try:
    import websockets
except ImportError:
    websockets = None


def ws_url(api: str, license_key: str, account: str) -> str:
    parts = urlsplit(api)
    scheme = "wss" if parts.scheme == "https" else "ws"
    query = urlencode({"license_key": license_key, "account_number": account})
    return urlunsplit((scheme, parts.netloc, "/ws/v1/terminal/stream", query, ""))


class Book:
    def __init__(self):
        self.block_new = False
        self.day = -1
        self.day_start = 0.0
        self.mt5 = None

    def start(self) -> bool:
        if mt5 is None:
            print("MetaTrader5 no está instalado: las órdenes se imprimen y no se envían.")
            return False
        if not mt5.initialize():
            print("No se pudo abrir la terminal:", mt5.last_error())
            return False
        self.mt5 = mt5
        return True

    def heartbeat(self) -> dict:
        if not self.mt5:
            return {"type": "heartbeat", "balance": 0, "equity": 0, "day_start_equity": 0, "open_trades": 0}
        info = self.mt5.account_info()
        day = datetime.now(timezone.utc).timetuple().tm_yday
        if day != self.day:
            self.day = day
            self.day_start = info.equity
        positions = self.mt5.positions_get() or []
        return {"type": "heartbeat", "balance": info.balance, "equity": info.equity,
                "day_start_equity": self.day_start, "open_trades": len(positions)}

    def handle(self, msg: dict) -> None:
        if msg.get("type") == "risk":
            self.block_new = msg.get("action") in ("BLOCK_NEW", "FORCE_FLAT")
            if msg.get("action") == "FORCE_FLAT":
                print("FORCE_FLAT")
                self.close_all()
            return
        if msg.get("type") != "signals":
            return
        for sig in msg.get("signals") or []:
            self.execute(sig)

    def execute(self, sig: dict) -> None:
        if sig.get("side") == "CLOSE":
            self.close_all()
            return
        if self.block_new:
            print("Señal rechazada por Risk Guardian", sig.get("symbol"))
            return
        if not self.mt5:
            print("orden", sig.get("side"), sig.get("symbol"), sig.get("volume"))
            return
        symbol = sig["symbol"]
        self.mt5.symbol_select(symbol, True)
        info = self.mt5.symbol_info(symbol)
        tick = self.mt5.symbol_info_tick(symbol)
        if not info or not tick:
            print("Símbolo no disponible", symbol)
            return
        volume = float(sig.get("volume") or info.volume_min)
        sl_points = float(sig.get("sl_points") or 0)
        tp_points = float(sig.get("tp_points") or 0)
        buy = sig.get("side") == "BUY"
        price = tick.ask if buy else tick.bid
        sl = price - sl_points * info.point if buy else price + sl_points * info.point
        tp = price + tp_points * info.point if buy else price - tp_points * info.point
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": self.mt5.ORDER_TYPE_BUY if buy else self.mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": sl if sl_points else 0.0,
            "tp": tp if tp_points else 0.0,
            "deviation": 20,
            "magic": MAGIC,
            "comment": "quant-guardian",
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }
        result = self.mt5.order_send(request)
        print("orden", symbol, getattr(result, "retcode", result))

    def close_all(self) -> None:
        if not self.mt5:
            print("cierre total")
            return
        for pos in self.mt5.positions_get() or []:
            if pos.magic != MAGIC:
                continue
            tick = self.mt5.symbol_info_tick(pos.symbol)
            if not tick:
                continue
            buy = pos.type == self.mt5.POSITION_TYPE_BUY
            self.mt5.order_send({
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "position": pos.ticket,
                "volume": pos.volume,
                "type": self.mt5.ORDER_TYPE_SELL if buy else self.mt5.ORDER_TYPE_BUY,
                "price": tick.bid if buy else tick.ask,
                "deviation": 20,
                "magic": MAGIC,
                "type_filling": self.mt5.ORDER_FILLING_IOC,
            })
        for order in self.mt5.orders_get() or []:
            if order.magic == MAGIC:
                self.mt5.order_send({"action": self.mt5.TRADE_ACTION_REMOVE, "order": order.ticket})


async def run(api: str, license_key: str, account: str) -> None:
    if websockets is None:
        raise SystemExit("Instale websockets: pip install websockets")
    book = Book()
    book.start()
    url = ws_url(api, license_key, account)
    async with websockets.connect(url) as ws:
        async def beats():
            while True:
                await ws.send(json.dumps(book.heartbeat()))
                await asyncio.sleep(1)
        task = asyncio.create_task(beats())
        try:
            async for raw in ws:
                book.handle(json.loads(raw))
        finally:
            task.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(description="Puente local MetaTrader 5 hacia Quant Guardian")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--license", required=True)
    parser.add_argument("--account", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.api, args.license, args.account))


if __name__ == "__main__":
    main()
