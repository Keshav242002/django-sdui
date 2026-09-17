"""
Business logic for the funds app.
"""

import logging
from decimal import Decimal

from apps.common.cache import cache_client, holdings_cache_key, portfolio_cache_key, widget_cache_key
from apps.funds.models import Fund, Holding, Portfolio, PortfolioSnapshot, Transaction

logger = logging.getLogger(__name__)

# Beat refreshes these on a schedule (config.settings.CELERY_BEAT_SCHEDULE:
# recompute_top_movers every 5 min, recompute_trending every 15 min) -- the
# TTL here is a safety net, not the primary freshness mechanism. It's 2x the
# beat interval so a healthy beat keeps the key alive indefinitely (refreshed
# at half its lifetime), but a dead beat lets the key expire into the
# Postgres fallback within two missed cycles instead of serving frozen data
# forever (plan.md Key Decisions §8).
TOP_MOVERS_TTL = 600  # 2x the 5 min beat schedule
TRENDING_FUNDS_TTL = 1800  # 2x the 15 min beat schedule
PORTFOLIO_SUMMARY_TTL = 60
HOLDINGS_TTL = 60
# 2x the 15 min recompute_recommended_funds beat schedule -- same
# half-lifetime-refresh reasoning as TRENDING_FUNDS_TTL (Phase 8 plan.md
# Key Decision #1).
RECOMMENDED_FUNDS_TTL = 1800
# Not precomputed, unlike the widgets above -- a single indexed-PK read is
# not the "expensive computation" PRD §9A guards against. 60s matches
# PORTFOLIO_SUMMARY_TTL/HOLDINGS_TTL: Fund.nav changes at most once daily,
# but a fund detail page may be hit repeatedly in one browsing session, so
# a short TTL absorbs that repeat traffic (Phase 8 plan.md Key Decision #4).
FUND_OVERVIEW_TTL = 60


def _quantize_money(value: Decimal) -> Decimal:
    """Round a Decimal to 2 decimal places for storage in a money field."""
    return value.quantize(Decimal("0.01"))


def get_portfolio_summary(user_id: str, fund_id: str | None = None) -> dict:
    """
    Read the latest PortfolioSnapshot for a user and return it as a dict.

    Cache-first: Redis (`portfolio:{user_id}:summary`, 60s TTL) then Postgres.
    Never recomputes here -- the snapshot is written by
    compute_portfolio_snapshot() (Celery task, Phase 5 / PRD §9A).

    `fund_id` is accepted (and ignored) so this function keeps the uniform
    `handler(user_id, fund_id=None)` contract every WIDGET_HANDLERS entry
    now shares (Phase 8 plan.md Key Decision #2) -- this widget has no use
    for it.
    """
    cache_key = portfolio_cache_key(user_id)
    cached = cache_client.get(cache_key)
    if cached is not None:
        return cached

    snapshot = (
        PortfolioSnapshot.objects.filter(user_id=user_id).order_by("-computed_at").first()
    )
    if snapshot is None:
        data = {}
    else:
        data = {
            "user_id": str(snapshot.user_id),
            "total_value": snapshot.total_value,
            "total_invested": snapshot.total_invested,
            "pnl": snapshot.pnl,
            "pnl_percentage": snapshot.pnl_percentage,
            "computed_at": snapshot.computed_at,
        }

    cache_client.set(cache_key, data, ttl=PORTFOLIO_SUMMARY_TTL)
    return data


def get_holdings_data(user_id: str, fund_id: str | None = None) -> list[dict]:
    """
    Return every Holding for a user's portfolio.

    Cache-first: Redis (`holdings:{user_id}:list`, 60s TTL) then Postgres.

    `fund_id` is accepted (and ignored) -- see get_portfolio_summary()'s
    docstring; same uniform handler contract, unused here.
    """
    cache_key = holdings_cache_key(user_id)
    cached = cache_client.get(cache_key)
    if cached is not None:
        return cached

    holdings = Holding.objects.filter(portfolio__user_id=user_id).select_related("fund")
    data = [
        {
            "fund_name": holding.fund.name,
            "units": holding.units,
            "invested_amount": holding.invested_amount,
            "current_value": holding.current_value,
        }
        for holding in holdings
    ]

    cache_client.set(cache_key, data, ttl=HOLDINGS_TTL)
    return data


def _serialize_fund_rows(funds) -> list[dict]:
    """
    Shared `{name, nav, one_day_change_pct}` row shape for the top-movers
    and trending widgets. Used by both the read path below and the Celery
    tasks that precompute these widgets (apps/funds/tasks.py), so the two
    can never drift apart (rules.md §2).
    """
    return [
        {
            "name": fund.name,
            "nav": fund.nav,
            "one_day_change_pct": fund.one_day_change_pct,
        }
        for fund in funds
    ]


