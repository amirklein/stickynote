"""Installing and removing the background pieces: the applet and the LaunchAgent."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

from . import paths

# How often launchd wakes us up to check whether it is time to fire. The actual
# notification times are random; this is just the polling granularity.
POLL_SECONDS = 300

APPLESCRIPT_SOURCE = paths.APPLESCRIPT_SOURCE
APPLET_BUNDLE_ID = "dev.stickynote.app"


def _run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(cmd)} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def build_applet() -> Path:
    """Compile the AppleScript applet used when swiftc is unavailable.

    Text only: AppleScript cannot attach a badge image. See nativeapp.py for
    the preferred transport.
    """
    app = paths.app_path()
    app.parent.mkdir(parents=True, exist_ok=True)
    if app.exists():
        shutil.rmtree(app)

    _run(["/usr/bin/osacompile", "-o", str(app), str(APPLESCRIPT_SOURCE)])

    info = app / "Contents" / "Info.plist"
    with info.open("rb") as handle:
        data = plistlib.load(handle)
    data["CFBundleName"] = paths.APP_NAME
    data["CFBundleDisplayName"] = paths.DISPLAY_NAME
    data["CFBundleIdentifier"] = APPLET_BUNDLE_ID
    # Keep the applet out of the Dock and the app switcher.
    data["LSUIElement"] = True
    with info.open("wb") as handle:
        plistlib.dump(data, handle)

    # Editing Info.plist invalidates the signature osacompile applied, and
    # macOS refuses to launch the bundle until it is signed again.
    _run(["/usr/bin/codesign", "--force", "--sign", "-", str(app)])

    # Re-register so Notification Center picks up the new bundle metadata.
    _run(
        [
            "/System/Library/Frameworks/CoreServices.framework/Frameworks"
            "/LaunchServices.framework/Support/lsregister",
            "-f",
            str(app),
        ],
        check=False,
    )
    return app


def write_plist() -> Path:
    plist = paths.plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    paths.log_path().parent.mkdir(parents=True, exist_ok=True)

    # `-m` rather than a path to a script: the job then survives the package
    # being installed anywhere, and does not pin the agent to a git checkout.
    job = {
        "Label": paths.LABEL,
        "ProgramArguments": [sys.executable, "-m", "stickynote", "tick"],
        "StartInterval": POLL_SECONDS,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": str(paths.log_path()),
        "StandardErrorPath": str(paths.log_path()),
    }

    # launchd starts with a bare environment, so an import that works in a
    # shell can still fail here. Naming the directory holding the package is
    # redundant for a site-packages install and essential for a checkout.
    environment = {"PYTHONPATH": str(paths.PACKAGE_ROOT.parent)}
    if os.environ.get("STICKYNOTE_HOME"):
        environment["STICKYNOTE_HOME"] = os.environ["STICKYNOTE_HOME"]
    job["EnvironmentVariables"] = environment

    with plist.open("wb") as handle:
        plistlib.dump(job, handle)
    return plist


def _domain() -> str:
    return f"gui/{os.getuid()}"


def load() -> None:
    plist = paths.plist_path()
    _run(["/bin/launchctl", "bootout", f"{_domain()}/{paths.LABEL}"], check=False)
    _run(["/bin/launchctl", "bootstrap", _domain(), str(plist)])
    _run(["/bin/launchctl", "enable", f"{_domain()}/{paths.LABEL}"], check=False)


def unload() -> None:
    _run(["/bin/launchctl", "bootout", f"{_domain()}/{paths.LABEL}"], check=False)


def is_loaded() -> bool:
    result = _run(["/bin/launchctl", "list"], check=False)
    return paths.LABEL in result.stdout


def kickstart() -> None:
    _run(
        ["/bin/launchctl", "kickstart", f"{_domain()}/{paths.LABEL}"],
        check=False,
    )


def write_menubar_plist() -> Path:
    """A separate job for the menu bar item, so it can be wanted independently.

    Folding it into the notification agent would mean anyone who wants notes
    also gets an icon in their menu bar, and anyone who quits the icon loses
    their notes.
    """
    plist = paths.menubar_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)

    job = {
        "Label": paths.MENUBAR_LABEL,
        "ProgramArguments": [sys.executable, "-m", "stickynote", "settings",
                             "--menu-bar"],
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(paths.log_path()),
        "StandardErrorPath": str(paths.log_path()),
        "EnvironmentVariables": {"PYTHONPATH": str(paths.PACKAGE_ROOT.parent)},
    }
    with plist.open("wb") as handle:
        plistlib.dump(job, handle)
    return plist


def load_menubar() -> None:
    plist = paths.menubar_plist_path()
    _run(["/bin/launchctl", "bootout", f"{_domain()}/{paths.MENUBAR_LABEL}"], check=False)
    _run(["/bin/launchctl", "bootstrap", _domain(), str(plist)], check=False)


def unload_menubar() -> None:
    _run(["/bin/launchctl", "bootout", f"{_domain()}/{paths.MENUBAR_LABEL}"], check=False)
    if paths.menubar_plist_path().exists():
        paths.menubar_plist_path().unlink()
