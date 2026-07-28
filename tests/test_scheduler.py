import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="cheerbot-test-")
os.environ["CHEERBOT_HOME"] = _TMP

from cheerbot import cli, messages, nativeapp, notifier, scheduler  # noqa: E402
from cheerbot.config import Config, coerce  # noqa: E402
from cheerbot.state import State  # noqa: E402


def at(day: str, clock: str) -> datetime:
    return datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M")


class ActiveWindowTests(unittest.TestCase):
    def test_daytime_window(self):
        cfg = Config(active_start="09:00", active_end="21:00")
        self.assertTrue(cfg.allows(at("2026-07-27", "09:00")))
        self.assertTrue(cfg.allows(at("2026-07-27", "20:59")))
        self.assertFalse(cfg.allows(at("2026-07-27", "08:59")))
        self.assertFalse(cfg.allows(at("2026-07-27", "21:00")))

    def test_window_wrapping_midnight(self):
        cfg = Config(active_start="22:00", active_end="02:00")
        self.assertTrue(cfg.allows(at("2026-07-27", "23:30")))
        self.assertTrue(cfg.allows(at("2026-07-28", "01:00")))
        self.assertFalse(cfg.allows(at("2026-07-28", "03:00")))

    def test_inactive_days_are_skipped(self):
        weekdays = Config(active_days=[0, 1, 2, 3, 4])
        self.assertTrue(weekdays.allows(at("2026-07-27", "12:00")))  # Monday
        self.assertFalse(weekdays.allows(at("2026-08-01", "12:00")))  # Saturday


class NextFireTests(unittest.TestCase):
    def test_delay_stays_within_configured_range(self):
        cfg = Config(min_minutes=10, max_minutes=20, active_start="00:00", active_end="23:59")
        now = at("2026-07-27", "10:00")
        for _ in range(200):
            gap = scheduler.next_fire_after(cfg, now) - now
            self.assertGreaterEqual(gap, timedelta(minutes=10))
            self.assertLessEqual(gap, timedelta(minutes=20))

    def test_late_evening_rolls_into_next_morning(self):
        cfg = Config(min_minutes=60, max_minutes=90, active_start="09:00", active_end="21:00")
        nxt = scheduler.next_fire_after(cfg, at("2026-07-27", "20:45"))
        self.assertEqual(nxt.date(), at("2026-07-28", "09:00").date())
        self.assertTrue(cfg.allows(nxt))

    def test_weekend_is_skipped_for_weekday_only_config(self):
        cfg = Config(min_minutes=60, max_minutes=90, active_days=[0, 1, 2, 3, 4])
        nxt = scheduler.next_fire_after(cfg, at("2026-07-31", "20:50"))  # Friday
        self.assertEqual(nxt.weekday(), 0)  # Monday


class TickTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(min_minutes=30, max_minutes=60)
        self.sent = []

    def deliver(self, message):
        self.sent.append(message)

    def test_first_tick_schedules_without_firing(self):
        result = scheduler.tick(self.cfg, State(), at("2026-07-27", "10:00"), self.deliver)
        self.assertEqual(result.action, "scheduled")
        self.assertEqual(self.sent, [])

    def test_waits_until_due(self):
        now = at("2026-07-27", "10:00")
        state = State(next_fire=(now + timedelta(minutes=5)).timestamp())
        result = scheduler.tick(self.cfg, state, now, self.deliver)
        self.assertEqual(result.action, "waiting")
        self.assertEqual(self.sent, [])

    def test_fires_and_reschedules_when_due(self):
        now = at("2026-07-27", "10:00")
        state = State(next_fire=(now - timedelta(minutes=1)).timestamp())
        result = scheduler.tick(self.cfg, state, now, self.deliver)
        self.assertEqual(result.action, "fired")
        self.assertEqual(len(self.sent), 1)
        self.assertGreater(state.next_fire, now.timestamp())
        self.assertEqual(state.fired_count, 1)
        self.assertIn(self.sent[0], state.recent)

    def test_due_outside_window_reschedules_instead_of_firing(self):
        now = at("2026-07-27", "03:00")
        state = State(next_fire=(now - timedelta(minutes=1)).timestamp())
        result = scheduler.tick(self.cfg, state, now, self.deliver)
        self.assertEqual(result.action, "scheduled")
        self.assertEqual(self.sent, [])

    def test_pause_suppresses_delivery(self):
        now = at("2026-07-27", "10:00")
        state = State(
            next_fire=(now - timedelta(minutes=1)).timestamp(),
            paused_until=(now + timedelta(hours=2)).timestamp(),
        )
        result = scheduler.tick(self.cfg, state, now, self.deliver)
        self.assertEqual(result.action, "paused")
        self.assertEqual(self.sent, [])

    def test_disabled_suppresses_delivery(self):
        self.cfg.enabled = False
        now = at("2026-07-27", "10:00")
        state = State(next_fire=(now - timedelta(minutes=1)).timestamp())
        self.assertEqual(scheduler.tick(self.cfg, state, now, self.deliver).action, "disabled")


