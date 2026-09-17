"""
Thin views for the serving app -- parse/validate the request, delegate to a
service function, return the response. No business logic here (rules.md §1).
"""

import logging

from django.db import Error as DjangoDBError
from django.shortcuts import render
from django.views import View
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import WidgetDataUnavailable
from apps.serving.serializers import ScreenRequestSerializer, WidgetRequestSerializer
from apps.serving.services import assemble_screen
from apps.serving.widget_registry import WIDGET_HANDLERS

logger = logging.getLogger(__name__)


class ScreenView(APIView):
    """Aggregator: GET /api/v1/screens/{screen_key}/ -- PRD §9."""

    def get(self, request, screen_key):
        serializer = ScreenRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        data = assemble_screen(
            screen_key=screen_key,
            user_id=str(params["user_id"]),
            platform=params.get("platform", ""),
            app_version=params.get("app_version", "0.0.0"),
            fund_id=params.get("fund_id") or None,
        )
        return Response(
            {
                "data": data,
                "meta": {
                    "screen_key": screen_key,
                    "layout_version": data["layout_version"],
                    "total_sections": len(data["sections"]),
                },
            }
        )


class WidgetView(APIView):
    """
    Standalone widget endpoint: GET /api/v1/widgets/{widget_key}/ -- PRD §12A.

    Calls the exact same handler the aggregator uses (via WIDGET_HANDLERS),
    so a client falling back to per-widget calls gets identical data. This
    is the endpoint apps/serving's client demo (ClientDemoView, plan.md
    phase-9) calls per-widget when the aggregator is unreachable -- a
    domain error here (e.g. WidgetDataUnavailable) is deliberately left to
    propagate to the global exception handler, which already maps it to a
    proper 503 + error envelope (rules.md §5: don't bury an error in a 200
    body -- that convention is specific to the aggregator's multi-section
    response, where one section failing must not fail the other sections).
    """

    def get(self, request, widget_key):
        handler = WIDGET_HANDLERS.get(widget_key)
        if handler is None:
            return Response(
                {
                    "error": {
                        "code": "WIDGET_NOT_FOUND",
                        "message": f"Unknown widget_key '{widget_key}'.",
                        "detail": None,
                    }
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = WidgetRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        user_id = str(serializer.validated_data["user_id"])
        fund_id = serializer.validated_data.get("fund_id") or None

        try:
            result = handler(user_id, fund_id=fund_id)
        except DjangoDBError as exc:
            # Postgres unreachable (plan.md phase-9): without this, a DB
            # outage here would surface as a generic, "unexpected" 500
            # (full Sentry capture) instead of the same expected,
            # dependency-unavailable 503 a WidgetDataUnavailable already
            # gets -- this is exactly the same class of expected
            # degradation, just triggered by infra instead of domain logic.
            logger.error(
                "Postgres unreachable fetching widget_key=%s", widget_key, exc_info=True
            )
            raise WidgetDataUnavailable(f"Widget '{widget_key}' is temporarily unavailable.") from exc

        return Response({"data": result, "meta": {"widget_key": widget_key}})


class ClientDemoView(View):
    """
    PRD §12A client-side demo (plan.md phase-9 Key Decision #3) -- a real
    page making real fetch() calls against the public API, showing the
    happy-path aggregator call and, on failure, the bundled-default-layout
    + per-widget fallback + progressive-rendering chain described in PRD
    §12A's client-side section.

    Deliberately public (no @staff_member_required): this *is* the
    demonstrable "client" PRD §3 describes the mock renderer as doubling
    for, not an internal admin tool like apps.screens' preview. Does no
    server-side lookup of screen_key at all -- everything, including
    discovering that a screen doesn't exist, happens client-side via
    fetch(), exactly as a real mobile client would.
    """

    def get(self, request, screen_key):
        context = {
            "screen_key": screen_key,
            "user_id": request.GET.get("user_id", ""),
            "force_down": request.GET.get("force_down") == "1",
        }
        return render(request, "serving/client_demo.html", context)
