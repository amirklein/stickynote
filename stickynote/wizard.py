"""The `stickynote setup` questionnaire.

Deliberately plain: `input()` and nothing else, so it works over SSH, inside
the curl installer, and for the many people who will never open Cursor. The
GUI in Phase 6 covers the same ground for anyone who would rather click.

Every answer is written to `~/.config/stickynote/config.json` and nowhere
else. Nothing here may write inside the installed package, which is asserted
by a test rather than left to good intentions: a package directory that
changes per user cannot be reinstalled, upgraded or reasoned about.
"""

from __future__ import annotations

import sys
from typing import Callable, List, Optional, Sequence, Tuple

from . import packs
from .config import Config

_RULE = "─" * 60

# Named here so the tests can answer the questionnaire without a terminal.
read_line = input


def interactive() -> bool:
    """False when there is no human to answer, e.g. piped or in a cron job."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def heading(text: str) -> None:
    print(f"\n{_RULE}\n{text}\n")


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = read_line(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    return answer or default


def ask_yes(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        answer = ask(f"{prompt} ({hint})").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  please answer y or n")


def choose(prompt: str, options: Sequence[Tuple[str, str]], default: int = 0) -> str:
    """Numbered menu. Options are (value, description) pairs."""
    print(f"{prompt}\n")
    for index, (value, description) in enumerate(options, start=1):
        marker = "*" if index - 1 == default else " "
        print(f"  {marker} {index}. {value:<12} {description}")
    print()
    while True:
        answer = ask("Choose a number", str(default + 1))
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        print(f"  pick a number from 1 to {len(options)}")


# (label, min_minutes, max_minutes, description)
_RHYTHMS = [
    ("gentle", 45.0, 180.0, "a handful a day, easy to miss"),
    ("steady", 25.0, 80.0, "about ten a day"),
    ("chatty", 15.0, 50.0, "about twenty a day, the default"),
    ("constant", 8.0, 25.0, "roughly one an hour, or more"),
]


def _frequency(cfg: Config) -> None:
    heading("How often should notes turn up?")
    labels = [(name, f"{desc} (every {lo:g}-{hi:g} min)") for name, lo, hi, desc in _RHYTHMS]
    labels.append(("custom", "pick the minutes yourself"))
    chosen = choose("Rhythm:", labels, default=2)

    if chosen == "custom":
        while True:
            try:
                low = float(ask("Shortest gap in minutes", "15"))
                high = float(ask("Longest gap in minutes", "50"))
                if low > 0 and high >= low:
                    cfg.min_minutes, cfg.max_minutes = low, high
                    break
            except ValueError:
                pass
            print("  needs two numbers, the second at least as big as the first")
    else:
        for name, low, high, _ in _RHYTHMS:
            if name == chosen:
                cfg.min_minutes, cfg.max_minutes = low, high

    # A no-repeat window wider than the pool would starve the picker, and one
    # much smaller than a few days' worth of notes lets echoes through.
    daily = (16 * 60) / ((cfg.min_minutes + cfg.max_minutes) / 2)
    cfg.no_repeat_window = max(20, int(daily * 4))


def _hours(cfg: Config) -> None:
    heading("When are you open to being interrupted?")
    cfg.active_start = ask("Start of the day (HH:MM)", cfg.active_start)
    cfg.active_end = ask("End of the day (HH:MM)", cfg.active_end)

    if ask_yes("Weekends too?", default=True):
        cfg.active_days = [0, 1, 2, 3, 4, 5, 6]
    else:
        cfg.active_days = [0, 1, 2, 3, 4]

    cfg.require_activity = ask_yes(
        "Only when you're actually at the machine?", default=True)


def _theme(cfg: Config) -> None:
    heading("Which notes do you want to hear?")
    catalogue = packs.available()
    options = [
        (pack.id, f"{len(pack.messages()):>4}  {pack.description}")
        for pack in catalogue.values()
    ]
    options.append(("mix", "     choose several and blend them"))

    default = next((i for i, (v, _) in enumerate(options) if v == "funny"), 0)
    chosen = choose("Theme pack:", options, default=default)

    if chosen != "mix":
        cfg.packs = [chosen]
    else:
        while True:
            raw = ask("Pack ids, comma separated", "funny,zen")
            wanted = [p.strip().lower() for p in raw.replace(",", " ").split()]
            unknown = [p for p in wanted if p not in catalogue]
            if wanted and not unknown:
                cfg.packs = wanted
                break
            print(f"  unknown: {', '.join(unknown) or '(nothing given)'}")

    from . import messages
    print(f"\n  {len(messages.load(cfg.packs))} notes selected. A taste:")
    for line in messages.load(cfg.packs)[:1] or []:
        print(f"    {line}")


def _looks(cfg: Config, apply_icon: Optional[Callable[[Config, str], int]] = None) -> None:
    heading("How should it look?")

    cfg.emoji = choose(
        "The badge on the right of each notification:",
        [
            ("random", "a different one every time"),
            ("off", "no badge at all"),
            ("fixed", "the same emoji every time"),
        ],
        default=0,
    )
    if cfg.emoji == "fixed":
        cfg.emoji = ask("Which emoji", "📝")

    print()
    print("The app icon on the left is baked into the app bundle, so changing")
    print("it later means macOS asks for notification permission again.")
    icon = ask("App icon: an emoji, or a path to a square image", cfg.app_icon)
    if icon and icon != cfg.app_icon and apply_icon:
        apply_icon(cfg, icon)
    elif icon:
        cfg.app_icon = icon


def _duration(cfg: Config) -> None:
    heading("How long should a note stay on screen?")
    print("macOS decides this, not the app. A banner disappears after about")
    print("five seconds; an alert stays until dismissed. Only you can switch")
    print("Sticky Note to alerts, in System Settings, and `stickynote alerts`")
    print("will take you there.\n")

    answer = ask("Seconds to keep it up once you've switched (0 = forever)",
                 f"{cfg.linger_seconds:g}")
    try:
        cfg.linger_seconds = max(0.0, float(answer))
    except ValueError:
        pass


def run(cfg: Config, apply_icon: Optional[Callable[[Config, str], int]] = None,
        first_run: bool = False) -> Config:
    """Ask everything, then hand back the config for the caller to save."""
    if first_run:
        print("\n📝  Sticky Note")
        print("\nA few questions, then notes start appearing. Every answer goes")
        print("into ~/.config/stickynote/config.json and can be changed later")
        print("with `stickynote config`, `stickynote setup`, or the settings window.")

    _frequency(cfg)
    _hours(cfg)
    _theme(cfg)
    _looks(cfg, apply_icon)
    _duration(cfg)
    return cfg


def summarise(cfg: Config) -> List[str]:
    from . import messages

    return [
        f"every {cfg.min_minutes:g}-{cfg.max_minutes:g} minutes, {cfg.window_label()}",
        f"{len(messages.load(cfg.packs))} notes from {', '.join(cfg.packs)}",
        f"badge {cfg.emoji}, app icon {cfg.app_icon}",
        f"on screen {cfg.linger_seconds:g}s once set to alerts",
    ]
