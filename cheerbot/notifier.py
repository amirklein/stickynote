"""Delivering a notification to macOS Notification Center.

Three transports, best first:

native      The Swift helper in Cheerbot.app. The only one that can put a badge
            image on the notification, and the only one with a real app icon.
applet      The AppleScript applet, used when swiftc is unavailable. Correctly
            attributed to Cheerbot, but text only.
osascript   Last resort when no bundle is installed at all. Works, but the
            notification is attributed to whatever is hosting the script.
"""

from __future__ import annotations

import subprocess
from typing import Tuple

from . import nativeapp, paths


class NotifyError(RuntimeError):
    pass


def _applet_installed() -> bool:
    return (paths.app_path() / "Contents" / "Resources" / "Scripts" / "main.scpt").exists()


def transport() -> str:
    if nativeapp.is_installed():
        return "native"
    if _applet_installed():
        return "applet"
    return "osascript"


def supports_badges() -> bool:
    return transport() == "native"


def resolve_placement(setting: str) -> str:
    """Turn the `emoji_placement` setting into a concrete placement.

    "auto" means: use the badge when the transport can render one, otherwise
    fall back to putting the emoji in the title text.
    """
    setting = (setting or "auto").strip().lower()
    if setting != "auto":
        return setting
    return "badge" if supports_badges() else "title"


def compose(title: str, emoji: str, placement: str) -> Tuple[str, str]:
    """Split an emoji into the title text and the badge slot."""
    if placement == "off" or not emoji:
        return title, ""
    if placement == "badge":
        return title, emoji
    if placement == "both":
        return f"{emoji} {title}".strip(), emoji
    return f"{emoji} {title}".strip(), ""


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _via_applet(title: str, body: str, sound: str) -> None:
    pending = paths.pending_path()
    pending.parent.mkdir(parents=True, exist_ok=True)
    # The applet parses exactly three lines: title, body, sound.
    payload = "\n".join(part.replace("\n", " ") for part in (title, body, sound))
    pending.write_text(payload + "\n", encoding="utf-8")

    result = subprocess.run(
        ["/usr/bin/open", str(paths.app_path())], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or "failed to launch Cheerbot.app")


def _via_osascript(title: str, body: str, sound: str) -> None:
    script = f'display notification "{_escape(body)}" with title "{_escape(title)}"'
    if sound:
        script += f' sound name "{_escape(sound)}"'
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or "osascript failed")


def send(title: str, body: str, sound: str = "", badge: str = "", linger: float = 0.0) -> str:
    """Show a notification. Returns the transport that was used."""
    chosen = transport()
    try:
        if chosen == "native":
            nativeapp.send(title, body, badge, sound, linger)
        elif chosen == "applet":
            _via_applet(title, body, sound)
        else:
            _via_osascript(title, body, sound)
    except nativeapp.BuildError as exc:
        raise NotifyError(str(exc))
    return chosen
