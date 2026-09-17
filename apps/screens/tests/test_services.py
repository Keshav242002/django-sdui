from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from kombu.exceptions import OperationalError

from apps.common.cache import layout_cache_key
from apps.common.exceptions import LayoutNotPublished
from apps.screens.models import LayoutVersion, Screen, Section, WidgetType
from apps.screens.services import get_active_sections, publish_layout
from apps.screens.tasks import warm_layout_cache

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


@override_settings(CACHES=TEST_CACHES)
class ScreensServicesTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.widget_type = WidgetType.objects.create(key="portfolio_summary", name="Portfolio Summary")
        self.screen = Screen.objects.create(key="mf_dashboard", name="Mutual Fund Dashboard")
        self.section = Section.objects.create(
            screen=self.screen,
            widget_type=self.widget_type,
            title="Your Portfolio",
            order=1,
        )

    def _publish(self, screen_key=None, published_by="admin"):
        """
        publish_layout() dispatches warm_layout_cache via
        transaction.on_commit -- captureOnCommitCallbacks(execute=True)
        makes that callback actually run, in place of the .delay() call
        going to a real broker/worker, since neither exists in this test
        process (mirrors "call the decorated function directly" from
        plan.md's Tests section, applied at the dispatch site).
        """
        screen_key = screen_key or self.screen.key
        with patch("apps.screens.services.warm_layout_cache.delay", side_effect=warm_layout_cache):
            with self.captureOnCommitCallbacks(execute=True):
                return publish_layout(screen_key, published_by=published_by)


class PublishLayoutTests(ScreensServicesTestCase):
    def test_creates_layout_version_with_correct_snapshot_shape(self):
        layout_version = self._publish()

        self.assertEqual(layout_version.version_number, 1)
        self.assertEqual(
            layout_version.sections_snapshot,
            {
                "version_number": 1,
                "sections": [
                    {
                        "widget_type": "portfolio_summary",
                        "title": "Your Portfolio",
                        "order": 1,
                        "config": {},
                        "min_app_version": "",
                    }
                ],
            },
        )

    def test_sets_is_current_and_unsets_previous_version(self):
        first = self._publish()
        second = self._publish()

        first.refresh_from_db()
        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)
        self.assertEqual(second.version_number, 2)

    def test_writes_to_redis_cache(self):
        self._publish()

        cached = cache.get(layout_cache_key(self.screen.key))
        self.assertIsNotNone(cached)
        self.assertEqual(cached["version_number"], 1)

    def test_no_active_sections_raises_layout_not_published(self):
        self.section.is_active = False
        self.section.save()

        with self.assertRaises(LayoutNotPublished):
            self._publish()

    def test_dispatches_warm_task_with_screen_key(self):
        with patch("apps.screens.services.warm_layout_cache.delay") as mock_delay:
            with self.captureOnCommitCallbacks(execute=True):
                publish_layout(self.screen.key, published_by="admin")

        mock_delay.assert_called_once_with(self.screen.key)

    def test_falls_back_to_sync_write_when_broker_down(self):
        with patch(
            "apps.screens.services.warm_layout_cache.delay",
            side_effect=OperationalError("broker unreachable"),
        ):
            with self.assertLogs("apps.screens.services", level="WARNING"):
                with self.captureOnCommitCallbacks(execute=True):
                    publish_layout(self.screen.key, published_by="admin")

        cached = cache.get(layout_cache_key(self.screen.key))
        self.assertIsNotNone(cached)
        self.assertEqual(cached["version_number"], 1)


class GetActiveSectionsTests(ScreensServicesTestCase):
    def test_returns_cached_snapshot_on_redis_hit_without_postgres_query(self):
        self._publish()

        with self.assertNumQueries(0):
            result = get_active_sections(self.screen.key)

        self.assertEqual(result["version_number"], 1)

    def test_falls_back_to_postgres_layout_version_on_cache_miss(self):
        self._publish()
        cache.clear()

        result = get_active_sections(self.screen.key)

        self.assertEqual(result["version_number"], 1)
        self.assertEqual(cache.get(layout_cache_key(self.screen.key))["version_number"], 1)

    def test_falls_back_to_live_sections_when_no_layout_version_exists(self):
        result = get_active_sections(self.screen.key)

        self.assertIsNone(result["version_number"])
        self.assertEqual(result["sections"][0]["widget_type"], "portfolio_summary")

    def test_unknown_screen_raises_layout_not_published(self):
        with self.assertRaises(LayoutNotPublished):
            get_active_sections("does_not_exist")

    def test_no_layout_version_and_no_active_sections_raises(self):
        self.section.is_active = False
        self.section.save()

        with self.assertRaises(LayoutNotPublished):
            get_active_sections(self.screen.key)

    def test_malformed_cached_snapshot_is_discarded_and_falls_back_to_postgres(self):
        self._publish()
        cache.set(layout_cache_key(self.screen.key), {"unexpected": "shape"})

        result = get_active_sections(self.screen.key)

        self.assertEqual(result["version_number"], 1)
        # The bad entry was discarded and replaced with a valid one.
        self.assertEqual(cache.get(layout_cache_key(self.screen.key))["version_number"], 1)

    def test_cached_snapshot_with_malformed_section_is_discarded(self):
        self._publish()
        cache.set(
            layout_cache_key(self.screen.key),
            {"version_number": 1, "sections": [{"widget_type": "portfolio_summary"}]},
        )

        result = get_active_sections(self.screen.key)

        self.assertEqual(result["sections"][0]["title"], "Your Portfolio")
