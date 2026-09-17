"""
Idempotent seed data for local development (`python manage.py seed_data`).

Note on location: the phase-1 plan lists this as `scripts/seed_data.py`, but
Django only discovers management commands under `<app>/management/commands/`,
so the real command lives here in `apps/common` (it touches screens, flags,
and funds — a cross-app orchestration script fits `common`).

Note on fund count: the plan specifies "10 sample funds (3 Equity, 4 Debt,
3 Hybrid)", but user #2's scenario needs 4 distinct Equity holdings. Rather
than fake a second holding on a fund already used elsewhere, a 4th Equity
fund was added — 11 funds total (4 Equity, 4 Debt, 3 Hybrid).

--------------------------------------------------------------------------
Seeded portfolio user_ids (fixed, hardcoded so they are stable across runs)
--------------------------------------------------------------------------
1. aaaaaaaa-0001-0001-0001-000000000001 — 5 holdings across Equity + Debt (standard multi-category)
2. aaaaaaaa-0002-0002-0002-000000000002 — 4 holdings, all Equity (equity-only portfolio)
3. aaaaaaaa-0003-0003-0003-000000000003 — 3 holdings across Equity + Hybrid (mixed portfolio)
4. aaaaaaaa-0004-0004-0004-000000000004 — 1 holding (single-holding edge case)
5. aaaaaaaa-0005-0005-0005-000000000005 — 0 holdings / no Portfolio object (empty-portfolio state)
6. aaaaaaaa-0006-0006-0006-000000000006 — only `sell` transactions, no holdings (fully-exited edge case)
7. aaaaaaaa-0007-0007-0007-000000000007 — 8 holdings across all 3 categories (pagination testing)
8. aaaaaaaa-0008-0008-0008-000000000008 — 10 holdings, heavy Debt allocation (large holdings list)
9. aaaaaaaa-0009-0009-0009-000000000009 — 2 holdings, both negative PnL (loss-making portfolio)
10. aaaaaaaa-0010-0010-0010-000000000010 — 3 holdings, all strongly positive PnL (high-gain portfolio)
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models.signals import post_save

from apps.flags.models import FeatureFlag
from apps.funds.models import Fund, Holding, Portfolio, Transaction, on_transaction_saved
from apps.screens.models import Screen, Section, WidgetType

USER_1 = "aaaaaaaa-0001-0001-0001-000000000001"
USER_2 = "aaaaaaaa-0002-0002-0002-000000000002"
USER_3 = "aaaaaaaa-0003-0003-0003-000000000003"
USER_4 = "aaaaaaaa-0004-0004-0004-000000000004"
USER_5 = "aaaaaaaa-0005-0005-0005-000000000005"
USER_6 = "aaaaaaaa-0006-0006-0006-000000000006"
USER_7 = "aaaaaaaa-0007-0007-0007-000000000007"
USER_8 = "aaaaaaaa-0008-0008-0008-000000000008"
USER_9 = "aaaaaaaa-0009-0009-0009-000000000009"
USER_10 = "aaaaaaaa-0010-0010-0010-000000000010"

WIDGET_TYPES = [
    {"key": "portfolio_summary", "name": "Portfolio Summary", "schema": {}},
    {"key": "holdings_list", "name": "Holdings List", "schema": {}},
    {"key": "horizontal_carousel", "name": "Horizontal Carousel", "schema": {}},
    {"key": "grid", "name": "Grid", "schema": {}},
]

FUNDS = [
    {"name": "Alpha Bluechip Equity Fund", "category": Fund.Category.EQUITY, "nav": "145.3200", "change": "1.85", "trending": True},
    {"name": "Momentum Growth Equity Fund", "category": Fund.Category.EQUITY, "nav": "89.1000", "change": "2.40", "trending": True},
    {"name": "Horizon Large Cap Equity Fund", "category": Fund.Category.EQUITY, "nav": "210.5500", "change": "-0.75", "trending": False},
    {"name": "Global Opportunities Equity Fund", "category": Fund.Category.EQUITY, "nav": "118.7500", "change": "1.10", "trending": False},
    {"name": "Steady Income Debt Fund", "category": Fund.Category.DEBT, "nav": "42.1800", "change": "0.05", "trending": False},
    {"name": "Liquid Plus Debt Fund", "category": Fund.Category.DEBT, "nav": "28.9000", "change": "0.02", "trending": False},
    {"name": "Corporate Bond Debt Fund", "category": Fund.Category.DEBT, "nav": "35.6700", "change": "-0.10", "trending": False},
    {"name": "Government Securities Debt Fund", "category": Fund.Category.DEBT, "nav": "50.2400", "change": "0.08", "trending": False},
    {"name": "Balanced Advantage Hybrid Fund", "category": Fund.Category.HYBRID, "nav": "65.4000", "change": "0.95", "trending": True},
    {"name": "Conservative Hybrid Fund", "category": Fund.Category.HYBRID, "nav": "48.7500", "change": "0.30", "trending": False},
    {"name": "Dynamic Asset Allocation Hybrid Fund", "category": Fund.Category.HYBRID, "nav": "72.1000", "change": "-0.45", "trending": False},
]


class Command(BaseCommand):
    help = "Populate the database with realistic seed data (idempotent, safe to re-run)."

    def handle(self, *args, **options):
        widget_types = self._seed_widget_types()
        self._seed_screens_and_sections(widget_types)
        funds = self._seed_funds()
        self._seed_feature_flag()

        # _seed_portfolios sets each Holding directly to its intended final
        # units/invested_amount/current_value, *and* separately writes a
        # matching BUY Transaction as an audit-trail record -- it treats
        # the two as independently-given starting state, not one derived
        # from the other. Since Phase 5, on_transaction_saved (see
        # apps.funds.models) applies every newly-created Transaction to its
        # Holding -- with the signal connected, creating that BUY
        # Transaction would add its units to the Holding a second time, on
        # top of the value get_or_create() just set explicitly. Disconnected
        # here, for this command only, so seeding writes exactly the values
        # given above.
        post_save.disconnect(on_transaction_saved, sender=Transaction)
        try:
            self._seed_portfolios(funds)
        finally:
            post_save.connect(on_transaction_saved, sender=Transaction)

        self.stdout.write(self.style.SUCCESS("Seed data created successfully."))

    def _seed_widget_types(self):
        widget_types = {}
        for wt in WIDGET_TYPES:
            obj, _ = WidgetType.objects.get_or_create(
                key=wt["key"], defaults={"name": wt["name"], "schema": wt["schema"]}
            )
            widget_types[wt["key"]] = obj
        return widget_types

    def _seed_screens_and_sections(self, widget_types):
        mf_dashboard, _ = Screen.objects.get_or_create(
            key="mf_dashboard", defaults={"name": "Mutual Fund Dashboard"}
        )
        Screen.objects.get_or_create(key="fund_detail", defaults={"name": "Fund Detail"})

        sections = [
            ("portfolio_summary", "Your Portfolio", 1),
            ("holdings_list", "Your Holdings", 2),
            ("horizontal_carousel", "Top Movers", 3),
            ("grid", "Trending Funds", 4),
        ]
        for widget_key, title, order in sections:
            Section.objects.get_or_create(
                screen=mf_dashboard,
                widget_type=widget_types[widget_key],
                order=order,
                defaults={"title": title, "is_active": True},
            )

    def _seed_funds(self):
        funds = []
        for f in FUNDS:
            obj, _ = Fund.objects.get_or_create(
                name=f["name"],
                defaults={
                    "category": f["category"],
                    "nav": Decimal(f["nav"]),
                    "one_day_change_pct": Decimal(f["change"]),
                    "is_trending": f["trending"],
                },
            )
            funds.append(obj)
        return funds

    def _seed_feature_flag(self):
        FeatureFlag.objects.get_or_create(
            key="new_recommended_funds_widget",
            defaults={
                "description": "Shows the recommended funds widget on the dashboard",
                "is_enabled": False,
                "rollout_percentage": 0,
            },
        )

    def _seed_portfolios(self, funds):
        eq1, eq2, eq3, eq4, debt1, debt2, debt3, debt4, hyb1, hyb2, hyb3 = funds

        # (user_id, [(fund, units, invested_amount, current_value), ...])
        scenarios = [
            (USER_1, [
                (eq1, "10.0000", "1200.00", "1450.00"),
                (eq2, "5.0000", "400.00", "445.00"),
                (debt1, "20.0000", "800.00", "810.00"),
                (debt2, "15.0000", "420.00", "421.00"),
                (debt3, "8.0000", "280.00", "279.00"),
            ]),
            (USER_2, [
                (eq1, "8.0000", "1000.00", "1160.00"),
                (eq2, "6.0000", "480.00", "530.00"),
                (eq3, "4.0000", "800.00", "790.00"),
                (eq4, "5.0000", "550.00", "593.00"),
            ]),
            (USER_3, [
                (eq1, "6.0000", "750.00", "870.00"),
                (hyb1, "10.0000", "600.00", "620.00"),
                (hyb2, "12.0000", "550.00", "555.00"),
            ]),
            (USER_4, [
                (eq2, "3.0000", "240.00", "260.00"),
            ]),
            (USER_5, []),
            (USER_6, []),
            (USER_7, [
                (eq1, "4.0000", "500.00", "560.00"),
                (eq2, "3.0000", "240.00", "255.00"),
                (eq3, "2.0000", "400.00", "395.00"),
                (debt1, "10.0000", "400.00", "405.00"),
                (debt2, "9.0000", "260.00", "261.00"),
                (debt4, "6.0000", "290.00", "292.00"),
                (hyb1, "5.0000", "300.00", "310.00"),
                (hyb2, "7.0000", "320.00", "322.00"),
            ]),
            (USER_8, [
                (eq1, "2.0000", "250.00", "270.00"),
                (eq2, "2.0000", "160.00", "170.00"),
                (eq3, "1.0000", "200.00", "198.00"),
                (debt1, "40.0000", "1600.00", "1620.00"),
                (debt2, "35.0000", "980.00", "985.00"),
                (debt3, "30.0000", "1050.00", "1045.00"),
                (debt4, "25.0000", "1200.00", "1210.00"),
                (hyb1, "5.0000", "300.00", "310.00"),
                (hyb2, "4.0000", "180.00", "182.00"),
                (hyb3, "3.0000", "200.00", "198.00"),
            ]),
            (USER_9, [
                (debt3, "20.0000", "720.00", "690.00"),
                (hyb3, "10.0000", "750.00", "700.00"),
            ]),
            (USER_10, [
                (eq2, "10.0000", "700.00", "980.00"),
                (hyb1, "15.0000", "800.00", "1020.00"),
                (eq1, "8.0000", "900.00", "1220.00"),
            ]),
        ]

        for user_id, holdings in scenarios:
            if not holdings and user_id == USER_5:
                continue  # USER_5: deliberately no Portfolio object at all

            total_value = sum((Decimal(cv) for _, _, _, cv in holdings), Decimal("0"))
            portfolio, _ = Portfolio.objects.get_or_create(
                user_id=user_id, defaults={"total_value": total_value}
            )

            for fund, units, invested_amount, current_value in holdings:
                Holding.objects.get_or_create(
                    portfolio=portfolio,
                    fund=fund,
                    defaults={
                        "units": Decimal(units),
                        "invested_amount": Decimal(invested_amount),
                        "current_value": Decimal(current_value),
                    },
                )
                Transaction.objects.get_or_create(
                    portfolio=portfolio,
                    fund=fund,
                    type=Transaction.Type.BUY,
                    units=Decimal(units),
                    price_per_unit=(Decimal(invested_amount) / Decimal(units)).quantize(Decimal("0.0001")),
                )

            if user_id == USER_6:
                # Fully-exited edge case: sell transactions on record, no current holdings.
                Transaction.objects.get_or_create(
                    portfolio=portfolio,
                    fund=eq3,
                    type=Transaction.Type.SELL,
                    units=Decimal("5.0000"),
                    price_per_unit=Decimal("210.5500"),
                )
                Transaction.objects.get_or_create(
                    portfolio=portfolio,
                    fund=debt1,
                    type=Transaction.Type.SELL,
                    units=Decimal("12.0000"),
                    price_per_unit=Decimal("42.1800"),
                )
