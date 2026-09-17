from django.contrib import admin, messages
from django.urls import path, reverse
from django.utils.html import format_html

from apps.common.exceptions import LayoutNotPublished
from apps.screens.models import LayoutVersion, Screen, Section, WidgetType
from apps.screens.services import publish_layout
from apps.screens.views import ScreenPreviewView


class SectionInline(admin.TabularInline):
    model = Section
    extra = 1
    fields = ("widget_type", "title", "order", "is_active", "min_app_version", "config")


@admin.action(description="Publish layout")
def publish_layout_action(modeladmin, request, queryset):
    for screen in queryset:
        try:
            layout_version = publish_layout(screen.key, request.user.username)
        except LayoutNotPublished as e:
            modeladmin.message_user(request, str(e), level=messages.ERROR)
            continue
        modeladmin.message_user(
            request, f"Published layout v{layout_version.version_number} for {screen.key}"
        )


@admin.register(Screen)
class ScreenAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "created_at", "updated_at", "preview_link")
    search_fields = ("key", "name")
    inlines = [SectionInline]
    actions = [publish_layout_action]

    def get_urls(self):
        """
        Registers the preview URL inside the admin's own namespace
        (admin/screens/screen/<pk>/preview/) so it gets the admin's
        `is_staff` authentication for free -- see plan.md Key Decisions #1.
        """
        opts = self.model._meta
        custom_urls = [
            path(
                "<int:screen_pk>/preview/",
                ScreenPreviewView.as_view(),
                name=f"{opts.app_label}_{opts.model_name}_preview",
            ),
        ]
        return custom_urls + super().get_urls()

    def preview_link(self, obj):
        opts = self.model._meta
        url = reverse(f"admin:{opts.app_label}_{opts.model_name}_preview", args=[obj.pk])
        return format_html('<a href="{}" target="_blank">Preview</a>', url)

    preview_link.short_description = "Preview"


@admin.register(WidgetType)
class WidgetTypeAdmin(admin.ModelAdmin):
    list_display = ("key", "name")
    search_fields = ("key", "name")
    readonly_fields = ("schema",)


@admin.register(LayoutVersion)
class LayoutVersionAdmin(admin.ModelAdmin):
    """
    Read-only audit trail. LayoutVersion rows must only ever be created by
    publish_layout() (via ScreenAdmin's "Publish layout" action), which
    snapshots Sections and warms the Redis cache atomically. Manually adding
    one here would create a row -- possibly with is_current=True -- that was
    never pushed to Redis, silently desyncing the cache from Postgres.
    """

    list_display = ("screen", "version_number", "is_current", "published_at", "published_by")
    list_filter = ("is_current", "screen")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
