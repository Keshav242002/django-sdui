"""
Domain exception hierarchy and the global DRF exception handler.

Expected (domain) errors subclass AppError and carry a `code` used to build
the client-facing error envelope: {"error": {"code", "message", "detail"}}.
Anything else is treated as unexpected and surfaced as a generic 500.
"""

import logging

import sentry_sdk
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for expected domain errors."""

    code = "APP_ERROR"
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, detail=None):
        self.message = message
        self.detail = detail
        super().__init__(message)


class WidgetDataUnavailable(AppError):
    code = "WIDGET_UNAVAILABLE"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class FeatureFlagNotFound(AppError):
    code = "FEATURE_FLAG_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND


class LayoutNotPublished(AppError):
    code = "LAYOUT_NOT_PUBLISHED"
    status_code = status.HTTP_404_NOT_FOUND


class LayoutUnavailable(AppError):
    """
    Both Redis and Postgres are unreachable for this screen's layout, and no
    static fallback file exists to serve instead (plan.md phase-9 Key
    Decision #2). Deliberately distinct from LayoutNotPublished (404): that
    means "this screen has no layout", this means "the backends are down" --
    a client should retry, not stop asking.
    """

    code = "LAYOUT_UNAVAILABLE"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


def custom_exception_handler(exc, context):
    """
    Global DRF exception handler registered via REST_FRAMEWORK["EXCEPTION_HANDLER"].

    Expected AppError subclasses are logged as warnings and mapped to their
    declared status code. Everything else is logged as an error with full
    traceback, reported to Sentry, and returned as a sanitized generic 500 —
    no raw tracebacks or internal exception messages ever reach the client.
    """
    if isinstance(exc, AppError):
        logger.warning("Domain error: %s - %s", exc.code, exc.message)
        return Response(
            {"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}},
            status=exc.status_code,
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    logger.error("Unhandled exception", exc_info=exc)
    sentry_sdk.capture_exception(exc)
    return Response(
        {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "detail": None,
            }
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
