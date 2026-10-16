"""NicheForge Phase 3 — Stealth Scheduler.

Decides WHEN browser automation may run. The anti-ban posture is:
automation only runs during configured "human hours", never starts at an
exact round hour, takes random off-days, and every run gets a random start
offset. A run outside the window is refused outright — no silent queueing.

All times are Asia/Karachi (PKT), matching the rest of NicheForge.
"""
import random
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    PKT = ZoneInfo("Asia/Karachi")
except Exception:  # very old Python fallback: fixed +05:00
    PKT = timezone(timedelta(hours=5))

DEFAULT_START_HOUR = 9    # 09:00 PKT
DEFAULT_END_HOUR = 23     # 23:00 PKT (exclusive)
DEFAULT_OFF_DAYS = {4}    # Friday (weekday(): Mon=0) — keep one rest day


def now_pkt():
    return datetime.now(PKT)


def _jitter_minutes(rng, low=3, high=27):
    return rng.randint(low, high)


def next_allowed_start(start_hour=DEFAULT_START_HOUR,
                       end_hour=DEFAULT_END_HOUR,
                       off_days=DEFAULT_OFF_DAYS,
                       at=None, seed=None):
    """Return the next datetime (PKT) at which automation may start.

    Rules: inside [start_hour, end_hour), never on an off-day, never at an
    exact round hour (random 3–27 minute offset applied), never in the past.
    """
    rng = random.Random(seed)
    t = at or now_pkt()
    if t.tzinfo is None:
        t = t.replace(tzinfo=PKT)

    # Candidate: today at start_hour + random offset.
    candidate = t.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    candidate += timedelta(minutes=_jitter_minutes(rng))

    # If that already passed, move to tomorrow and re-roll the offset.
    while candidate <= t or candidate.weekday() in (off_days or set()):
        candidate += timedelta(days=1)
        candidate = candidate.replace(hour=start_hour, minute=0,
                                      second=0, microsecond=0)
        candidate += timedelta(minutes=_jitter_minutes(rng))

    # If the candidate somehow lands past end_hour (can't with 3–27 min
    # offsets and a 09:00 start, but guard anyway), push a day forward.
    while candidate.hour >= end_hour or candidate.weekday() in (off_days or set()):
        candidate += timedelta(days=1)
        candidate = candidate.replace(hour=start_hour, minute=0,
                                      second=0, microsecond=0)
        candidate += timedelta(minutes=_jitter_minutes(rng))
    return candidate


def within_window(at=None, start_hour=DEFAULT_START_HOUR,
                  end_hour=DEFAULT_END_HOUR, off_days=DEFAULT_OFF_DAYS):
    """True when `at` (default now) is inside human hours and not an off-day."""
    t = at or now_pkt()
    if t.tzinfo is None:
        t = t.replace(tzinfo=PKT)
    if t.weekday() in (off_days or set()):
        return False
    return start_hour <= t.hour < end_hour


def describe_policy(start_hour=DEFAULT_START_HOUR, end_hour=DEFAULT_END_HOUR,
                    off_days=DEFAULT_OFF_DAYS):
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    off = ", ".join(days[d] for d in sorted(off_days or set())) or "none"
    return ("Human hours {:02d}:00–{:02d}:00 PKT, random 3–27 min start offset, "
            "never on round hours, off-days: {}.".format(start_hour, end_hour, off))
