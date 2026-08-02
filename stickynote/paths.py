"""Filesystem locations used by stickynote.

Two rules hold everywhere in here. Anything shipped with the package is
read-only and lives under `data/`; anything belonging to the user lives under
`home()`, which STICKYNOTE_HOME can redirect so the tests (and anyone wanting a
second profile) never touch a real install.

Nothing resolves relative to a git checkout, so the package works the same
installed into site-packages as it does from a clone.
"""

from __future__ import annotations

import os
from pathlib import Path

LABEL = "dev.stickynote.agent"
# The bundle filename, kept free of spaces so it is pleasant on a command line.
APP_NAME = "StickyNote"
# What macOS shows in the notification header and the app list.
DISPLAY_NAME = "Sticky Note"

PACKAGE_ROOT = Path(__file__).resolve().parent
DATA = PACKAGE_ROOT / "data"

BUNDLED_PACKS = DATA / "packs"
NOTIFIER_SOURCE = DATA / "notifier.swift"
SETTINGS_SOURCE = DATA / "settings.swift"
APPLESCRIPT_SOURCE = DATA / "notifier.applescript"

BUNDLED_EMOJI = DATA / "emoji.txt"

# Names of the previous incarnation, kept only so migrate.py can find and
# retire it. Nothing else should reference these.
LEGACY_NAME = "cheerbot"
LEGACY_LABEL = "dev.cheerbot.agent"


def home() -> Path:
    override = os.environ.get("STICKYNOTE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "stickynote"


def legacy_home() -> Path:
    return Path.home() / ".config" / LEGACY_NAME


def config_path() -> Path:
    return home() / "config.json"


def state_path() -> Path:
    return home() / "state.json"


def ai_path() -> Path:
    return home() / "ai.json"


def user_packs_dir() -> Path:
    """Packs the user wrote, generated or translated."""
    return home() / "packs"


def user_messages_path() -> Path:
    return home() / "messages.txt"


def user_emoji_path() -> Path:
    return home() / "emoji.txt"


def log_path() -> Path:
    return home() / "stickynote.log"


def support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def pending_path() -> Path:
    """Handoff file the notifier app reads its payload from."""
    return support_dir() / "pending.txt"


def app_path() -> Path:
    return Path.home() / "Applications" / f"{APP_NAME}.app"


def legacy_app_path() -> Path:
    return Path.home() / "Applications" / "Cheerbot.app"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def legacy_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LEGACY_LABEL}.plist"
