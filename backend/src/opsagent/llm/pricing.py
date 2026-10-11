"""List prices used to estimate cost per invoice.

Prices are USD per million tokens. They are configuration, not facts fetched
from the provider: on Groq's free tier the real bill is $0, and these numbers
show what the same workload would cost on a paid plan.
Sources (2026-10): Groq price list for gpt-oss-120b; qwen3.8-27b had no public
price, so the qwen3.6-27b price is used as an estimate.
"""

from decimal import Decimal

PRICES_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "openai/gpt-oss-120b": (Decimal("0.15"), Decimal("0.60")),
    "qwen/qwen3.8-27b": (Decimal("0.60"), Decimal("3.00")),
}
_MILLION = Decimal(1_000_000)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    price_in, price_out = PRICES_PER_MTOK.get(model, (Decimal(0), Decimal(0)))
    cost = (price_in * prompt_tokens + price_out * completion_tokens) / _MILLION
    return cost.quantize(Decimal("0.000001"))
