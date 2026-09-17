"""
Hand-rolled request/DB metrics (rules.md §11, master/phase/phase-7-monitoring
Key Decision #5 -- django-prometheus's Django<6.1 pin rules it out for this
project's Django 6.1.1; forcing the pin or downgrading Django was rejected in
favor of a small, self-contained middleware using prometheus_client directly).
"""

import time

from django.db import connection
from prometheus_client import Counter, Histogram

REQUEST_LATENCY = Histogram(
    "sdui_http_request_duration_seconds",
    "HTTP request latency by view and method",
    ["view", "method"],
)
REQUEST_COUNT = Counter(
    "sdui_http_requests_total",
    "HTTP requests by view, method, and status",
    ["view", "method", "status"],
)
DB_QUERY_LATENCY = Histogram(
    "sdui_db_query_duration_seconds",
    "Database query latency by connection alias",
    ["alias"],
)


def _time_query(execute, sql, params, many, context):
    start = time.perf_counter()
    try:
        return execute(sql, params, many, context)
    finally:
        DB_QUERY_LATENCY.labels(alias=context["connection"].alias).observe(time.perf_counter() - start)


class PrometheusMetricsMiddleware:
    """
    First entry in MIDDLEWARE (config/settings.py) so it wraps the full
    request lifecycle, including every other middleware and the view itself.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        with connection.execute_wrapper(_time_query):
            response = self.get_response(request)
        duration = time.perf_counter() - start

        view_name = getattr(request.resolver_match, "view_name", None) or request.path
        REQUEST_LATENCY.labels(view=view_name, method=request.method).observe(duration)
        REQUEST_COUNT.labels(view=view_name, method=request.method, status=str(response.status_code)).inc()
        return response