class RandomizeTests(unittest.TestCase):
    def test_rolled_settings_are_always_valid_and_usable(self):
        for _ in range(200):
            cfg = scheduler.randomize(Config())
            cfg.validate()
            self.assertFalse(cfg.show_next)
            self.assertGreater(cfg.max_minutes, cfg.min_minutes)
            nxt = scheduler.next_fire_after(cfg, at("2026-07-27", "10:00"))
            self.assertTrue(cfg.allows(nxt))


class MessageTests(unittest.TestCase):
    def test_bundled_pool_is_substantial_and_unique(self):
        pool = messages.load()
        self.assertGreater(len(pool), 50)
        self.assertEqual(len(pool), len(set(pool)))

    def test_pick_avoids_recent_until_forced(self):
        pool = ["a", "b", "c"]
        self.assertEqual(messages.pick(pool, ["a", "b"]), "c")
        self.assertIn(messages.pick(pool, pool), pool)

    def test_state_keeps_only_the_recent_window(self):
        state = State()
        for i in range(10):
            state.remember(str(i), window=3)
        self.assertEqual(state.recent, ["7", "8", "9"])


class EmojiTests(unittest.TestCase):
    def test_bundled_pool_is_populated_and_unique(self):
        pool = messages.load_emoji()
        self.assertGreater(len(pool), 20)
        self.assertEqual(len(pool), len(set(pool)))

    def test_random_draws_from_the_pool(self):
        pool = set(messages.load_emoji())
        for _ in range(100):
            self.assertIn(messages.pick_emoji("random"), pool)

    def test_random_never_repeats_the_previous_one(self):
        last = messages.pick_emoji("random")
        for _ in range(100):
            nxt = messages.pick_emoji("random", last)
            self.assertNotEqual(nxt, last)
            last = nxt

    def test_off_values_empty_the_slot(self):
        for setting in ("", "off", "none", "OFF", "  "):
            self.assertEqual(messages.pick_emoji(setting), "")

    def test_literal_value_is_used_verbatim(self):
        self.assertEqual(messages.pick_emoji("🌵"), "🌵")
        self.assertEqual(messages.pick_emoji("🌵", last="🌵"), "🌵")


class PlacementTests(unittest.TestCase):
    def test_badge_placement_keeps_the_title_clean(self):
        self.assertEqual(notifier.compose("Cheerbot", "✨", "badge"), ("Cheerbot", "✨"))

    def test_title_placement_prefixes_the_text(self):
        self.assertEqual(notifier.compose("Cheerbot", "✨", "title"), ("✨ Cheerbot", ""))

    def test_both_places_it_twice(self):
        self.assertEqual(notifier.compose("Cheerbot", "✨", "both"), ("✨ Cheerbot", "✨"))

    def test_off_and_empty_emoji_yield_nothing(self):
        self.assertEqual(notifier.compose("Cheerbot", "✨", "off"), ("Cheerbot", ""))
        self.assertEqual(notifier.compose("Cheerbot", "", "badge"), ("Cheerbot", ""))

    def test_auto_follows_what_the_transport_supports(self):
        original = notifier.supports_badges
        try:
            notifier.supports_badges = lambda: True
            self.assertEqual(notifier.resolve_placement("auto"), "badge")
            notifier.supports_badges = lambda: False
            self.assertEqual(notifier.resolve_placement("auto"), "title")
        finally:
            notifier.supports_badges = original

    def test_explicit_placement_is_not_overridden(self):
        self.assertEqual(notifier.resolve_placement("title"), "title")
        self.assertEqual(notifier.resolve_placement("off"), "off")

    def test_config_rejects_unknown_placement(self):
        with self.assertRaises(ValueError):
            Config(emoji_placement="sideways").validate()
        Config(emoji_placement="badge").validate()


