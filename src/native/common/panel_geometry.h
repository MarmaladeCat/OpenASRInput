#pragma once
#include <algorithm>
#include <limits>
#include <string>
#include <vector>

namespace openasrinput {
struct MonitorRect {
    int x, y, width, height;
};
inline MonitorRect monitorForPoint(const std::vector<MonitorRect> &monitors, int x, int y) {
    MonitorRect best{0, 0, 1, 1};
    long long distance = std::numeric_limits<long long>::max();
    for (const auto &m : monitors) {
        if (m.width <= 0 || m.height <= 0)
            continue;
        const long long dx = x - std::clamp(x, m.x, m.x + m.width - 1);
        const long long dy = y - std::clamp(y, m.y, m.y + m.height - 1);
        if (dx * dx + dy * dy < distance) {
            best = m;
            distance = dx * dx + dy * dy;
        }
    }
    return best;
}
inline MonitorRect placePanel(MonitorRect area, int x, int y, int caretHeight, int width,
                              int height, bool status = false,
                              const std::string &position = "cursor") {
    const int margin = std::min(12, std::max(0, (std::min(area.width, area.height) - 1) / 4));
    width = std::clamp(width, 1, std::max(1, area.width - 2 * margin));
    height = std::clamp(height, 1, std::max(1, area.height - 2 * margin));
    int top = y + caretHeight + 8;
    if (top + height > area.y + area.height - margin)
        top = y - height - 8;
    if (status) {
        x = area.x + (area.width - width) / 2;
        top = area.y + area.height - height - 16;
    }
    if (position != "cursor") {
        x = area.x + (area.width - width) / 2;
        if (position.find("left") != std::string::npos)
            x = area.x + margin;
        if (position.find("right") != std::string::npos)
            x = area.x + area.width - width - margin;
        top = position.find("top") == 0 ? area.y + margin : area.y + area.height - height - margin;
    }
    return {std::clamp(x, area.x + margin, area.x + area.width - width - margin),
            std::clamp(top, area.y + margin, area.y + area.height - height - margin), width,
            height};
}
} // namespace openasrinput
