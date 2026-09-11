from datetime import UTC, datetime, timedelta


QUOTA_PERIOD = timedelta(days=30)


def quota_period(signup_at: datetime, at: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the signup-anchored 30-day window containing at, in UTC.

    The start is inclusive and the end is exclusive. A reset never changes
    the original anchor, even when several periods have passed without usage.
    """
    at = datetime.now(UTC) if at is None else at
    if signup_at.utcoffset() is None or at.utcoffset() is None:
        raise ValueError("Signup and lookup timestamps must be timezone-aware.")
    signup_at = signup_at.astimezone(UTC)
    at = at.astimezone(UTC)
    if at < signup_at:
        raise ValueError("Lookup timestamp cannot be before signup.")

    elapsed_periods = (at - signup_at) // QUOTA_PERIOD
    start = signup_at + elapsed_periods * QUOTA_PERIOD
    return start, start + QUOTA_PERIOD
