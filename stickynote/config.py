"""User configuration: when stickynote is allowed to speak, and how."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from datetime import datetime, time
from typing import Any, Dict, List

from . import paths


def _parse_hhmm(value: str) -> time:
    hours, _, minutes = value.partition(":")
    return time(int(hours), int(minutes or 0))


# What the retired `tone` setting used to mean.
_TONES = {"funny": ["funny"], "sincere": ["sincere"], "mixed": ["funny", "sincere"]}


@dataclass
class Config:
    enabled: bool = True
    # A notification fires at a uniformly random point in this range.
    min_minutes: float = 15.0
    max_minutes: float = 50.0
    # Local-time window during which notifications are allowed.
    active_start: str = "09:00"
    active_end: str = "21:00"
    # 0 = Monday ... 6 = Sunday.
    active_days: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    title: str = "Sticky Note"
    # "random" draws from the emoji pool, "off" empties the slot, anything else
    # is used literally.
    emoji: str = "random"
    # Where the emoji goes: "badge" (image on the notification), "title" (text
    # prefix), "both", "off", or "auto" to use a badge when the transport can
    # render one and fall back to the title when it cannot.
    emoji_placement: str = "auto"
    # The app's own icon: an emoji, or a path to an image. Baked in at install
    # time, since macOS freezes it at the first permission grant.
    app_icon: str = "📝"
    # Bumped whenever app_icon changes, to present macOS with a bundle
    # identifier it has not cached an icon for. See nativeapp.bundle_id.
    bundle_generation: int = 1
    # Any macOS alert sound name, or "" for silent.
    sound: str = ""
    # How long the notification stays on screen, in seconds. Only has an effect
    # once Sticky Note is set to Alerts in System Settings; a banner is dismissed
    # by the system after about five seconds no matter what. 0 leaves it up
    # until dismissed.
    linger_seconds: float = 15.0
    # Which theme packs to draw from. Several can be mixed; duplicate lines
    # across packs are collapsed. Ignored once you supply your own messages
    # file. Supersedes the old `tone` setting, which is still read on load.
    packs: List[str] = field(default_factory=lambda: ["funny"])
    # Hold notifications back unless someone is actually at the machine.
    require_activity: bool = True
    # How long without input counts as away.
    max_idle_minutes: float = 5.0
    # How many recent messages to avoid repeating. Wants to scale with the
    # frequency: at roughly 20 a day this is about four days of no echoes.
    no_repeat_window: int = 80
    # When off, `status` hides the exact next-nudge time so it stays a surprise.
    show_next: bool = True

    # --- Optional model access. Everything here is off until asked for, and
    # every one of these paths falls back to the bundled packs on failure.
    # Top the generated pack up in the background when unseen lines run low.
    ai_auto_refill: bool = False
    # How few unseen lines is "running low", and how many to add when it is.
    ai_refill_threshold: int = 40
    ai_refill_count: int = 100
    # Generate each note as it is sent. Off by default: the delivery path runs
    # unattended, so a hung request would be silence, and an unreviewed line
    # would be one nobody approved.
    ai_live: bool = False
    ai_live_timeout: float = 4.0
    # Free-text guidance handed to the model, e.g. "dry, British, no exclamation marks".
    ai_style: str = ""

    # Agent hooks ignore the active-hours window, since an agent finishing at
    # 23:00 is exactly when you want to know, but they do respect a pause.
    hooks_respect_pause: bool = True

    @classmethod
    def load(cls) -> "Config":
        path = paths.config_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            return cls()
        # `tone` became `packs`. Translate rather than warn: a config written
        # before the change should keep working without anyone being told to
        # go and edit it.
        if "packs" not in raw and "tone" in raw:
            raw["packs"] = _TONES.get(str(raw["tone"]).strip().lower(), ["funny"])

        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        path = paths.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2) + "\n")

    def as_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def validate(self) -> None:
        if self.min_minutes <= 0:
            raise ValueError("min_minutes must be greater than 0")
        if self.max_minutes < self.min_minutes:
            raise ValueError("max_minutes must be >= min_minutes")
        if not self.active_days:
            raise ValueError("active_days must contain at least one day")
        if any(d < 0 or d > 6 for d in self.active_days):
            raise ValueError("active_days must be integers 0 (Mon) through 6 (Sun)")
        allowed = ("auto", "badge", "title", "both", "off")
        if self.emoji_placement.strip().lower() not in allowed:
            raise ValueError(f"emoji_placement must be one of {', '.join(allowed)}")
        if not self.packs:
            raise ValueError("packs must name at least one theme pack")
        from . import packs as packs_module

        known = packs_module.available()
        unknown = [p for p in self.packs if p not in known]
        if unknown:
            raise ValueError(
                f"unknown pack(s): {', '.join(unknown)}. "
                f"Available: {', '.join(sorted(known))}"
            )
        if self.max_idle_minutes <= 0:
            raise ValueError("max_idle_minutes must be greater than 0")
        if self.linger_seconds < 0:
            raise ValueError("linger_seconds must be 0 or greater")
        if self.ai_live_timeout <= 0:
            raise ValueError("ai_live_timeout must be greater than 0")
        if self.ai_refill_count <= 0:
            raise ValueError("ai_refill_count must be greater than 0")
        _parse_hhmm(self.active_start)
        _parse_hhmm(self.active_end)

    def allows(self, moment: datetime) -> bool:
        """True if a notification may fire at this local datetime."""
        start = _parse_hhmm(self.active_start)
        end = _parse_hhmm(self.active_end)
        clock = moment.time()

        if start <= end:
            in_window = start <= clock < end
            day = moment.weekday()
        else:
            # Window wraps past midnight; the early-morning tail belongs to the
            # previous day for the purpose of active_days.
            in_window = clock >= start or clock < end
            day = moment.weekday() if clock >= start else (moment.weekday() - 1) % 7

        return in_window and day in self.active_days

    def window_label(self) -> str:
        days = ",".join(
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d]
            for d in sorted(self.active_days)
        )
        return f"{self.active_start}-{self.active_end} on {days}"


def coerce(field_name: str, raw: str) -> Any:
    """Turn a command-line string into the right type for a config field."""
    types = {f.name: f.type for f in fields(Config)}
    if field_name not in types:
        raise KeyError(field_name)

    declared = types[field_name]
    if declared == "bool":
        lowered = raw.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{field_name} expects a boolean, got {raw!r}")
    if declared == "float":
        return float(raw)
    if declared == "int":
        return int(raw)
    if declared == "List[int]":
        return [int(part) for part in raw.replace(",", " ").split()]
    if declared == "List[str]":
        return [part.strip().lower() for part in raw.replace(",", " ").split()]
    return raw
