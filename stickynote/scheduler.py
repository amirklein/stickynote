"""Decides when the next bit of encouragement lands."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .config import Config
from .state import State

_STEP = timedelta(minutes=5)
_SEARCH_LIMIT = timedelta(days=8)


def _next_allowed(cfg: Config, start: datetime) -> datetime:
    """Walk forward to the first moment inside the active window."""
    moment = start
    deadline = start + _SEARCH_LIMIT
    while moment < deadline:
        if cfg.allows(moment):
            return moment
        moment += _STEP
    # No window in a full week means the config is unusable; fall back rather
    # than looping forever.
    return start


def next_fire_after(cfg: Config, now: datetime) -> datetime:
    """Pick a random delay, then slide it into the next allowed window."""
    delay = random.uniform(cfg.min_minutes, cfg.max_minutes)
    target = now + timedelta(minutes=delay)
    if cfg.allows(target):
        return target

    window_start = _next_allowed(cfg, target)
    jitter = timedelta(minutes=random.uniform(0, min(cfg.min_minutes, 30.0)))
    jittered = window_start + jitter
    return jittered if cfg.allows(jittered) else window_start


def randomize(cfg: Config) -> Config:
    """Re-roll the timing settings so the rhythm itself is unpredictable."""
    cfg.min_minutes = float(random.randint(10, 22))
    cfg.max_minutes = cfg.min_minutes + float(random.randint(25, 60))
    cfg.active_start = "{:02d}:{:02d}".format(random.randint(7, 10), random.choice([0, 15, 30, 45]))
    cfg.active_end = "{:02d}:{:02d}".format(random.randint(20, 22), random.choice([0, 15, 30, 45]))
    cfg.sound = random.choice(["", "", "Glass", "Hero", "Submarine", "Tink"])
    cfg.show_next = False
    cfg.validate()
    return cfg


@dataclass
class TickResult:
    action: str  # fired | waiting | paused | disabled | scheduled | idle
    message: Optional[str] = None
    next_fire: Optional[datetime] = None
    detail: str = ""


def tick(cfg: Config, state: State, now: datetime, deliver) -> TickResult:
    """Advance the schedule by one poll.

    `deliver` is called with the chosen message only when it is time to fire;
    injecting it keeps this function pure enough to test.
    """
    from . import activity, messages

    timestamp = now.timestamp()

    if not cfg.enabled:
        return TickResult("disabled", detail="stickynote is disabled")

    if state.paused_until and timestamp < state.paused_until:
        resume_at = datetime.fromtimestamp(state.paused_until)
        return TickResult("paused", detail=f"paused until {resume_at:%Y-%m-%d %H:%M}")

    if state.paused_until:
        state.paused_until = None

    if state.next_fire is None:
        scheduled = next_fire_after(cfg, now)
        state.next_fire = scheduled.timestamp()
        state.save()
        return TickResult("scheduled", next_fire=scheduled, detail="first run")

    if timestamp < state.next_fire:
        return TickResult("waiting", next_fire=datetime.fromtimestamp(state.next_fire))

    if not cfg.allows(now):
        # Woke up outside the window (laptop was asleep, config changed, ...).
        scheduled = next_fire_after(cfg, now)
        state.next_fire = scheduled.timestamp()
        state.save()
        return TickResult("scheduled", next_fire=scheduled, detail="outside active hours")

    if cfg.require_activity and not activity.is_active(cfg.max_idle_minutes):
        # Hold the nudge rather than rescheduling it, so it lands shortly after
        # you come back instead of being lost to an empty desk.
        return TickResult("idle", detail=activity.describe(cfg.max_idle_minutes))

    message = messages.pick(messages.load(cfg.packs), state.recent)
    deliver(message)

    scheduled = next_fire_after(cfg, now)
    state.next_fire = scheduled.timestamp()
    state.last_fire = timestamp
    state.fired_count += 1
    state.remember(message, cfg.no_repeat_window)
    state.save()
    return TickResult("fired", message=message, next_fire=scheduled)
