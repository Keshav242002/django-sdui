from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.common.cache import CacheClient

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


@override_settings(CACHES=TEST_CACHES)
class CacheClientRoundtripTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = CacheClient()

    def test_get_returns_none_on_miss(self):
        self.assertIsNone(self.client.get("does:not:exist"))

    def test_set_then_get_roundtrip(self):
        self.client.set("some:key", {"a": 1}, ttl=60)
        self.assertEqual(self.client.get("some:key"), {"a": 1})

    def test_delete_removes_key(self):
        self.client.set("some:key", "value")
        self.client.delete("some:key")
        self.assertIsNone(self.client.get("some:key"))


class CacheClientRedisDownTests(TestCase):
    def setUp(self):
        self.client = CacheClient()

    def test_get_returns_none_when_redis_down(self):
        with patch("apps.common.cache.cache.get", side_effect=Exception("connection refused")):
            self.assertIsNone(self.client.get("layout:mf_dashboard:current"))

    def test_set_is_noop_when_redis_down(self):
        with patch("apps.common.cache.cache.set", side_effect=Exception("connection refused")):
            self.client.set("layout:mf_dashboard:current", {"sections": []})

    def test_delete_is_noop_when_redis_down(self):
        with patch("apps.common.cache.cache.delete", side_effect=Exception("connection refused")):
            self.client.delete("layout:mf_dashboard:current")
