/**
 * Mock mobile client renderer for the admin preview (PRD §11.4).
 *
 * Not a real client: no data fetching, no API calls -- the layout JSON is
 * injected server-side into a <script type="application/json"> tag (not
 * assigned as a JS object literal -- browsers and editor tooling never try
 * to parse a non-JS-typed script tag's contents, which also sidesteps
 * template-delimiter confusion in JS-aware editors) and rendered
 * identically into both phone frames, since the JSON is platform-agnostic.
 */
(function () {
    "use strict";

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function card(title) {
        var wrapper = el("div", "widget-card");
        if (title) wrapper.appendChild(el("h3", null, title));
        return wrapper;
    }

    function emptyLine(message) {
        return el("div", "empty", message);
    }

    // A section's data is either the widget's real payload, or one of the
    // bulkhead/placeholder sentinels fetch_section_data() can return
    // (apps/serving/services.py::fetch_section_data, reused by the preview
    // view -- same shape whether it's this admin tool or the real client).
    function statusMessage(data) {
        if (data && data.status === "no_user_selected") {
            return "No user selected — pass ?user_id=... to see personalized data.";
        }
        if (data && data.status === "unavailable") {
            return "Data unavailable (" + (data.error_code || "unknown error") + ").";
        }
        return null;
    }

    function renderPortfolioSummary(section) {
        var wrapper = card(section.title || "Portfolio Summary");
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
        var wrapper = card(section.title || "Holdings");
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
        var wrapper = card(section.title);
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

    var WIDGET_RENDERERS = {
        portfolio_summary: renderPortfolioSummary,
        holdings_list: renderHoldingsList,
        horizontal_carousel: function (section) {
            return renderFundList(section, "No trending movers available.");
        },
        grid: function (section) {
            return renderFundList(section, "No trending funds available.");
        },
    };

    function renderUnknown(section) {
        var wrapper = card(section.title || "Unknown widget");
        var badge = el("span", "unknown-badge", section.widget_type);
        wrapper.appendChild(badge);
        return wrapper;
    }

    function renderSection(section) {
        var renderer = WIDGET_RENDERERS[section.widget_type];
        return renderer ? renderer(section) : renderUnknown(section);
    }

    function renderInto(layout, container) {
        if (!container) return;
        container.innerHTML = "";
        (layout.sections || []).forEach(function (section) {
            container.appendChild(renderSection(section));
        });
    }

    function loadLayout() {
        var node = document.getElementById("sdui-layout-data");
        if (!node) return { sections: [] };
        try {
            return JSON.parse(node.textContent);
        } catch (err) {
            return { sections: [] };
        }
    }

    var layout = loadLayout();
    document.querySelectorAll(".phone-frame .screen-content").forEach(function (container) {
        renderInto(layout, container);
    });
})();
