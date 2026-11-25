"""Atomic sliding window shared across workers, instances and restarts."""
import hashlib
import uuid
from fastapi import HTTPException
from app.config import settings
from app.redis_client import r

# Redis time avoids clock differences. Lua makes prune/count/insert atomic.
_CHECK = r.register_script("""
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then
    local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return math.max(1, math.ceil(tonumber(first[2]) + 60 - now))
end
redis.call('ZADD', KEYS[1], now, ARGV[2])
redis.call('EXPIRE', KEYS[1], 61)
return 0
""")


def check_rate_limit(key: str) -> None:
    if settings.rate_limit_per_minute <= 0:
        raise HTTPException(429, "Request limit is zero", headers={"Retry-After": "60"})
    identity = hashlib.sha256(key.encode()).hexdigest()
    retry = _CHECK(keys=[f"agent:rate:{identity}"], args=[
        settings.rate_limit_per_minute, uuid.uuid4().hex,
    ])
    if retry:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(retry)})
