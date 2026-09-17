"""
The screen-aggregation service.

assemble_screen() loads a Screen's published layout snapshot (via
apps.screens.services -- never apps.screens.models directly, per the
app-boundary rule in rules.md §2/PRD §9A), filters out sections the
requesting client is too old for or that fail their feature-flag gate
(apps.flags.services.evaluate_flag()), then fetches each remaining
section's data concurrently. Each fetch is isolated (Bulkhead pattern,
PRD §12A): one widget's failure never fails the rest of the screen.

As of Phase 3, sections come from a LayoutVersion snapshot (dicts), not
live Section ORM rows -- see apps.screens.services.get_active_sections().
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from django.db import connections

from apps.common.exceptions import AppError
from apps.flags.services import evaluate_flag
from apps.screens.services import get_active_sections
from apps.serving.widget_registry import WIDGET_HANDLERS

logger = logging.getLogger(__name__)


def assemble_screen(
    screen_key: str,
    user_id: str,
    platform: str = "",
    app_version: str = "0.0.0",
    fund_id: str | None = None,
) -> dict:
    """
    Assemble the full screen response for a given user.

    `platform` is accepted (mirrors the PRD §9 request signature) but not
    used for filtering in this phase -- only `min_app_version` gates a
    section today.

    `fund_id` (Phase 8) is passed through to each section's handler for
    fund-scoped screens like `fund_detail` (e.g. `fund_overview`,
    `recommended_funds`); widgets that don't use it ignore it.
    """
    layout = get_active_sections(screen_key)
    layout_version = layout["version_number"]
    user_context = {"user_id": user_id, "platform": platform, "app_version": app_version}
    sections = [
        s
        for s in layout["sections"]
        if _compare_versions(app_version, s["min_app_version"]) and _passes_flag_gate(s, user_context)
    ]

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            index: executor.submit(fetch_section_data, section, user_id, fund_id)
            for index, section in enumerate(sections)
        }
        data_by_index = {index: future.result() for index, future in futures.items()}

    assembled_sections = [
        {
            "widget_type": section["widget_type"],
            "title": section["title"],
            "order": section["order"],
            "config": section["config"],
            "data": data_by_index[index],
        }
        for index, section in enumerate(sections)
    ]

    return {"screen_key": screen_key, "layout_version": layout_version, "sections": assembled_sections}


def fetch_section_data(section: dict, user_id: str, fund_id: str | None = None) -> dict:
    """
    Fetch one section's data, isolating its failure from the rest of the screen.

    `fund_id` (Phase 8) is passed through to the widget handler, which
    accepts (and most ignore) it -- see apps.serving.widget_registry's
    uniform `handler(user_id, fund_id=None)` contract.

    Public (not `_`-prefixed): also called directly by the admin preview
    (apps/screens/views.py::ScreenPreviewView) so both callers share the
    exact same bulkhead wrapper instead of the preview reimplementing its
    own try/except around WIDGET_HANDLERS (rules.md §2, PRD §12A).

    Runs on a ThreadPoolExecutor worker thread when called from
    assemble_screen(), which gets its own DB connection that Django's
    request/response cycle never closes (that cleanup only runs on the main
    thread). Close it explicitly here so concurrent screen requests don't
    leak a connection per worker per request. When called directly from the
    preview view (main thread, no executor), this is a harmless no-op
    beyond forcing a reconnect on the next query.
    """
    try:
        widget_type = section["widget_type"]
        handler = WIDGET_HANDLERS.get(widget_type)
        if handler is None:
            return {"status": "unavailable", "error_code": "WIDGET_UNKNOWN"}

        try:
            return handler(user_id, fund_id=fund_id)
        except AppError as e:
            logger.warning("Widget data unavailable for widget_type=%s: %s", widget_type, e.message)
            return {"status": "unavailable", "error_code": "WIDGET_UNAVAILABLE"}
    finally:
        connections.close_all()


def _passes_flag_gate(section: dict, user_context: dict) -> bool:
    """Return False only if the section's config.feature_flag_key gate rejects this user."""
    flag_key = section.get("config", {}).get("feature_flag_key")
    if not flag_key:
        return True
    return evaluate_flag(flag_key, user_context)


def _compare_versions(client_version: str, min_version: str) -> bool:
    """Return True if client_version >= min_version (section should be shown)."""
    if not min_version:
        return True
    if not client_version:
        return False

    def _parse(version: str) -> tuple:
        parts = [int(p) for p in version.split(".")]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])

    return _parse(client_version) >= _parse(min_version)
