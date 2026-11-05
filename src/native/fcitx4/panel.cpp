#include "panel.h"

#include "panel_layout.h"
#include "panel_renderer.h"
#include "preview_buffer.h"
#include "x11_geometry.h"

#include <X11/Xatom.h>
#include <X11/Xutil.h>
#include <X11/extensions/shape.h>
#include <algorithm>
#include <cairo/cairo-xlib.h>
#include <cmath>
#include <pango/pangocairo.h>
#include <vector>

namespace openasrinput {
X11Panel::X11Panel() {
    display_ = XOpenDisplay(nullptr);
    if (!display_)
        return;
    int event, error;
    if (!XShapeQueryExtension(display_, &event, &error)) {
        XCloseDisplay(display_);
        display_ = nullptr;
        return;
    }
    XSetWindowAttributes attributes{};
    visual_.open(display_);
    attributes.colormap = visual_.colormap;
    attributes.background_pixel = 0;
    attributes.border_pixel = 0;
    attributes.override_redirect = True;
    attributes.event_mask = ExposureMask;
    window_ = XCreateWindow(
        display_, DefaultRootWindow(display_), 0, 0, width_, height_, 0, visual_.depth, InputOutput,
        visual_.visual, CWOverrideRedirect | CWEventMask | CWColormap | CWBackPixel | CWBorderPixel,
        &attributes);
    XStoreName(display_, window_, "OpenASRInput Voice Panel");
    XWMHints hints{};
    hints.flags = InputHint;
    hints.input = False;
    XSetWMHints(display_, window_, &hints);
    XShapeCombineRectangles(display_, window_, ShapeInput, 0, 0, nullptr, 0, ShapeSet, YXBanded);
}
X11Panel::~X11Panel() {
    if (display_) {
        XDestroyWindow(display_, window_);
        visual_.close(display_);
        XCloseDisplay(display_);
    }
}
unsigned int X11Panel::keyCode(unsigned long symbol) const {
    return display_ ? XKeysymToKeycode(display_, symbol) : 0;
}
bool X11Panel::keyHeld(unsigned int code) const {
    if (!display_ || !code || code >= 256)
        return false;
    char keys[32];
    XQueryKeymap(display_, keys);
    return (static_cast<unsigned char>(keys[code / 8]) & (1u << (code % 8))) != 0;
}
void X11Panel::hide() {
    active_ = false;
    unmap();
}
void X11Panel::unmap() {
    if (display_ && visible_) {
        XUnmapWindow(display_, window_);
        XFlush(display_);
    }
    visible_ = false;
}
void X11Panel::process() {
    if (!display_)
        return;
    while (XPending(display_)) {
        XEvent event;
        XNextEvent(display_, &event);
        if (event.type == Expose && visible_)
            paint();
    }
}
void X11Panel::show(int x, int y, std::string text, std::string wave, std::string state) {
    active_ = true;
    anchorX_ = x;
    anchorY_ = y;
    buffer_ = previewBuffer(text);
    wave_ = std::move(wave);
    state_ = std::move(state);
    refresh();
}
void X11Panel::configure(const PanelStyle &style) {
    style_ = style;
    refresh();
}
void X11Panel::refresh() {
    if (!display_)
        return;
    if (!active_ || !panelPlacement(style_).visible) {
        unmap();
        return;
    }
    int x = anchorX_, y = anchorY_;
    const auto area = monitorForPoint(x11Monitors(display_), x, y);
    const auto layout = resolvePanelLayout(style_, {"", x, y, 0, 0, 1, true, true}, area);
    scale_ = layout.scale;
    const auto &position = layout.bounds;
    width_ = position.width;
    height_ = position.height;
    x = position.x;
    y = position.y;
    XMoveResizeWindow(display_, window_, x, y, width_, height_);
    const int radius =
        std::min({static_cast<int>(style_.radius * scale_), width_ / 2, height_ / 2});
    std::vector<XRectangle> rows;
    for (int row = 0; row < height_; ++row) {
        const double dy = row < radius              ? radius - row - 0.5
                          : row >= height_ - radius ? row - (height_ - radius) + 0.5
                                                    : 0;
        const int inset =
            dy > 0 ? static_cast<int>(
                         std::ceil(radius - std::sqrt(std::max(0.0, radius * radius - dy * dy))))
                   : 0;
        rows.push_back({static_cast<short>(inset), static_cast<short>(row),
                        static_cast<unsigned short>(width_ - 2 * inset), 1});
    }
    XShapeCombineRectangles(display_, window_, ShapeBounding, 0, 0, rows.data(),
                            static_cast<int>(rows.size()), ShapeSet, YXBanded);
    XMapRaised(display_, window_);
    visible_ = true;
    paint();
}
void X11Panel::paint() {
    auto *surface = cairo_xlib_surface_create(display_, window_, visual_.visual, width_, height_);
    auto *frame = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, width_, height_);
    auto *cr = cairo_create(frame);
    cairo_scale(cr, scale_, scale_);
    drawPanel(cr, static_cast<int>(width_ / scale_), style_, buffer_, wave_, state_);
    cairo_destroy(cr);
    auto *target = cairo_create(surface);
    visual_.paint(target, frame, panelPlacement(style_).opacity);
    cairo_destroy(target);
    cairo_surface_destroy(frame);
    cairo_surface_destroy(surface);
    XFlush(display_);
}
} // namespace openasrinput
