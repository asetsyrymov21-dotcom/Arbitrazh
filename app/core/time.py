from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def ms_to_utc(timestamp_ms: int | str | None) -> datetime | None:
    if timestamp_ms in (None, ""):
        return None
    return datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=UTC)

