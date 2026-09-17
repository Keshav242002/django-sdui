from celery.signals import task_failure, task_success
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.common.cache import CACHE_REQUESTS, CacheClient, _domain
from apps.common.metrics import CELERY_TASKS

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


class _DummyTask:
    def __init__(self, name):
        self.name = name


@override_settings(CACHES=TEST_CACHES)
class CacheMetricsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = CacheClient()

    def _counter_value(self, domain, result):
        return CACHE_REQUESTS.labels(domain=domain, result=result)._value.get()

    def test_cache_hit_increments_hit_counter(self):
        self.client.set("layout:mf_dashboard:current", {"sections": []})
        before = self._counter_value("layout", "hit")
        self.client.get("layout:mf_dashboard:current")
        self.assertEqual(self._counter_value("layout", "hit"), before + 1)

    def test_cache_miss_increments_miss_counter(self):
        before = self._counter_value("layout", "miss")
        self.client.get("layout:does-not-exist:current")
        self.assertEqual(self._counter_value("layout", "miss"), before + 1)

    def test_cache_domain_parsed_from_key_prefix(self):
        self.assertEqual(_domain("layout:mf_dashboard:current"), "layout")
        self.assertEqual(_domain("widget:top_movers"), "widget")
        self.assertEqual(_domain("no-colon-here"), "unknown")


class CeleryMetricsTests(TestCase):
    def _counter_value(self, task_name, status):
        return CELERY_TASKS.labels(task_name=task_name, status=status)._value.get()

    def test_celery_task_success_increments_counter(self):
        task_name = "apps.tests.dummy_success_task"
        before = self._counter_value(task_name, "success")
        task_success.send(sender=_DummyTask(task_name))
        self.assertEqual(self._counter_value(task_name, "success"), before + 1)

    def test_celery_task_failure_increments_counter(self):
        task_name = "apps.tests.dummy_failure_task"
        before = self._counter_value(task_name, "failure")
        task_failure.send(sender=_DummyTask(task_name))
        self.assertEqual(self._counter_value(task_name, "failure"), before + 1)
