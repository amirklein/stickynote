"""Generating new notes with a model, in batches, offline from delivery.

Batch rather than live, by default, for two reasons the delivery path makes
unavoidable. It runs from a launchd tick with nobody watching, so a hung API
call is silence rather than an error someone sees. And an unreviewed line is
one nobody approved, which is fine on average and awful on the day it lands
badly. Batching keeps the curation floor the bundled packs have, and costs
one request per few hundred notes instead of one per note.

Generated lines go to a user pack in ~/.config/stickynote/packs/, never into
the installed package.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Iterable, List, Sequence, Set

from . import ai, messages, packs, paths
from .config import Config

GENERATED_PACK = "brewed"

_SYSTEM = (
    "You write short encouraging notifications that appear on someone's "
    "desktop while they work. Rules: one per line, no numbering, no quotes, "
    "no emoji, no preamble. Under 100 characters each. Warm and specific, "
    "never corporate, never a platitude, never condescending. They land at "
    "random moments, so nothing that assumes what the reader is doing, and "
    "nothing that would be cruel on a genuinely bad day."
)

# One request per batch; small enough that a failure is cheap, large enough
# that the per-request overhead is not the dominant cost.
BATCH = 50


def normalise(line: str) -> str:
    """The comparison key for near-duplicates.

    Matches the duplicate guard in the test suite: lines differing only in
    case or punctuation are the same line as far as a reader is concerned.
    """
    key = re.sub(r"[^a-z0-9 ]", "", line.lower())
    return re.sub(r"\s+", " ", key).strip()


def known_keys() -> Set[str]:
    """Every line already available anywhere, bundled or local."""
    seen = set()
    for pack in packs.available().values():
        seen.update(normalise(line) for line in pack.messages())
    seen.update(normalise(line) for line in packs.read_lines(paths.user_messages_path()))
    return seen


def _prompt(count: int, style: str, avoid: Sequence[str]) -> str:
    parts = [f"Write {count} of them."]
    if style:
        parts.append(f"Style: {style}")
    if avoid:
        parts.append(
            "For voice, here are existing ones. Match the register, but do "
            "not repeat or lightly reword them:\n" + "\n".join(avoid)
        )
    return "\n\n".join(parts)


def generate(count: int, style: str = "", timeout: float = 120.0,
             on_batch=None) -> List[str]:
    """Generate `count` new lines, deduplicated against everything known."""
    existing = known_keys()
    samples = messages.load(["funny"])[:12]
    fresh: List[str] = []
    attempts = 0

    # A model asked for 50 will return some it has effectively said before, so
    # keep going until there are enough genuinely new ones. Cap the attempts:
    # a pool that has exhausted a style should stop, not spend money forever.
    while len(fresh) < count and attempts < 6:
        attempts += 1
        want = min(BATCH, (count - len(fresh)) * 2)
        reply = ai.complete(_SYSTEM, _prompt(want, style, samples),
                            max_tokens=4000, timeout=timeout)

        added = 0
        for line in ai.lines_from(reply):
            key = normalise(line)
            if key and key not in existing:
                existing.add(key)
                fresh.append(line)
                added += 1
        if on_batch:
            on_batch(len(fresh), count, added)
        if added == 0:
            break

    return fresh[:count]


def save(lines: Iterable[str], pack_id: str = GENERATED_PACK) -> int:
    """Append to the generated pack, creating it if needed. Returns the total."""
    lines = list(lines)
    if not lines:
        return len(packs.read_lines(packs.user_pack_dir(pack_id) / "messages.txt"))

    existing = packs.read_lines(packs.user_pack_dir(pack_id) / "messages.txt")
    combined = existing + [l for l in lines if normalise(l) not in
                           {normalise(e) for e in existing}]
    packs.write_pack(
        pack_id,
        "Brewed",
        "Generated locally and kept here, never in the installed package.",
        "en",
        combined,
    )
    return len(combined)


def needs_refill(cfg: Config, recent: Sequence[str], pool: Sequence[str]) -> bool:
    """True when the unseen part of the pool has run down."""
    if not cfg.ai_auto_refill:
        return False
    unseen = len([line for line in pool if line not in recent])
    return unseen < cfg.ai_refill_threshold


def refill_in_background(cfg: Config) -> None:
    """Start a detached brew so the delivery path never waits on a network call."""
    log = paths.log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "stickynote", "brew",
               "--count", str(cfg.ai_refill_count), "--quiet"]
    if cfg.ai_style:
        command += ["--style", cfg.ai_style]

    environment = dict(os.environ)
    environment.setdefault("PYTHONPATH", str(paths.PACKAGE_ROOT.parent))
    try:
        with open(log, "a", encoding="utf-8") as handle:
            subprocess.Popen(command, stdout=handle, stderr=handle,
                             start_new_session=True, env=environment)
    except OSError:
        # Refilling is a nicety; failing to start one must not break delivery.
        pass


def live_line(cfg: Config, fallback: str) -> str:
    """One freshly generated line, or the fallback if anything at all goes wrong."""
    if not cfg.ai_live:
        return fallback
    try:
        reply = ai.complete(_SYSTEM, _prompt(1, cfg.ai_style, []),
                            max_tokens=200, timeout=cfg.ai_live_timeout)
        candidates = ai.lines_from(reply)
        return candidates[0] if candidates else fallback
    except ai.AIError:
        return fallback
