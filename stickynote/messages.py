"""Loading and picking the two content pools: encouragements and emoji."""

from __future__ import annotations

import random
from pathlib import Path
from typing import List, Sequence, Tuple

from . import paths

# Values of the `emoji` setting that mean "leave the slot empty".
_OFF = ("", "off", "none", "no")


def _read(path: Path) -> List[str]:
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def _pool(user: Path, bundled: Path) -> Tuple[List[str], Path]:
    """A user file replaces the bundled set entirely when it has content."""
    entries = _read(user)
    if entries:
        return entries, user
    return _read(bundled), bundled


def _bundled_for(tone: str) -> List[Path]:
    tone = (tone or "funny").strip().lower()
    if tone == "sincere":
        return [paths.BUNDLED_MESSAGES]
    if tone == "mixed":
        return [paths.BUNDLED_FUNNY, paths.BUNDLED_MESSAGES]
    return [paths.BUNDLED_FUNNY]


def load(tone: str = "funny") -> List[str]:
    """Your own messages file wins outright; otherwise tone picks the pools."""
    user = _read(paths.user_messages_path())
    if user:
        return user
    combined: List[str] = []
    for path in _bundled_for(tone):
        combined.extend(_read(path))
    return combined


def source_path(tone: str = "funny") -> Path:
    user = paths.user_messages_path()
    if _read(user):
        return user
    bundled = _bundled_for(tone)
    return bundled[0] if len(bundled) == 1 else bundled[0].parent


def load_emoji() -> List[str]:
    return _pool(paths.user_emoji_path(), paths.BUNDLED_EMOJI)[0]


def emoji_source_path() -> Path:
    return _pool(paths.user_emoji_path(), paths.BUNDLED_EMOJI)[1]


def pick(pool: Sequence[str], recent: Sequence[str]) -> str:
    if not pool:
        return "You're doing better than you think."
    fresh = [m for m in pool if m not in recent]
    return random.choice(fresh or list(pool))


def pick_emoji(setting: str, last: str = "") -> str:
    """Resolve the `emoji` setting into the character for this notification.

    "random" draws from the pool (never twice in a row), anything else is
    treated as a literal emoji to use every time.
    """
    setting = (setting or "").strip()
    if setting.lower() in _OFF:
        return ""
    if setting.lower() != "random":
        return setting

    pool = load_emoji()
    if not pool:
        return ""
    fresh = [e for e in pool if e != last]
    return random.choice(fresh or pool)
