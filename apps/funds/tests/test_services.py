import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.funds.models import Fund, Holding, Portfolio, PortfolioSnapshot
from apps.funds.services import (
    get_fund_overview_data,
    get_holdings_data,
    get_portfolio_summary,
    get_recommended_funds_data,
    get_top_movers_data,
    get_trending_funds_data,
)

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


@override_settings(CACHES=TEST_CACHES)
class FundsServicesTestCase(TestCase):
    def setUp(self):
        cache.clear()


class GetPortfolioSummaryTests(FundsServicesTestCase):
    def test_returns_latest_snapshot_for_user(self):
        user_id = uuid.uuid4()
        PortfolioSnapshot.objects.create(
            user_id=user_id,
            total_value=Decimal("1000.00"),
            total_invested=Decimal("900.00"),
            pnl=Decimal("100.00"),
            pnl_percentage=Decimal("11.11"),
        )

        result = get_portfolio_summary(str(user_id))

        self.assertEqual(result["total_value"], Decimal("1000.00"))
        self.assertEqual(result["pnl"], Decimal("100.00"))

    def test_returns_empty_dict_when_no_snapshot(self):
        result = get_portfolio_summary(str(uuid.uuid4()))
        self.assertEqual(result, {})

    def test_second_call_hits_cache_no_second_query(self):
        user_id = uuid.uuid4()
        PortfolioSnapshot.objects.create(
            user_id=user_id,
            total_value=Decimal("1000.00"),
            total_invested=Decimal("900.00"),
            pnl=Decimal("100.00"),
            pnl_percentage=Decimal("11.11"),
        )

        get_portfolio_summary(str(user_id))

        with patch("apps.funds.services.PortfolioSnapshot") as mock_model:
            result = get_portfolio_summary(str(user_id))

        mock_model.objects.filter.assert_not_called()
        self.assertEqual(result["total_value"], Decimal("1000.00"))


class GetHoldingsDataTests(FundsServicesTestCase):
    def test_returns_holdings_for_user(self):
        portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=1000)
        fund = Fund.objects.create(
            name="Alpha Equity Fund", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1.5
        )
        Holding.objects.create(
            portfolio=portfolio, fund=fund, units=10, invested_amount=1000, current_value=1050
        )

        result = get_holdings_data(str(portfolio.user_id))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["fund_name"], "Alpha Equity Fund")

    def test_returns_empty_list_for_user_with_no_holdings(self):
        result = get_holdings_data(str(uuid.uuid4()))
        self.assertEqual(result, [])

    def test_second_call_hits_cache_no_second_query(self):
        portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=1000)
        fund = Fund.objects.create(
            name="Alpha Equity Fund", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1.5
        )
        Holding.objects.create(
            portfolio=portfolio, fund=fund, units=10, invested_amount=1000, current_value=1050
        )

        get_holdings_data(str(portfolio.user_id))

        with patch("apps.funds.services.Holding") as mock_model:
            result = get_holdings_data(str(portfolio.user_id))

        mock_model.objects.filter.assert_not_called()
        self.assertEqual(result[0]["fund_name"], "Alpha Equity Fund")


class GetTopMoversDataTests(FundsServicesTestCase):
    def test_ordered_by_one_day_change_pct_descending(self):
        Fund.objects.create(name="Low", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="0.50")
        Fund.objects.create(name="High", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="2.40")
        Fund.objects.create(name="Mid", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="1.10")

        result = get_top_movers_data()

        self.assertEqual([f["name"] for f in result], ["High", "Mid", "Low"])

    def test_second_call_hits_cache_no_second_query(self):
        Fund.objects.create(name="High", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="2.40")

        get_top_movers_data()

        with patch("apps.funds.services.Fund") as mock_model:
            result = get_top_movers_data()

        mock_model.objects.order_by.assert_not_called()
        self.assertEqual(result[0]["name"], "High")


