/**
 * Shared widget-render registry (plan.md phase-9 Key Decision #4).
 *
 * Pure `section -> DOM node` logic, extracted from the admin preview's
 * former preview_renderer.js so both the admin preview
 * (apps/screens/static/screens/preview_renderer.js) and the public client
 * demo (apps/serving/static/serving/client_demo.js) render sections
 * identically without duplicating ~150 lines of DOM-building code
 * (rules.md §2). No fetch, no phone-frame assumptions, no knowledge of how
 * `section.data` arrived (server-injected JSON for the preview, a resolved
 * fetch() Promise for the client demo) -- callers own that.
 *
 * Exposes window.SDUIWidgetRenderers.renderSection(section).
 */
(function () {
    "use strict";

    // Fixed, hardcoded per-widget-type accent palette for the admin preview
    // only -- NOT server-configurable. Coloring/theming is not sent by the
    // API (brand theme is owned by the client's fixed design system, the
    // same split real production SDUI systems use); this map exists purely
    // so the internal admin preview is visually easy to scan, and its
    // values are a plain developer choice, not admin-authored data.
    var WIDGET_ACCENTS = {
        portfolio_summary: "#00D09C",
        holdings_list: "#0A5C36",
        horizontal_carousel: "#F59E0B",
        grid: "#3B82F6",
        fund_overview: "#10B981",
        recommended_funds: "#8B5CF6",
    };
    var DEFAULT_ACCENT = "#9CA3AF";

    function accentFor(widgetType) {
        return WIDGET_ACCENTS[widgetType] || DEFAULT_ACCENT;
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        // textContent, never innerHTML: badge_text and other admin-authored
        // strings render as literal text, never parsed as markup.
        if (text !== undefined) node.textContent = text;
        return node;
    }

    // Applies the fixed per-widget-type accent (left border + badge fill,
    // if `badgeText` -- admin-authored content, e.g. "NEW" -- is present)
    // to a widget card. The accent color itself is never read from
    // section.config; only badgeText is admin data.
    function card(title, widgetType, badgeText) {
        var wrapper = el("div", "widget-card");
        var accent = accentFor(widgetType);
        wrapper.style.borderLeftColor = accent;

        if (title) {
            var heading = el("h3", null, title);
            if (badgeText) {
                var badge = el("span", "badge", badgeText);
                badge.style.background = accent;
                heading.appendChild(badge);
            }
            wrapper.appendChild(heading);
        }
        return wrapper;
    }

    function emptyLine(message) {
        return el("div", "empty", message);
    }

    // A section's data is either the widget's real payload, or one of the
    // bulkhead/placeholder sentinels fetch_section_data() can return
    // (apps/serving/services.py::fetch_section_data) -- same shape whether
    // the caller is the admin preview or the public client demo.
    function statusMessage(data) {
        if (data && data.status === "no_user_selected") {
            return "No user selected — pass ?user_id=... to see personalized data.";
        }
        if (data && data.status === "unavailable") {
            return "Data unavailable (" + (data.error_code || "unknown error") + ").";
        }
        return null;
    }

    function badgeTextFor(section) {
        return (section.config && section.config.badge_text) || null;
    }

    function renderPortfolioSummary(section) {
        var wrapper = card(section.title || "Portfolio Summary", section.widget_type, badgeTextFor(section));
        var data = section.data;
        var status = statusMessage(data);
        if (status) {
            wrapper.appendChild(emptyLine(status));
            return wrapper;
        }
        if (!data || Object.keys(data).length === 0) {
            wrapper.appendChild(emptyLine("No portfolio data for this user."));
            return wrapper;
        }
        var rows = [
            ["Total Value", data.total_value],
            ["Invested", data.total_invested],
            ["P&L", data.pnl],
            ["P&L %", data.pnl_percentage],
        ];
        rows.forEach(function (row) {
            var line = el("div", "holding-row");
            line.appendChild(el("span", null, row[0]));
            line.appendChild(el("span", null, String(row[1])));
            wrapper.appendChild(line);
        });
        return wrapper;
    }

    function renderHoldingsList(section) {
        var wrapper = card(section.title || "Holdings", section.widget_type, badgeTextFor(section));
        var data = section.data;
        var status = statusMessage(data);
        if (status) {
            wrapper.appendChild(emptyLine(status));
            return wrapper;
        }
        if (!Array.isArray(data) || data.length === 0) {
            wrapper.appendChild(emptyLine("No holdings for this user."));
            return wrapper;
        }
        data.forEach(function (holding) {
            var row = el("div", "holding-row");
            row.appendChild(el("span", null, holding.fund_name));
            row.appendChild(el("span", null, holding.units + " units · " + holding.current_value));
            wrapper.appendChild(row);
        });
        return wrapper;
    }

    function renderFundList(section, emptyMessage) {
        var wrapper = card(section.title, section.widget_type, badgeTextFor(section));
        var data = section.data;
        var status = statusMessage(data);
        if (status) {
            wrapper.appendChild(emptyLine(status));
            return wrapper;
        }
        if (!Array.isArray(data) || data.length === 0) {
            wrapper.appendChild(emptyLine(emptyMessage));
            return wrapper;
        }
        data.forEach(function (fund) {
            var row = el("div", "fund-row");
            row.appendChild(el("span", null, fund.name));
            row.appendChild(el("span", null, "NAV " + fund.nav + " (" + fund.one_day_change_pct + "%)"));
            wrapper.appendChild(row);
        });
        return wrapper;
    }

    function renderFundOverview(section) {
        var wrapper = card(section.title || "Fund Overview", section.widget_type, badgeTextFor(section));
        var data = section.data;
        var status = statusMessage(data);
        if (status) {
            wrapper.appendChild(emptyLine(status));
            return wrapper;
        }
        if (!data || Object.keys(data).length === 0) {
            wrapper.appendChild(emptyLine("No fund selected — pass ?fund_id=... to see fund details."));
            return wrapper;
        }
        var rows = [
            ["Name", data.name],
            ["Category", data.category],
            ["NAV", data.nav],
            ["1-Day Change", data.one_day_change_pct + "%"],
        ];
        rows.forEach(function (row) {
            var line = el("div", "holding-row");
            line.appendChild(el("span", null, row[0]));
            line.appendChild(el("span", null, String(row[1])));
            wrapper.appendChild(line);
        });
        return wrapper;
    }

    function renderRecommendedFunds(section) {
        return renderFundList(section, "No recommendations available.");
    }

    var WIDGET_RENDERERS = {
        portfolio_summary: renderPortfolioSummary,
        holdings_list: renderHoldingsList,
        horizontal_carousel: function (section) {
            return renderFundList(section, "No trending movers available.");
        },
        grid: function (section) {
            return renderFundList(section, "No trending funds available.");
        },
        fund_overview: renderFundOverview,
        recommended_funds: renderRecommendedFunds,
    };

    function renderUnknown(section) {
        var wrapper = card(section.title || "Unknown widget", section.widget_type, badgeTextFor(section));
        var badge = el("span", "unknown-badge", section.widget_type);
        wrapper.appendChild(badge);
        return wrapper;
    }

    function renderSection(section) {
        var renderer = WIDGET_RENDERERS[section.widget_type];
        return renderer ? renderer(section) : renderUnknown(section);
    }

    window.SDUIWidgetRenderers = {
        renderSection: renderSection,
    };
})();