def get_top_movers_data(limit: int = 10) -> list[dict]:
    """
    Return the top `limit` funds by one_day_change_pct.

    Cache-first: Redis (`widget:top_movers`, 10 min TTL) then Postgres.
    """
    cache_key = widget_cache_key("top_movers")
    cached = cache_client.get(cache_key)
    if cached is not None:
        return cached

    funds = Fund.objects.order_by("-one_day_change_pct")[:limit]
    data = _serialize_fund_rows(funds)

    cache_client.set(cache_key, data, ttl=TOP_MOVERS_TTL)
    return data


def get_trending_funds_data(limit: int = 10) -> list[dict]:
    """
    Return up to `limit` funds flagged as trending.

    Cache-first: Redis (`widget:trending_funds`, 30 min TTL) then Postgres.
    """
    cache_key = widget_cache_key("trending_funds")
    cached = cache_client.get(cache_key)
    if cached is not None:
        return cached

    funds = Fund.objects.filter(is_trending=True)[:limit]
    data = _serialize_fund_rows(funds)

    cache_client.set(cache_key, data, ttl=TRENDING_FUNDS_TTL)
    return data


def get_fund_overview_data(user_id: str, fund_id: str | None = None) -> dict:
    """
    Return one Fund's overview (name, category, nav, one_day_change_pct).

    Cache-first: Redis (`fund_overview:{fund_id}`, 60s TTL) then a single
    indexed-PK Postgres read. Returns {} (not an error) when fund_id is
    falsy or the fund doesn't exist -- same "no data, not a failure"
    convention as get_portfolio_summary() (Phase 8 plan.md Key Decision #4).

    `user_id` is accepted (and ignored) to keep the uniform
    `handler(user_id, fund_id=None)` contract -- this widget has no use
    for it.
    """
    if not fund_id:
        return {}

    cache_key = f"fund_overview:{fund_id}"
    cached = cache_client.get(cache_key)
    if cached is not None:
        return cached

    fund = Fund.objects.filter(pk=fund_id).first()
    if fund is None:
        return {}

    data = {
        "name": fund.name,
        "category": fund.category,
        "nav": fund.nav,
        "one_day_change_pct": fund.one_day_change_pct,
    }

    cache_client.set(cache_key, data, ttl=FUND_OVERVIEW_TTL)
    return data


def _serialize_recommendable_fund_rows(funds) -> list[dict]:
    """
    Like _serialize_fund_rows(), plus `id` -- the recommended-funds pool
    needs a real, unique key to exclude held funds by (Phase 8 plan.md Key
    Decision #1). Fund.name has no uniqueness constraint, so matching by
    name the way _serialize_fund_rows()'s shape would invite would be
    unreliable; `id` is the PK. Kept as its own function rather than
    changing _serialize_fund_rows() itself, since that shape is also the
    top-movers/trending API response shape and isn't part of this phase's
    scope to change.
    """
    return [
        {
            "id": fund.id,
            "name": fund.name,
            "nav": fund.nav,
            "one_day_change_pct": fund.one_day_change_pct,
        }
        for fund in funds
    ]


def get_recommended_funds_data(user_id: str, fund_id: str | None = None) -> list[dict]:
    """
    Return a ranked pool of recommended funds, excluding funds the
    requesting user already holds.

    Cache-first for the pool: Redis (`widget:recommended_funds`, 30 min
    TTL) then Postgres, same pattern as get_top_movers_data(). The
    exclusion is one bounded query against the user's Holding rows (same
    shape as get_holdings_data()'s filter) -- not one query per fund in
    the pool (Phase 8 plan.md Key Decision #1).

    `fund_id` is accepted (and ignored) -- this widget is not scoped to a
    single fund, but shares the uniform handler contract.
    """
    cache_key = widget_cache_key("recommended_funds")
    pool = cache_client.get(cache_key)
    if pool is None:
        funds = Fund.objects.order_by("-one_day_change_pct")[:10]
        pool = _serialize_recommendable_fund_rows(funds)
        cache_client.set(cache_key, pool, ttl=RECOMMENDED_FUNDS_TTL)

    held_fund_ids = set(
        Holding.objects.filter(portfolio__user_id=user_id).values_list("fund_id", flat=True)
    )
    return [fund for fund in pool if fund["id"] not in held_fund_ids]


