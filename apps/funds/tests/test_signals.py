"""
Tests for on_transaction_saved (apps.funds.models) -- the PRD §9A CQRS
wiring: a Transaction save synchronously updates its Holding (command
side) and dispatches recompute_portfolio_snapshot once the transaction
commits (query side).

captureOnCommitCallbacks(execute=True) is required to observe the
dispatch: TestCase wraps each test in a rollback-only transaction, so
transaction.on_commit() callbacks would otherwise never fire.
"""

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from kombu.exceptions import OperationalError

from apps.funds.models import Fund, Holding, Portfolio, Transaction

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


@override_settings(CACHES=TEST_CACHES)
class TransactionSignalTestCase(TestCase):
    def setUp(self):
        self.portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=0)
        self.fund = Fund.objects.create(
            name="Alpha", category=Fund.Category.EQUITY, nav=Decimal("100.0000"), one_day_change_pct=1
        )

    def _create_transaction(self, **kwargs):
        defaults = {
            "portfolio": self.portfolio,
            "fund": self.fund,
            "type": Transaction.Type.BUY,
            "units": Decimal("1.0000"),
            "price_per_unit": Decimal("100.0000"),
        }
        defaults.update(kwargs)
        with patch("apps.funds.tasks.recompute_portfolio_snapshot.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                return Transaction.objects.create(**defaults)


class ApplyTransactionToHoldingTests(TransactionSignalTestCase):
    def test_buy_transaction_creates_and_updates_holding(self):
        self._create_transaction(units=Decimal("10.0000"), price_per_unit=Decimal("100.0000"))

        holding = Holding.objects.get(portfolio=self.portfolio, fund=self.fund)
        self.assertEqual(holding.units, Decimal("10.0000"))
        self.assertEqual(holding.invested_amount, Decimal("1000.00"))
        self.assertEqual(holding.current_value, Decimal("1000.00"))

        self._create_transaction(units=Decimal("5.0000"), price_per_unit=Decimal("100.0000"))

        holding.refresh_from_db()
        self.assertEqual(holding.units, Decimal("15.0000"))
        self.assertEqual(holding.invested_amount, Decimal("1500.00"))

    def test_sell_transaction_reduces_units_and_deletes_holding_on_full_exit(self):
        self._create_transaction(units=Decimal("10.0000"), price_per_unit=Decimal("100.0000"))

        self._create_transaction(
            type=Transaction.Type.SELL, units=Decimal("10.0000"), price_per_unit=Decimal("110.0000")
        )

        self.assertFalse(Holding.objects.filter(portfolio=self.portfolio, fund=self.fund).exists())

    def test_partial_sell_reduces_units_and_proportional_cost_basis(self):
        self._create_transaction(units=Decimal("10.0000"), price_per_unit=Decimal("100.0000"))

        self._create_transaction(
            type=Transaction.Type.SELL, units=Decimal("4.0000"), price_per_unit=Decimal("110.0000")
        )

        holding = Holding.objects.get(portfolio=self.portfolio, fund=self.fund)
        self.assertEqual(holding.units, Decimal("6.0000"))
        self.assertEqual(holding.invested_amount, Decimal("600.00"))  # 1000 - (1000 * 4/10)

    def test_oversell_is_clamped_to_held_units_and_logged(self):
        self._create_transaction(units=Decimal("5.0000"), price_per_unit=Decimal("100.0000"))

        with self.assertLogs("apps.funds.services", level="WARNING"):
            self._create_transaction(
                type=Transaction.Type.SELL, units=Decimal("999.0000"), price_per_unit=Decimal("100.0000")
            )

        self.assertFalse(Holding.objects.filter(portfolio=self.portfolio, fund=self.fund).exists())


class RecomputeDispatchTests(TransactionSignalTestCase):
    def test_transaction_dispatches_recompute_task_with_str_user_id(self):
        with patch("apps.funds.tasks.recompute_portfolio_snapshot.delay") as mock_delay:
            with self.captureOnCommitCallbacks(execute=True):
                Transaction.objects.create(
                    portfolio=self.portfolio,
                    fund=self.fund,
                    type=Transaction.Type.BUY,
                    units=Decimal("1.0000"),
                    price_per_unit=Decimal("100.0000"),
                )

        mock_delay.assert_called_once_with(str(self.portfolio.user_id))

    def test_broker_down_does_not_break_transaction_save(self):
        with patch(
            "apps.funds.tasks.recompute_portfolio_snapshot.delay",
            side_effect=OperationalError("broker unreachable"),
        ):
            with self.assertLogs("apps.funds.models", level="WARNING"):
                with self.captureOnCommitCallbacks(execute=True):
                    txn = Transaction.objects.create(
                        portfolio=self.portfolio,
                        fund=self.fund,
                        type=Transaction.Type.BUY,
                        units=Decimal("1.0000"),
                        price_per_unit=Decimal("100.0000"),
                    )

        self.assertTrue(Transaction.objects.filter(pk=txn.pk).exists())
        # The Holding still got its synchronous, non-broker-dependent update.
        self.assertTrue(Holding.objects.filter(portfolio=self.portfolio, fund=self.fund).exists())
