from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.common.cache import layout_cache_key
from apps.screens.models import LayoutVersion, Screen, Section, WidgetType
from apps.screens.tasks import warm_layout_cache

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


@override_settings(CACHES=TEST_CACHES)
class WarmLayoutCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.widget_type = WidgetType.objects.create(key="portfolio_summary", name="Portfolio Summary")
        self.screen = Screen.objects.create(key="mf_dashboard", name="Mutual Fund Dashboard")
        Section.objects.create(
            screen=self.screen, widget_type=self.widget_type, title="Your Portfolio", order=1
        )

    def test_populates_redis_from_current_layout_version(self):
        snapshot = {
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
        }
        LayoutVersion.objects.create(
            screen=self.screen,
            version_number=1,
            sections_snapshot=snapshot,
            published_by="tester",
            is_current=True,
        )

        result = warm_layout_cache(self.screen.key)

        self.assertEqual(result, {"warmed": True})
        self.assertEqual(cache.get(layout_cache_key(self.screen.key)), snapshot)

    def test_no_current_version_logs_warning_and_does_not_write_cache(self):
        with self.assertLogs("apps.screens.tasks", level="WARNING"):
            result = warm_layout_cache(self.screen.key)

        self.assertEqual(result, {"warmed": False})
        self.assertIsNone(cache.get(layout_cache_key(self.screen.key)))
