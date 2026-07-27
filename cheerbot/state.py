"""Persisted scheduler state: when to fire next, and what was said recently."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional

from . import paths


@dataclass
class State:
    next_fire: Optional[float] = None
    last_fire: Optional[float] = None
    paused_until: Optional[float] = None
    recent: List[str] = field(default_factory=list)
    fired_count: int = 0

    @classmethod
    def load(cls) -> "State":
        path = paths.state_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        path = paths.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.as_dict(), indent=2) + "\n")
        tmp.replace(path)

    def as_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def remember(self, message: str, window: int) -> None:
        self.recent.append(message)
        if window > 0:
            del self.recent[:-window]
        else:
            self.recent.clear()
