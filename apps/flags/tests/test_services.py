import uuid
from unittest.mock import patch

from django.core.cache import cache
from django.db.utils import OperationalError as DjangoOperationalError
from django.test import TestCase, override_settings

from apps.common.cache import cache_client, flag_cache_key
from apps.flags.models import FeatureFlag, TargetingRule
from apps.flags.services import FLAG_CACHE_TTL, evaluate_flag

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


@override_settings(CACHES=TEST_CACHES)
class FlagsServicesTestCase(TestCase):
    def setUp(self):
        cache.clear()


class EvaluateFlagRolloutTests(FlagsServicesTestCase):
    def test_disabled_flag_returns_false(self):
        flag = FeatureFlag.objects.create(key="off_flag", is_enabled=False, rollout_percentage=100)

        self.assertFalse(evaluate_flag(flag.key, {"user_id": str(uuid.uuid4())}))

    def test_100pct_rollout_returns_true(self):
        flag = FeatureFlag.objects.create(key="full_flag", is_enabled=True, rollout_percentage=100)

        for _ in range(5):
            self.assertTrue(evaluate_flag(flag.key, {"user_id": str(uuid.uuid4())}))

    def test_0pct_rollout_returns_false(self):
        flag = FeatureFlag.objects.create(key="zero_flag", is_enabled=True, rollout_percentage=0)

        for _ in range(5):
            self.assertFalse(evaluate_flag(flag.key, {"user_id": str(uuid.uuid4())}))

    def test_rollout_50_is_deterministic(self):
        flag = FeatureFlag.objects.create(key="half_flag", is_enabled=True, rollout_percentage=50)
        user_id = str(uuid.uuid4())

        first = evaluate_flag(flag.key, {"user_id": user_id})
        second = evaluate_flag(flag.key, {"user_id": user_id})

        self.assertEqual(first, second)

    def test_different_users_can_bucket_differently_at_50pct(self):
        flag = FeatureFlag.objects.create(key="half_flag_2", is_enabled=True, rollout_percentage=50)

        results = {evaluate_flag(flag.key, {"user_id": str(uuid.uuid4())}) for _ in range(200)}

        self.assertEqual(results, {True, False})


class EvaluateFlagTargetingRuleTests(FlagsServicesTestCase):
    def test_equals_rule_excludes_user(self):
        flag = FeatureFlag.objects.create(key="equals_flag", is_enabled=True, rollout_percentage=100)
        TargetingRule.objects.create(
            feature_flag=flag, attribute="platform", operator="equals", value="ios"
        )

        self.assertFalse(evaluate_flag(flag.key, {"user_id": "u1", "platform": "ios"}))
        self.assertTrue(evaluate_flag(flag.key, {"user_id": "u2", "platform": "android"}))

    def test_in_rule_excludes_user(self):
        flag = FeatureFlag.objects.create(key="in_flag", is_enabled=True, rollout_percentage=100)
        TargetingRule.objects.create(
            feature_flag=flag, attribute="platform", operator="in", value=["ios"]
        )

        self.assertFalse(evaluate_flag(flag.key, {"user_id": "u1", "platform": "ios"}))
        self.assertTrue(evaluate_flag(flag.key, {"user_id": "u2", "platform": "android"}))

    def test_gte_lte_rules(self):
        gte_flag = FeatureFlag.objects.create(key="gte_flag", is_enabled=True, rollout_percentage=100)
        TargetingRule.objects.create(
            feature_flag=gte_flag, attribute="app_build", operator="gte", value=100
        )
        self.assertFalse(evaluate_flag(gte_flag.key, {"user_id": "u1", "app_build": 150}))
        self.assertTrue(evaluate_flag(gte_flag.key, {"user_id": "u2", "app_build": 50}))

        lte_flag = FeatureFlag.objects.create(key="lte_flag", is_enabled=True, rollout_percentage=100)
        TargetingRule.objects.create(
            feature_flag=lte_flag, attribute="app_build", operator="lte", value=100
        )
        self.assertFalse(evaluate_flag(lte_flag.key, {"user_id": "u3", "app_build": 50}))
        self.assertTrue(evaluate_flag(lte_flag.key, {"user_id": "u4", "app_build": 150}))


class EvaluateFlagUnknownKeyTests(FlagsServicesTestCase):
    def test_unknown_flag_fails_open_and_logs_warning(self):
        with self.assertLogs("apps.flags.services", level="WARNING") as logs:
            result = evaluate_flag("does_not_exist", {"user_id": "u1"})

        self.assertTrue(result)
        self.assertTrue(any("does_not_exist" in message for message in logs.output))


class EvaluateFlagPostgresDownTests(FlagsServicesTestCase):
    """
    plan.md phase-9: caught live while manually verifying the static
    layout fallback -- Postgres down (and no Redis-cached flag definition)
    must fail the gated section open, not 500 the whole screen just
    because one flag's DB fallback query failed.
    """

    def test_postgres_down_fails_open_and_logs_error(self):
        flag = FeatureFlag.objects.create(key="db_down_flag", is_enabled=True, rollout_percentage=0)

        with patch(
            "apps.flags.services.FeatureFlag.objects.prefetch_related",
            side_effect=DjangoOperationalError("connection refused"),
        ):
            with self.assertLogs("apps.flags.services", level="ERROR") as logs:
                result = evaluate_flag(flag.key, {"user_id": "u1"})

        self.assertTrue(result)
        self.assertTrue(any("db_down_flag" in message for message in logs.output))


class EvaluateFlagCachingTests(FlagsServicesTestCase):
    def test_redis_down_evaluates_from_postgres(self):
        flag = FeatureFlag.objects.create(key="cache_down_flag", is_enabled=True, rollout_percentage=100)

        with patch.object(cache_client, "get", side_effect=Exception("redis down")):
            result = evaluate_flag(flag.key, {"user_id": "u1"})

        self.assertTrue(result)

    def test_cache_hit_skips_postgres(self):
        flag = FeatureFlag.objects.create(key="cache_hit_flag", is_enabled=True, rollout_percentage=100)
        evaluate_flag(flag.key, {"user_id": "u1"})

        with self.assertNumQueries(0):
            result = evaluate_flag(flag.key, {"user_id": "u2"})

        self.assertTrue(result)

    def test_cache_populated_on_miss(self):
        flag = FeatureFlag.objects.create(key="cache_miss_flag", is_enabled=True, rollout_percentage=100)

        with patch.object(cache_client, "set", wraps=cache_client.set) as mock_set:
            evaluate_flag(flag.key, {"user_id": "u1"})

        mock_set.assert_called_once_with(
            flag_cache_key(flag.key),
            {"is_enabled": True, "rollout_percentage": 100, "targeting_rules": []},
            ttl=FLAG_CACHE_TTL,
        )
        self.assertIsNotNone(cache.get(flag_cache_key(flag.key)))


class FlagCacheInvalidationSignalTests(FlagsServicesTestCase):
    def test_signal_invalidates_cache_on_flag_save(self):
        flag = FeatureFlag.objects.create(key="signal_flag", is_enabled=True, rollout_percentage=100)
        evaluate_flag(flag.key, {"user_id": "u1"})
        self.assertIsNotNone(cache.get(flag_cache_key(flag.key)))

        with patch.object(cache_client, "delete", wraps=cache_client.delete) as mock_delete:
            flag.is_enabled = False
            flag.save()

        mock_delete.assert_called_once_with(flag_cache_key(flag.key))
        self.assertIsNone(cache.get(flag_cache_key(flag.key)))
