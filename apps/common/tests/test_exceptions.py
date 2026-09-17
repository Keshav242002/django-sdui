from unittest.mock import patch

from django.test import TestCase

from apps.common.exceptions import LayoutNotPublished, custom_exception_handler


class SentryReportingTests(TestCase):
    def test_unexpected_exception_reported_to_sentry(self):
        exc = RuntimeError("boom")
        with patch("apps.common.exceptions.sentry_sdk.capture_exception") as mock_capture:
            response = custom_exception_handler(exc, context={})

        mock_capture.assert_called_once_with(exc)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["error"]["code"], "INTERNAL_ERROR")

    def test_expected_app_error_not_reported_to_sentry(self):
        exc = LayoutNotPublished("no layout")
        with patch("apps.common.exceptions.sentry_sdk.capture_exception") as mock_capture:
            response = custom_exception_handler(exc, context={})

        mock_capture.assert_not_called()
        self.assertEqual(response.status_code, 404)
