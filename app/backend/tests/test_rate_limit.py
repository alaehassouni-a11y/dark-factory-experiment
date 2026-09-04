from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend import rate_limit


def test_cap_is_enforced_per_client() -> None:
    for _ in range(rate_limit.DAILY_TURN_CAP):
        rate_limit.check_and_record("a")
    assert rate_limit.remaining("a") == 0
    with pytest.raises(rate_limit.RateLimitExceeded):
        rate_limit.check_and_record("a")
    rate_limit.check_and_record("b")
    assert rate_limit.remaining("b") == rate_limit.DAILY_TURN_CAP - 1


def test_window_slides_after_24_hours() -> None:
    start = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    for _ in range(rate_limit.DAILY_TURN_CAP):
        rate_limit.check_and_record("a", now=start)
    with pytest.raises(rate_limit.RateLimitExceeded) as exc:
        rate_limit.check_and_record("a", now=start + timedelta(hours=23))
    assert exc.value.reset_at == start + timedelta(hours=rate_limit.WINDOW_HOURS)
    rate_limit.check_and_record("a", now=start + timedelta(hours=24, seconds=1))