class TransportTests(unittest.TestCase):
    """Transport selection, with the filesystem checks stubbed out."""

    def setUp(self):
        self.native = nativeapp.is_installed
        self.applet = notifier._applet_installed
        self.addCleanup(self.restore)

    def restore(self):
        nativeapp.is_installed = self.native
        notifier._applet_installed = self.applet

    def use(self, native: bool, applet: bool):
        nativeapp.is_installed = lambda: native
        notifier._applet_installed = lambda: applet

    def test_native_wins_when_present(self):
        self.use(native=True, applet=True)
        self.assertEqual(notifier.transport(), "native")
        self.assertTrue(notifier.supports_badges())

    def test_applet_is_next_best(self):
        self.use(native=False, applet=True)
        self.assertEqual(notifier.transport(), "applet")
        self.assertFalse(notifier.supports_badges())

    def test_osascript_is_the_last_resort(self):
        self.use(native=False, applet=False)
        self.assertEqual(notifier.transport(), "osascript")

    def test_auto_placement_degrades_without_the_native_app(self):
        self.use(native=False, applet=True)
        self.assertEqual(notifier.resolve_placement("auto"), "title")
        self.use(native=True, applet=False)
        self.assertEqual(notifier.resolve_placement("auto"), "badge")

    def test_badge_request_is_dropped_by_text_only_transports(self):
        """A badge must never leak into the body text of a text-only transport."""
        self.use(native=False, applet=True)
        placement = notifier.resolve_placement("auto")
        title, badge = notifier.compose("Cheerbot", "✨", placement)
        self.assertEqual(badge, "")
        self.assertEqual(title, "✨ Cheerbot")


class AppIconTests(unittest.TestCase):
    def test_generation_one_keeps_the_original_identifier(self):
        """Existing installs must not be pushed onto a new bundle id."""
        self.assertEqual(nativeapp.bundle_id(1), "dev.cheerbot.notifier")
        self.assertEqual(nativeapp.bundle_id(0), "dev.cheerbot.notifier")

    def test_later_generations_are_distinct(self):
        ids = {nativeapp.bundle_id(gen) for gen in range(1, 6)}
        self.assertEqual(len(ids), 5)
        self.assertEqual(nativeapp.bundle_id(2), "dev.cheerbot.notifier2")

    def test_path_shaped_values_are_recognised(self):
        """A path that does not exist should be rejected, not taken as an emoji."""
        self.assertTrue(any(
            "/nope/icon.png".endswith(suffix) for suffix in cli._IMAGE_SUFFIXES
        ))
        self.assertFalse(any("🌱".endswith(suffix) for suffix in cli._IMAGE_SUFFIXES))

    def test_bundle_generation_survives_a_config_roundtrip(self):
        cfg = Config(app_icon="/tmp/icon.png", bundle_generation=4)
        cfg.save()
        loaded = Config.load()
        self.assertEqual(loaded.bundle_generation, 4)
        self.assertEqual(loaded.app_icon, "/tmp/icon.png")


class ConfigTests(unittest.TestCase):
    def test_values_coerce_from_strings(self):
        self.assertIs(coerce("enabled", "off"), False)
        self.assertEqual(coerce("min_minutes", "12.5"), 12.5)
        self.assertEqual(coerce("active_days", "0,1,2"), [0, 1, 2])
        self.assertEqual(coerce("title", "Hi"), "Hi")

    def test_validation_rejects_inverted_range(self):
        with self.assertRaises(ValueError):
            Config(min_minutes=90, max_minutes=10).validate()

    def test_roundtrip_through_disk(self):
        cfg = Config(title="Pep", min_minutes=5, active_days=[0, 4])
        cfg.save()
        self.assertEqual(Config.load().as_dict(), cfg.as_dict())


if __name__ == "__main__":
    unittest.main()
