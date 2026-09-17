import time
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.common.cache import _REDIS_BREAKER, CacheClient

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


@override_settings(CACHES=TEST_CACHES)
class CacheClientRoundtripTests(TestCase):
    def setUp(self):
        cache.clear()
        _REDIS_BREAKER.close()
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
        _REDIS_BREAKER.close()
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


class CacheClientCircuitBreakerTests(TestCase):
    """
    plan.md phase-9 Key Decision #1: one shared breaker guards get/set/delete
    together. _REDIS_BREAKER is module-level shared state across every test
    in this suite, not just this class -- setUp resets it here (and in the
    two classes above) the same way cache.clear() resets LocMemCache state.
    """

    def setUp(self):
        _REDIS_BREAKER.close()
        self.client = CacheClient()

    def test_breaker_stays_closed_below_failure_threshold(self):
        with patch(
            "apps.common.cache.cache.get", side_effect=Exception("connection refused")
        ) as mock_get:
            self.client.get("k1")
            self.client.get("k2")
            self.assertEqual(mock_get.call_count, 2)
            self.assertEqual(_REDIS_BREAKER.current_state, "closed")

    def test_breaker_opens_after_consecutive_failures(self):
        with patch(
            "apps.common.cache.cache.get", side_effect=Exception("connection refused")
        ) as mock_get:
            for _ in range(3):
                self.client.get("k1")
            self.assertEqual(mock_get.call_count, 3)
            self.assertEqual(_REDIS_BREAKER.current_state, "open")

            # 4th call must short-circuit -- the underlying cache.get is
            # never invoked again while the breaker is open.
            self.assertIsNone(self.client.get("k1"))
            self.assertEqual(mock_get.call_count, 3)

    def test_breaker_open_short_circuits_set_and_delete_too(self):
        with patch("apps.common.cache.cache.get", side_effect=Exception("down")):
            for _ in range(3):
                self.client.get("k1")
        self.assertEqual(_REDIS_BREAKER.current_state, "open")

        with patch("apps.common.cache.cache.set") as mock_set, patch(
            "apps.common.cache.cache.delete"
        ) as mock_delete:
            self.client.set("k1", "v")
            self.client.delete("k1")
            mock_set.assert_not_called()
            mock_delete.assert_not_called()

    def test_breaker_closes_after_reset_timeout_and_successful_call(self):
        _REDIS_BREAKER.reset_timeout = 0.05
        try:
            with patch(
                "apps.common.cache.cache.get", side_effect=Exception("down")
            ) as mock_get:
                for _ in range(3):
                    self.client.get("k1")
            self.assertEqual(_REDIS_BREAKER.current_state, "open")

            time.sleep(0.1)

            # A trial call through the now-half-open breaker succeeds
            # against the real LocMemCache backend and closes it again.
            self.assertIsNone(self.client.get("some:other:key"))
            self.assertEqual(_REDIS_BREAKER.current_state, "closed")
        finally:
            _REDIS_BREAKER.reset_timeout = 5

    def test_successful_calls_do_not_accumulate_toward_trip(self):
        with patch("apps.common.cache.cache.get") as mock_get:
            mock_get.side_effect = Exception("down")
            self.client.get("k1")
            mock_get.side_effect = None
            mock_get.return_value = None
            self.client.get("k2")
            mock_get.side_effect = Exception("down")
            self.client.get("k3")
            self.client.get("k4")

        # 3 failures total, but interleaved with a success -- the failure
        # counter resets on success, so this must not have tripped the
        # breaker (only 2 consecutive failures at any point).
        self.assertEqual(_REDIS_BREAKER.current_state, "closed")
