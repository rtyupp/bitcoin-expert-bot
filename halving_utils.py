import datetime

# Halving dates (UTC) — including estimated April 2028 halving
_HALVING_DATES = [
    datetime.date(2016, 7, 9),
    datetime.date(2020, 5, 11),
    datetime.date(2024, 4, 20),
    datetime.date(2028, 4, 15),
]


def halving_phase(ts: datetime.datetime | datetime.date | None = None) -> str:
    """Return market regime based on Bitcoin halving cycle.
    Bull: first 540 days (~18 months) after halving.
    Bear: last 365 days before next halving.
    Side: remaining accumulation/transition period.
    """
    if ts is None:
        today = datetime.datetime.now(datetime.timezone.utc).date()
    elif isinstance(ts, datetime.datetime):
        today = ts.date()
    elif isinstance(ts, datetime.date):
        today = ts
    else:
        today = ts.date()  # type: ignore[union-attr]
    past = [d for d in _HALVING_DATES if d <= today]
    last = max(past) if past else _HALVING_DATES[0]
    future = [d for d in _HALVING_DATES if d > today]
    next_halving = future[0] if future else None
    days = (today - last).days
    if days <= 540:
        return "bull"
    if next_halving and days >= (next_halving - last).days - 365:
        return "bear"
    return "side"

