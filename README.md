# Cheerbot

Random encouraging notifications on macOS. A background LaunchAgent picks a
random moment inside your active hours, picks a message you haven't seen
recently, and puts it in Notification Center. That's the whole product.

No dependencies beyond the system Python, no menu bar icon, no account.

## Install

```bash
./install.sh
```

That does three things:

1. Compiles `~/Applications/Cheerbot.app`, a tiny AppleScript applet that exists
   only so notifications are attributed to "Cheerbot" and can be managed in
   System Settings → Notifications.
2. Installs the LaunchAgent at `~/Library/LaunchAgents/dev.cheerbot.agent.plist`,
   which starts at login and polls every 5 minutes.
3. Sends one notification so macOS shows the permission prompt.

**Approve the permission prompt the first time**, otherwise everything will run
silently and deliver nothing. If you miss it, enable Cheerbot under System
Settings → Notifications.

To call it from anywhere:

```bash
ln -s "$PWD/bin/cheerbot" /usr/local/bin/cheerbot
```

## Usage

```bash
cheerbot status              # schedule, next nudge, health
cheerbot now                 # encourage me right now
cheerbot pause 3h            # quiet for a while (also: 90m, 2d, today)
cheerbot resume
cheerbot stop                # unload the agent
cheerbot start               # load it again
```

## Configuration

Settings live in `~/.config/cheerbot/config.json`, edited through the CLI:

```bash
cheerbot config                          # show everything
cheerbot config min_minutes 20           # nudge more often
cheerbot config max_minutes 90
cheerbot config active_start 08:30       # active window, local time
cheerbot config active_end 19:00
cheerbot config active_days 0,1,2,3,4    # 0 = Monday ... 6 = Sunday
cheerbot config title "Hey you"
cheerbot config sound Glass              # any macOS alert sound, "" for silent
cheerbot config enabled off
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `min_minutes` / `max_minutes` | 45 / 180 | Each notification lands at a uniformly random gap in this range |
| `active_start` / `active_end` | 09:00 / 21:00 | Local-time window; wrapping past midnight (e.g. 22:00–02:00) works |
| `active_days` | all | Days the window applies to |
| `no_repeat_window` | 25 | How many recent messages to avoid repeating |

Timing changes reschedule the pending nudge immediately.

## Messages

102 messages ship with it. To use your own:

```bash
cheerbot messages edit       # copies the defaults to ~/.config/cheerbot/messages.txt
cheerbot messages add "Your text here"
cheerbot messages list
```

Your file replaces the bundled set entirely. One message per line; blank lines
and `#` comments are ignored.

## How it works

`launchd` runs `cheerbot tick` every 5 minutes. A tick is cheap and almost
always a no-op: it compares the current time against `next_fire` in
`~/.config/cheerbot/state.json`, and only when that has passed (and the moment
is inside the active window) does it deliver a message and roll a new random
`next_fire`. Polling keeps the timing random without needing a resident process,
and it recovers correctly when the Mac is asleep at the scheduled moment: the
missed nudge is skipped rather than dumped on you all at once on wake.

Delivery prefers the app bundle. If `Cheerbot.app` is missing it falls back to
plain `osascript`, which still works but attributes notifications to whatever is
hosting the script.

Logs: `~/.config/cheerbot/cheerbot.log` (only records actual deliveries and errors).

## Uninstall

```bash
cheerbot stop --purge        # unload agent, delete the app bundle and plist
rm -rf ~/.config/cheerbot    # optional: settings, state, custom messages
```

## Development

```bash
python3 -m unittest discover -s tests -v
```

Tests run against a temporary `CHEERBOT_HOME`, so they never touch your real
config, and the scheduler takes its delivery function as an argument so nothing
gets sent while testing.
