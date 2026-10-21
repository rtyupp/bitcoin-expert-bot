import datetime

# Halving dates (UTC)
_HALVING_DATES = [
    datetime.date(2016, 7, 9),
    datetime.date(2020, 5, 11),
    datetime.date(2024, 4, 20),
]

def halving_phase(ts: datetime.datetime) -> str:
    """Return market regime based on Bitcoin halving cycle.
    Bull: first 365 days after halving.
    Side: next 365 days.
    Bear: remaining period until next halving.
    """
    today = ts.date()
    # Last halving on or before today
    last = max(d for d in _HALVING_DATES if d <= today)
    # Next halving after today (if any)
    future = [d for d in _HALVING_DATES if d > today]
    next_halving = future[0] if future else None
    days = (today - last).days
    if days <= 365:
        return "bull"
    if next_halving and days >= (next_halving - last).days - 365:
        return "bear"
    return "side"
