"""
URL configuration for config project.
"""

from django.contrib import admin
from django.urls import include, path

from apps.common.views import metrics_view
from apps.serving.views import ClientDemoView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("metrics", metrics_view, name="metrics"),
    path("client-demo/<slug:screen_key>/", ClientDemoView.as_view(), name="client-demo"),
    path("api/v1/", include("apps.serving.urls")),
]
