"""
Business logic for the funds app.
"""

from apps.funds.models import PortfolioSnapshot


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


def get_top_movers_data(limit: int = 10) -> list[dict]:
    """
    Return the top `limit` funds by one_day_change_pct.

    Stub for Phase 1 — Phase 5 will fill in precomputation.
    """
    return []
