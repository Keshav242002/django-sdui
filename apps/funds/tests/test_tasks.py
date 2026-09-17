import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.common.cache import cache_client, holdings_cache_key, portfolio_cache_key, widget_cache_key
from apps.funds.models import FailedTaskRecompute, Fund, Holding, Portfolio, PortfolioSnapshot
from apps.funds.services import (
    TOP_MOVERS_TTL,
    TRENDING_FUNDS_TTL,
    compute_portfolio_snapshot,
)
from django.conf import settings as django_settings

from apps.funds.tasks import (
    recompute_all_portfolio_snapshots,
    recompute_portfolio_snapshot,
    recompute_recommended_funds,
    recompute_top_movers,
    recompute_trending,
    retry_failed_portfolio_recomputes,
)
from apps.screens.tasks import warm_layout_cache

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


@override_settings(CACHES=TEST_CACHES)
class FundsTasksTestCase(TestCase):
    def setUp(self):
        cache.clear()


class TasksAreAcksLateTests(TestCase):
    """
    plan.md phase-9 Key Decision #7: every task in this project is an
    idempotent overwrite/append-only write, so a single global
    CELERY_TASK_ACKS_LATE = True (rather than acks_late=True sprinkled
    per-@shared_task) is correct -- redelivery after a worker crash
    mid-task is safe to allow rather than silently losing the task.
    """

    def test_celery_task_acks_late_setting_is_true(self):
        self.assertTrue(django_settings.CELERY_TASK_ACKS_LATE)

    def test_tasks_do_not_override_acks_late(self):
        tasks = [
            recompute_top_movers,
            recompute_trending,
            recompute_recommended_funds,
            recompute_portfolio_snapshot,
            recompute_all_portfolio_snapshots,
            retry_failed_portfolio_recomputes,
            warm_layout_cache,
        ]
        for task in tasks:
            with self.subTest(task=task.name):
                self.assertTrue(task.acks_late)


class RecomputeTopMoversTests(FundsTasksTestCase):
    def test_populates_cache_ordered_by_one_day_change_pct(self):
        Fund.objects.create(name="Low", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="0.50")
        Fund.objects.create(name="High", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="2.40")

        recompute_top_movers()

        cached = cache.get(widget_cache_key("top_movers"))
        self.assertEqual([f["name"] for f in cached], ["High", "Low"])

    def test_sets_expected_ttl(self):
        Fund.objects.create(name="High", category=Fund.Category.EQUITY, nav=100, one_day_change_pct="2.40")

        with patch.object(cache_client, "set", wraps=cache_client.set) as mock_set:
            recompute_top_movers()

        mock_set.assert_called_once()
        self.assertEqual(mock_set.call_args.kwargs["ttl"], TOP_MOVERS_TTL)


class RecomputeTrendingTests(FundsTasksTestCase):
    def test_populates_cache_only_trending_funds(self):
        Fund.objects.create(
            name="Trending", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1, is_trending=True
        )
        Fund.objects.create(
            name="NotTrending", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1, is_trending=False
        )

        recompute_trending()

        cached = cache.get(widget_cache_key("trending_funds"))
        self.assertEqual([f["name"] for f in cached], ["Trending"])

    def test_sets_expected_ttl(self):
        Fund.objects.create(
            name="Trending", category=Fund.Category.EQUITY, nav=100, one_day_change_pct=1, is_trending=True
        )

        with patch.object(cache_client, "set", wraps=cache_client.set) as mock_set:
            recompute_trending()

        mock_set.assert_called_once()
        self.assertEqual(mock_set.call_args.kwargs["ttl"], TRENDING_FUNDS_TTL)


