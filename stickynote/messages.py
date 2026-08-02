"""Loading and picking the two content pools: messages and emoji."""

from __future__ import annotations

import random
from pathlib import Path
from typing import List, Sequence, Tuple

from . import packs, paths

# Values of the `emoji` setting that mean "leave the slot empty".
_OFF = ("", "off", "none", "no")

# What the old `tone` setting meant, kept so existing configs keep working.
_TONE_ALIASES = {
    "funny": ["funny"],
    "sincere": ["sincere"],
    "mixed": ["funny", "sincere"],
}

_read = packs.read_lines


def resolve(selection) -> List[str]:
    """Turn either a pack list or a legacy tone string into pack ids."""
    if isinstance(selection, str):
        return list(_TONE_ALIASES.get(selection.strip().lower(), [selection.strip().lower()]))
    return [str(entry).strip().lower() for entry in (selection or []) if str(entry).strip()]


def _pool(user: Path, bundled: Path) -> Tuple[List[str], Path]:
    """A user file replaces the bundled set entirely when it has content."""
    entries = _read(user)
    if entries:
        return entries, user
    return _read(bundled), bundled


def load(selection="funny") -> List[str]:
    """Your own messages.txt wins outright; otherwise the chosen packs apply."""
    user = _read(paths.user_messages_path())
    if user:
        return user

    chosen = packs.messages_for(resolve(selection))
    if chosen:
        return chosen
    # A config naming packs that no longer exist should still say something.
    return packs.messages_for(["funny"])


def source_path(selection="funny") -> Path:
    user = paths.user_messages_path()
    if _read(user):
        return user
    ids = resolve(selection)
    catalogue = packs.available()
    live = [catalogue[i].messages_path for i in ids if i in catalogue]
    if len(live) == 1:
        return live[0]
    return paths.BUNDLED_PACKS


def load_emoji(selection=None) -> List[str]:
    """Emoji come from the user file, else any pack that supplies its own."""
    user = _read(paths.user_emoji_path())
    if user:
        return user
    if selection is not None:
        from_packs = packs.emoji_for(resolve(selection))
        if from_packs:
            return from_packs
    return _read(paths.BUNDLED_EMOJI)


def emoji_source_path(selection=None) -> Path:
    user = paths.user_emoji_path()
    if _read(user):
        return user
    if selection is not None:
        for pack_id in resolve(selection):
            pack = packs.get(pack_id)
            if pack and pack.emoji():
                return pack.emoji_path
    return paths.BUNDLED_EMOJI


def pick(pool: Sequence[str], recent: Sequence[str]) -> str:
    if not pool:
        return "You're doing better than you think."
    fresh = [m for m in pool if m not in recent]
    return random.choice(fresh or list(pool))


def pick_emoji(setting: str, last: str = "", selection=None) -> str:
    """Resolve the `emoji` setting into the character for this notification.

    "random" draws from the pool (never twice in a row), anything else is
    treated as a literal emoji to use every time.
    """
    setting = (setting or "").strip()
    if setting.lower() in _OFF:
        return ""
    if setting.lower() != "random":
        return setting

    pool = load_emoji(selection)
    if not pool:
        return ""
    fresh = [e for e in pool if e != last]
    return random.choice(fresh or pool)
