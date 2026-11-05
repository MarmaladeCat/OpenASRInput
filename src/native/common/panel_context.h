#pragma once
#include <string>

namespace openasrinput {
// Presentation input only: no input-method object, lease, or ownership policy.
struct PanelContext {
    std::string display;
    int x = 0, y = 0, width = 0, height = 0;
    double scale = 1;
    bool focused = false, globalCursor = false;
};
} // namespace openasrinput
