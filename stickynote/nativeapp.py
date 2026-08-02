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
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

from . import paths

BUNDLE_ID = "dev.stickynote.notifier"
BINARY_NAME = "stickynote-notifier"


def bundle_id(generation: int = 1) -> str:
    """The bundle identifier for a given icon generation.

    macOS freezes a bundle's notification icon at its first permission grant,
    so the only way to change the icon later is to present a new identifier.
    Generation 1 keeps the original id so existing installs are untouched.
    """
    return BUNDLE_ID if generation <= 1 else f"{BUNDLE_ID}{generation}"
SOURCE = paths.NOTIFIER_SOURCE

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
    for source in (SOURCE, paths.SETTINGS_SOURCE):
        if not source.exists():
            raise BuildError(f"missing Swift source at {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Two files, one binary. Swift only allows top-level statements in a file
    # called main.swift, so the entry point is copied under that name rather
    # than being stored under it, where the name would say nothing useful.
    with tempfile.TemporaryDirectory() as work_dir:
        work = Path(work_dir)
        shutil.copyfile(SOURCE, work / "main.swift")
        shutil.copyfile(paths.SETTINGS_SOURCE, work / "settings.swift")
        _run([swiftc(), "-O", str(work / "main.swift"),
              str(work / "settings.swift"), "-o", str(destination)])


def _dimensions(image: Path) -> Tuple[int, int]:
    result = _run(["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", str(image)])
    values = {}
    for line in result.stdout.splitlines():
        key, _, value = line.strip().partition(": ")
        if value.isdigit():
            values[key] = int(value)
    return values.get("pixelWidth", 0), values.get("pixelHeight", 0)


def _prepare_source(icon: str, binary: Path, work: Path) -> Path:
    """Produce a square PNG to build the .icns from.

    `icon` is either a path to an image or an emoji to render. Images are
    converted to real PNG regardless of their extension, since files are
    routinely named .png while holding JPEG data, and iconutil rejects those.
    """
    base = work / "base.png"
    candidate = Path(icon).expanduser()
    if not candidate.is_file():
        _run([str(binary), "render", icon, str(base)])
        return base

    _run(["/usr/bin/sips", "-s", "format", "png", str(candidate), "--out", str(base)])

    width, height = _dimensions(base)
    if width and height and width != height:
        # Pad rather than crop: sips -z would stretch, and cropping silently
        # discards whatever sits at the edges of the artwork.
        side = max(width, height)
        _run([
            "/usr/bin/sips", "--padToHeightWidth", str(side), str(side),
            "--padColor", "FFFFFF", str(base), "--out", str(base),
        ])
    return base


def _build_icon(binary: Path, icon: str, resources: Path) -> None:
    """Turn an emoji or image into the .icns the notification banner shows."""
    resources.mkdir(parents=True, exist_ok=True)

    candidate = Path(icon).expanduser()
    if candidate.is_file() and candidate.suffix.lower() == ".icns":
        # Already an icon set. Copy it verbatim rather than rebuilding from one
        # flattened PNG, which would discard any per-size artwork it carries.
        shutil.copyfile(candidate, resources / "AppIcon.icns")
        return

    with tempfile.TemporaryDirectory() as work_dir:
        work = Path(work_dir)
        base = _prepare_source(icon, binary, work)

        iconset = work / "AppIcon.iconset"
        iconset.mkdir()
        for size in _ICON_SIZES:
            for scale, suffix in ((1, ""), (2, "@2x")):
                pixels = size * scale
                _run([
                    "/usr/bin/sips", "-s", "format", "png",
                    "-z", str(pixels), str(pixels), str(base),
                    "--out", str(iconset / f"icon_{size}x{size}{suffix}.png"),
                ])

        icns = work / "AppIcon.icns"
        _run(["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(icns)])
        shutil.copyfile(icns, resources / "AppIcon.icns")


def _write_info_plist(contents: Path, generation: int) -> None:
    info = {
        "CFBundleName": paths.APP_NAME,
        "CFBundleDisplayName": paths.DISPLAY_NAME,
        "CFBundleIdentifier": bundle_id(generation),
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


def build(icon: str = "📝", generation: int = 1) -> Path:
    """Compile and assemble ~/Applications/StickyNote.app, ready but unlaunched.

    The icon is written before the bundle is ever launched, which is required:
    macOS caches it at the first permission grant and never re-reads it.
    """
    app = paths.app_path()
    app.parent.mkdir(parents=True, exist_ok=True)
    if app.exists():
        shutil.rmtree(app)

    contents = app / "Contents"
    binary = contents / "MacOS" / BINARY_NAME
    _compile(binary)
    _build_icon(binary, icon or "📝", contents / "Resources")
    _write_info_plist(contents, generation)

    # Ad-hoc signing is enough for local use, but the bundle must be signed
    # after its contents are final or macOS will refuse to launch it.
    _run(["/usr/bin/codesign", "--force", "--sign", "-", str(app)])
    _run([
        "/System/Library/Frameworks/CoreServices.framework/Frameworks"
        "/LaunchServices.framework/Support/lsregister",
        "-f",
        str(app),
    ], check=False)

    # Registration is asynchronous. An authorization request that beats it is
    # refused, and macOS holds that refusal against the bundle identifier
    # permanently, so the cheap wait here is worth far more than it costs.
    time.sleep(1.5)
    return app


def adopt_icon(source: Path) -> Path:
    """Copy a chosen icon into the config directory, in a stable format.

    Keeps the icon working after the original is moved out of Downloads. Images
    are normalised to PNG up front so a mislabelled JPEG cannot fail the build
    later; an .icns is kept as-is to preserve its per-size representations.
    """
    home = paths.home()
    home.mkdir(parents=True, exist_ok=True)

    if source.suffix.lower() == ".icns":
        destination = home / "app_icon.icns"
        shutil.copyfile(source, destination)
    else:
        destination = home / "app_icon.png"
        _run(["/usr/bin/sips", "-s", "format", "png", str(source), "--out", str(destination)])

    # Drop the other form so a stale file cannot be mistaken for the current one.
    for other in (home / "app_icon.png", home / "app_icon.icns"):
        if other != destination and other.exists():
            other.unlink()
    return destination


def log_path() -> Path:
    # Mirrors the hard-coded location in data/notifier.swift, which has no way
    # to learn about STICKYNOTE_HOME.
    return Path.home() / ".config" / "stickynote" / "notifier.log"


def send(title: str, body: str, emoji: str = "", sound: str = "", linger: float = 0.0) -> None:
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
    if linger > 0:
        args += ["--linger", str(linger)]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise BuildError(result.stderr.strip() or "could not launch the notifier app")


def open_window(mode: str = "settings") -> None:
    """Launch the settings window or the menu bar item.

    Through `open` rather than the binary directly, so the process belongs to
    the bundle: run straight from a terminal it inherits the terminal's
    identity, and a window from an unbundled process behaves oddly.
    """
    if not is_installed():
        raise BuildError("the app has not been built yet; run `stickynote start`")

    args = ["/usr/bin/open", "-n", "-a", str(paths.app_path()), "--args", mode,
            "--python", sys.executable, "--pypath", str(paths.PACKAGE_ROOT.parent)]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise BuildError(result.stderr.strip() or "could not open the window")


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
