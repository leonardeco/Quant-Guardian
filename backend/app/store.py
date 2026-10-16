"""Redis client. REDIS_URL=memory:// uses an in-process fake (tests / local dev without Redis)."""
import redis.asyncio as aioredis

from .config import settings

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        if settings.redis_url.startswith("memory://"):
            from fakeredis import FakeAsyncRedis
            _client = FakeAsyncRedis(decode_responses=True)
        else:
            _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client
