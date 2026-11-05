#pragma once

#include "panel_style.h"
#include "preview_buffer.h"

#include <algorithm>
#include <cairo/cairo.h>
#include <pango/pangocairo.h>
#include <unicode/unistr.h>
#include <vector>

namespace openasrinput {
// Shared by the Fcitx4 X11 and Fcitx5 X11/Wayland surfaces.
inline constexpr int PanelHeight = 156;
namespace panel {
inline constexpr double Pi = 3.14159265358979323846;
inline void color(cairo_t *cr, unsigned int rgb) {
    cairo_set_source_rgb(cr, ((rgb >> 16) & 255) / 255.0, ((rgb >> 8) & 255) / 255.0,
                         (rgb & 255) / 255.0);
}
inline void rounded(cairo_t *cr, double x, double y, double w, double h, double radius) {
    cairo_new_sub_path(cr);
    cairo_arc(cr, x + w - radius, y + radius, radius, -Pi / 2, 0);
    cairo_arc(cr, x + w - radius, y + h - radius, radius, 0, Pi / 2);
    cairo_arc(cr, x + radius, y + h - radius, radius, Pi / 2, Pi);
    cairo_arc(cr, x + radius, y + radius, radius, Pi, 3 * Pi / 2);
    cairo_close_path(cr);
}
inline void label(cairo_t *cr, const std::string &text, double x, double y, double size,
                  unsigned int rgb, int width = -1) {
    auto *layout = pango_cairo_create_layout(cr);
    auto *font = pango_font_description_new();
    pango_font_description_set_family(font, "sans");
    pango_font_description_set_absolute_size(font, size * PANGO_SCALE);
    pango_layout_set_font_description(layout, font);
    pango_layout_set_text(layout, text.c_str(), static_cast<int>(text.size()));
    pango_layout_set_single_paragraph_mode(layout, true);
    pango_layout_set_auto_dir(layout, false);
    if (width >= 0) {
        pango_layout_set_width(layout, width * PANGO_SCALE);
        pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_START);
    }
    color(cr, rgb);
    cairo_move_to(cr, x, y);
    pango_cairo_show_layout(cr, layout);
    pango_font_description_free(font);
    g_object_unref(layout);
}
inline std::string stateLabel(const std::string &state) {
    if (state == "listening")
        return "录音中";
    if (state == "connecting")
        return "录音缓存";
    if (state == "edit-connecting")
        return "指令缓存";
    if (state == "edit-listening")
        return "听取指令";
    if (state == "edit-pausing")
        return "识别指令";
    if (state == "edit-processing")
        return "修改中";
    if (state == "pausing")
        return "收尾中";
    if (state == "needs-config")
        return "需设置";
    return state;
}
} // namespace panel

inline void drawPanel(cairo_t *cr, int panelWidth, const PanelStyle &style,
                      const PreviewBuffer &buffer, const std::string &wave,
                      const std::string &state) {
    using namespace panel;
    const double w = panelWidth;
    const auto &p = style.colors;
    cairo_set_operator(cr, CAIRO_OPERATOR_SOURCE);
    cairo_set_source_rgba(cr, 0, 0, 0, 0);
    cairo_paint(cr);
    cairo_set_operator(cr, CAIRO_OPERATOR_OVER);
    rounded(cr, 1, 1, w - 2, PanelHeight - 2, style.radius - 1);
    color(cr, p[0]);
    cairo_fill_preserve(cr);
    color(cr, p[2]);
    cairo_set_line_width(cr, 1);
    cairo_stroke(cr);

    rounded(cr, 20, 16, 32, 32, 10);
    color(cr, p[8]);
    cairo_fill(cr);
    rounded(cr, 32, 22, 8, 13, 4);
    color(cr, p[7]);
    cairo_fill(cr);
    cairo_set_line_width(cr, 1.7);
    cairo_arc(cr, 36, 30, 7, 0, Pi);
    cairo_move_to(cr, 36, 37);
    cairo_line_to(cr, 36, 41);
    cairo_move_to(cr, 32, 41);
    cairo_line_to(cr, 40, 41);
    cairo_stroke(cr);

    const auto signal = icu::UnicodeString::fromUTF8(wave);
    std::vector<double> levels;
    for (int32_t i = 0; i < signal.length();) {
        const auto c = signal.char32At(i);
        i += U16_LENGTH(c);
        if (c >= 0x2581 && c <= 0x2588)
            levels.push_back((c - 0x2581) / 7.0);
    }
    if (levels.empty())
        levels.push_back(0);
    auto *gradient = cairo_pattern_create_linear(68, 0, w - 126, 0);
    for (int stop = 0; stop < 2; ++stop) {
        auto rgb = p[stop == 0 ? 6 : 7];
        cairo_pattern_add_color_stop_rgb(gradient, stop, ((rgb >> 16) & 255) / 255.0,
                                         ((rgb >> 8) & 255) / 255.0, (rgb & 255) / 255.0);
    }
    cairo_set_source(cr, gradient);
    constexpr int bars = 56;
    const double step = (w - 198) / (bars - 1);
    for (int i = 0; i < bars; ++i) {
        const double position = static_cast<double>(i) * (levels.size() - 1) / (bars - 1);
        const auto index = static_cast<size_t>(position);
        const double fraction = position - index;
        const double energy = levels[index] * (1 - fraction) +
                              levels[std::min(index + 1, levels.size() - 1)] * fraction;
        const double height = 3 + energy * 25;
        rounded(cr, 70 + i * step, 32 - height / 2, 3.5, height, 1.75);
        cairo_fill(cr);
    }
    cairo_pattern_destroy(gradient);
    rounded(cr, w - 102, 20, 80, 25, 12.5);
    color(cr, state == "listening" ? p[9] : p[8]);
    cairo_fill(cr);
    label(cr, stateLabel(state), w - 85, 23, 13, state == "listening" ? p[10] : p[7]);

    rounded(cr, 20, 58, w - 40, 43, 9);
    color(cr, p[1]);
    cairo_fill(cr);
    label(cr, buffer.text.empty() ? "等待语音识别…" : buffer.text, 34, 68, style.fontSize,
          buffer.text.empty() ? p[4] : p[3], static_cast<int>(w - 138));
    label(cr, std::to_string(buffer.words) + " / 20", w - 82, 71, 12, p[4]);

    double x = 24;
    const bool compact = w < 620;
    auto key = [&](const std::string &name, const std::string &hint, int keyWidth, int hintWidth) {
        rounded(cr, x, 117, keyWidth, 22, 5);
        color(cr, p[1]);
        cairo_fill(cr);
        label(cr, name, x + 7, 120, 11, p[5]);
        label(cr, hint, x + keyWidth + 8, 119, 12, p[4]);
        x += keyWidth + hintWidth + (compact ? 16 : 28);
    };
    key(compact ? "⇧ Space" : "Shift + Space",
        state == "needs-config" ? "重试"
        : compact               ? "启停"
                                : "暂停 / 恢复",
        compact ? 62 : 96, compact ? 30 : 70);
    if (state == "needs-config") {
        label(cr, "请打开设置检查 Portal 连接与识别档案", x, 119, 12, p[4],
              static_cast<int>(w - x - 24));
    } else {
        key("Enter", "收尾", compact ? 42 : 46, 30);
        key("Esc", "取消", compact ? 32 : 34, 30);
        if (w >= 720)
            label(cr, "Alt + Z 也可启停", x, 119, 11, p[4], static_cast<int>(w - x - 24));
    }
}
} // namespace openasrinput