class RecomputePortfolioSnapshotTaskTests(FundsTasksTestCase):
    def test_creates_snapshot_row_with_nav_resolved_totals(self):
        user_id = uuid.uuid4()
        portfolio = Portfolio.objects.create(user_id=user_id, total_value=0)
        fund_a = Fund.objects.create(
            name="A", category=Fund.Category.EQUITY, nav=Decimal("100.0000"), one_day_change_pct=1
        )
        fund_b = Fund.objects.create(
            name="B", category=Fund.Category.DEBT, nav=Decimal("50.0000"), one_day_change_pct=1
        )
        Holding.objects.create(
            portfolio=portfolio,
            fund=fund_a,
            units=Decimal("10.0000"),
            invested_amount=Decimal("900.00"),
            current_value=Decimal("950.00"),  # stale on purpose
        )
        Holding.objects.create(
            portfolio=portfolio,
            fund=fund_b,
            units=Decimal("4.0000"),
            invested_amount=Decimal("180.00"),
            current_value=Decimal("190.00"),  # stale on purpose
        )

        result = recompute_portfolio_snapshot(str(user_id))

        self.assertEqual(result, {"user_id": str(user_id), "created": True})
        snapshot = PortfolioSnapshot.objects.get(user_id=user_id)
        self.assertEqual(snapshot.total_value, Decimal("1200.00"))  # 10*100 + 4*50
        self.assertEqual(snapshot.total_invested, Decimal("1080.00"))
        self.assertEqual(snapshot.pnl, Decimal("120.00"))
        self.assertEqual(snapshot.pnl_percentage, Decimal("11.11"))

    def test_refreshes_denormalized_holding_and_portfolio_fields(self):
        user_id = uuid.uuid4()
        portfolio = Portfolio.objects.create(user_id=user_id, total_value=0)
        fund = Fund.objects.create(
            name="A", category=Fund.Category.EQUITY, nav=Decimal("120.0000"), one_day_change_pct=1
        )
        holding = Holding.objects.create(
            portfolio=portfolio,
            fund=fund,
            units=Decimal("5.0000"),
            invested_amount=Decimal("500.00"),
            current_value=Decimal("500.00"),  # stale, nav has since moved to 120
        )

        recompute_portfolio_snapshot(str(user_id))

        holding.refresh_from_db()
        portfolio.refresh_from_db()
        self.assertEqual(holding.current_value, Decimal("600.00"))  # 5 * 120
        self.assertEqual(portfolio.total_value, Decimal("600.00"))

    def test_invalidates_per_user_cache_keys(self):
        user_id = uuid.uuid4()
        Portfolio.objects.create(user_id=user_id, total_value=0)
        cache.set(portfolio_cache_key(str(user_id)), {"stale": True}, timeout=60)
        cache.set(holdings_cache_key(str(user_id)), [{"stale": True}], timeout=60)

        recompute_portfolio_snapshot(str(user_id))

        self.assertIsNone(cache.get(portfolio_cache_key(str(user_id))))
        self.assertIsNone(cache.get(holdings_cache_key(str(user_id))))

    def test_missing_portfolio_logs_warning_and_creates_no_row(self):
        user_id = uuid.uuid4()

        with self.assertLogs("apps.funds.services", level="WARNING"):
            result = recompute_portfolio_snapshot(str(user_id))

        self.assertEqual(result, {"user_id": str(user_id), "created": False})
        self.assertFalse(PortfolioSnapshot.objects.filter(user_id=user_id).exists())

    def test_zero_holdings_writes_all_zero_snapshot_without_error(self):
        user_id = uuid.uuid4()
        Portfolio.objects.create(user_id=user_id, total_value=0)

        recompute_portfolio_snapshot(str(user_id))

        snapshot = PortfolioSnapshot.objects.get(user_id=user_id)
        self.assertEqual(snapshot.total_value, Decimal("0"))
        self.assertEqual(snapshot.total_invested, Decimal("0"))
        self.assertEqual(snapshot.pnl, Decimal("0"))
        self.assertEqual(snapshot.pnl_percentage, Decimal("0.00"))


