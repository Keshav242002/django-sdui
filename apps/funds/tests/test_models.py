import uuid

from django.db.models.signals import post_save
from django.test import TestCase

from apps.funds.models import Fund, Holding, Portfolio, Transaction, on_transaction_saved


class PortfolioHoldingModelTests(TestCase):
    def test_portfolio_holding_relationship(self):
        portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=1000)
        fund = Fund.objects.create(
            name="Alpha Equity Fund", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1.5
        )
        holding = Holding.objects.create(
            portfolio=portfolio, fund=fund, units=10, invested_amount=1000, current_value=1050
        )

        self.assertEqual(portfolio.holdings.count(), 1)
        self.assertEqual(portfolio.holdings.first(), holding)


class TransactionSignalTests(TestCase):
    def test_post_save_signal_is_connected(self):
        was_connected = post_save.disconnect(on_transaction_saved, sender=Transaction)
        self.assertTrue(was_connected)
        post_save.connect(on_transaction_saved, sender=Transaction)
