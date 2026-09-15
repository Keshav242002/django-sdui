"""
Thin views for the serving app -- parse/validate the request, delegate to a
service function, return the response. No business logic here (rules.md §1).
"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.serving.serializers import ScreenRequestSerializer, WidgetRequestSerializer
from apps.serving.services import assemble_screen
from apps.serving.widget_registry import WIDGET_HANDLERS


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
        )
        return Response(
            {
                "data": data,
                "meta": {"screen_key": screen_key, "total_sections": len(data["sections"])},
            }
        )


class WidgetView(APIView):
    """
    Standalone widget endpoint: GET /api/v1/widgets/{widget_key}/ -- PRD §12A.

    Calls the exact same handler the aggregator uses (via WIDGET_HANDLERS),
    so a client falling back to per-widget calls gets identical data.
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

        result = handler(user_id)
        return Response({"data": result, "meta": {"widget_key": widget_key}})
