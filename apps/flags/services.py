"""
Business logic for the flags app.

evaluate_flag() is the rollout-percentage + targeting-rule evaluator used
by the serving endpoint (apps.serving.services._passes_flag_gate) to decide
whether a section gated by config.feature_flag_key should be shown to a
given user. See PRD §8 for the five evaluation steps and
master/phase/phase-4-feature-flags/plan.md "Key Decisions" for the
fail-open and caching rationale.
"""

import hashlib
import logging

from apps.common.cache import cache_client, flag_cache_key
from apps.flags.models import FeatureFlag

logger = logging.getLogger(__name__)

FLAG_CACHE_TTL = 60

_OPERATORS = {
    "equals": lambda actual, expected: actual == expected,
    "in": lambda actual, expected: actual in expected,
    "gte": lambda actual, expected: actual >= expected,
    "lte": lambda actual, expected: actual <= expected,
    "contains": lambda actual, expected: expected in actual,
}


def _get_flag_definition(flag_key: str) -> dict | None:
    """
    Fetch a flag's definition dict from cache, falling back to Postgres on
    a miss. Returns None if no FeatureFlag with this key exists.
    """
    try:
        cached = cache_client.get(flag_cache_key(flag_key))
    except Exception:
        logger.warning("Cache GET failed for flag '%s'; evaluating from Postgres", flag_key, exc_info=True)
        cached = None
    if cached is not None:
        return cached

    try:
        flag = FeatureFlag.objects.prefetch_related("targeting_rules").get(key=flag_key)
    except FeatureFlag.DoesNotExist:
        return None

    definition = {
        "is_enabled": flag.is_enabled,
        "rollout_percentage": flag.rollout_percentage,
        "targeting_rules": [
            {"attribute": rule.attribute, "operator": rule.operator, "value": rule.value}
            for rule in flag.targeting_rules.all()
        ],
    }
    cache_client.set(flag_cache_key(flag_key), definition, ttl=FLAG_CACHE_TTL)
    return definition


def _passes_targeting_rules(targeting_rules: list[dict], user_context: dict) -> bool:
    """
    Targeting rules are exclusion rules: the user must pass all of them to
    proceed. If any rule matches "exclude this user", return False.
    """
    for rule in targeting_rules:
        operator = _OPERATORS[rule["operator"]]
        actual = user_context.get(rule["attribute"])
        if operator(actual, rule["value"]):
            return False
    return True


def evaluate_flag(flag_key: str, user_context: dict) -> bool:
    """
    Evaluate whether `flag_key` is on for the user described by
    `user_context` (e.g. {"user_id", "platform", "app_version"}).

    Steps (PRD §8): fetch (cache-then-Postgres) -> kill switch ->
    targeting rules -> rollout bucket. An unknown flag key fails open
    (returns True) and logs a WARNING, since a typo silently hiding a
    section is a harder-to-notice bug than briefly over-showing one.
    """
    definition = _get_flag_definition(flag_key)
    if definition is None:
        logger.warning("Unknown feature flag key '%s'; failing open", flag_key)
        return True

    if not definition["is_enabled"]:
        return False

    if not _passes_targeting_rules(definition["targeting_rules"], user_context):
        return False

    user_id = user_context.get("user_id", "")
    bucket = int(hashlib.md5(f"{user_id}{flag_key}".encode()).hexdigest(), 16) % 100
    return bucket < definition["rollout_percentage"]
