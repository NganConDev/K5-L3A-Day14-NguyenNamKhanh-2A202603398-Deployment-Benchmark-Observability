"""Track daily and monthly mock LLM spending in persistent Redis counters."""
from datetime import datetime, timezone
from fastapi import HTTPException
from app.config import settings
from app.redis_client import r

PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _period_keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"agent:cost:day:{now:%Y-%m-%d}", f"agent:cost:month:{now:%Y-%m}"


def check_budget() -> None:
    daily, monthly = r.mget(_period_keys())
    if float(daily or 0) >= settings.daily_budget_usd:
        raise HTTPException(402, "Daily budget exhausted")
    if float(monthly or 0) >= settings.monthly_budget_usd:
        raise HTTPException(402, "Monthly budget exhausted")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    cost = (input_tokens * PRICE_INPUT_PER_1K + output_tokens * PRICE_OUTPUT_PER_1K) / 1000
    daily, monthly = _period_keys()
    with r.pipeline(transaction=True) as pipe:
        pipe.incrbyfloat(daily, cost)
        pipe.expire(daily, 2 * 86400)
        pipe.incrbyfloat(monthly, cost)
        pipe.expire(monthly, 62 * 86400)
        pipe.execute()
    return cost
