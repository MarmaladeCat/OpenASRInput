#pragma once
#include "panel_context.h"
#include "panel_geometry.h"
#include "panel_style.h"

namespace openasrinput {
// The only native placement/visibility/alpha policy. Backends apply its result;
// they never reinterpret a fixed position as a caret or status-panel position.
struct PanelPlacement {
    bool followsCaret, visible;
    double opacity;
    unsigned int layerAnchor;
};
inline PanelPlacement panelPlacement(const PanelStyle &style) {
    unsigned int anchor = style.position.find("top") == 0 ? 1u : 2u;
    if (style.position.find("left") != std::string::npos)
        anchor |= 4u;
    if (style.position.find("right") != std::string::npos)
        anchor |= 8u;
    return {style.position == "cursor", style.position != "hidden" && style.transparency < 100,
            1 - style.transparency / 100.0, anchor};
}
struct PanelLayout {
    MonitorRect bounds;
    double scale, opacity;
    int logicalWidth;
    bool visible;
};
inline PanelLayout resolvePanelLayout(const PanelStyle &style, const PanelContext &context,
                                      MonitorRect area) {
    const auto placement = panelPlacement(style);
    const double scale =
        std::min({std::clamp(context.scale, .75, 3.0) * style.scale,
                  std::max(1, area.height - 24) / 156.0, std::max(1, area.width - 24) / 320.0});
    const int logicalWidth =
        std::min(style.width, static_cast<int>(std::max(1, area.width - 24) / scale));
    return {placePanel(area, context.x, context.y, context.height,
                       static_cast<int>(logicalWidth * scale), static_cast<int>(156 * scale),
                       !context.globalCursor, style.position),
            scale, placement.opacity, logicalWidth, context.focused && placement.visible};
}
} // namespace openasrinput
