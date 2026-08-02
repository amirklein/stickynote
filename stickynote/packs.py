"""Theme packs: named collections of messages, bundled or user-made.

A pack is a directory holding `messages.txt`, optional `emoji.txt` and a
`pack.json` describing it. Bundled packs ship read-only inside the package;
anything the user writes, generates or translates lands in
`~/.config/stickynote/packs/` and shadows a bundled pack of the same name.

Packs are selected as a list so they can be mixed, and mixing deduplicates:
the themed packs are curated views of the same funny pool, so `funny` plus
`cosmic` would otherwise weight the cosmic lines twice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import paths


@dataclass
class Pack:
    id: str
    name: str
    description: str
    language: str
    path: Path
    bundled: bool

    @property
    def messages_path(self) -> Path:
        return self.path / "messages.txt"

    @property
    def emoji_path(self) -> Path:
        return self.path / "emoji.txt"

    def messages(self) -> List[str]:
        return read_lines(self.messages_path)

    def emoji(self) -> List[str]:
        return read_lines(self.emoji_path)


def read_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _load_one(folder: Path, bundled: bool) -> Optional[Pack]:
    if not (folder / "messages.txt").exists():
        return None
    meta: Dict[str, str] = {}
    manifest = folder / "pack.json"
    if manifest.exists():
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
    return Pack(
        id=meta.get("id") or folder.name,
        name=meta.get("name") or folder.name.replace("-", " ").title(),
        description=meta.get("description", ""),
        language=meta.get("language", "en"),
        path=folder,
        bundled=bundled,
    )


def available() -> Dict[str, Pack]:
    """Every pack, user copies shadowing bundled ones of the same name."""
    found: Dict[str, Pack] = {}
    for root, bundled in ((paths.BUNDLED_PACKS, True), (paths.user_packs_dir(), False)):
        if not root.is_dir():
            continue
        for folder in sorted(root.iterdir()):
            if not folder.is_dir():
                continue
            pack = _load_one(folder, bundled)
            if pack:
                found[pack.id] = pack
    return found


def get(pack_id: str) -> Optional[Pack]:
    return available().get(pack_id)


def messages_for(pack_ids: List[str]) -> List[str]:
    """Combined, order-preserving, deduplicated messages for these packs."""
    catalogue = available()
    seen, out = set(), []
    for pack_id in pack_ids:
        pack = catalogue.get(pack_id)
        if not pack:
            continue
        for line in pack.messages():
            if line not in seen:
                seen.add(line)
                out.append(line)
    return out


def emoji_for(pack_ids: List[str]) -> List[str]:
    catalogue = available()
    seen, out = set(), []
    for pack_id in pack_ids:
        pack = catalogue.get(pack_id)
        if not pack:
            continue
        for entry in pack.emoji():
            if entry not in seen:
                seen.add(entry)
                out.append(entry)
    return out


def user_pack_dir(pack_id: str) -> Path:
    """Where a writable pack of this name lives, created on demand."""
    folder = paths.user_packs_dir() / pack_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_pack(pack_id: str, name: str, description: str, language: str,
               lines: List[str]) -> Path:
    folder = user_pack_dir(pack_id)
    meta = {"id": pack_id, "name": name, "description": description, "language": language}
    (folder / "pack.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    header = f"# {name}: {description}\n# One per line; blank lines and #comments ignored.\n\n"
    (folder / "messages.txt").write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return folder
