"""
Business logic for the funds app.
"""

from apps.funds.models import Fund, Holding, PortfolioSnapshot


def get_portfolio_summary(user_id: str) -> dict:
    """
    Read the latest PortfolioSnapshot for a user and return it as a dict.

    Phase 5 will add caching in front of this read.
    """
    snapshot = (
        PortfolioSnapshot.objects.filter(user_id=user_id).order_by("-computed_at").first()
    )
    if snapshot is None:
        return {}
    return {
        "user_id": str(snapshot.user_id),
        "total_value": snapshot.total_value,
        "total_invested": snapshot.total_invested,
        "pnl": snapshot.pnl,
        "pnl_percentage": snapshot.pnl_percentage,
        "computed_at": snapshot.computed_at,
    }


def get_holdings_data(user_id: str) -> list[dict]:
    """
    Return every Holding for a user's portfolio.

    Phase 5 will add caching in front of this read.
    """
    holdings = Holding.objects.filter(portfolio__user_id=user_id).select_related("fund")
    return [
        {
            "fund_name": holding.fund.name,
            "units": holding.units,
            "invested_amount": holding.invested_amount,
            "current_value": holding.current_value,
        }
        for holding in holdings
    ]


def get_top_movers_data(limit: int = 10) -> list[dict]:
    """
    Return the top `limit` funds by one_day_change_pct.

    Stub for Phase 1 — Phase 5 will fill in precomputation.
    """
    funds = Fund.objects.order_by("-one_day_change_pct")[:limit]
    return [
        {
            "name": fund.name,
            "nav": fund.nav,
            "one_day_change_pct": fund.one_day_change_pct,
        }
        for fund in funds
    ]


def get_trending_funds_data(limit: int = 10) -> list[dict]:
    """
    Return up to `limit` funds flagged as trending.

    Stub for Phase 1 — Phase 5 will fill in precomputation.
    """
    funds = Fund.objects.filter(is_trending=True)[:limit]
    return [
        {
            "name": fund.name,
            "nav": fund.nav,
            "one_day_change_pct": fund.one_day_change_pct,
        }
        for fund in funds
    ]
