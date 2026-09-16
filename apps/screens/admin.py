from django.contrib import admin, messages

from apps.common.exceptions import LayoutNotPublished
from apps.screens.models import LayoutVersion, Screen, Section, WidgetType
from apps.screens.services import publish_layout


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
    list_display = ("key", "name", "created_at", "updated_at")
    search_fields = ("key", "name")
    inlines = [SectionInline]
    actions = [publish_layout_action]


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
