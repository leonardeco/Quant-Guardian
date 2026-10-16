"""High-impact calendar. Keeps NFP, CPI, FOMC and rate decisions, and stores their times in Redis."""
import asyncio
import json
import re
import urllib.request

import pandas as pd

from .config import settings
from .engine import set_news

_SHORT = re.compile(r"\b(cpi|nfp|fomc)\b", re.I)
_PHRASES = ("non-farm", "nonfarm", "consumer price", "federal funds", "interest rate",
            "rate decision", "cash rate", "bank rate")


def is_tracked(event: dict) -> bool:
    if str(event.get("impact", "")).lower() != "high":
        return False
    title = str(event.get("title", ""))
    return bool(_SHORT.search(title) or any(phrase in title.lower() for phrase in _PHRASES))


def select_events(payload: list) -> list[pd.Timestamp]:
    times = []
    for event in payload:
        if not isinstance(event, dict) or not is_tracked(event) or not event.get("date"):
            continue
        stamp = pd.Timestamp(event["date"])
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        times.append(stamp)
    return times


async def _fetch() -> str:
    def read() -> str:
        req = urllib.request.Request(settings.news_feed_url, headers={"User-Agent": "QuantGuardian/0.2"})
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.read().decode()
    return await asyncio.to_thread(read)


async def refresh() -> int:
    if not settings.news_feed_url:
        return 0
    events = select_events(json.loads(await _fetch()))
    await set_news(events)
    return len(events)


async def news_loop() -> None:
    while True:
        if settings.news_feed_url:
            try:
                await refresh()
            except Exception:
                print("news feed failed")
        await asyncio.sleep(max(settings.news_refresh_hours, 1) * 3600)
