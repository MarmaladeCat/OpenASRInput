#pragma once

#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace openasrinput {
struct PanelStyle {
    std::string name = "material:light";
    double scale = 1;
    int width = 760;
    int fontSize = 15;
    int radius = 18;
    std::string position = "cursor";
    int transparency = 0;
    void placement(const std::string &value, const std::string &alpha) {
        if (value != "cursor" && value != "hidden" && value != "top" && value != "bottom" &&
            value != "top-left" && value != "top-right" && value != "bottom-left" &&
            value != "bottom-right")
            throw std::invalid_argument("position");
        size_t used;
        int number = std::stoi(alpha, &used);
        if (used != alpha.size() || number < 0 || number > 100)
            throw std::invalid_argument("transparency");
        position = value;
        transparency = number;
    }
    // background, surface, border, text, muted, keyText, waveStart, accent,
    // accentBackground, successBackground, successText (themes.py contract).
    std::array<uint32_t, 11> colors = {0xffffff, 0xf8fafc, 0xdbe4ee, 0x1e293b, 0x64748b, 0x475569,
                                       0x38b8ab, 0x6366f1, 0xeef2ff, 0xecfdf5, 0x15803d};
};
} // namespace openasrinput
