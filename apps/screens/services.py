"""
Business logic for the screens app.
"""

import logging

from django.db import transaction
from kombu.exceptions import OperationalError

from apps.common.cache import cache_client, layout_cache_key
from apps.common.exceptions import LayoutNotPublished
from apps.screens.models import LayoutVersion, Screen
from apps.screens.tasks import warm_layout_cache

logger = logging.getLogger(__name__)

_SECTION_KEYS = {"widget_type", "title", "order", "config", "min_app_version"}


def _is_valid_snapshot(data) -> bool:
    """
    Defensive shape check for a value read back from the layout cache.

    The layout cache key has no TTL (event-driven invalidation only, per
    plan.md), so a stale entry written by a previous code version could
    otherwise outlive a deploy that changes the snapshot shape and crash
    the serving hot path with a KeyError instead of degrading gracefully.
    """
    if not isinstance(data, dict) or "version_number" not in data or "sections" not in data:
        return False
    sections = data["sections"]
    if not isinstance(sections, list):
        return False
    return all(isinstance(s, dict) and _SECTION_KEYS.issubset(s) for s in sections)


def _snapshot_sections(sections) -> list[dict]:
    """Serialize live Section ORM rows into the JSON-serializable snapshot shape."""
    return [
        {
            "widget_type": section.widget_type.key,
            "title": section.title,
            "order": section.order,
            "config": section.config,
            "min_app_version": section.min_app_version,
        }
        for section in sections
    ]


def publish_layout(screen_key: str, published_by: str) -> LayoutVersion:
    """
    Snapshot a Screen's active Sections into a new immutable LayoutVersion,
    mark it current, and warm the Redis cache.

    Cache warming is dispatched to Celery (warm_layout_cache) once this
    transaction commits -- never inside it, since post_save-style dispatch
    before commit would let a worker read the DB before the new
    LayoutVersion row is visible (plan.md Key Decisions §6). If the
    broker is unreachable, falls back to the same synchronous write this
    function used before Phase 5, so publishing never fails just because
    a worker is down (plan.md Key Decisions §7).

    Raises LayoutNotPublished if the screen doesn't exist or has no active
    sections to publish.
    """
    try:
        screen = Screen.objects.get(key=screen_key)
    except Screen.DoesNotExist:
        raise LayoutNotPublished(f"No screen found for key '{screen_key}'.")

    sections = list(
        screen.sections.filter(is_active=True).select_related("widget_type").order_by("order")
    )
    if not sections:
        raise LayoutNotPublished(f"Screen '{screen_key}' has no active sections to publish.")

    last_version = screen.layout_versions.order_by("-version_number").first()
    version_number = (last_version.version_number + 1) if last_version else 1

    snapshot = {"version_number": version_number, "sections": _snapshot_sections(sections)}

    layout_version = LayoutVersion.objects.create(
        screen=screen,
        version_number=version_number,
        sections_snapshot=snapshot,
        published_by=published_by,
        is_current=True,
    )

    def _dispatch_cache_warm():
        try:
            warm_layout_cache.delay(screen_key)
        except OperationalError:
            logger.warning(
                "Celery broker unreachable; warming layout cache for '%s' synchronously",
                screen_key,
            )
            cache_client.set(layout_cache_key(screen_key), snapshot, ttl=None)

    transaction.on_commit(_dispatch_cache_warm)

    logger.info("Published layout v%s for screen '%s'", version_number, screen_key)
    return layout_version


def get_active_sections(screen_key: str) -> dict:
    """
    Return the published layout snapshot for a screen: a dict with
    `version_number` and a `sections` list of dicts (widget_type, title,
    order, config, min_app_version).

    Lookup order:
    1. Redis cache (`layout:{screen_key}:current`), discarded if its shape
       doesn't match what this code expects (see _is_valid_snapshot).
    2. Postgres `LayoutVersion` with is_current=True -- populates the cache
       for next time on a hit.
    3. Live `Section` rows (no LayoutVersion ever published for this
       screen) -- same shape, version_number=None. Logged as a WARNING.

    Raises LayoutNotPublished if the screen doesn't exist, or no
    LayoutVersion exists and there are no active live Sections either.

    A valid cache hit returns without touching Postgres at all.
    """
    cache_key = layout_cache_key(screen_key)
    cached = cache_client.get(cache_key)
    if cached is not None:
        if _is_valid_snapshot(cached):
            return cached
        logger.warning(
            "Cached layout snapshot for screen '%s' has an unexpected shape; "
            "discarding and falling back to Postgres",
            screen_key,
        )
        cache_client.delete(cache_key)

    try:
        screen = Screen.objects.get(key=screen_key)
    except Screen.DoesNotExist:
        raise LayoutNotPublished(f"No screen found for key '{screen_key}'.")

    layout_version = screen.layout_versions.filter(is_current=True).first()
    if layout_version is not None:
        snapshot = layout_version.sections_snapshot
        cache_client.set(cache_key, snapshot, ttl=None)
        return snapshot

    logger.warning(
        "No published LayoutVersion for screen '%s'; falling back to live Section rows",
        screen_key,
    )
    sections = list(
        screen.sections.filter(is_active=True).select_related("widget_type").order_by("order")
    )
    if not sections:
        raise LayoutNotPublished(f"Screen '{screen_key}' has no active sections.")

    return {"version_number": None, "sections": _snapshot_sections(sections)}
