from django.contrib import admin

from apps.flags.models import FeatureFlag, TargetingRule


class TargetingRuleInline(admin.TabularInline):
    model = TargetingRule
    extra = 1


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ("key", "is_enabled", "rollout_percentage", "updated_at")
    list_filter = ("is_enabled",)
    search_fields = ("key", "description")
    inlines = [TargetingRuleInline]
