from django.contrib import admin

from apps.flags.models import FeatureFlag, TargetingRule


class TargetingRuleInline(admin.TabularInline):
    model = TargetingRule
    extra = 1


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ("key", "is_enabled", "rollout_display", "updated_at")
    list_filter = ("is_enabled",)
    search_fields = ("key", "description")
    inlines = [TargetingRuleInline]

    @admin.display(description="Rollout (est. users)")
    def rollout_display(self, obj):
        # Rough estimate over seeded Portfolio rows -- not a real user count.
        from apps.funds.models import Portfolio

        total = Portfolio.objects.count()
        n = total * obj.rollout_percentage // 100
        return f"{obj.rollout_percentage}% (~{n} users)"
