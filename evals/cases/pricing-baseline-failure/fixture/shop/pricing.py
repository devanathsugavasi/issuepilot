def apply_discount(price_cents: int, percent: int) -> int:
    """Return the price after a percentage discount, rounded down to whole cents."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    return price_cents - price_cents * percent // 10
