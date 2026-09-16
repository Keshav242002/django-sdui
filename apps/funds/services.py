"""
Business logic for the funds app.
"""

from apps.common.cache import cache_client, holdings_cache_key, portfolio_cache_key, widget_cache_key
from apps.funds.models import Fund, Holding, PortfolioSnapshot

# TTLs are placeholders until Phase 5's Celery beat takes over refresh
# responsibility (see master/phase-3-layout-caching/plan.md §2, §8).
TOP_MOVERS_TTL = 300  # 5 min
TRENDING_FUNDS_TTL = 900  # 15 min
PORTFOLIO_SUMMARY_TTL = 60
HOLDINGS_TTL = 60


def get_portfolio_summary(user_id: str) -> dict:
    """
    Read the latest PortfolioSnapshot for a user and return it as a dict.

    Cache-first: Redis (`portfolio:{user_id}:summary`, 60s TTL) then Postgres.
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


def get_holdings_data(user_id: str) -> list[dict]:
    """
    Return every Holding for a user's portfolio.

    Cache-first: Redis (`holdings:{user_id}:list`, 60s TTL) then Postgres.
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


def get_top_movers_data(limit: int = 10) -> list[dict]:
    """
    Return the top `limit` funds by one_day_change_pct.

    Cache-first: Redis (`widget:top_movers`, 5 min TTL) then Postgres.
    """
    cache_key = widget_cache_key("top_movers")
    cached = cache_client.get(cache_key)
    if cached is not None:
        return cached

    funds = Fund.objects.order_by("-one_day_change_pct")[:limit]
    data = [
        {
            "name": fund.name,
            "nav": fund.nav,
            "one_day_change_pct": fund.one_day_change_pct,
        }
        for fund in funds
    ]

    cache_client.set(cache_key, data, ttl=TOP_MOVERS_TTL)
    return data


def get_trending_funds_data(limit: int = 10) -> list[dict]:
    """
    Return up to `limit` funds flagged as trending.

    Cache-first: Redis (`widget:trending_funds`, 15 min TTL) then Postgres.
    """
    cache_key = widget_cache_key("trending_funds")
    cached = cache_client.get(cache_key)
    if cached is not None:
        return cached

    funds = Fund.objects.filter(is_trending=True)[:limit]
    data = [
        {
            "name": fund.name,
            "nav": fund.nav,
            "one_day_change_pct": fund.one_day_change_pct,
        }
        for fund in funds
    ]

    cache_client.set(cache_key, data, ttl=TRENDING_FUNDS_TTL)
    return data
