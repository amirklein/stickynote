"""The Swift notification helper: building it, and talking to it.

This exists because AppleScript's `display notification` cannot carry an image.
UserNotifications can, via UNNotificationAttachment, which is what puts the
interchanging emoji badge on the notification.

Two macOS constraints shape everything here:

1. The app must be registered in ~/Applications and launched with `open`. Run
   the binary straight from a shell and the authorization request is attributed
   to the terminal, and macOS refuses it outright.
2. The icon shown on the left of a notification is cached by the notification
   daemon the first time the bundle registers for permission, and is frozen
   from then on. Swapping the .icns afterwards updates Finder and
   LaunchServices but never the banner. So the icon has to be in place *before*
   the bundle is ever launched.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from . import paths

BUNDLE_ID = "dev.cheerbot.notifier"
BINARY_NAME = "cheerbot-notifier"
SOURCE = paths.REPO_ROOT / "notifier" / "CheerbotNotifier.swift"

# Sizes iconutil expects in an .iconset, each also needed at @2x.
_ICON_SIZES = (16, 32, 128, 256, 512)


class BuildError(RuntimeError):
    pass


def _run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise BuildError(
            f"{cmd[0]} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def swiftc() -> Optional[str]:
    return shutil.which("swiftc")


def available() -> bool:
    return swiftc() is not None


def binary_path() -> Path:
    return paths.app_path() / "Contents" / "MacOS" / BINARY_NAME


def is_installed() -> bool:
    return binary_path().exists()


def _compile(destination: Path) -> None:
    if not available():
        raise BuildError("swiftc not found; install the Xcode Command Line Tools")
    if not SOURCE.exists():
        raise BuildError(f"missing notifier source at {SOURCE}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run([swiftc(), "-O", str(SOURCE), "-o", str(destination)])


def _build_icon(binary: Path, emoji: str, resources: Path) -> None:
    """Render an emoji into the .icns the notification banner will show."""
    with tempfile.TemporaryDirectory() as work_dir:
        work = Path(work_dir)
        base = work / "base.png"
        _run([str(binary), "render", emoji, str(base)])

        iconset = work / "AppIcon.iconset"
        iconset.mkdir()
        for size in _ICON_SIZES:
            for scale, suffix in ((1, ""), (2, "@2x")):
                pixels = size * scale
                _run([
                    "/usr/bin/sips", "-z", str(pixels), str(pixels), str(base),
                    "--out", str(iconset / f"icon_{size}x{size}{suffix}.png"),
                ])

        icns = work / "AppIcon.icns"
        _run(["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(icns)])
        resources.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(icns, resources / "AppIcon.icns")


def _write_info_plist(contents: Path) -> None:
    info = {
        "CFBundleName": paths.APP_NAME,
        "CFBundleDisplayName": paths.APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": BINARY_NAME,
        "CFBundleIconFile": "AppIcon",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "11.0",
        # Keep it out of the Dock and the app switcher.
        "LSUIElement": True,
    }
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(info, handle)


def build(icon_emoji: str = "🌱") -> Path:
    """Compile and assemble ~/Applications/Cheerbot.app, ready but unlaunched."""
    app = paths.app_path()
    app.parent.mkdir(parents=True, exist_ok=True)
    if app.exists():
        shutil.rmtree(app)

    contents = app / "Contents"
    binary = contents / "MacOS" / BINARY_NAME
    _compile(binary)
    _build_icon(binary, icon_emoji or "🌱", contents / "Resources")
    _write_info_plist(contents)

    # Ad-hoc signing is enough for local use, but the bundle must be signed
    # after its contents are final or macOS will refuse to launch it.
    _run(["/usr/bin/codesign", "--force", "--sign", "-", str(app)])
    _run([
        "/System/Library/Frameworks/CoreServices.framework/Frameworks"
        "/LaunchServices.framework/Support/lsregister",
        "-f",
        str(app),
    ], check=False)
    return app


def log_path() -> Path:
    # Mirrors the hard-coded location in CheerbotNotifier.swift, which has no
    # way to learn about CHEERBOT_HOME.
    return Path.home() / ".config" / "cheerbot" / "notifier.log"


def send(title: str, body: str, emoji: str = "", sound: str = "") -> None:
    """Launch the helper to post one notification.

    `-n` forces a fresh instance: `open` would otherwise just activate the
    running one and silently drop the request if two land close together.
    """
    args = [
        "/usr/bin/open", "-n", "-a", str(paths.app_path()), "--args",
        "notify", "--title", title, "--body", body,
    ]
    if emoji:
        args += ["--emoji", emoji]
    if sound:
        args += ["--sound", sound]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise BuildError(result.stderr.strip() or "could not launch the notifier app")


def recent_failure(since_size: int) -> Optional[str]:
    """Any error the helper logged after `since_size` bytes. Delivery is
    asynchronous, so this is how an interactive command notices a problem."""
    path = log_path()
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[since_size:]
    except OSError:
        return None
    for line in text.splitlines():
        if any(word in line for word in ("denied", "failed", "error")):
            return line.strip()
    return None


def log_size() -> int:
    path = log_path()
    return path.stat().st_size if path.exists() else 0
