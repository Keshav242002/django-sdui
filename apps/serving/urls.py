from django.urls import path

from apps.serving.views import ScreenView, WidgetView

urlpatterns = [
    path("screens/<slug:screen_key>/", ScreenView.as_view(), name="screen-detail"),
    path("widgets/<slug:widget_key>/", WidgetView.as_view(), name="widget-detail"),
]