def apply_transaction_to_holding(transaction: Transaction) -> None:
    """
    Apply one BUY/SELL Transaction to the Holding write model.

    This is the command side of the PRD §9A CQRS split -- called
    synchronously, inside the same DB transaction as the Transaction
    insert (see apps.funds.models.on_transaction_saved), so the write
    model is never transiently wrong. The async side
    (recompute_portfolio_snapshot) rebuilds the read model afterwards.

    BUY: adds units and invested_amount, using this transaction's own
    price_per_unit as the cost basis for the units bought.

    SELL: subtracts units and a proportional share of the existing cost
    basis, deleting the Holding once units reach zero. A sell for more
    units than are currently held is clamped to the held amount and
    logged as a WARNING rather than raised -- a signal handler is the
    wrong place to reject bad input, and this project has no validation
    layer in front of the admin.

    Also refreshes Holding.current_value from the fund's current NAV so
    it's reasonable immediately, ahead of the async recompute which is
    the authoritative source (plan.md Key Decisions §4).
    """
    holding, _created = Holding.objects.get_or_create(
        portfolio=transaction.portfolio,
        fund=transaction.fund,
        defaults={
            "units": Decimal("0"),
            "invested_amount": Decimal("0"),
            "current_value": Decimal("0"),
        },
    )

    if transaction.type == Transaction.Type.BUY:
        holding.units += transaction.units
        holding.invested_amount += _quantize_money(transaction.units * transaction.price_per_unit)
        holding.current_value = _quantize_money(holding.units * transaction.fund.nav)
        holding.save(update_fields=["units", "invested_amount", "current_value"])
        return

    # SELL
    if transaction.units > holding.units:
        logger.warning(
            "Sell of %s units exceeds held %s units for portfolio_id=%s fund_id=%s; clamping to held amount",
            transaction.units,
            holding.units,
            transaction.portfolio_id,
            transaction.fund_id,
        )
        sell_units = holding.units
    else:
        sell_units = transaction.units

    cost_basis_fraction = (sell_units / holding.units) if holding.units > 0 else Decimal("0")
    invested_reduction = _quantize_money(holding.invested_amount * cost_basis_fraction)

    holding.units -= sell_units
    holding.invested_amount -= invested_reduction

    if holding.units <= 0:
        holding.delete()
    else:
        holding.current_value = _quantize_money(holding.units * transaction.fund.nav)
        holding.save(update_fields=["units", "invested_amount", "current_value"])


def compute_portfolio_snapshot(user_id: str) -> PortfolioSnapshot | None:
    """
    Recompute one user's portfolio value and persist it as a new
    PortfolioSnapshot row -- the query side of the PRD §9A CQRS split.

    Resolves NAV per fund at compute time (total_value = Σ units x
    Fund.nav) rather than summing the stored Holding.current_value
    column, so a Fund.nav change actually changes the result -- this is
    what makes the daily recompute_all_portfolio_snapshots batch job
    meaningful (plan.md Key Decisions §4). Also refreshes the
    denormalized Holding.current_value and Portfolio.total_value fields
    so the holdings widget can't disagree with the summary widget.

    Drops the two per-user cache keys rather than rewriting them --
    get_portfolio_summary()/get_holdings_data() own that dict shape in
    exactly one place; the next read repopulates from Postgres with the
    fresh snapshot (plan.md Key Decisions §9).

    Returns None (logging a WARNING) if the user has no Portfolio at
    all. A Portfolio with zero holdings still writes an all-zero
    snapshot, so get_portfolio_summary() returns a real zeroed summary
    instead of {}.
    """
    try:
        portfolio = Portfolio.objects.get(user_id=user_id)
    except Portfolio.DoesNotExist:
        logger.warning("No Portfolio found for user_id=%s; skipping snapshot recompute", user_id)
        return None

    holdings = list(portfolio.holdings.select_related("fund"))

    total_invested = Decimal("0")
    total_value = Decimal("0")
    for holding in holdings:
        current_value = _quantize_money(holding.units * holding.fund.nav)
        if current_value != holding.current_value:
            holding.current_value = current_value
            holding.save(update_fields=["current_value"])
        total_invested += holding.invested_amount
        total_value += current_value

    pnl = total_value - total_invested
    if total_invested > 0:
        pnl_percentage = (pnl / total_invested * 100).quantize(Decimal("0.01"))
    else:
        pnl_percentage = Decimal("0.00")

    portfolio.total_value = total_value
    portfolio.save(update_fields=["total_value"])

    snapshot = PortfolioSnapshot.objects.create(
        user_id=user_id,
        total_value=total_value,
        total_invested=total_invested,
        pnl=pnl,
        pnl_percentage=pnl_percentage,
    )

    cache_client.delete(portfolio_cache_key(str(user_id)))
    cache_client.delete(holdings_cache_key(str(user_id)))

    logger.info(
        "Recomputed portfolio snapshot for user_id=%s: total_value=%s total_invested=%s pnl=%s",
        user_id,
        total_value,
        total_invested,
        pnl,
    )
    return snapshot
