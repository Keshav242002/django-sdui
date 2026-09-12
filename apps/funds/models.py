import logging

from django.db import models
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
    """TODO: trigger portfolio recompute (Phase 5 — Celery task body)."""
    if created:
        logger.warning(
            "TODO: trigger portfolio recompute for portfolio_id=%s (transaction_id=%s)",
            instance.portfolio_id,
            instance.pk,
        )


class PortfolioSnapshot(models.Model):
    user_id = models.UUIDField(db_index=True)
    total_value = models.DecimalField(max_digits=14, decimal_places=2)
    total_invested = models.DecimalField(max_digits=14, decimal_places=2)
    pnl = models.DecimalField(max_digits=14, decimal_places=2)
    pnl_percentage = models.DecimalField(max_digits=6, decimal_places=2)
    computed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user_id} @ {self.computed_at}"
