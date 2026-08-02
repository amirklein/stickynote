"""One-way migration from the old cheerbot install.

Two installs must never run at once: both would schedule notifications and both
would answer to `launchctl`. So the old agent is retired before the new one is
allowed to start, and the old config is copied rather than moved, leaving a
working fallback if any of this goes wrong.

Notification permission cannot come with it. macOS ties the grant to a bundle
identifier, and the identifier necessarily changed, so the user re-grants once
and the stale entry stays in System Settings forever. Nothing can be done about
that from here beyond saying so plainly.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import List

from . import paths

# Files worth carrying over. State is included so the no-repeat memory and the
# delivery count survive; logs are not.
_CARRY = ("config.json", "state.json", "messages.txt", "emoji.txt",
          "app_icon.png", "app_icon.icns")


def pending() -> bool:
    """True if an old install is present and has not been migrated yet."""
    if os.environ.get("STICKYNOTE_HOME"):
        return False
    return paths.legacy_home().is_dir() and not paths.home().exists()


def _retire_old_agent() -> List[str]:
    done = []
    plist = paths.legacy_plist_path()
    if plist.exists():
        subprocess.run(
            ["/bin/launchctl", "bootout", f"gui/{os.getuid()}/{paths.LEGACY_LABEL}"],
            capture_output=True, text=True,
        )
        plist.unlink()
        done.append("stopped and removed the old launch agent")
    if paths.legacy_app_path().exists():
        shutil.rmtree(paths.legacy_app_path(), ignore_errors=True)
        done.append("removed Cheerbot.app")
    return done


def _rewrite_icon_path(destination: Path) -> None:
    """Point app_icon at the copied file rather than the old directory."""
    config = destination / "config.json"
    if not config.exists():
        return
    try:
        data = json.loads(config.read_text())
    except (OSError, ValueError):
        return

    icon = str(data.get("app_icon", ""))
    old = str(paths.legacy_home())
    if icon.startswith(old):
        moved = destination / Path(icon).name
        data["app_icon"] = str(moved) if moved.exists() else "📝"

    # The old default title would otherwise keep announcing the old name.
    if data.get("title") in ("Cheerbot", "cheerbot"):
        data["title"] = paths.DISPLAY_NAME

    config.write_text(json.dumps(data, indent=2) + "\n")


def run() -> List[str]:
    """Carry an old install across. Returns a description of what happened."""
    source = paths.legacy_home()
    destination = paths.home()
    done = []

    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        copied = []
        for name in _CARRY:
            origin = source / name
            if origin.exists() and not (destination / name).exists():
                shutil.copyfile(origin, destination / name)
                copied.append(name)
        if copied:
            done.append(f"copied {', '.join(copied)} to {destination}")
        _rewrite_icon_path(destination)

    done.extend(_retire_old_agent())
    if source.is_dir():
        done.append(f"left the old files in {source}, delete them when happy")
    return done
