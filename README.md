# Sticky Note

Random encouraging notifications on macOS. A background LaunchAgent picks a
random moment inside your active hours, picks a message you haven't seen
recently, and puts it in Notification Center. That's the whole product.

No dependencies beyond the system Python, no menu bar icon, no account.

## Install

```bash
./install.sh
```

That does three things:

1. Builds `~/Applications/StickyNote.app`, a small Swift helper that posts
   notifications through the `UserNotifications` framework, with the app icon
   baked in beforehand (see [Badges](#badges) for why the order matters). If
   `swiftc` is unavailable it falls back to an AppleScript applet, which works
   but cannot show badges.
2. Installs the LaunchAgent at `~/Library/LaunchAgents/dev.stickynote.agent.plist`,
   which starts at login and polls every 5 minutes.
3. Sends one notification so macOS shows the permission prompt.

**Approve the permission prompt the first time**, otherwise everything will run
silently and deliver nothing. If you miss it, enable Sticky Note under System
Settings → Notifications.

To call it from anywhere:

```bash
ln -s "$PWD/bin/stickynote" /usr/local/bin/stickynote
```

## Usage

```bash
stickynote status              # schedule, next nudge, health
stickynote now                 # encourage me right now
stickynote demo                # watch a burst of them up close, without touching the schedule
stickynote alerts              # make notifications last longer than a five-second banner
stickynote surprise            # re-roll the timing at random, and stop showing me when
stickynote pause 3h            # quiet for a while (also: 90m, 2d, today)
stickynote resume
stickynote stop                # unload the agent
stickynote start               # load it again
```

## Configuration

Settings live in `~/.config/stickynote/config.json`, edited through the CLI:

```bash
stickynote config                          # show everything
stickynote config min_minutes 20           # nudge more often
stickynote config max_minutes 90
stickynote config active_start 08:30       # active window, local time
stickynote config active_end 19:00
stickynote config active_days 0,1,2,3,4    # 0 = Monday ... 6 = Sunday
stickynote config title "Hey you"
stickynote config tone sincere             # funny | sincere | mixed
stickynote config linger_seconds 30        # longer on screen; 0 = until dismissed
stickynote config max_idle_minutes 10      # how long away before nudges are held
stickynote config require_activity off     # nudge even when you are not there
stickynote config emoji off                # or a literal emoji, or "random"
stickynote config sound Glass              # any macOS alert sound, "" for silent
stickynote config emoji_placement title    # badge | title | both | off | auto
stickynote config enabled off
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `min_minutes` / `max_minutes` | 15 / 50 | Each notification lands at a uniformly random gap in this range |
| `active_start` / `active_end` | 09:00 / 21:00 | Local-time window; wrapping past midnight (e.g. 22:00–02:00) works |
| `active_days` | all | Days the window applies to |
| `linger_seconds` | 15 | How long a notification stays on screen. Needs the Alerts style; see below. 0 leaves it until dismissed |
| `tone` | `funny` | Which bundled pool to draw from: `funny`, `sincere`, or `mixed`. Ignored once you write your own messages file |
| `require_activity` | true | Hold a nudge back unless you are actually at the machine |
| `max_idle_minutes` | 5 | How long without keyboard or mouse input counts as away |
| `emoji` | `random` | Which emoji: `random` draws from the pool, `off` empties the slot, anything else is used literally |
| `emoji_placement` | `auto` | `badge`, `title`, `both`, `off`, or `auto` to use a badge when the transport supports one |
| `app_icon` | 🌱 | The app's own icon: an emoji or a path to an image. Changing it bumps `bundle_generation` |
| `bundle_generation` | 1 | Bumped automatically when `app_icon` changes, to get past the frozen icon cache |
| `no_repeat_window` | 80 | How many recent messages to avoid repeating. Scale it with the frequency |
| `show_next` | true | When off, `status` hides the exact next-nudge time |

Timing changes reschedule the pending nudge immediately.

`stickynote surprise` rolls all the timing settings for you and turns `show_next`
off, so even you don't know when the next one is coming. `stickynote config` still
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
and Sticky Note is stuck with a generic icon forever, with no way back short of a
new bundle identifier.

So: the app icon is fixed (`app_icon`, default 🌱) and the badge beside the text
is what varies.

### Changing the app icon

`app_icon` takes either an emoji or a path to an image:

```bash
stickynote config app_icon ☀️
stickynote config app_icon ~/Pictures/my-icon.png
stickynote start                 # rebuild, then approve the new permission prompt
```

Images are copied into `~/.config/stickynote/` so the icon keeps working after you
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
`stickynote config emoji_placement title`. The default, `auto`, uses a badge when
the native helper is installed and falls back to the title when it isn't, so
machines without Xcode Command Line Tools still get an emoji.

## Messages and emoji

Two bundled message pools ship with it: 480 funny ones (the default) and 102
straight ones, selected with `tone`, plus 47 emoji. All of it is replaceable:

```bash
stickynote messages edit       # seeds ~/.config/stickynote/messages.txt with what's in use
stickynote messages add "Your text here"
stickynote messages list

stickynote emoji edit          # same, for ~/.config/stickynote/emoji.txt
stickynote emoji add 🦆
stickynote emoji list
```

Your file replaces the bundled set entirely, and `tone` no longer applies. One
entry per line; blank lines and `#` comments are ignored. To preview:

```bash
stickynote now -e 🦆 -m "Just checking the layout"   # one specific combination
stickynote demo -n 5 --min 8 --max 20                # a burst, at random short gaps
```

## Why not a million messages?

At roughly 20 nudges a day you see about 7,300 a year, so pool size maps to
freshness like this:

| Pool | Times you'd see each line per year | First possible repeat |
| --- | --- | --- |
| 480 (today) | ~15 | ~24 days |
| 1,000 | ~7 | ~7 weeks |
| 10,000 | ~0.7 | ~1.4 years |
| 1,000,000 | ~0.007 | ~137 years |

Storage was never the constraint; a million lines is a few dozen megabytes.
The real ceiling is that past about 10,000 you will never read most of them, so
the marginal line is worth nothing. Somewhere between one and a few thousand is
the point where more stops being noticeable.

The binding constraint is quality, not quantity. Every line here was chosen,
which sets a floor: none of them will land badly on a bad day. A generated pool
has a distribution instead of a floor, and the bottom of that distribution
eventually arrives at the worst possible moment, with nobody having read it
first.

That is also the argument against generating them live. It would trade a
zero-dependency offline tool for one needing a network, an API key, a per-nudge
cost, and a fallback pool for when any of that fails — and a message written
while you are not looking is one nobody approved. Novelty is easy; a random
suffix makes every line unique. Being *good* is the hard part, and uniqueness
does not help with it.

The middle path, if the pool ever feels stale, is to use a model as an
authoring tool: generate candidates offline, read them, keep the ones that are
actually funny, and commit them. Same scale, no runtime dependency, floor
intact.

## How long it stays up

macOS has two notification styles, and an app does not get to pick. A **banner**
is taken off screen by the system after about five seconds no matter what the
app asks for; an **alert** stays until it is dismissed. The old
`NSUserNotificationAlertStyle` Info.plist key has no effect under
`UNUserNotificationCenter`, and Apple has said choosing the style will stay off
limits to apps. So the switch is yours to flip, once:

```bash
stickynote alerts     # opens the pane, tells you what to change
```

With Sticky Note set to Alerts, `linger_seconds` becomes real: the helper stays
alive that long and then withdraws its own notification, which turns "until
dismissed" into a duration you choose. Set it to `0` to leave notifications up
until you dismiss them yourself.

Two things worth knowing. Withdrawing also takes the notification out of
Notification Center, so it won't be there to scroll back to; use `0` if you
want them to accumulate. And if several entries in System Settings are named
Sticky Note, left over from earlier icon changes, the live one is whichever shows
your current app icon.

`stickynote status` reports the configured duration, but it cannot confirm the
style: `UNNotificationSettings` keeps reporting `banner` even for a bundle
switched to Alerts, so the only reliable check is watching one land.

## Only when you're there

Encouragement that arrives while you're at lunch is wasted, so a nudge is held
back unless there has been keyboard or mouse input in the last
`max_idle_minutes` and the screen is unlocked. Held nudges aren't dropped: the
pending fire time stays put, so the message lands on the next tick after you
come back rather than never.

Idle time comes from `ioreg`'s `HIDIdleTime`, which needs no dependencies and
works from a `launchd` job. If that probe ever stops working the check fails
open and nudges continue, since going permanently silent is the worse failure.
`stickynote status` shows the current reading.

## How it works

`launchd` runs `stickynote tick` every 5 minutes. A tick is cheap and almost
always a no-op: it compares the current time against `next_fire` in
`~/.config/stickynote/state.json`, and only when that has passed (and the moment
is inside the active window, and you're at the machine) does it deliver a
message and roll a new random
`next_fire`. Polling keeps the timing random without needing a resident process,
and it recovers correctly when the Mac is asleep at the scheduled moment: the
missed nudge is skipped rather than dumped on you all at once on wake.

Delivery has three transports, best first: the native Swift helper (the only one
that can show a badge), the AppleScript applet, and plain `osascript`. The last
still works but attributes notifications to whatever is hosting the script.
`stickynote status` reports which one is in use.

Logs: `~/.config/stickynote/stickynote.log` for deliveries, and
`~/.config/stickynote/notifier.log` for helper errors, which is the only way to
see a refused notification given delivery is asynchronous.

## Uninstall

```bash
stickynote stop --purge        # unload agent, delete the app bundle and plist
rm -rf ~/.config/stickynote    # optional: settings, state, custom messages
```

## Development

```bash
python3 -m unittest discover -s tests -v
```

Tests run against a temporary `STICKYNOTE_HOME`, so they never touch your real
config, and the scheduler takes its delivery function as an argument so nothing
gets sent while testing.
