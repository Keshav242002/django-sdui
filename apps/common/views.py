"""
Metrics endpoint (PRD §13) -- aggregates Prometheus metrics across every
process (Django web + Celery worker) via multiprocess mode. See
config/settings.py's PROMETHEUS_MULTIPROC_DIR setup for the write side.
"""

from django.http import HttpResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest, multiprocess


def metrics_view(request):
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
