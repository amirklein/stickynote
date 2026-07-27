"""Loading and picking encouragement lines."""

from __future__ import annotations

import random
from pathlib import Path
from typing import List, Sequence

from . import paths


def _read(path: Path) -> List[str]:
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def load() -> List[str]:
    """User messages replace the bundled set entirely when present."""
    user = _read(paths.user_messages_path())
    return user or _read(paths.BUNDLED_MESSAGES)


def source_path() -> Path:
    user = paths.user_messages_path()
    return user if _read(user) else paths.BUNDLED_MESSAGES


def pick(pool: Sequence[str], recent: Sequence[str]) -> str:
    if not pool:
        return "You're doing better than you think."
    fresh = [m for m in pool if m not in recent]
    return random.choice(fresh or list(pool))