class RecomputeAllPortfolioSnapshotsTests(FundsTasksTestCase):
    def test_covers_every_portfolio(self):
        fund = Fund.objects.create(
            name="A", category=Fund.Category.EQUITY, nav=Decimal("10.0000"), one_day_change_pct=1
        )
        portfolios = []
        for _ in range(3):
            portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=0)
            Holding.objects.create(
                portfolio=portfolio,
                fund=fund,
                units=Decimal("1.0000"),
                invested_amount=Decimal("10.00"),
                current_value=Decimal("10.00"),
            )
            portfolios.append(portfolio)

        result = recompute_all_portfolio_snapshots()

        self.assertEqual(result, {"processed": 3, "failed": 0})
        for portfolio in portfolios:
            self.assertTrue(PortfolioSnapshot.objects.filter(user_id=portfolio.user_id).exists())

    def test_isolates_one_failing_user_and_continues(self):
        fund = Fund.objects.create(
            name="A", category=Fund.Category.EQUITY, nav=Decimal("10.0000"), one_day_change_pct=1
        )
        good_portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=0)
        bad_portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=0)
        for portfolio in (good_portfolio, bad_portfolio):
            Holding.objects.create(
                portfolio=portfolio,
                fund=fund,
                units=Decimal("1.0000"),
                invested_amount=Decimal("10.00"),
                current_value=Decimal("10.00"),
            )

        bad_user_id = str(bad_portfolio.user_id)

        def side_effect(user_id):
            if user_id == bad_user_id:
                raise ValueError("simulated failure")
            return compute_portfolio_snapshot(user_id)

        with patch("apps.funds.tasks.compute_portfolio_snapshot", side_effect=side_effect):
            with self.assertLogs("apps.funds.tasks", level="WARNING"):
                result = recompute_all_portfolio_snapshots()

        self.assertEqual(result, {"processed": 1, "failed": 1})
        self.assertTrue(PortfolioSnapshot.objects.filter(user_id=good_portfolio.user_id).exists())
        self.assertFalse(PortfolioSnapshot.objects.filter(user_id=bad_portfolio.user_id).exists())

    def test_writes_dlq_row_for_failing_user(self):
        fund = Fund.objects.create(
            name="A", category=Fund.Category.EQUITY, nav=Decimal("10.0000"), one_day_change_pct=1
        )
        bad_portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=0)
        Holding.objects.create(
            portfolio=bad_portfolio,
            fund=fund,
            units=Decimal("1.0000"),
            invested_amount=Decimal("10.00"),
            current_value=Decimal("10.00"),
        )
        bad_user_id = str(bad_portfolio.user_id)

        def side_effect(user_id):
            if user_id == bad_user_id:
                raise ValueError("simulated failure")
            return compute_portfolio_snapshot(user_id)

        with patch("apps.funds.tasks.compute_portfolio_snapshot", side_effect=side_effect):
            with self.assertLogs("apps.funds.tasks", level="WARNING"):
                recompute_all_portfolio_snapshots()

        dlq_row = FailedTaskRecompute.objects.get(user_id=bad_portfolio.user_id)
        self.assertEqual(dlq_row.status, FailedTaskRecompute.Status.FAILED)
        self.assertEqual(dlq_row.attempts, 0)
        self.assertIsNone(dlq_row.resolved_at)
        self.assertIn("ValueError", dlq_row.error)
        self.assertIn("simulated failure", dlq_row.error)


