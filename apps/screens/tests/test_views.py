import json
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TransactionTestCase, override_settings

from apps.common.exceptions import WidgetDataUnavailable
from apps.funds.models import Fund, Holding, Portfolio, PortfolioSnapshot
from apps.screens.models import Screen, Section, WidgetType
from apps.screens.services import publish_layout
from apps.screens.tasks import warm_layout_cache
from apps.serving import widget_registry

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


@override_settings(CACHES=TEST_CACHES)
class ScreenPreviewViewTests(TransactionTestCase):
    """
    TransactionTestCase, not TestCase: the preview view calls
    apps.serving.services.fetch_section_data() directly on the request's
    main thread, which closes its DB connection in a `finally` block (safe
    for its original ThreadPoolExecutor caller, which owns a private
    per-thread connection). Under TestCase's class-level atomic wrapper,
    that same close() only flags the connection `closed_in_transaction`
    without clearing it, so every later query -- including setUp() of the
    next test in the class -- fails with "connection already closed".
    TransactionTestCase runs each test without that outer atomic block, so
    close() behaves as it does in production (mirrors the same reasoning
    apps/serving/tests/test_views.py::ServingTestDataMixin already
    documents for this function).
    """

    def setUp(self):
        cache.clear()
        self.staff_user = User.objects.create_user(
            username="admin", password="password", is_staff=True
        )
        self.widget_types = {}
        for key in ["portfolio_summary", "holdings_list", "horizontal_carousel", "grid"]:
            self.widget_types[key] = WidgetType.objects.create(key=key, name=key)

        self.screen = Screen.objects.create(key="mf_dashboard", name="Mutual Fund Dashboard")
        self.sections = [
            Section.objects.create(
                screen=self.screen,
                widget_type=self.widget_types["portfolio_summary"],
                title="Your Portfolio",
                order=1,
            ),
            Section.objects.create(
                screen=self.screen,
                widget_type=self.widget_types["holdings_list"],
                title="Your Holdings",
                order=2,
            ),
            Section.objects.create(
                screen=self.screen,
                widget_type=self.widget_types["horizontal_carousel"],
                title="Top Movers",
                order=3,
            ),
            Section.objects.create(
                screen=self.screen,
                widget_type=self.widget_types["grid"],
                title="Trending Funds",
                order=4,
            ),
        ]

        self.fund = Fund.objects.create(
            name="Alpha Bluechip Equity Fund",
            category=Fund.Category.EQUITY,
            nav=Decimal("145.3200"),
            one_day_change_pct=Decimal("1.85"),
            is_trending=True,
        )

        self.user_with_data = uuid.uuid4()
        portfolio = Portfolio.objects.create(user_id=self.user_with_data, total_value=Decimal("1453.20"))
        Holding.objects.create(
            portfolio=portfolio,
            fund=self.fund,
            units=Decimal("10.0000"),
            invested_amount=Decimal("1200.00"),
            current_value=Decimal("1453.20"),
        )
        PortfolioSnapshot.objects.create(
            user_id=self.user_with_data,
            total_value=Decimal("1453.20"),
            total_invested=Decimal("1200.00"),
            pnl=Decimal("253.20"),
            pnl_percentage=Decimal("21.10"),
        )

        self.zero_holdings_user = uuid.uuid4()

    def _preview_url(self, **params):
        url = f"/admin/screens/screen/{self.screen.pk}/preview/"
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return url

    def _publish(self):
        """
        No captureOnCommitCallbacks here (TestCase-only): TransactionTestCase
        runs outside any wrapping atomic block, so transaction.on_commit()
        inside publish_layout() fires immediately, the same as production.
        """
        with patch("apps.screens.services.warm_layout_cache.delay", side_effect=warm_layout_cache):
            return publish_layout(self.screen.key, published_by="admin")

    def _layout(self, response) -> dict:
        return json.loads(response.context["layout_json"])

    def test_preview_requires_staff_login(self):
        response = self.client.get(self._preview_url())

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_preview_draft_mode_shows_live_sections(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(self._preview_url(mode="draft"))

        self.assertEqual(response.status_code, 200)
        layout = self._layout(response)
        self.assertEqual(
            [s["widget_type"] for s in layout["sections"]],
            ["portfolio_summary", "holdings_list", "horizontal_carousel", "grid"],
        )

    def test_preview_published_mode_shows_layout_version(self):
        self.client.force_login(self.staff_user)
        self._publish()
        Section.objects.create(
            screen=self.screen,
            widget_type=self.widget_types["grid"],
            title="Unpublished New Section",
            order=5,
        )

        response = self.client.get(self._preview_url(mode="published"))

        layout = self._layout(response)
        titles = [s["title"] for s in layout["sections"]]
        self.assertNotIn("Unpublished New Section", titles)
        self.assertEqual(len(layout["sections"]), 4)

    def test_preview_published_mode_no_layout_version_shows_not_published_state(self):
        """
        A screen with live Section rows but no LayoutVersion ever published
        must show an explicit "not yet published" state in Published mode,
        never silently fall back to draft/live sections -- that fallback is
        exactly what get_active_sections() does and exactly what the preview
        must NOT do (plan.md Key Decisions #2).
        """
        self.client.force_login(self.staff_user)

        response = self.client.get(self._preview_url(mode="published"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["empty_state"], "not_published")
        layout = self._layout(response)
        self.assertEqual(layout["sections"], [])

    def test_preview_draft_vs_published_order_change(self):
        self.client.force_login(self.staff_user)
        self._publish()

        top_movers = self.sections[2]
        trending = self.sections[3]
        top_movers.order, trending.order = trending.order, top_movers.order
        top_movers.save()
        trending.save()

        draft_layout = self._layout(self.client.get(self._preview_url(mode="draft")))
        published_layout = self._layout(self.client.get(self._preview_url(mode="published")))

        self.assertEqual(
            [s["widget_type"] for s in draft_layout["sections"]],
            ["portfolio_summary", "holdings_list", "grid", "horizontal_carousel"],
        )
        self.assertEqual(
            [s["widget_type"] for s in published_layout["sections"]],
            ["portfolio_summary", "holdings_list", "horizontal_carousel", "grid"],
        )

    def test_preview_nonexistent_screen_returns_404(self):
        self.client.force_login(self.staff_user)

        response = self.client.get("/admin/screens/screen/999999/preview/")

        self.assertEqual(response.status_code, 404)

    def test_preview_with_user_id_includes_per_user_data(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(self._preview_url(mode="draft", user_id=str(self.user_with_data)))

        layout = self._layout(response)
        portfolio_section = layout["sections"][0]
        self.assertEqual(Decimal(str(portfolio_section["data"]["total_value"])), Decimal("1453.20"))
        holdings_section = layout["sections"][1]
        self.assertEqual(holdings_section["data"][0]["fund_name"], "Alpha Bluechip Equity Fund")

    def test_preview_without_user_id_shows_no_user_selected_for_personalized_sections(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(self._preview_url(mode="draft"))

        layout = self._layout(response)
        self.assertEqual(layout["sections"][0]["data"], {"status": "no_user_selected"})
        self.assertEqual(layout["sections"][1]["data"], {"status": "no_user_selected"})

    def test_preview_zero_holdings_user_shows_empty_state(self):
        """
        A seeded zero-holdings user (no Portfolio at all) must render an
        explicit empty state for portfolio_summary/holdings_list, not a
        blank or broken card -- get_portfolio_summary() returns {} and
        get_holdings_data() returns [] for this case (apps/funds/services.py),
        and the JS renderer must handle both shapes explicitly.
        """
        self.client.force_login(self.staff_user)

        response = self.client.get(
            self._preview_url(mode="draft", user_id=str(self.zero_holdings_user))
        )

        layout = self._layout(response)
        self.assertEqual(layout["sections"][0]["data"], {})
        self.assertEqual(layout["sections"][1]["data"], [])

    def test_preview_widget_fetch_failure_isolated(self):
        """
        The preview must reuse the aggregator's per-section bulkhead
        (apps.serving.services.fetch_section_data) so one widget's fetch
        failure shows "unavailable" on that card instead of 500ing the
        whole preview page (rules.md §2, PRD §12A).
        """
        self.client.force_login(self.staff_user)

        def raising_handler(user_id, fund_id=None):
            raise WidgetDataUnavailable("top movers is down")

        with patch.dict(widget_registry.WIDGET_HANDLERS, {"horizontal_carousel": raising_handler}):
            response = self.client.get(
                self._preview_url(mode="draft", user_id=str(self.user_with_data))
            )

        self.assertEqual(response.status_code, 200)
        layout = self._layout(response)
        self.assertEqual(
            layout["sections"][2]["data"], {"status": "unavailable", "error_code": "WIDGET_UNAVAILABLE"}
        )
        # The other sections are unaffected.
        self.assertEqual(layout["sections"][1]["data"][0]["fund_name"], "Alpha Bluechip Equity Fund")


@override_settings(CACHES=TEST_CACHES)
class FundDetailPreviewTests(TransactionTestCase):
    """
    Phase 8: the fund_detail screen's fund_overview/recommended_funds
    widgets, previewed with a `fund_id` query param (see
    apps.screens.views.ScreenPreviewView -- same TransactionTestCase
    reasoning as ScreenPreviewViewTests above).
    """

    def setUp(self):
        cache.clear()
        self.staff_user = User.objects.create_user(
            username="admin2", password="password", is_staff=True
        )
        self.widget_types = {
            key: WidgetType.objects.create(key=key, name=key)
            for key in ["fund_overview", "recommended_funds"]
        }
        self.screen = Screen.objects.create(key="fund_detail", name="Fund Detail")
        Section.objects.create(
            screen=self.screen,
            widget_type=self.widget_types["fund_overview"],
            title="Fund Overview",
            order=1,
        )
        Section.objects.create(
            screen=self.screen,
            widget_type=self.widget_types["recommended_funds"],
            title="Recommended Funds",
            order=2,
        )

        self.fund = Fund.objects.create(
            name="Alpha Bluechip Equity Fund",
            category=Fund.Category.EQUITY,
            nav=Decimal("145.3200"),
            one_day_change_pct=Decimal("1.85"),
        )
        self.held_fund = Fund.objects.create(
            name="Beta Debt Fund",
            category=Fund.Category.DEBT,
            nav=Decimal("50.0000"),
            one_day_change_pct=Decimal("2.50"),
        )
        self.user_id = uuid.uuid4()
        portfolio = Portfolio.objects.create(user_id=self.user_id, total_value=Decimal("500.00"))
        Holding.objects.create(
            portfolio=portfolio,
            fund=self.held_fund,
            units=Decimal("10.0000"),
            invested_amount=Decimal("500.00"),
            current_value=Decimal("500.00"),
        )

    def _preview_url(self, **params):
        url = f"/admin/screens/screen/{self.screen.pk}/preview/"
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return url

    def _layout(self, response) -> dict:
        return json.loads(response.context["layout_json"])

    def test_preview_fund_detail_with_fund_id_shows_overview(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(
            self._preview_url(mode="draft", fund_id=self.fund.pk, user_id=str(self.user_id))
        )

        self.assertEqual(response.status_code, 200)
        layout = self._layout(response)
        overview = layout["sections"][0]["data"]
        self.assertEqual(overview["name"], "Alpha Bluechip Equity Fund")

        recommended = layout["sections"][1]["data"]
        recommended_names = [f["name"] for f in recommended]
        self.assertIn("Alpha Bluechip Equity Fund", recommended_names)
        self.assertNotIn("Beta Debt Fund", recommended_names)

    def test_preview_fund_detail_without_fund_id_shows_no_fund_selected(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(self._preview_url(mode="draft", user_id=str(self.user_id)))

        layout = self._layout(response)
        self.assertEqual(layout["sections"][0]["data"], {})

    def test_preview_fund_detail_without_user_id_shows_no_user_selected_for_recommended(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(self._preview_url(mode="draft", fund_id=self.fund.pk))

        layout = self._layout(response)
        self.assertEqual(layout["sections"][1]["data"], {"status": "no_user_selected"})
