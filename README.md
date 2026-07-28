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

1. Builds `~/Applications/Cheerbot.app`, a small Swift helper that posts
   notifications through the `UserNotifications` framework, with the app icon
   baked in beforehand (see [Badges](#badges) for why the order matters). If
   `swiftc` is unavailable it falls back to an AppleScript applet, which works
   but cannot show badges.
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
cheerbot demo                # watch a burst of them up close, without touching the schedule
cheerbot surprise            # re-roll the timing at random, and stop showing me when
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
cheerbot config tone sincere             # funny | sincere | mixed
cheerbot config max_idle_minutes 10      # how long away before nudges are held
cheerbot config require_activity off     # nudge even when you are not there
cheerbot config emoji off                # or a literal emoji, or "random"
cheerbot config sound Glass              # any macOS alert sound, "" for silent
cheerbot config emoji_placement title    # badge | title | both | off | auto
cheerbot config enabled off
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `min_minutes` / `max_minutes` | 45 / 180 | Each notification lands at a uniformly random gap in this range |
| `active_start` / `active_end` | 09:00 / 21:00 | Local-time window; wrapping past midnight (e.g. 22:00–02:00) works |
| `active_days` | all | Days the window applies to |
| `tone` | `funny` | Which bundled pool to draw from: `funny`, `sincere`, or `mixed`. Ignored once you write your own messages file |
| `require_activity` | true | Hold a nudge back unless you are actually at the machine |
| `max_idle_minutes` | 5 | How long without keyboard or mouse input counts as away |
| `emoji` | `random` | Which emoji: `random` draws from the pool, `off` empties the slot, anything else is used literally |
| `emoji_placement` | `auto` | `badge`, `title`, `both`, `off`, or `auto` to use a badge when the transport supports one |
| `app_icon` | 🌱 | The app's own icon: an emoji or a path to an image. Changing it bumps `bundle_generation` |
| `bundle_generation` | 1 | Bumped automatically when `app_icon` changes, to get past the frozen icon cache |
| `no_repeat_window` | 25 | How many recent messages to avoid repeating |
| `show_next` | true | When off, `status` hides the exact next-nudge time |

Timing changes reschedule the pending nudge immediately.

`cheerbot surprise` rolls all the timing settings for you and turns `show_next`
off, so even you don't know when the next one is coming. `cheerbot config` still
shows what it picked if you want to peek.

## Badges

Each notification carries a badge: the emoji, rendered to an image and attached
to the notification itself, so it appears as a thumbnail beside the text. The
badge changes every time and never repeats twice in a row.

Getting there ran into two hard macOS constraints, both verified by experiment
rather than assumed, and both of which shape the implementation:

**AppleScript can't carry an image.** `display notification` is text only. A
badge requires `UNNotificationAttachment`, which means a real app built against
`UserNotifications` — hence the Swift helper in `notifier/`. It has to be
registered in `~/Applications` and launched via `open`; run the binary straight
from a shell and the authorization request gets attributed to the terminal, and
macOS refuses it outright with "Notifications are not allowed for this
application".

**The app icon on the left cannot change per notification.** It is frozen the
first time the bundle registers for notification permission. Replacing the
`.icns`, re-signing, re-registering with `lsregister` and killing
`usernotificationsd` all update Finder and LaunchServices but never the banner.
The corollary is that the icon must be baked in *before* the bundle is ever
launched, which is exactly what `nativeapp.build()` does — miss that ordering
and Cheerbot is stuck with a generic icon forever, with no way back short of a
new bundle identifier.

So: the app icon is fixed (`app_icon`, default 🌱) and the badge beside the text
is what varies.

### Changing the app icon

`app_icon` takes either an emoji or a path to an image:

```bash
cheerbot config app_icon ☀️
cheerbot config app_icon ~/Pictures/my-icon.png
cheerbot start                 # rebuild, then approve the new permission prompt
```

Images are copied into `~/.config/cheerbot/` so the icon keeps working after you
move the original, and converted to real PNG on the way in — files named `.png`
while containing JPEG data are common, and `iconutil` rejects them. Non-square
images are padded rather than stretched.

An `.icns` is used verbatim rather than rebuilt, since it already carries
artwork at every size and flattening it through a single PNG would discard any
per-size differences. That makes a purpose-built `.icns` the best input if you
have one.

Because the icon is frozen per bundle identifier, changing it bumps
`bundle_generation`, which gives macOS an identifier it has not cached. The cost
is one fresh permission prompt each time, and a stale entry left in System
Settings → Notifications that you can delete. Generation 1 keeps the original
identifier, so existing installs are unaffected until they change their icon.

A practical note on choosing one: notification icons render at roughly 40px, so
detailed lettering turns to mush. One bold shape with high contrast survives;
fine text does not, no matter how large the source file is.

If you would rather have the emoji in the title text as before, set
`cheerbot config emoji_placement title`. The default, `auto`, uses a badge when
the native helper is installed and falls back to the title when it isn't, so
machines without Xcode Command Line Tools still get an emoji.

## Messages and emoji

Two bundled message pools ship with it: 91 funny ones (the default) and 102
straight ones, selected with `tone`, plus 48 emoji. All of it is replaceable:

```bash
cheerbot messages edit       # seeds ~/.config/cheerbot/messages.txt with what's in use
cheerbot messages add "Your text here"
cheerbot messages list

cheerbot emoji edit          # same, for ~/.config/cheerbot/emoji.txt
cheerbot emoji add 🦆
cheerbot emoji list
```

Your file replaces the bundled set entirely, and `tone` no longer applies. One
entry per line; blank lines and `#` comments are ignored. To preview:

```bash
cheerbot now -e 🦆 -m "Just checking the layout"   # one specific combination
cheerbot demo -n 5 --min 8 --max 20                # a burst, at random short gaps
```

## Only when you're there

Encouragement that arrives while you're at lunch is wasted, so a nudge is held
back unless there has been keyboard or mouse input in the last
`max_idle_minutes` and the screen is unlocked. Held nudges aren't dropped: the
pending fire time stays put, so the message lands on the next tick after you
come back rather than never.

Idle time comes from `ioreg`'s `HIDIdleTime`, which needs no dependencies and
works from a `launchd` job. If that probe ever stops working the check fails
open and nudges continue, since going permanently silent is the worse failure.
`cheerbot status` shows the current reading.

## How it works

`launchd` runs `cheerbot tick` every 5 minutes. A tick is cheap and almost
always a no-op: it compares the current time against `next_fire` in
`~/.config/cheerbot/state.json`, and only when that has passed (and the moment
is inside the active window, and you're at the machine) does it deliver a
message and roll a new random
`next_fire`. Polling keeps the timing random without needing a resident process,
and it recovers correctly when the Mac is asleep at the scheduled moment: the
missed nudge is skipped rather than dumped on you all at once on wake.

Delivery has three transports, best first: the native Swift helper (the only one
that can show a badge), the AppleScript applet, and plain `osascript`. The last
still works but attributes notifications to whatever is hosting the script.
`cheerbot status` reports which one is in use.

Logs: `~/.config/cheerbot/cheerbot.log` for deliveries, and
`~/.config/cheerbot/notifier.log` for helper errors, which is the only way to
see a refused notification given delivery is asynchronous.

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
