import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from apps.common.cache import widget_cache_key
from apps.common.exceptions import WidgetDataUnavailable
from apps.flags.models import FeatureFlag
from apps.funds.models import Fund, Holding, Portfolio, PortfolioSnapshot
from apps.funds.tasks import recompute_top_movers
from apps.screens.models import Screen, Section, WidgetType
from apps.screens.services import publish_layout
from apps.serving import widget_registry

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


class ServingTestDataMixin:
    """
    Uses APITransactionTestCase (real commits) rather than APITestCase:
    assemble_screen() fetches sections concurrently via ThreadPoolExecutor,
    and worker threads get their own DB connection which cannot see rows
    created inside APITestCase's uncommitted per-test transaction.
    """

    def setUp(self):
        cache.clear()
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

        self.user_without_data = uuid.uuid4()


@override_settings(CACHES=TEST_CACHES)
class ScreenViewTests(ServingTestDataMixin, APITransactionTestCase):
    def test_happy_path_returns_four_sections_with_real_data(self):
        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["meta"]["total_sections"], 4)
        sections = response.data["data"]["sections"]
        self.assertEqual(
            [s["widget_type"] for s in sections],
            ["portfolio_summary", "holdings_list", "horizontal_carousel", "grid"],
        )
        self.assertEqual(sections[0]["data"]["total_value"], Decimal("1453.20"))
        self.assertEqual(sections[1]["data"][0]["fund_name"], "Alpha Bluechip Equity Fund")

    def test_user_with_no_portfolio_gets_empty_summary_other_sections_intact(self):
        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_without_data)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sections = response.data["data"]["sections"]
        self.assertEqual(sections[0]["data"], {})
        self.assertEqual(sections[2]["data"][0]["name"], "Alpha Bluechip Equity Fund")

    def test_unknown_screen_returns_404_with_error_envelope(self):
        response = self.client.get(
            "/api/v1/screens/does_not_exist/", {"user_id": str(self.user_with_data)}
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("error", response.data)
        self.assertEqual(response.data["error"]["code"], "LAYOUT_NOT_PUBLISHED")

    def test_missing_user_id_returns_400(self):
        response = self.client.get(f"/api/v1/screens/{self.screen.key}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_uuid_user_id_returns_400(self):
        response = self.client.get(f"/api/v1/screens/{self.screen.key}/", {"user_id": "not-a-uuid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_min_app_version_excludes_section_for_older_client(self):
        Section.objects.create(
            screen=self.screen,
            widget_type=self.widget_types["grid"],
            title="New Grid Widget",
            order=5,
            min_app_version="2.0.0",
        )

        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/",
            {"user_id": str(self.user_with_data), "app_version": "1.0.0"},
        )
        self.assertEqual(response.data["meta"]["total_sections"], 4)

        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/",
            {"user_id": str(self.user_with_data), "app_version": "2.0.0"},
        )
        self.assertEqual(response.data["meta"]["total_sections"], 5)

    def test_bulkhead_isolates_one_failing_widget(self):
        def raising_handler(user_id):
            raise WidgetDataUnavailable("top movers is down")

        with patch.dict(widget_registry.WIDGET_HANDLERS, {"horizontal_carousel": raising_handler}):
            response = self.client.get(
                f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sections = response.data["data"]["sections"]
        self.assertEqual(sections[2]["data"], {"status": "unavailable", "error_code": "WIDGET_UNAVAILABLE"})
        # The other three sections are unaffected.
        self.assertEqual(sections[0]["data"]["total_value"], Decimal("1453.20"))
        self.assertEqual(sections[1]["data"][0]["fund_name"], "Alpha Bluechip Equity Fund")
        self.assertEqual(sections[3]["data"][0]["name"], "Alpha Bluechip Equity Fund")

    def test_response_uses_published_snapshot_not_live_sections(self):
        publish_layout(self.screen.key, published_by="tester")

        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
        )

        self.assertEqual(response.data["meta"]["layout_version"], 1)
        self.assertEqual(response.data["data"]["layout_version"], 1)
        self.assertEqual(response.data["meta"]["total_sections"], 4)

    def test_unpublished_screen_has_null_layout_version(self):
        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
        )

        self.assertIsNone(response.data["meta"]["layout_version"])
        self.assertIsNone(response.data["data"]["layout_version"])

    def test_snapshot_isolation_editing_section_after_publish_does_not_change_response(self):
        publish_layout(self.screen.key, published_by="tester")

        self.sections[0].title = "Your Portfolio EDITED"
        self.sections[0].save()

        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
        )

        self.assertEqual(response.data["data"]["sections"][0]["title"], "Your Portfolio")

    def test_republish_picks_up_the_edit(self):
        publish_layout(self.screen.key, published_by="tester")

        self.sections[0].title = "Your Portfolio EDITED"
        self.sections[0].save()
        publish_layout(self.screen.key, published_by="tester")

        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
        )

        self.assertEqual(response.data["data"]["sections"][0]["title"], "Your Portfolio EDITED")
        self.assertEqual(response.data["data"]["layout_version"], 2)

    def test_killed_widget_key_degrades_to_postgres_then_beat_repopulates_it(self):
        """
        The PRD §15 Phase 5 checkpoint: kill a Redis key manually, confirm
        graceful degradation, confirm the beat job repopulates it.
        """
        cache.delete(widget_cache_key("top_movers"))

        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        top_movers_section = response.data["data"]["sections"][2]
        self.assertEqual(top_movers_section["data"][0]["name"], "Alpha Bluechip Equity Fund")

        recompute_top_movers()

        self.assertIsNotNone(cache.get(widget_cache_key("top_movers")))


