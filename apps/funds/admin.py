from django.contrib import admin

from apps.funds.models import Fund, Holding, Portfolio, PortfolioSnapshot, Transaction


@admin.register(Fund)
class FundAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "nav", "one_day_change_pct", "is_trending")
    list_filter = ("category", "is_trending")
    search_fields = ("name",)


class HoldingInline(admin.TabularInline):
    model = Holding
    extra = 1


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("user_id", "total_value", "updated_at")
    search_fields = ("user_id",)
    inlines = [HoldingInline]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("portfolio", "fund", "type", "units", "price_per_unit", "created_at")
    list_filter = ("type", "fund")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PortfolioSnapshot)
class PortfolioSnapshotAdmin(admin.ModelAdmin):
    list_display = ("user_id", "total_value", "pnl", "pnl_percentage", "computed_at")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
