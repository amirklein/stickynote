"""Is anyone actually at the machine?

Encouragement that lands while you are at lunch is wasted, so a notification is
held back unless there has been recent input and the screen is unlocked.

Both signals come from `ioreg`, which needs no dependencies and works from a
launchd job. `HIDIdleTime` is the time since the last keyboard or mouse event,
in nanoseconds.
"""

from __future__ import annotations

import re
import subprocess
from typing import Optional

_IDLE_PATTERN = re.compile(r'"?HIDIdleTime"?\s*=\s*(\d+)')
_NANOSECONDS = 1_000_000_000


def _ioreg(args) -> str:
    try:
        result = subprocess.run(
            ["/usr/sbin/ioreg"] + args, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


def idle_seconds() -> Optional[float]:
    """Seconds since the last input event, or None if it cannot be determined."""
    output = _ioreg(["-c", "IOHIDSystem"])
    matches = _IDLE_PATTERN.findall(output)
    if not matches:
        return None
    # Several HID entries can report a time; the smallest is the most recent
    # interaction across all input devices.
    return min(int(value) for value in matches) / _NANOSECONDS


def screen_locked() -> bool:
    output = _ioreg(["-n", "Root", "-d1", "-k", "CGSSessionScreenIsLocked"])
    return "CGSSessionScreenIsLocked" in output and "Yes" in output


def is_active(max_idle_minutes: float) -> bool:
    """True if someone appears to be using the machine right now.

    Fails open: if idle time cannot be read, assume active rather than going
    permanently silent on a machine where the probe does not work.
    """
    if screen_locked():
        return False
    idle = idle_seconds()
    if idle is None:
        return True
    return idle <= max_idle_minutes * 60


def describe(max_idle_minutes: float) -> str:
    if screen_locked():
        return "screen locked"
    idle = idle_seconds()
    if idle is None:
        return "unknown (assuming active)"
    if idle <= max_idle_minutes * 60:
        return f"active, idle {int(idle)}s"
    return f"away, idle {int(idle // 60)}m"
