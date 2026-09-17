/**
 * Client-bundled default layouts (PRD §12A fallback tier 5, plan.md
 * phase-9 Key Decision #6): "Client's bundled default layout (shipped
 * inside the app itself, always available, structure-only, no live data)."
 *
 * Structure-only -- widget_type/title/order/config, deliberately no `data`
 * key at all. A real mobile app would compile this in at build time; this
 * project has no build step (Phase 6 Key Decision #9), so a checked-in JS
 * literal is the direct equivalent.
 *
 * One entry per screen this project actually has. A screen_key with no
 * entry here is a real, expected case -- see client_demo.js's explicit
 * guard, not an oversight (a missing-entry crash was caught and fixed
 * during this phase's plan review).
 */
window.SDUI_BUNDLED_LAYOUTS = {
    mf_dashboard: {
        sections: [
            { widget_type: "portfolio_summary", title: "Your Portfolio", order: 1, config: {} },
            { widget_type: "holdings_list", title: "Your Holdings", order: 2, config: {} },
            { widget_type: "horizontal_carousel", title: "Top Movers", order: 3, config: {} },
            { widget_type: "grid", title: "Trending Funds", order: 4, config: {} },
        ],
    },
    fund_detail: {
        sections: [
            { widget_type: "fund_overview", title: "Fund Overview", order: 1, config: {} },
            { widget_type: "recommended_funds", title: "Recommended Funds", order: 2, config: {} },
        ],
    },
};
