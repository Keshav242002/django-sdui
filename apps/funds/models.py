import logging

from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


class Fund(models.Model):
    class Category(models.TextChoices):
        EQUITY = "equity", "Equity"
        DEBT = "debt", "Debt"
        HYBRID = "hybrid", "Hybrid"

    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=Category.choices)
    nav = models.DecimalField(max_digits=12, decimal_places=4)
    one_day_change_pct = models.DecimalField(max_digits=6, decimal_places=2)
    is_trending = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Portfolio(models.Model):
    """
    No auth FK — user_id is a non-guessable UUID identifier.
    Auth is out of scope per PRD §16.
    """

    user_id = models.UUIDField(db_index=True)
    total_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.user_id)


class Holding(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="holdings")
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="holdings")
    units = models.DecimalField(max_digits=14, decimal_places=4)
    invested_amount = models.DecimalField(max_digits=14, decimal_places=2)
    current_value = models.DecimalField(max_digits=14, decimal_places=2)

    def __str__(self):
        return f"{self.portfolio.user_id} - {self.fund.name}"


class Transaction(models.Model):
    class Type(models.TextChoices):
        BUY = "buy", "Buy"
        SELL = "sell", "Sell"

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="transactions")
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="transactions")
    type = models.CharField(max_length=10, choices=Type.choices)
    units = models.DecimalField(max_digits=14, decimal_places=4)
    price_per_unit = models.DecimalField(max_digits=12, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.type} {self.units} {self.fund.name}"


@receiver(post_save, sender=Transaction)
def on_transaction_saved(sender, instance, created, **kwargs):
    """
    Command side (sync) + query side (async) of the PRD §9A CQRS split.

    apply_transaction_to_holding() runs immediately, inside this same DB
    transaction, so the Holding write model is never transiently wrong.
    recompute_portfolio_snapshot is dispatched only after that transaction
    commits (django.db.transaction.on_commit) -- dispatching eagerly here
    would let a worker read the DB before this Transaction/Holding are
    actually visible (plan.md Key Decisions §6).

    Imports are function-local: apps.funds.services and apps.funds.tasks
    both import apps.funds.models at module load time, so a top-level
    import here would be circular.
    """
    if not created:
        return

    from apps.funds.services import apply_transaction_to_holding

    apply_transaction_to_holding(instance)

    user_id = str(instance.portfolio.user_id)

    def _dispatch_recompute():
        from kombu.exceptions import OperationalError

        from apps.funds.tasks import recompute_portfolio_snapshot

        try:
            recompute_portfolio_snapshot.delay(user_id)
        except OperationalError:
            logger.warning(
                "Celery broker unreachable; portfolio snapshot for user_id=%s not "
                "recomputed now -- will self-heal on the next daily batch run",
                user_id,
            )

    transaction.on_commit(_dispatch_recompute)


class PortfolioSnapshot(models.Model):
    user_id = models.UUIDField(db_index=True)
    total_value = models.DecimalField(max_digits=14, decimal_places=2)
    total_invested = models.DecimalField(max_digits=14, decimal_places=2)
    pnl = models.DecimalField(max_digits=14, decimal_places=2)
    pnl_percentage = models.DecimalField(max_digits=6, decimal_places=2)
    computed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user_id} @ {self.computed_at}"


class FailedTaskRecompute(models.Model):
    """
    Database-backed Dead Letter Queue (DLQ) for the nightly portfolio
    snapshot batch job (apps.funds.tasks.recompute_all_portfolio_snapshots).

    When compute_portfolio_snapshot(user_id) raises inside the per-user
    loop, the exception is persisted here in addition to being logged.
    A separate beat task (retry_failed_portfolio_recomputes, every 15 min)
    picks up FAILED rows and retries them automatically, so a user whose
    snapshot failed at 01:30 UTC is self-healed within 15-45 minutes
    without any engineer intervention.

    Status lifecycle:
        FAILED     -> initial state on first failure
        RECOVERED  -> retry succeeded; resolved_at is set
        EXHAUSTED  -> max_attempts reached; needs manual investigation
    """

    class Status(models.TextChoices):
        FAILED = "failed", "Failed"
        RECOVERED = "recovered", "Recovered"
        EXHAUSTED = "exhausted", "Exhausted (max retries reached)"

    MAX_RETRY_ATTEMPTS = 3

    user_id = models.UUIDField(db_index=True)
    error = models.TextField(help_text="Full exception message from the failed compute call.")
    failed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.FAILED,
        db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of retry attempts made by retry_failed_portfolio_recomputes.",
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when status transitions to RECOVERED or EXHAUSTED.",
    )

    class Meta:
        ordering = ["-failed_at"]
        verbose_name = "Failed Recompute (DLQ)"
        verbose_name_plural = "Failed Recomputes (DLQ)"

    def __str__(self):
        return f"[{self.status}] user_id={self.user_id} failed_at={self.failed_at}"
