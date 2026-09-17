/**
 * Mock mobile client renderer for the admin preview (PRD §11.4).
 *
 * Not a real client: no data fetching, no API calls -- the layout JSON is
 * injected server-side into a <script type="application/json"> tag (not
 * assigned as a JS object literal -- browsers and editor tooling never try
 * to parse a non-JS-typed script tag's contents, which also sidesteps
 * template-delimiter confusion in JS-aware editors) and rendered
 * identically into both phone frames, since the JSON is platform-agnostic.
 *
 * The actual per-widget DOM-building logic lives in
 * apps/common/static/common/widget_renderers.js (window.SDUIWidgetRenderers),
 * shared with the public client demo (apps/serving) so the two never drift
 * apart (rules.md §2, plan.md phase-9 Key Decision #4). This file's only
 * job is loading the server-injected layout and fanning it out into both
 * phone frames.
 */
(function () {
    "use strict";

    function renderInto(layout, container) {
        if (!container) return;
        container.innerHTML = "";
        (layout.sections || []).forEach(function (section) {
            container.appendChild(window.SDUIWidgetRenderers.renderSection(section));
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
