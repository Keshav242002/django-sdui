import uuid
from decimal import Decimal

from django.test import TestCase

from apps.funds.models import Fund, Holding, Portfolio, PortfolioSnapshot
from apps.funds.services import (
    get_holdings_data,
    get_portfolio_summary,
    get_top_movers_data,
    get_trending_funds_data,
)


class GetPortfolioSummaryTests(TestCase):
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


class GetHoldingsDataTests(TestCase):
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


class GetTopMoversDataTests(TestCase):
    def test_ordered_by_one_day_change_pct_descending(self):
        Fund.objects.create(name="Low", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="0.50")
        Fund.objects.create(name="High", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="2.40")
        Fund.objects.create(name="Mid", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="1.10")

        result = get_top_movers_data()

        self.assertEqual([f["name"] for f in result], ["High", "Mid", "Low"])


class GetTrendingFundsDataTests(TestCase):
    def test_only_trending_funds_returned(self):
        Fund.objects.create(
            name="Trending", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1, is_trending=True
        )
        Fund.objects.create(
            name="NotTrending", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1, is_trending=False
        )

        result = get_trending_funds_data()

        self.assertEqual([f["name"] for f in result], ["Trending"])
