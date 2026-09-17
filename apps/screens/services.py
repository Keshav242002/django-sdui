"""
Business logic for the screens app.
"""

import json
import logging
from pathlib import Path

from django.conf import settings
from django.db import Error as DjangoDBError
from django.db import transaction
from kombu.exceptions import OperationalError

from apps.common.cache import cache_client, layout_cache_key
from apps.common.exceptions import LayoutNotPublished, LayoutUnavailable
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


def _fallback_file_path(screen_key: str) -> Path:
    return settings.LAYOUT_FALLBACK_DIR / f"{screen_key}.json"


def _write_fallback_snapshot(screen_key: str, snapshot: dict) -> None:
    """
    Best-effort local-disk write of the last published snapshot (PRD §12A
    fallback tier 4: server static last-known-good fallback file, used only
    when both Postgres and Redis are unreachable). Called from
    publish_layout()'s on_commit callback -- never blocks or fails a
    publish; disk errors are logged and swallowed, same posture as this
    function's existing broker-down fallback.
    """
    try:
        path = _fallback_file_path(screen_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot))
    except OSError:
        logger.warning(
            "Could not write static fallback file for screen '%s'", screen_key, exc_info=True
        )


def _read_fallback_snapshot(screen_key: str) -> dict | None:
    """
    Read the last-written static fallback snapshot for a screen, or None if
    it doesn't exist or is unreadable/malformed. A malformed file is treated
    the same as "no fallback available" (returns None) rather than raising --
    mirrors _is_valid_snapshot's defensiveness for the Redis tier.
    """
    try:
        path = _fallback_file_path(screen_key)
        if not path.exists():
            return None
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning(
            "Could not read static fallback file for screen '%s'", screen_key, exc_info=True
        )
        return None


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

    The same on_commit callback also writes the static fallback file (PRD
    §12A tier 4, plan.md phase-9 Key Decision #2) -- after commit, so a
    rolled-back publish never writes a fallback file for a version that
    doesn't exist.

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

    def _after_commit():
        _write_fallback_snapshot(screen_key, snapshot)
        try:
            warm_layout_cache.delay(screen_key)
        except OperationalError:
            logger.warning(
                "Celery broker unreachable; warming layout cache for '%s' synchronously",
                screen_key,
            )
            cache_client.set(layout_cache_key(screen_key), snapshot, ttl=None)

    transaction.on_commit(_after_commit)

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
    4. Static fallback file (PRD §12A tier 4, plan.md phase-9 Key Decision
       #2) -- only reached if Postgres itself is unreachable (tiers 2/3
       both require a working DB connection). Logged as an ERROR: this is a
       severe degraded state (both Redis and Postgres down), not a routine
       cache miss.

    Raises LayoutNotPublished if the screen doesn't exist, or no
    LayoutVersion exists and there are no active live Sections either.
    Raises LayoutUnavailable if Postgres is unreachable and no static
    fallback file exists either (e.g. a screen that's never been published).

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
    except Screen.DoesNotExist:
        raise LayoutNotPublished(f"No screen found for key '{screen_key}'.")
    except DjangoDBError:
        logger.error(
            "Postgres unreachable loading screen '%s'; trying static fallback file",
            screen_key,
            exc_info=True,
        )
        fallback = _read_fallback_snapshot(screen_key)
        if fallback is not None:
            return fallback
        raise LayoutUnavailable(
            f"Screen '{screen_key}' is temporarily unavailable "
            "(layout cache and database are both unreachable)."
        )


def get_draft_sections(screen_key: str) -> dict:
    """
    Return the current live Section rows for a screen, in the same shape
    as get_active_sections() ({version_number, sections}) but reading
    directly from Postgres, never from cache or LayoutVersion. Used by the
    admin preview (plan.md Key Decisions #2/#8) to show what a Publish
    *would* produce.

    version_number is always None -- draft has no version (same convention
    as the live-fallback tier of get_active_sections). Raises
    LayoutNotPublished if the screen doesn't exist or has no active
    sections, matching get_active_sections' error contract.
    """
    try:
        screen = Screen.objects.get(key=screen_key)
    except Screen.DoesNotExist:
        raise LayoutNotPublished(f"No screen found for key '{screen_key}'.")

    sections = list(
        screen.sections.filter(is_active=True).select_related("widget_type").order_by("order")
    )
    if not sections:
        raise LayoutNotPublished(f"Screen '{screen_key}' has no active sections.")

    return {"version_number": None, "sections": _snapshot_sections(sections)}


def get_published_sections(screen_key: str) -> dict | None:
    """
    Return the current published LayoutVersion snapshot for a screen, or
    None if the screen has never been published.

    Unlike get_active_sections(), this never falls back to live Section
    rows. The admin preview's "Published" mode must show exactly what real
    end users are seeing right now -- falling back to live sections here
    would silently defeat the draft/published distinction the preview
    exists to demonstrate, for any screen that hasn't been published yet
    (plan.md Key Decisions #2).

    Raises LayoutNotPublished if the screen doesn't exist.
    """
    try:
        screen = Screen.objects.get(key=screen_key)
    except Screen.DoesNotExist:
        raise LayoutNotPublished(f"No screen found for key '{screen_key}'.")

    layout_version = screen.layout_versions.filter(is_current=True).first()
    if layout_version is None:
        return None
    return layout_version.sections_snapshot
