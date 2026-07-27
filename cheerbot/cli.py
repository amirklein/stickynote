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
        notifier.send(cfg.title, message, cfg.sound)

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
    try:
        transport = notifier.send(cfg.title, message, cfg.sound)
    except notifier.NotifyError as exc:
        print(f"could not send notification: {exc}", file=sys.stderr)
        return 1

    if not args.message:
        state.remember(message, cfg.no_repeat_window)
        state.last_fire = datetime.now().timestamp()
        state.fired_count += 1
        state.save()
    print(f"sent via {transport}: {message}")
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

    if state.next_fire:
        nxt = datetime.fromtimestamp(state.next_fire)
        print(f"next          {nxt:%a %d %b %H:%M} (in {_humanize(nxt - now)})")
    else:
        print("next          not scheduled yet")

    if state.last_fire:
        last = datetime.fromtimestamp(state.last_fire)
        print(f"last          {last:%a %d %b %H:%M} ({_humanize(now - last)} ago)")
    print(f"delivered     {state.fired_count}")
    print(f"messages      {len(messages.load())} from {messages.source_path()}")
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

    state = State.load()
    if state.next_fire is None:
        nxt = scheduler.next_fire_after(cfg, datetime.now())
        state.next_fire = nxt.timestamp()
        state.save()
        print(f"first nudge around {nxt:%a %H:%M}")

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
    nxt = scheduler.next_fire_after(cfg, datetime.now())
    state.next_fire = nxt.timestamp()
    state.save()
    print(f"resumed; next nudge around {nxt:%a %H:%M}")
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
        state = State.load()
        nxt = scheduler.next_fire_after(cfg, datetime.now())
        state.next_fire = nxt.timestamp()
        state.save()
        print(f"rescheduled; next nudge around {nxt:%a %H:%M}")
    return 0


def cmd_messages(args) -> int:
    if args.action == "path":
        print(messages.source_path())
        return 0

    if args.action == "list":
        for line in messages.load():
            print(line)
        return 0

    if args.action == "edit":
        target = paths.user_messages_path()
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                paths.BUNDLED_MESSAGES.read_text(encoding="utf-8"), encoding="utf-8"
            )
            print(f"copied the bundled set to {target}")
        editor = os.environ.get("EDITOR", "open -t")
        subprocess.run(f'{editor} "{target}"', shell=True, check=False)
        return 0

    if args.action == "add":
        target = paths.user_messages_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(
                paths.BUNDLED_MESSAGES.read_text(encoding="utf-8"), encoding="utf-8"
            )
        with target.open("a", encoding="utf-8") as handle:
            handle.write(args.text.strip() + "\n")
        print(f"added to {target}")
        return 0

    return 2


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

    now = subs.add_parser("now", help="send an encouragement immediately")
    now.add_argument("-m", "--message", help="send this exact text instead of a random one")

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

    return parser


_HANDLERS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "status": cmd_status,
    "now": cmd_now,
    "tick": cmd_tick,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "config": cmd_config,
    "messages": cmd_messages,
}


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "messages" and args.action == "add" and not args.text:
        print('usage: cheerbot messages add "your text here"', file=sys.stderr)
        return 2
    try:
        return _HANDLERS[args.command](args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
