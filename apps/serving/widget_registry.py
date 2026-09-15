"""
Single source of truth for widget routing.

Both the aggregator (ScreenView -> assemble_screen) and the standalone
WidgetView import WIDGET_HANDLERS from here so a widget's fetch logic is
never duplicated between the two call paths (PRD §12A, rules.md §2).

Every handler in this dict is called as `handler(user_id)`. The two global
(non-personalized) widgets' underlying service functions take `limit`, not
`user_id` -- they are wrapped below so the call site stays uniform without
changing their natural signatures.
"""

from apps.funds.services import (
    get_holdings_data,
    get_portfolio_summary,
    get_top_movers_data,
    get_trending_funds_data,
)


def _top_movers_handler(user_id):
    return get_top_movers_data()


def _trending_funds_handler(user_id):
    return get_trending_funds_data()


# Maps widget_type.key -> handler(user_id).
# Add a new widget here and both the aggregator and standalone endpoint pick it up automatically.
WIDGET_HANDLERS = {
    "portfolio_summary": get_portfolio_summary,
    "holdings_list": get_holdings_data,
    "horizontal_carousel": _top_movers_handler,
    "grid": _trending_funds_handler,
}
