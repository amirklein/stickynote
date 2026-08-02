"""Command line interface."""

from __future__ import annotations

import argparse
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

from . import (
    activity,
    launchagent,
    messages,
    migrate,
    nativeapp,
    notifier,
    packs,
    paths,
    scheduler,
    wizard,
)
from .config import Config, coerce
from .state import State

# Old tone names, still accepted by `config tone ...`.
_TONE_ALIASES = {"funny": ["funny"], "sincere": ["sincere"], "mixed": ["funny", "sincere"]}

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)\s*([mhd])$", re.IGNORECASE)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".heic", ".tiff", ".tif", ".gif", ".icns")


def _parse_duration(raw: str) -> timedelta:
    if raw.lower() == "today":
        tomorrow = (datetime.now() + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return tomorrow - datetime.now()
    match = _DURATION.match(raw.strip())
    if not match:
        raise argparse.ArgumentTypeError(
            f"cannot read duration {raw!r}; use forms like 90m, 3h, 2d, or today"
        )
    amount, unit = float(match.group(1)), match.group(2).lower()
    return {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]


def _humanize(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "now"
    if seconds < 90:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m"
    hours = minutes / 60
    if hours < 36:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def _compose(cfg: Config, emoji: str) -> Tuple[str, str]:
    """Resolve an emoji into the notification's title text and badge image."""
    return notifier.compose(cfg.title, emoji, notifier.resolve_placement(cfg.emoji_placement))


def _load_config() -> Config:
    cfg = Config.load()
    try:
        cfg.validate()
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    return cfg


def cmd_tick(_args) -> int:
    cfg = _load_config()
    state = State.load()
    now = datetime.now()

    def deliver(message: str) -> None:
        # scheduler.tick saves state after this returns, which persists the
        # emoji we just used so the next one differs.
        state.last_emoji = messages.pick_emoji(cfg.emoji, state.last_emoji)
        title, badge = _compose(cfg, state.last_emoji)
        notifier.send(title, message, cfg.sound, badge, cfg.linger_seconds)

    try:
        result = scheduler.tick(cfg, state, now, deliver)
    except notifier.NotifyError as exc:
        print(f"[{now:%Y-%m-%d %H:%M:%S}] notify failed: {exc}", file=sys.stderr)
        return 1

    if result.action == "fired":
        print(f"[{now:%Y-%m-%d %H:%M:%S}] fired: {result.message}")
    return 0


def cmd_now(args) -> int:
    cfg = _load_config()
    state = State.load()
    message = args.message or messages.pick(messages.load(cfg.packs), state.recent)
    emoji = args.emoji if args.emoji is not None else messages.pick_emoji(cfg.emoji, state.last_emoji)
    title, badge = _compose(cfg, emoji)
    linger = args.linger if args.linger is not None else cfg.linger_seconds
    before = nativeapp.log_size()
    try:
        transport = notifier.send(title, message, cfg.sound, badge, linger)
    except notifier.NotifyError as exc:
        print(f"could not send notification: {exc}", file=sys.stderr)
        return 1

    state.last_emoji = emoji
    if not args.message:
        state.remember(message, cfg.no_repeat_window)
        state.last_fire = datetime.now().timestamp()
        state.fired_count += 1
    state.save()
    label = f"{title} [badge {badge}]" if badge else title
    print(f"sent via {transport}: {label} - {message}")

    # Native delivery is asynchronous, so the only way to notice a refused
    # notification is to watch the helper's log.
    if transport == "native":
        time.sleep(2.0)
        failure = nativeapp.recent_failure(before)
        if failure:
            print(f"the notifier reported: {failure}", file=sys.stderr)
            return 1
    return 0


def _reschedule(cfg: Config, note: str) -> None:
    """Roll a new next-fire time and say so, without spoiling surprise mode."""
    state = State.load()
    nxt = scheduler.next_fire_after(cfg, datetime.now())
    state.next_fire = nxt.timestamp()
    state.save()
    if cfg.show_next:
        print(f"{note} around {nxt:%a %H:%M}")
    else:
        print(f"{note} at a time I'm not telling you")


def cmd_surprise(_args) -> int:
    cfg = scheduler.randomize(Config.load())
    cfg.save()
    _reschedule(cfg, "timing re-rolled; next nudge")
    print("run `stickynote config` if you'd rather see what it picked")
    return 0


def cmd_demo(args) -> int:
    """Fire a burst of notifications at random short gaps.

    Exercises the real pipeline (packs, no-repeat, badge, activity gate) on a
    timescale you can actually watch, without touching the schedule or stats.
    """
    cfg = _load_config()
    state = State.load()
    pool = messages.load(cfg.packs)
    recent = list(state.recent)
    last_emoji = state.last_emoji

    print(f"{args.count} notifications, {args.min}-{args.max}s apart, packs={'+'.join(cfg.packs)}")
    print("(this is a preview: the real schedule and counters are untouched)\n")

    for index in range(1, args.count + 1):
        if index > 1:
            gap = random.uniform(args.min, args.max)
            print(f"  ... waiting {gap:.0f}s")
            time.sleep(gap)

        if cfg.require_activity and not activity.is_active(cfg.max_idle_minutes):
            print(f"  {index}. held back: {activity.describe(cfg.max_idle_minutes)}")
            continue

        message = messages.pick(pool, recent)
        recent.append(message)
        last_emoji = messages.pick_emoji(cfg.emoji, last_emoji)
        title, badge = _compose(cfg, last_emoji)
        try:
            notifier.send(title, message, cfg.sound, badge, cfg.linger_seconds)
        except notifier.NotifyError as exc:
            print(f"  {index}. failed: {exc}", file=sys.stderr)
            return 1
        print(f"  {index}. {badge or '—'}  {message}")

    print("\ndemo over; your real schedule is unchanged")
    return 0


def _linger_label(cfg: Config) -> str:
    if cfg.linger_seconds <= 0:
        return "until dismissed"
    return f"{cfg.linger_seconds:g}s, if set to Alerts (banners are capped near 5s)"


def cmd_alerts(_args) -> int:
    """Open the pane where the banner/alert choice lives.

    It cannot be set programmatically, nor read back reliably: the preference
    is guarded by the system, and Apple has said apps will not be allowed to
    choose it.
    """
    print("macOS only lets you set this by hand, so:")
    print()
    print("  1. In the window opening now, find Sticky Note in the app list")
    print("  2. Choose 'Alerts' instead of 'Banners'")
    print()
    print("Earlier icon changes can leave more than one entry named Sticky Note.")
    print("The live one is the entry showing your current app icon.")
    print()
    print("Banners are taken off screen by the system after about five seconds")
    print("no matter what an app asks for. Alerts stay until dismissed, which is")
    print(f"what lets linger_seconds ({Config.load().linger_seconds:g}s) mean anything.")
    subprocess.run(
        ["/usr/bin/open",
         "x-apple.systempreferences:com.apple.Notifications-Settings.extension"],
        check=False,
    )
    return 0


def cmd_status(_args) -> int:
    cfg = Config.load()
    state = State.load()
    now = datetime.now()

    if not cfg.enabled:
        status = "disabled"
    elif state.paused_until and now.timestamp() < state.paused_until:
        resume_at = datetime.fromtimestamp(state.paused_until)
        status = f"paused until {resume_at:%a %H:%M} ({_humanize(resume_at - now)})"
    elif not launchagent.is_loaded():
        status = "not running (run: stickynote start)"
    else:
        status = "running"

    print(f"status        {status}")
    print(f"window        {cfg.window_label()}")
    print(f"interval      every {cfg.min_minutes:g}-{cfg.max_minutes:g} minutes")

    if not state.next_fire:
        print("next          not scheduled yet")
    elif cfg.show_next:
        nxt = datetime.fromtimestamp(state.next_fire)
        print(f"next          {nxt:%a %d %b %H:%M} (in {_humanize(nxt - now)})")
    else:
        nxt = datetime.fromtimestamp(state.next_fire)
        when = "today" if nxt.date() == now.date() else f"{nxt:%a %d %b}"
        print(f"next          sometime {when} (surprise mode)")

    if state.last_fire:
        last = datetime.fromtimestamp(state.last_fire)
        print(f"last          {last:%a %d %b %H:%M} ({_humanize(now - last)} ago)")
    print(f"delivered     {state.fired_count}")
    print(f"messages      {len(messages.load(cfg.packs))} from {messages.source_path(cfg.packs)}")
    print(f"packs         {', '.join(cfg.packs)}")
    print(f"on screen     {_linger_label(cfg)}")
    if cfg.require_activity:
        print(f"activity      {activity.describe(cfg.max_idle_minutes)}, away after {cfg.max_idle_minutes:g}m")
    else:
        print("activity      not required")
    if cfg.emoji.strip().lower() == "random":
        print(f"emoji         random, {len(messages.load_emoji())} in the pool")
    elif cfg.emoji.strip():
        print(f"emoji         always {cfg.emoji}")
    else:
        print("emoji         off")

    placement = notifier.resolve_placement(cfg.emoji_placement)
    detail = "as a badge image" if placement == "badge" else f"in the {placement}"
    if placement == "both":
        detail = "as a badge image and in the title"
    print(f"placement     {detail}" if placement != "off" else "placement     off")

    chosen = notifier.transport()
    note = {
        "native": "native app, badges supported",
        "applet": "applescript applet, text only",
        "osascript": "osascript fallback, text only",
    }[chosen]
    print(f"transport     {note}")
    print(f"config        {paths.config_path()}")
    return 0


def _build_notifier(cfg: Config, force_applet: bool = False) -> str:
    """Build the best notification bundle this machine can manage."""
    if not force_applet and nativeapp.available():
        print("building StickyNote.app with native badge support ...")
        try:
            nativeapp.build(cfg.app_icon, cfg.bundle_generation)
            return "native"
        except nativeapp.BuildError as exc:
            print(f"native build failed ({exc}); falling back to the applet", file=sys.stderr)

    if not force_applet:
        print("swiftc not found, so badges are unavailable; building the applet instead")
        print("(install the Xcode Command Line Tools and rerun to get badges)")
    else:
        print("building the AppleScript applet ...")
    launchagent.build_applet()
    return "applet"


def cmd_migrate(_args) -> int:
    if not paths.legacy_home().is_dir():
        print("nothing to migrate: no old cheerbot install found")
        return 0

    for line in migrate.run():
        print(f"  {line}")
    print()
    print("macOS ties notification permission to the bundle identifier, which")
    print("has changed, so run `stickynote start` and approve the prompt again.")
    print("The old Cheerbot entry stays in System Settings; macOS gives no way")
    print("to remove it.")
    return 0


def cmd_start(args) -> int:
    if migrate.pending():
        print("found an old cheerbot install, carrying it over first:")
        for line in migrate.run():
            print(f"  {line}")
        print()

    cfg = _load_config()
    if not cfg.enabled:
        cfg.enabled = True
        cfg.save()
    if not paths.config_path().exists():
        cfg.save()

    if not args.no_app:
        _build_notifier(cfg, force_applet=args.applet)

    launchagent.write_plist()
    launchagent.load()
    print(f"launch agent loaded ({paths.LABEL})")

    if State.load().next_fire is None:
        _reschedule(cfg, "first nudge")

    if not args.no_app:
        print("sending a test notification so macOS asks for permission ...")
        badge = messages.pick_emoji(cfg.emoji) if notifier.supports_badges() else ""
        title, badge = _compose(cfg, badge)
        try:
            notifier.send(
                title, "Sticky Note is on. I'll check in now and then.",
                cfg.sound, badge, cfg.linger_seconds,
            )
        except notifier.NotifyError as exc:
            print(f"(test notification failed: {exc})", file=sys.stderr)
        print("approve the permission prompt, or you'll get nothing but silence")
    return 0


def cmd_stop(args) -> int:
    launchagent.unload()
    print("launch agent unloaded")
    if args.purge:
        for target in (paths.app_path(), paths.plist_path()):
            if target.exists():
                subprocess.run(["/bin/rm", "-rf", str(target)], check=False)
                print(f"removed {target}")
    return 0


def cmd_pause(args) -> int:
    delta = _parse_duration(args.duration)
    state = State.load()
    until = datetime.now() + delta
    state.paused_until = until.timestamp()
    state.save()
    print(f"paused until {until:%a %d %b %H:%M}")
    return 0


def cmd_resume(_args) -> int:
    cfg = _load_config()
    state = State.load()
    state.paused_until = None
    state.save()
    _reschedule(cfg, "resumed; next nudge")
    return 0


def _set_app_icon(cfg: Config, value: str) -> int:
    """Point app_icon at an emoji or image, and arrange for it to take effect.

    macOS caches a bundle's notification icon at its first permission grant, so
    a changed icon only appears under an identifier it has not seen before.
    """
    source = Path(value).expanduser()
    # Anything path-shaped that does not exist is a typo, not an emoji.
    if not source.is_file() and ("/" in value or source.suffix.lower() in _IMAGE_SUFFIXES):
        print(f"no such image: {source}", file=sys.stderr)
        return 1

    if source.is_file():
        try:
            stored = nativeapp.adopt_icon(source)
        except nativeapp.BuildError as exc:
            print(f"could not read that image: {exc}", file=sys.stderr)
            return 1
        cfg.app_icon = str(stored)
        described = f"image {source.name}"
    else:
        cfg.app_icon = value
        described = value

    cfg.bundle_generation += 1
    cfg.save()

    print(f"app_icon = {described}")
    print(f"bundle identifier will become {nativeapp.bundle_id(cfg.bundle_generation)}")
    print("run `stickynote start` to rebuild; macOS will ask for notification")
    print("permission again, and the old entry in System Settings can be deleted")
    return 0


def cmd_setup(args) -> int:
    if migrate.pending():
        print("found an old cheerbot install, carrying it over first:")
        for line in migrate.run():
            print(f"  {line}")

    if not wizard.interactive():
        # Reached when the installer is piped through bash, which leaves stdin
        # attached to the script rather than the terminal.
        print("Sticky Note is installed. To choose a theme and rhythm, run:")
        print()
        print("    stickynote setup")
        print()
        return 0

    cfg = Config.load()
    try:
        cfg = wizard.run(cfg, apply_icon=_set_app_icon, first_run=args.first_run)
    except (EOFError, KeyboardInterrupt):
        print("setup cancelled, nothing was changed")
        return 1

    try:
        cfg.validate()
    except ValueError as exc:
        print(f"that combination does not work: {exc}", file=sys.stderr)
        return 1
    cfg.save()

    wizard.heading("Ready")
    for line in wizard.summarise(cfg):
        print(f"  {line}")
    print(f"\n  saved to {paths.config_path()}")

    if args.first_run or wizard.ask_yes("\nStart it now?", default=True):
        print()
        return cmd_start(argparse.Namespace(no_app=False, applet=False))

    print("\nrun `stickynote start` when you're ready")
    return 0


def cmd_packs(args) -> int:
    cfg = Config.load()
    catalogue = packs.available()

    if args.use:
        wanted = [p.strip().lower() for p in args.use.replace(",", " ").split()]
        cfg.packs = wanted
        try:
            cfg.validate()
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        cfg.save()
        print(f"packs = {', '.join(cfg.packs)} ({len(messages.load(cfg.packs))} messages)")
        return 0

    for pack in catalogue.values():
        mark = "*" if pack.id in cfg.packs else " "
        origin = "bundled" if pack.bundled else "yours"
        count = len(pack.messages())
        print(f"{mark} {pack.id:<12} {count:>4} {pack.language}  {origin:<7} {pack.description}")

    if paths.user_messages_path().exists():
        print()
        print(f"note: {paths.user_messages_path()} overrides every pack")
    return 0


def cmd_config(args) -> int:
    cfg = Config.load()

    # `tone` was retired in favour of `packs`; accept it silently rather than
    # making anyone with muscle memory look up the new name.
    if args.key == "tone" and args.value is not None:
        args = argparse.Namespace(
            key="packs",
            value=",".join(_TONE_ALIASES.get(args.value.strip().lower(), [args.value])),
        )

    if args.key is None:
        for key, value in cfg.as_dict().items():
            print(f"{key:18} {value}")
        return 0

    if args.value is None:
        data = cfg.as_dict()
        if args.key not in data:
            print(f"unknown setting {args.key!r}", file=sys.stderr)
            return 2
        print(data[args.key])
        return 0

    try:
        setattr(cfg, args.key, coerce(args.key, args.value))
        cfg.validate()
    except KeyError:
        print(f"unknown setting {args.key!r}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"invalid value: {exc}", file=sys.stderr)
        return 2

    if args.key == "app_icon":
        return _set_app_icon(cfg, args.value)

    cfg.save()
    saved = getattr(cfg, args.key)
    print(f"{args.key} = {', '.join(str(v) for v in saved) if isinstance(saved, list) else saved}")

    # Timing settings only take effect on the next schedule, so redo it now.
    if args.key in ("min_minutes", "max_minutes", "active_start", "active_end", "active_days"):
        _reschedule(cfg, "rescheduled; next nudge")
    return 0


def _pool_command(args, entries, source, user_path) -> int:
    """Shared list/path/edit/add handling for the message and emoji pools."""
    if args.action == "path":
        print(source)
        return 0

    if args.action == "list":
        for line in entries:
            print(line)
        return 0

    def ensure_user_copy() -> None:
        if user_path.exists():
            return
        user_path.parent.mkdir(parents=True, exist_ok=True)
        # Seed from what is currently in use rather than one bundled file, so
        # the voice you are hearing is the voice you start editing.
        user_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
        print(f"seeded {user_path} with the {len(entries)} entries in use")

    if args.action == "edit":
        ensure_user_copy()
        editor = os.environ.get("EDITOR", "open -t")
        subprocess.run(f'{editor} "{user_path}"', shell=True, check=False)
        return 0

    if args.action == "add":
        ensure_user_copy()
        with user_path.open("a", encoding="utf-8") as handle:
            handle.write(args.text.strip() + "\n")
        print(f"added to {user_path}")
        return 0

    return 2


def cmd_messages(args) -> int:
    chosen = Config.load().packs
    return _pool_command(
        args,
        messages.load(chosen),
        messages.source_path(chosen),
        paths.user_messages_path(),
    )


def cmd_emoji(args) -> int:
    return _pool_command(
        args,
        messages.load_emoji(),
        messages.emoji_source_path(),
        paths.user_emoji_path(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stickynote",
        description="Cute, funny sticky notes that turn up on your Mac.",
    )
    subs = parser.add_subparsers(dest="command", required=True)

    start = subs.add_parser("start", help="install the background agent and start nudging")
    start.add_argument(
        "--no-app",
        action="store_true",
        help="skip building StickyNote.app (notifications fall back to osascript)",
    )
    start.add_argument(
        "--applet",
        action="store_true",
        help="force the AppleScript applet instead of the native app (no badges)",
    )
    stop = subs.add_parser("stop", help="stop the background agent")
    stop.add_argument("--purge", action="store_true", help="also delete the app bundle and plist")

    subs.add_parser("status", help="show schedule and health")
    subs.add_parser("surprise", help="re-roll the timing settings at random")

    subs.add_parser("alerts", help="switch macOS to the longer-lasting alert style")

    setup = subs.add_parser("setup", help="choose a theme, rhythm and icon")
    setup.add_argument(
        "--first-run", action="store_true",
        help="greet the user and start the agent when done (used by the installer)",
    )

    subs.add_parser("migrate", help="carry over an install of the old cheerbot")

    pack_cmd = subs.add_parser("packs", help="list theme packs, or switch to others")
    pack_cmd.add_argument(
        "use", nargs="?",
        help="comma-separated pack ids to draw from, e.g. funny,zen",
    )

    demo = subs.add_parser("demo", help="watch a burst of notifications up close")
    demo.add_argument("-n", "--count", type=int, default=5, help="how many to send")
    demo.add_argument("--min", type=float, default=8.0, help="shortest gap in seconds")
    demo.add_argument("--max", type=float, default=20.0, help="longest gap in seconds")

    now = subs.add_parser("now", help="send an encouragement immediately")
    now.add_argument("-m", "--message", help="send this exact text instead of a random one")
    now.add_argument("-e", "--emoji", help="use this exact emoji instead of a random one")
    now.add_argument(
        "--linger", type=float, default=None,
        help="seconds to keep it on screen, overriding linger_seconds (0 = until dismissed)",
    )

    subs.add_parser("tick", help="scheduler poll (run by launchd)")

    pause = subs.add_parser("pause", help="mute for a while, e.g. 2h or today")
    pause.add_argument("duration", nargs="?", default="today")
    subs.add_parser("resume", help="unmute and reschedule")

    config = subs.add_parser("config", help="read or change settings")
    config.add_argument("key", nargs="?")
    config.add_argument("value", nargs="?")

    msg = subs.add_parser("messages", help="inspect or extend the message pool")
    msg.add_argument("action", choices=["list", "path", "edit", "add"], nargs="?", default="list")
    msg.add_argument("text", nargs="?", help="text to add when using: messages add")

    emoji = subs.add_parser("emoji", help="inspect or extend the emoji pool")
    emoji.add_argument("action", choices=["list", "path", "edit", "add"], nargs="?", default="list")
    emoji.add_argument("text", nargs="?", help="emoji to add when using: emoji add")

    return parser


_HANDLERS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "status": cmd_status,
    "surprise": cmd_surprise,
    "migrate": cmd_migrate,
    "packs": cmd_packs,
    "setup": cmd_setup,
    "demo": cmd_demo,
    "alerts": cmd_alerts,
    "now": cmd_now,
    "tick": cmd_tick,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "config": cmd_config,
    "messages": cmd_messages,
    "emoji": cmd_emoji,
}


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in ("messages", "emoji") and args.action == "add" and not args.text:
        print(f'usage: stickynote {args.command} add "..."', file=sys.stderr)
        return 2
    try:
        return _HANDLERS[args.command](args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
