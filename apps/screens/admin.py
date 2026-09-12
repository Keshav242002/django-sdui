from django.contrib import admin

from apps.screens.models import LayoutVersion, Screen, Section, WidgetType


class SectionInline(admin.TabularInline):
    model = Section
    extra = 1
    fields = ("widget_type", "title", "order", "is_active", "min_app_version")


@admin.register(Screen)
class ScreenAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "created_at", "updated_at")
    search_fields = ("key", "name")
    inlines = [SectionInline]


@admin.register(WidgetType)
class WidgetTypeAdmin(admin.ModelAdmin):
    list_display = ("key", "name")
    search_fields = ("key", "name")
    readonly_fields = ("schema",)


@admin.register(LayoutVersion)
class LayoutVersionAdmin(admin.ModelAdmin):
    list_display = ("screen", "version_number", "is_current", "published_at", "published_by")
    list_filter = ("is_current", "screen")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
