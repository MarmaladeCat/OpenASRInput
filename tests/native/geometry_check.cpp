#include "panel_geometry.h"

#include <iostream>
#include <stdexcept>
using namespace openasrinput;
void require(bool ok) {
    if (!ok)
        throw std::runtime_error("monitor geometry regression");
}
int main() {
    const std::vector<MonitorRect> monitors{{-1920, 0, 1920, 1080}, {0, 400, 2560, 1440}};
    auto left = monitorForPoint(monitors, -100, 1000);
    auto panel = placePanel(left, -100, 1000, 24, 760, 156);
    require(panel.x < 0 && panel.x >= -1920 && panel.x + panel.width <= 0);
    require(panel.y + panel.height <= 1080);
    auto fixed = placePanel(left, -100, 1000, 24, 760, 156, false, "top-right");
    require(fixed.x == -772 && fixed.y == 12);
    auto other = placePanel(left, -1800, 10, 24, 760, 156, false, "top-right");
    require(other.x == fixed.x && other.y == fixed.y);
    auto gap = monitorForPoint(monitors, 2000, 100);
    require(gap.x == 0 && gap.y == 400);
    panel = placePanel(gap, 2000, 100, 24, 760, 156);
    require(panel.y >= 400 && panel.x + panel.width <= 2560);
    panel = placePanel({100, -800, 640, 480}, 700, -350, 24, 2000, 700);
    require(panel.x >= 100 && panel.y >= -800 && panel.width <= 640 && panel.height <= 480);
    std::cout
        << "PASS monitor geometry: negative origins, gaps, hotplug bounds and scaled panels\n";
}
