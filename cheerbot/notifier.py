"""Delivering a notification to macOS Notification Center.

Preferred path is the tiny Cheerbot.app applet built by `cheerbot install`, so
alerts are attributed to Cheerbot and can be managed in System Settings. When
that bundle is missing we fall back to raw osascript, which works but shows up
under whichever app is hosting the script.
"""

from __future__ import annotations

import subprocess
from typing import Optional

from . import paths


class NotifyError(RuntimeError):
    pass


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _via_app(title: str, body: str, sound: str) -> bool:
    app = paths.app_path()
    if not app.exists():
        return False

    pending = paths.pending_path()
    pending.parent.mkdir(parents=True, exist_ok=True)
    # The applet parses exactly three lines: title, body, sound.
    payload = "\n".join(part.replace("\n", " ") for part in (title, body, sound))
    pending.write_text(payload + "\n", encoding="utf-8")

    result = subprocess.run(
        ["/usr/bin/open", "-a", str(app)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or "failed to launch Cheerbot.app")
    return True


def _via_osascript(title: str, body: str, sound: str) -> None:
    script = f'display notification "{_escape(body)}" with title "{_escape(title)}"'
    if sound:
        script += f' sound name "{_escape(sound)}"'
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or "osascript failed")


def send(title: str, body: str, sound: str = "") -> str:
    """Show a notification. Returns the transport that was used."""
    if _via_app(title, body, sound):
        return "app"
    _via_osascript(title, body, sound)
    return "osascript"


def transport() -> Optional[str]:
    return "app" if paths.app_path().exists() else "osascript"