class RetryFailedPortfolioRecomputesTests(FundsTasksTestCase):
    def _make_dlq_row(self, user_id=None, attempts=0):
        return FailedTaskRecompute.objects.create(
            user_id=user_id or uuid.uuid4(),
            error="ValueError: simulated failure",
            attempts=attempts,
        )

    def test_recovers_row_when_portfolio_now_computes_cleanly(self):
        fund = Fund.objects.create(
            name="A", category=Fund.Category.EQUITY, nav=Decimal("10.0000"), one_day_change_pct=1
        )
        portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=0)
        Holding.objects.create(
            portfolio=portfolio,
            fund=fund,
            units=Decimal("1.0000"),
            invested_amount=Decimal("10.00"),
            current_value=Decimal("10.00"),
        )
        dlq_row = self._make_dlq_row(user_id=portfolio.user_id)

        result = retry_failed_portfolio_recomputes()

        dlq_row.refresh_from_db()
        self.assertEqual(result, {"recovered": 1, "exhausted": 0, "still_failing": 0})
        self.assertEqual(dlq_row.status, FailedTaskRecompute.Status.RECOVERED)
        self.assertEqual(dlq_row.attempts, 1)
        self.assertIsNotNone(dlq_row.resolved_at)
        self.assertTrue(PortfolioSnapshot.objects.filter(user_id=portfolio.user_id).exists())

    def test_still_failing_row_stays_failed_and_increments_attempts(self):
        # No Portfolio row exists for this user_id, so compute_portfolio_snapshot
        # logs a warning and returns None without raising -- retry_failed_
        # portfolio_recomputes treats that the same as a hard failure only if
        # the underlying call raises, so patch it to simulate a real exception.
        dlq_row = self._make_dlq_row(attempts=1)

        with patch("apps.funds.tasks.compute_portfolio_snapshot", side_effect=ValueError("still broken")):
            with self.assertLogs("apps.funds.tasks", level="WARNING"):
                result = retry_failed_portfolio_recomputes()

        dlq_row.refresh_from_db()
        self.assertEqual(result, {"recovered": 0, "exhausted": 0, "still_failing": 1})
        self.assertEqual(dlq_row.status, FailedTaskRecompute.Status.FAILED)
        self.assertEqual(dlq_row.attempts, 2)
        self.assertIsNone(dlq_row.resolved_at)

    def test_exhausts_row_after_max_retry_attempts(self):
        dlq_row = self._make_dlq_row(attempts=FailedTaskRecompute.MAX_RETRY_ATTEMPTS)

        result = retry_failed_portfolio_recomputes()

        dlq_row.refresh_from_db()
        self.assertEqual(result, {"recovered": 0, "exhausted": 1, "still_failing": 0})
        self.assertEqual(dlq_row.status, FailedTaskRecompute.Status.EXHAUSTED)
        self.assertEqual(dlq_row.attempts, FailedTaskRecompute.MAX_RETRY_ATTEMPTS + 1)
        self.assertIsNotNone(dlq_row.resolved_at)

    def test_ignores_rows_not_in_failed_status(self):
        recovered_row = self._make_dlq_row(attempts=1)
        recovered_row.status = FailedTaskRecompute.Status.RECOVERED
        recovered_row.save(update_fields=["status"])

        result = retry_failed_portfolio_recomputes()

        recovered_row.refresh_from_db()
        self.assertEqual(result, {"recovered": 0, "exhausted": 0, "still_failing": 0})
        self.assertEqual(recovered_row.attempts, 1)

    def test_processes_multiple_rows_independently(self):
        fund = Fund.objects.create(
            name="A", category=Fund.Category.EQUITY, nav=Decimal("10.0000"), one_day_change_pct=1
        )
        good_portfolio = Portfolio.objects.create(user_id=uuid.uuid4(), total_value=0)
        Holding.objects.create(
            portfolio=good_portfolio,
            fund=fund,
            units=Decimal("1.0000"),
            invested_amount=Decimal("10.00"),
            current_value=Decimal("10.00"),
        )
        good_row = self._make_dlq_row(user_id=good_portfolio.user_id)
        exhausted_row = self._make_dlq_row(attempts=FailedTaskRecompute.MAX_RETRY_ATTEMPTS)

        result = retry_failed_portfolio_recomputes()

        good_row.refresh_from_db()
        exhausted_row.refresh_from_db()
        self.assertEqual(result, {"recovered": 1, "exhausted": 1, "still_failing": 0})
        self.assertEqual(good_row.status, FailedTaskRecompute.Status.RECOVERED)
        self.assertEqual(exhausted_row.status, FailedTaskRecompute.Status.EXHAUSTED)
