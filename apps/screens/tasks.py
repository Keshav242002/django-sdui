"""
Celery tasks for the screens app (PRD §10).

ignore_result=True: nothing reads this task's result, and without it
.delay() also opens a result-backend connection (same Redis as the
broker) to track the task -- a failure there surfaces as a plain
RuntimeError, not kombu.exceptions.OperationalError, which the
broker-down fallback in apps.screens.services.publish_layout doesn't
catch. See apps/funds/tasks.py's module docstring for the full story.
"""

import logging

from celery import shared_task

from apps.common.cache import cache_client, layout_cache_key
from apps.screens.models import LayoutVersion

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def warm_layout_cache(screen_key: str) -> dict:
    """
    On-demand, dispatched right after admin Publish
    (apps.screens.services.publish_layout, via transaction.on_commit).

    Reads the LayoutVersion with is_current=True for this screen and
    writes its sections_snapshot into Redis. ttl=None -- the layout
    cache is invalidated on publish (event-driven), never time-based
    (Phase 3 decision, unchanged).
    """
    layout_version = LayoutVersion.objects.filter(screen__key=screen_key, is_current=True).first()
    if layout_version is None:
        logger.warning("warm_layout_cache: no current LayoutVersion for screen '%s'", screen_key)
        return {"warmed": False}

    cache_client.set(layout_cache_key(screen_key), layout_version.sections_snapshot, ttl=None)
    logger.info("warm_layout_cache: warmed cache for screen '%s'", screen_key)
    return {"warmed": True}
