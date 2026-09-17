from django.db import connection
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase

from apps.common.middleware import DB_QUERY_LATENCY, REQUEST_COUNT, REQUEST_LATENCY, PrometheusMetricsMiddleware


class PrometheusMetricsMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_request_increments_latency_and_count(self):
        def get_response(request):
            request.resolver_match = type("ResolverMatch", (), {"view_name": "test-view"})()
            return HttpResponse(status=204)

        middleware = PrometheusMetricsMiddleware(get_response)
        request = self.factory.get("/some/path/")

        count_before = REQUEST_COUNT.labels(view="test-view", method="GET", status="204")._value.get()
        latency_sum_before = REQUEST_LATENCY.labels(view="test-view", method="GET")._sum.get()

        middleware(request)

        self.assertEqual(
            REQUEST_COUNT.labels(view="test-view", method="GET", status="204")._value.get(),
            count_before + 1,
        )
        self.assertGreater(
            REQUEST_LATENCY.labels(view="test-view", method="GET")._sum.get(),
            latency_sum_before,
        )

    def test_db_query_increments_query_latency(self):
        def get_response(request):
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            request.resolver_match = None
            return HttpResponse(status=200)

        middleware = PrometheusMetricsMiddleware(get_response)
        request = self.factory.get("/db-hit/")

        latency_sum_before = DB_QUERY_LATENCY.labels(alias="default")._sum.get()

        middleware(request)

        self.assertGreater(DB_QUERY_LATENCY.labels(alias="default")._sum.get(), latency_sum_before)

    def test_metrics_endpoint_returns_prometheus_text(self):
        response = Client().get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        body = response.content.decode()
        self.assertIn("sdui_http_requests_total", body)
