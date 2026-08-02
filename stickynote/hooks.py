"""Wiring Sticky Note into coding agents.

All three tools converge on the same two moments — the agent finished, or the
agent needs you — and all three can be configured with JSON, which the stdlib
can both read and write. Codex also has a `notify` field in config.toml, but
writing TOML is not something the stdlib does, and on many machines that field
is already taken by something else. Its hooks.json is the safer door.

Installing merges into whatever is already there and backs the file up first.
Someone's editor hooks are not ours to overwrite.
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import paths

MARKER = "stickynote event"


@dataclass
class Tool:
    id: str
    name: str
    config: Path
    note: str = ""


def _command(kind: str, source: str) -> str:
    """The command a hook runs.

    Absolute python and an explicit PYTHONPATH, because a hook inherits very
    little environment: `stickynote` may not be on PATH, and `-m stickynote`
    will not resolve from a checkout without being told where to look.
    """
    return (f'PYTHONPATH="{paths.PACKAGE_ROOT.parent}" {sys.executable} '
            f'-m stickynote event --source "{source}" --kind {kind}')


def tools() -> Dict[str, Tool]:
    home = Path.home()
    return {
        "cursor": Tool("cursor", "Cursor", home / ".cursor" / "hooks.json"),
        "claude": Tool(
            "claude", "Claude Code", home / ".claude" / "settings.json",
            "also covers permission and idle prompts",
        ),
        "codex": Tool(
            "codex", "Codex", home / ".codex" / "hooks.json",
            "run /hooks in Codex afterwards to trust it",
        ),
    }


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict) -> Optional[Path]:
    """Write the config, returning the backup path if one was needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_suffix(path.suffix + ".stickynote-backup")
        shutil.copyfile(path, backup)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return backup


# Each tool's shape differs enough that describing them separately is clearer
# than one abstraction bent around three formats.

def _cursor_entries(data: dict) -> Dict[str, List[dict]]:
    return data.setdefault("hooks", {})


def _install_cursor(data: dict) -> dict:
    """Cursor takes a flat list of {command} objects per event."""
    hooks = _cursor_entries(data)
    entries = hooks.setdefault("stop", [])
    if not any(MARKER in str(e.get("command", "")) for e in entries):
        entries.append({"command": _command("done", "cursor")})
    return data


def _install_claude(data: dict) -> dict:
    """Claude Code nests handlers under a matcher."""
    hooks = data.setdefault("hooks", {})

    def add(event: str, matcher: str, kind: str) -> None:
        groups = hooks.setdefault(event, [])
        for group in groups:
            for handler in group.get("hooks", []):
                if MARKER in str(handler.get("command", "")):
                    return
        entry = {"hooks": [{"type": "command", "command": _command(kind, "claude code")}]}
        if matcher:
            entry["matcher"] = matcher
        groups.append(entry)

    add("Stop", "", "done")
    add("Notification", "permission_prompt|idle_prompt", "waiting")
    return data


def _install_codex(data: dict) -> dict:
    """Codex uses the same nested shape as Claude Code, in its own file."""
    hooks = data.setdefault("hooks", {})
    groups = hooks.setdefault("Stop", [])
    for group in groups:
        for handler in group.get("hooks", []):
            if MARKER in str(handler.get("command", "")):
                return data
    groups.append(
        {"hooks": [{"type": "command", "command": _command("done", "codex"),
                    "statusMessage": "Sticky Note"}]}
    )
    return data


_INSTALLERS = {"cursor": _install_cursor, "claude": _install_claude, "codex": _install_codex}


def _strip(value):
    """Recursively drop anything of ours, and any group left empty by that."""
    if isinstance(value, dict):
        if MARKER in str(value.get("command", "")):
            return None
        cleaned = {}
        for key, item in value.items():
            result = _strip(item)
            if result is not None:
                cleaned[key] = result
        if "hooks" in value and not cleaned.get("hooks"):
            return None
        return cleaned
    if isinstance(value, list):
        kept = [r for r in (_strip(item) for item in value) if r is not None]
        return kept
    return value


def installed(tool_id: str) -> bool:
    return MARKER in json.dumps(_read(tools()[tool_id].config))


def install(tool_id: str) -> Tuple[bool, Optional[Path]]:
    """Returns (changed, backup path)."""
    tool = tools()[tool_id]
    if installed(tool_id):
        return False, None
    data = _INSTALLERS[tool_id](_read(tool.config))
    return True, _write(tool.config, data)


def uninstall(tool_id: str) -> Tuple[bool, Optional[Path]]:
    tool = tools()[tool_id]
    if not installed(tool_id):
        return False, None
    return True, _write(tool.config, _strip(_read(tool.config)))


def codex_feature_enabled() -> Optional[bool]:
    """Whether Codex has hooks switched on. None when it cannot be determined."""
    config = Path.home() / ".codex" / "config.toml"
    if not config.exists():
        return None
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        return None

    # Reading it as text rather than parsing: tomllib is 3.11+, and this is
    # only used to decide whether to print a reminder.
    for key in ("hooks", "codex_hooks"):
        if f"{key} = false" in text:
            return False
        if f"{key} = true" in text:
            return True
    return None


def events_path() -> Path:
    return paths.DATA / "events.json"


def event_lines(kind: str) -> Tuple[List[str], str]:
    try:
        data = json.loads(events_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], ""
    entry = data.get(kind, {})
    return entry.get("lines", []), entry.get("badge", "")
