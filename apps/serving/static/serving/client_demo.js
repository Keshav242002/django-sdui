/**
 * Public client demo (PRD §12A client-side behavior, plan.md phase-9 Key
 * Decisions #3/#5/#6) -- a real page making real fetch() calls against the
 * live API, not a server-side-rendered mock like apps.screens' admin
 * preview.
 *
 * Happy path: one call to the aggregator (/api/v1/screens/{screen_key}/),
 * render every section directly.
 *
 * Fallback path (aggregator unreachable): render the bundled default
 * layout (window.SDUI_BUNDLED_LAYOUTS, structure-only) immediately as
 * skeleton cards, then fetch each section's data independently from its
 * standalone widget endpoint (/api/v1/widgets/{widget_type}/) and fill
 * each card in as its own call resolves -- progressive rendering, and one
 * widget's failure only affects its own card (bulkhead survives the
 * fallback path too).
 *
 * Depends on apps/common/static/common/widget_renderers.js
 * (window.SDUIWidgetRenderers) and bundled_layouts.js
 * (window.SDUI_BUNDLED_LAYOUTS), both loaded before this file.
 */
(function () {
    "use strict";

    var screenKey = document.body.getAttribute("data-screen-key");
    var searchParams = new URLSearchParams(window.location.search);
    var userId = searchParams.get("user_id") || "";
    var forceDown = searchParams.get("force_down") === "1";

    var statusEl = document.getElementById("status-line");
    var contentEl = document.getElementById("screen-content");

    function setStatus(text, cls) {
        statusEl.textContent = text;
        statusEl.className = "status-line " + (cls || "");
    }

    function aggregatorUrl() {
        if (forceDown) {
            // Deliberately request a path that doesn't exist, so the
            // fetch() genuinely fails (a real 404/network error, not a
            // mocked result) -- only the *trigger* is simulated, per
            // plan.md Key Decision #5.
            return "/api/v1/force-down-demo-nonexistent/";
        }
        return "/api/v1/screens/" + encodeURIComponent(screenKey) + "/?user_id=" + encodeURIComponent(userId);
    }

    function widgetUrl(widgetType) {
        return "/api/v1/widgets/" + encodeURIComponent(widgetType) + "/?user_id=" + encodeURIComponent(userId);
    }

    function withData(section, data) {
        var copy = {};
        for (var key in section) {
            if (Object.prototype.hasOwnProperty.call(section, key)) copy[key] = section[key];
        }
        copy.data = data;
        return copy;
    }

    function placeCard(node, index) {
        node.setAttribute("data-section-index", String(index));
        var existing = contentEl.querySelector('[data-section-index="' + index + '"]');
        if (existing) {
            existing.replaceWith(node);
        } else {
            contentEl.appendChild(node);
        }
    }

    function runHappyPath(body) {
        setStatus("Aggregator: reachable.", "status-ok");
        contentEl.innerHTML = "";
        (body.data.sections || []).forEach(function (section) {
            contentEl.appendChild(window.SDUIWidgetRenderers.renderSection(section));
        });
    }

    function runFallback() {
        setStatus("Aggregator: unreachable — falling back to bundled layout.", "status-warn");

        var bundled = window.SDUI_BUNDLED_LAYOUTS[screenKey];
        if (!bundled) {
            // Guard: a screen_key with no bundled-layout entry is a real,
            // expected case (not every screen has one hardcoded), not an
            // error to let crash the fallback path (plan.md Key Decision #6
            // -- caught during plan review before this was written).
            contentEl.innerHTML = "";
            var notice = document.createElement("div");
            notice.className = "empty";
            notice.textContent = "No bundled default layout configured for this screen.";
            contentEl.appendChild(notice);
            return;
        }

        contentEl.innerHTML = "";
        bundled.sections.forEach(function (section, index) {
            placeCard(window.SDUIWidgetRenderers.renderSection(withData(section, {})), index);
        });

        bundled.sections.forEach(function (section, index) {
            fetch(widgetUrl(section.widget_type))
                .then(function (res) {
                    if (!res.ok) throw new Error("widget fetch failed: " + res.status);
                    return res.json();
                })
                .then(function (body) {
                    placeCard(window.SDUIWidgetRenderers.renderSection(withData(section, body.data)), index);
                })
                .catch(function () {
                    placeCard(
                        window.SDUIWidgetRenderers.renderSection(
                            withData(section, { status: "unavailable", error_code: "WIDGET_UNAVAILABLE" })
                        ),
                        index
                    );
                });
        });
    }

    setStatus("Loading…", "");
    fetch(aggregatorUrl())
        .then(function (res) {
            if (!res.ok) throw new Error("aggregator fetch failed: " + res.status);
            return res.json();
        })
        .then(runHappyPath)
        .catch(runFallback);
})();
