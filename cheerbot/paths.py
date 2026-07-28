"""Filesystem locations used by cheerbot.

Everything is overridable through CHEERBOT_HOME so the test suite (and anyone
who wants a second profile) can run without touching the real config.
"""

from __future__ import annotations

import os
from pathlib import Path

LABEL = "dev.cheerbot.agent"
APP_NAME = "Cheerbot"

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO_ROOT / "bin" / "cheerbot"
BUNDLED_MESSAGES = Path(__file__).resolve().parent / "data" / "messages.txt"
BUNDLED_FUNNY = Path(__file__).resolve().parent / "data" / "messages-funny.txt"
BUNDLED_EMOJI = Path(__file__).resolve().parent / "data" / "emoji.txt"


def home() -> Path:
    override = os.environ.get("CHEERBOT_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "cheerbot"


def config_path() -> Path:
    return home() / "config.json"


def state_path() -> Path:
    return home() / "state.json"


def user_messages_path() -> Path:
    return home() / "messages.txt"


def user_emoji_path() -> Path:
    return home() / "emoji.txt"


def log_path() -> Path:
    return home() / "cheerbot.log"


def support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def pending_path() -> Path:
    """Handoff file the notifier app reads its payload from."""
    return support_dir() / "pending.txt"


def app_path() -> Path:
    return Path.home() / "Applications" / f"{APP_NAME}.app"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
