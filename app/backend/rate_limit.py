"""The per-client daily turn cap. MISSION hard invariant 5.

The cap is ONE number defined in ONE module. It protects the inference budget, and only a
human commit may change it. The counter is in-process: one service, one process, one
window per client id.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

DAILY_TURN_CAP: int = 100
WINDOW_HOURS: int = 24

_turns: dict[str, deque[datetime]] = defaultdict(deque)


class RateLimitExceeded(Exception):
    def __init__(self, reset_at: datetime) -> None:
        super().__init__("daily turn cap reached")
        self.reset_at = reset_at


def _prune(client_id: str, now: datetime) -> deque[datetime]:
    window = _turns[client_id]
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    while window and window[0] <= cutoff:
        window.popleft()
    return window


def check_and_record(client_id: str, now: datetime | None = None) -> None:
    """Count one turn for the client, or raise if the cap is already reached."""
    now = now or datetime.now(UTC)
    window = _prune(client_id, now)
    if len(window) >= DAILY_TURN_CAP:
        raise RateLimitExceeded(reset_at=window[0] + timedelta(hours=WINDOW_HOURS))
    window.append(now)


def remaining(client_id: str, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    return max(0, DAILY_TURN_CAP - len(_prune(client_id, now)))


def reset() -> None:
    """Test hook: forget every client."""
    _turns.clear()
