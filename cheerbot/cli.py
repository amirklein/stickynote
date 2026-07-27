"""Command line interface."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Optional

from . import launchagent, messages, notifier, paths, scheduler
from .config import Config, coerce
from .state import State

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)\s*([mhd])$", re.IGNORECASE)


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


def _title(cfg: Config, emoji: str) -> str:
    """The notification title, with the emoji slot filled if there is one."""
    return f"{emoji} {cfg.title}".strip() if emoji else cfg.title


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
        notifier.send(_title(cfg, state.last_emoji), message, cfg.sound)

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
    message = args.message or messages.pick(messages.load(), state.recent)
    emoji = args.emoji if args.emoji is not None else messages.pick_emoji(cfg.emoji, state.last_emoji)
    title = _title(cfg, emoji)
    try:
        transport = notifier.send(title, message, cfg.sound)
    except notifier.NotifyError as exc:
        print(f"could not send notification: {exc}", file=sys.stderr)
        return 1

    state.last_emoji = emoji
    if not args.message:
        state.remember(message, cfg.no_repeat_window)
        state.last_fire = datetime.now().timestamp()
        state.fired_count += 1
    state.save()
    print(f"sent via {transport}: {title} - {message}")
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
    print("run `cheerbot config` if you'd rather see what it picked")
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
        status = "not running (run: cheerbot start)"
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
    print(f"messages      {len(messages.load())} from {messages.source_path()}")
    if cfg.emoji.strip().lower() == "random":
        print(f"emoji         random, {len(messages.load_emoji())} in the pool")
    elif cfg.emoji.strip():
        print(f"emoji         always {cfg.emoji}")
    else:
        print("emoji         off")
    print(f"transport     {notifier.transport()}")
    print(f"config        {paths.config_path()}")
    return 0


def cmd_start(args) -> int:
    cfg = _load_config()
    if not cfg.enabled:
        cfg.enabled = True
        cfg.save()
    if not paths.config_path().exists():
        cfg.save()

    if not args.no_app:
        print("building Cheerbot.app ...")
        launchagent.build_app()

    launchagent.write_plist()
    launchagent.load()
    print(f"launch agent loaded ({paths.LABEL})")

    if State.load().next_fire is None:
        _reschedule(cfg, "first nudge")

    if not args.no_app:
        print("sending a test notification so macOS asks for permission ...")
        try:
            notifier.send(cfg.title, "Cheerbot is on. I'll check in now and then.", cfg.sound)
        except notifier.NotifyError as exc:
            print(f"(test notification failed: {exc})", file=sys.stderr)
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


def cmd_config(args) -> int:
    cfg = Config.load()
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

    cfg.save()
    print(f"{args.key} = {getattr(cfg, args.key)}")

    # Timing settings only take effect on the next schedule, so redo it now.
    if args.key in ("min_minutes", "max_minutes", "active_start", "active_end", "active_days"):
        _reschedule(cfg, "rescheduled; next nudge")
    return 0


def _pool_command(args, entries, source, user_path, bundled_path) -> int:
    """Shared list/path/edit/add handling for the message and emoji pools."""
    if args.action == "path":
        print(source)
        return 0

    if args.action == "list":
        for line in entries:
            print(line)
        return 0

    def ensure_user_copy() -> None:
        if not user_path.exists():
            user_path.parent.mkdir(parents=True, exist_ok=True)
            user_path.write_text(bundled_path.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"copied the bundled set to {user_path}")

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
    return _pool_command(
        args,
        messages.load(),
        messages.source_path(),
        paths.user_messages_path(),
        paths.BUNDLED_MESSAGES,
    )


def cmd_emoji(args) -> int:
    return _pool_command(
        args,
        messages.load_emoji(),
        messages.emoji_source_path(),
        paths.user_emoji_path(),
        paths.BUNDLED_EMOJI,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cheerbot",
        description="Random encouraging notifications on macOS.",
    )
    subs = parser.add_subparsers(dest="command", required=True)

    subs.add_parser("start", help="install the background agent and start nudging").add_argument(
        "--no-app",
        action="store_true",
        help="skip building Cheerbot.app (notifications fall back to osascript)",
    )
    stop = subs.add_parser("stop", help="stop the background agent")
    stop.add_argument("--purge", action="store_true", help="also delete the app bundle and plist")

    subs.add_parser("status", help="show schedule and health")
    subs.add_parser("surprise", help="re-roll the timing settings at random")

    now = subs.add_parser("now", help="send an encouragement immediately")
    now.add_argument("-m", "--message", help="send this exact text instead of a random one")
    now.add_argument("-e", "--emoji", help="use this exact emoji instead of a random one")

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
        print(f'usage: cheerbot {args.command} add "..."', file=sys.stderr)
        return 2
    try:
        return _HANDLERS[args.command](args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