@override_settings(CACHES=TEST_CACHES)
class WidgetViewTests(ServingTestDataMixin, APITransactionTestCase):
    def test_standalone_widget_returns_data(self):
        response = self.client.get(
            "/api/v1/widgets/portfolio_summary/", {"user_id": str(self.user_with_data)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["total_value"], Decimal("1453.20"))
        self.assertEqual(response.data["meta"]["widget_key"], "portfolio_summary")

    def test_unknown_widget_key_returns_404(self):
        response = self.client.get("/api/v1/widgets/unknown_key/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_user_id_returns_400(self):
        response = self.client.get("/api/v1/widgets/portfolio_summary/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_parity_with_aggregator_response(self):
        screen_response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
        )
        widget_response = self.client.get(
            "/api/v1/widgets/portfolio_summary/", {"user_id": str(self.user_with_data)}
        )

        embedded_data = screen_response.data["data"]["sections"][0]["data"]
        self.assertEqual(embedded_data, widget_response.data["data"])


@override_settings(CACHES=TEST_CACHES)
class FlagGatedSectionTests(ServingTestDataMixin, APITransactionTestCase):
    def _add_flagged_section(self, flag_key):
        Section.objects.create(
            screen=self.screen,
            widget_type=self.widget_types["grid"],
            title="Flagged Grid Widget",
            order=5,
            config={"feature_flag_key": flag_key},
        )

    def test_flagged_section_hidden_when_flag_disabled(self):
        FeatureFlag.objects.create(key="new_widget", is_enabled=False, rollout_percentage=100)
        self._add_flagged_section("new_widget")

        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
        )

        self.assertEqual(response.data["meta"]["total_sections"], 4)
        widget_types = [s["widget_type"] for s in response.data["data"]["sections"]]
        self.assertNotIn("grid", widget_types[4:])

    def test_flagged_section_shown_at_100pct_rollout(self):
        FeatureFlag.objects.create(key="new_widget", is_enabled=True, rollout_percentage=100)
        self._add_flagged_section("new_widget")

        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
        )

        self.assertEqual(response.data["meta"]["total_sections"], 5)
        self.assertEqual(response.data["data"]["sections"][4]["title"], "Flagged Grid Widget")

    def test_unflagged_section_always_shown(self):
        FeatureFlag.objects.create(key="new_widget", is_enabled=False, rollout_percentage=0)

        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
        )

        self.assertEqual(response.data["meta"]["total_sections"], 4)

    def test_unknown_flag_key_fails_open(self):
        self._add_flagged_section("does_not_exist_flag")

        response = self.client.get(
            f"/api/v1/screens/{self.screen.key}/", {"user_id": str(self.user_with_data)}
        )

        self.assertEqual(response.data["meta"]["total_sections"], 5)
        self.assertEqual(response.data["data"]["sections"][4]["title"], "Flagged Grid Widget")
