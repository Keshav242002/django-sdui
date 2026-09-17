"""
Admin preview renderer view (PRD §11.4, §15 Phase 6, plan.md).

Thin view -- parses the request, delegates to apps.screens.services for the
layout data and apps.serving.services.fetch_section_data for widget data,
then renders the mock HTML/CSS/JS client (rules.md §1).
"""

import json
import logging
from uuid import UUID

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from apps.common.exceptions import AppError
from apps.screens.models import Screen
from apps.screens.services import get_draft_sections, get_published_sections
from apps.serving.services import fetch_section_data

logger = logging.getLogger(__name__)

# Widget types whose handler reads real per-user data (portfolio_summary ->
# get_portfolio_summary, holdings_list -> get_holdings_data, recommended_funds
# -> get_recommended_funds_data's held-fund exclusion query). The aggregator
# never needs this distinction because its DRF serializer always supplies a
# real, validated user_id (apps/serving/serializers.py). The preview is the
# one caller that can have no user selected at all, so it needs to know
# which sections to skip rather than query a UUIDField with an empty string.
PERSONALIZED_WIDGET_TYPES = {"portfolio_summary", "holdings_list", "recommended_funds"}


@method_decorator(staff_member_required, name="dispatch")
class ScreenPreviewView(View):
    """
    Admin preview renderer (PRD §11.4, §15 Phase 6).

    Renders the draft (live Section rows) or published (current
    LayoutVersion snapshot) layout for a screen as a mock mobile preview
    with Android/iOS frames. Staff-only, via staff_member_required --
    matches the rest of the admin's access control without reimplementing
    auth (plan.md Key Decisions #1).
    """

    def get(self, request, screen_pk):
        screen = get_object_or_404(Screen, pk=screen_pk)
        mode = request.GET.get("mode", "draft")
        if mode not in ("draft", "published"):
            mode = "draft"
        user_id = self._parse_user_id(request.GET.get("user_id", ""))
        fund_id = request.GET.get("fund_id", "") or None

        sections, layout_version, empty_state = self._load_sections(screen.key, mode)

        assembled_sections = [
            {**section, "data": self._fetch_widget_data(section, user_id, fund_id)}
            for section in sections
        ]

        layout_json = {
            "screen_key": screen.key,
            "layout_version": layout_version,
            "sections": assembled_sections,
        }

        context = {
            "screen": screen,
            "mode": mode,
            "user_id": str(user_id) if user_id else "",
            "fund_id": fund_id or "",
            "empty_state": empty_state,
            # `</` broken up so a fund/section name containing "</script>"
            # can't terminate the injected <script> block early (XSS via
            # admin-authored but not fully trusted content).
            "layout_json": json.dumps(layout_json, default=str).replace("</", "<\\/"),
        }
        return render(request, "screens/preview.html", context)

    @staticmethod
    def _load_sections(screen_key: str, mode: str) -> tuple[list[dict], int | None, str | None]:
        """
        Return (sections, layout_version, empty_state) for the requested mode.

        empty_state is None when there's real data to show, otherwise one of
        "not_published" (Published mode, screen never published -- see
        get_published_sections' docstring for why this must NOT fall back to
        draft/live sections) or "no_sections" (either mode, screen has no
        active sections at all).
        """
        if mode == "published":
            layout = get_published_sections(screen_key)
            if layout is None:
                return [], None, "not_published"
            return layout["sections"], layout["version_number"], None

        try:
            layout = get_draft_sections(screen_key)
        except AppError:
            return [], None, "no_sections"
        return layout["sections"], layout["version_number"], None

    @staticmethod
    def _parse_user_id(raw: str) -> UUID | None:
        if not raw:
            return None
        try:
            return UUID(raw)
        except ValueError:
            return None

    @staticmethod
    def _fetch_widget_data(section: dict, user_id: UUID | None, fund_id: str | None = None) -> dict:
        if section["widget_type"] in PERSONALIZED_WIDGET_TYPES and user_id is None:
            return {"status": "no_user_selected"}
        return fetch_section_data(section, str(user_id) if user_id else "", fund_id)
