"""
URL configuration for config project.
"""

from django.contrib import admin
from django.urls import include, path

from apps.common.views import metrics_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("metrics", metrics_view, name="metrics"),
    path("api/v1/", include("apps.serving.urls")),
]