class GetTrendingFundsDataTests(FundsServicesTestCase):
    def test_only_trending_funds_returned(self):
        Fund.objects.create(
            name="Trending", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1, is_trending=True
        )
        Fund.objects.create(
            name="NotTrending", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1, is_trending=False
        )

        result = get_trending_funds_data()

        self.assertEqual([f["name"] for f in result], ["Trending"])

    def test_second_call_hits_cache_no_second_query(self):
        Fund.objects.create(
            name="Trending", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1, is_trending=True
        )

        get_trending_funds_data()

        with patch("apps.funds.services.Fund") as mock_model:
            result = get_trending_funds_data()

        mock_model.objects.filter.assert_not_called()
        self.assertEqual(result[0]["name"], "Trending")


class GetFundOverviewDataTests(FundsServicesTestCase):
    def test_returns_fund_data_for_known_fund_id(self):
        fund = Fund.objects.create(
            name="Alpha Equity Fund", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1.5
        )

        result = get_fund_overview_data(str(uuid.uuid4()), fund_id=str(fund.pk))

        self.assertEqual(result["name"], "Alpha Equity Fund")
        self.assertEqual(result["category"], Fund.Category.EQUITY)

    def test_returns_empty_dict_for_unknown_fund_id(self):
        result = get_fund_overview_data(str(uuid.uuid4()), fund_id="999999")
        self.assertEqual(result, {})

    def test_returns_empty_dict_when_fund_id_not_given(self):
        result = get_fund_overview_data(str(uuid.uuid4()), fund_id=None)
        self.assertEqual(result, {})

    def test_second_call_hits_cache_no_second_query(self):
        fund = Fund.objects.create(
            name="Alpha Equity Fund", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1.5
        )

        get_fund_overview_data(str(uuid.uuid4()), fund_id=str(fund.pk))

        with patch("apps.funds.services.Fund") as mock_model:
            result = get_fund_overview_data(str(uuid.uuid4()), fund_id=str(fund.pk))

        mock_model.objects.filter.assert_not_called()
        self.assertEqual(result["name"], "Alpha Equity Fund")


class GetRecommendedFundsDataTests(FundsServicesTestCase):
    def test_excludes_held_funds(self):
        held_fund = Fund.objects.create(
            name="Held Fund", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="2.40"
        )
        Fund.objects.create(
            name="Other Fund", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="1.10"
        )
        portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=1000)
        Holding.objects.create(
            portfolio=portfolio, fund=held_fund, units=10, invested_amount=1000, current_value=1050
        )

        result = get_recommended_funds_data(str(portfolio.user_id))

        names = [f["name"] for f in result]
        self.assertNotIn("Held Fund", names)
        self.assertIn("Other Fund", names)

    def test_user_with_no_holdings_sees_full_pool(self):
        Fund.objects.create(
            name="Some Fund", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="2.40"
        )

        result = get_recommended_funds_data(str(uuid.uuid4()))

        self.assertEqual([f["name"] for f in result], ["Some Fund"])

    def test_exclusion_runs_exactly_one_query_on_a_warm_pool(self):
        """
        Guards Phase 8 plan.md Key Decision #1: the held-fund exclusion is
        one bounded query against the user's Holding rows, never one query
        per fund in the pool. The pool itself is cached after the first
        call, so a second call should cost exactly one query (the
        exclusion) -- not (1 + pool size).
        """
        held_fund = Fund.objects.create(
            name="Held Fund", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="9.99"
        )
        for i in range(5):
            Fund.objects.create(
                name=f"Fund {i}", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=str(i)
            )
        portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=1000)
        Holding.objects.create(
            portfolio=portfolio, fund=held_fund, units=10, invested_amount=1000, current_value=1050
        )

        get_recommended_funds_data(str(portfolio.user_id))  # warms the pool cache

        with self.assertNumQueries(1):
            get_recommended_funds_data(str(portfolio.user_id))

    def test_cache_miss_falls_back_to_postgres(self):
        Fund.objects.create(
            name="High", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="2.40"
        )

        result = get_recommended_funds_data(str(uuid.uuid4()))

        self.assertEqual(result[0]["name"], "High")
