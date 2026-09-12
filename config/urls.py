"""
URL configuration for config project.
"""

from django.contrib import admin
from django.http import HttpResponse
from django.urls import path


def metrics_placeholder(request):
    """
    Placeholder /metrics endpoint.
    Phase 7 will replace this with django-prometheus metrics.
    Returns a 200 with an empty body so Prometheus scrape config can be
    wired up and verified now without the real exporter.
    """
    return HttpResponse("# metrics placeholder\n", content_type="text/plain")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("metrics", metrics_placeholder, name="metrics"),
]
