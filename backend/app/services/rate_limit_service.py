from __future__ import annotations

import math
from datetime import datetime, timezone

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings


class RateLimitExceededError(Exception):
    def __init__(self, *, scope: str, limit: int, window_seconds: int, retry_after_seconds: int) -> None:
        self.scope = scope
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Rate limit exceeded")


def _redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, socket_connect_timeout=1.5, socket_timeout=1.5)


def enforce_rate_limit(*, key_id: str, scope: str, limit: int, window_seconds: int) -> None:
    now = datetime.now(tz=timezone.utc)
    bucket = math.floor(now.timestamp() / window_seconds)
    redis_key = f"argus:rate:{scope}:{key_id}:{bucket}"

    try:
        client = _redis_client()
        count = int(client.incr(redis_key))
        if count == 1:
            client.expire(redis_key, window_seconds + 2)
    except RedisError:
        return

    if count <= limit:
        return

    retry_after_seconds = int(window_seconds - (now.timestamp() % window_seconds))
    raise RateLimitExceededError(
        scope=scope,
        limit=limit,
        window_seconds=window_seconds,
        retry_after_seconds=max(1, retry_after_seconds),
    )
