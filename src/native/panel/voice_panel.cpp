#include "voice_panel.h"

#include "gnome_panel.h"
#include "panel_layout.h"
#include "panel_renderer.h"
#include "preview_buffer.h"
#include "wayland_panel.h"
#include "x11_geometry.h"
#include "x11_panel_surface.h"

#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/shape.h>
#include <algorithm>
#include <cairo/cairo-xlib.h>
#include <cmath>
#include <cstdlib>
#include <pango/pangocairo.h>
#include <sstream>
#include <unicode/unistr.h>
#include <vector>

namespace openasrinput {
namespace {
constexpr int Height = PanelHeight;
} // namespace

struct VoicePanel::Impl {
    explicit Impl(fcitx::EventLoop &eventLoop)
        : loop(eventLoop), gnome(eventLoop),
          wayland(eventLoop, [this](cairo_t *cr, int width) { draw(cr, width); }) {}
    ~Impl() {
        hide();
        close();
    }

    fcitx::EventLoop &loop;
    GnomePanel gnome;
    WaylandPanel wayland;
    std::string backend = "text";
    Display *display = nullptr;
    Window window = 0;
    X11PanelVisual visual;
    cairo_surface_t *surface = nullptr;
    cairo_surface_t *frame = nullptr;
    std::unique_ptr<fcitx::EventSourceIO> io;
    std::string displayName, text, wave, state;
    PreviewBuffer buffer;
    PanelStyle style;
    PanelContext context;
    bool active = false;
    int width = 760;
    double scale = 1;
    bool visible = false;
    int windowX = -1, windowY = -1, windowWidth = 0, windowHeight = 0, windowRadius = -1;

    void close() {
        io.reset();
        if (frame) {
            cairo_surface_destroy(frame);
            frame = nullptr;
        }
        if (surface) {
            cairo_surface_destroy(surface);
            surface = nullptr;
        }
        if (display) {
            if (window) {
                XDestroyWindow(display, window);
            }
            visual.close(display);
            XCloseDisplay(display);
        }
        display = nullptr;
        window = 0;
        visible = false;
        windowX = windowY = -1;
        windowWidth = windowHeight = 0;
        windowRadius = -1;
    }

    bool openX11(const std::string &name) {
        if (display && name == displayName) {
            return true;
        }
        close();
        display = XOpenDisplay(name.substr(4).c_str());
        if (!display) {
            return false;
        }
        displayName = name;
        int shapeEvent, shapeError;
        if (!XShapeQueryExtension(display, &shapeEvent, &shapeError)) {
            close();
            return false;
        }
        const int screen = DefaultScreen(display);
        visual.open(display);
        XSetWindowAttributes attributes{};
        attributes.override_redirect = True;
        attributes.background_pixel = 0;
        attributes.border_pixel = 0;
        attributes.colormap = visual.colormap;
        attributes.event_mask = ExposureMask | StructureNotifyMask;
        window = XCreateWindow(display, RootWindow(display, screen), 0, 0, width, Height, 0,
                               visual.depth, InputOutput, visual.visual,
                               CWOverrideRedirect | CWBackPixel | CWBorderPixel | CWColormap |
                                   CWEventMask,
                               &attributes);
        XStoreName(display, window, "OpenASRInput Voice Panel");
        XWMHints hints{};
        hints.flags = InputHint;
        hints.input = False;
        XSetWMHints(display, window, &hints);
        // Pure status surface: clicks pass through to the original application.
        XShapeCombineRectangles(display, window, ShapeInput, 0, 0, nullptr, 0, ShapeSet, YXBanded);
        surface = cairo_xlib_surface_create(display, window, visual.visual, width, Height);
        io = loop.addIOEvent(
            ConnectionNumber(display), fcitx::IOEventFlag::In, [this](auto *, int, auto) {
                while (XPending(display)) {
                    XEvent event;
                    XNextEvent(display, &event);
                    if (event.type == UnmapNotify)
                        visible = false;
                    if (event.type == Expose && event.xexpose.count == 0 && visible) {
                        paint();
                    }
                }
                return true;
            });
        return true;
    }

    void hide() {
        gnome.hide();
        wayland.hide();
        if (display && visible) {
            XUnmapWindow(display, window);
            XFlush(display);
            visible = false;
        }
    }

    bool selectBackend(const PanelContext &context) {
        std::string next = "text";
        const auto &name = context.display;
        if (std::getenv("WAYLAND_DISPLAY") && gnome.available()) {
            next = "gnome-shell";
        } else if (name.starts_with("x11:") && context.globalCursor) {
            if (openX11(name))
                next = "x11";
        } else if (gnome.available()) {
            next = "gnome-shell";
        } else if (wayland.available()) {
            next = "wayland-layer-shell";
        } else if (std::getenv("WAYLAND_DISPLAY") && std::getenv("DISPLAY")) {
            // GNOME can run without the extension for this session. Wayland
            // relative cursor rectangles must never be treated as screen coords.
            if (openX11(std::string("x11:") + std::getenv("DISPLAY")))
                next = "xwayland-status";
        }
        if (next != backend) {
            hide();
            backend = next;
        }
        return backend != "text";
    }

    void shape(int w, int h, int radius) {
        std::vector<XRectangle> strips;
        strips.reserve(h);
        for (int y = 0; y < h; ++y) {
            const double dy = y < radius        ? radius - y - 0.5
                              : y >= h - radius ? y - (h - radius) + 0.5
                                                : 0;
            const int inset =
                dy > 0 ? static_cast<int>(std::ceil(
                             radius - std::sqrt(std::max(0.0, radius * radius - dy * dy))))
                       : 0;
            strips.push_back({static_cast<short>(inset), static_cast<short>(y),
                              static_cast<unsigned short>(w - 2 * inset), 1});
        }
        XShapeCombineRectangles(display, window, ShapeBounding, 0, 0, strips.data(),
                                static_cast<int>(strips.size()), ShapeSet, YXBanded);
    }

    void draw(cairo_t *cr, int panelWidth) {
        drawPanel(cr, panelWidth, style, buffer, wave, state);
    }

    void paint() {
        const int pixelWidth = static_cast<int>(width * scale);
        const int pixelHeight = static_cast<int>(Height * scale);
        if (!frame || cairo_image_surface_get_width(frame) != pixelWidth ||
            cairo_image_surface_get_height(frame) != pixelHeight) {
            if (frame)
                cairo_surface_destroy(frame);
            frame = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, pixelWidth, pixelHeight);
        }
        auto *cr = cairo_create(frame);
        cairo_scale(cr, scale, scale);
        draw(cr, width);
        cairo_destroy(cr);
        auto *target = cairo_create(surface);
        visual.paint(target, frame, panelPlacement(style).opacity);
        cairo_destroy(target);
        cairo_surface_flush(surface);
        XFlush(display);
    }
};

VoicePanel::VoicePanel(fcitx::EventLoop &loop) : impl_(std::make_unique<Impl>(loop)) {}
VoicePanel::~VoicePanel() = default;

bool VoicePanel::available(const PanelContext &context) { return impl_->selectBackend(context); }

void VoicePanel::show(const PanelContext &context, const std::string &text, const std::string &wave,
                      const std::string &state) {
    impl_->context = context;
    impl_->active = context.focused;
    if (impl_->text != text) {
        impl_->buffer = previewBuffer(text);
        impl_->text = text;
    }
    impl_->wave = wave;
    impl_->state = state;
    refresh();
}

void VoicePanel::refresh() {
    const auto &context = impl_->context;
    if (!impl_->active || !available(context)) {
        impl_->hide();
        return;
    }
    // Keep the latest frame while suppressed, so unhide/configure does not need audio.
    if (!panelPlacement(impl_->style).visible) {
        impl_->hide();
        return;
    }
    if (impl_->backend == "gnome-shell") {
        impl_->gnome.show(context, impl_->style, impl_->buffer, impl_->wave, impl_->state);
        return;
    }
    if (impl_->backend == "wayland-layer-shell") {
        impl_->wayland.show(impl_->style);
        return;
    }
    int anchorX = context.x, anchorY = context.y;
    const bool status = impl_->backend == "xwayland-status";
    if (status && !x11FocusPoint(impl_->display, anchorX, anchorY)) {
        Window root, child;
        int localX, localY;
        unsigned int mask;
        XQueryPointer(impl_->display, DefaultRootWindow(impl_->display), &root, &child, &anchorX,
                      &anchorY, &localX, &localY, &mask);
    }
    const auto area = monitorForPoint(x11Monitors(impl_->display), anchorX, anchorY);
    auto anchor = context;
    anchor.x = anchorX;
    anchor.y = anchorY;
    anchor.globalCursor = !status && context.globalCursor;
    const auto layout = resolvePanelLayout(impl_->style, anchor, area);
    impl_->scale = layout.scale;
    impl_->width = layout.logicalWidth;
    const auto &position = layout.bounds;
    const int width = position.width, height = position.height;
    const int x = position.x, y = position.y;
    const bool sizeChanged = width != impl_->windowWidth || height != impl_->windowHeight;
    if (sizeChanged || x != impl_->windowX || y != impl_->windowY) {
        XMoveResizeWindow(impl_->display, impl_->window, x, y, width, height);
        impl_->windowX = x;
        impl_->windowY = y;
    }
    if (sizeChanged) {
        cairo_xlib_surface_set_size(impl_->surface, width, height);
        impl_->windowWidth = width;
        impl_->windowHeight = height;
    }
    const int radius = static_cast<int>(impl_->style.radius * impl_->scale);
    if (sizeChanged || radius != impl_->windowRadius) {
        impl_->shape(width, height, radius);
        impl_->windowRadius = radius;
    }
    if (!impl_->visible) {
        impl_->visible = true;
        XMapRaised(impl_->display, impl_->window);
    }
    impl_->paint();
}

void VoicePanel::hide() {
    impl_->active = false;
    impl_->hide();
}

void VoicePanel::setStyle(const PanelStyle &style) {
    impl_->style = style;
    refresh();
}
std::string VoicePanel::backendName() const { return impl_->backend; }
bool VoicePanel::suppressed() const { return !panelPlacement(impl_->style).visible; }
std::string VoicePanel::diagnostics() const {
    std::ostringstream value;
    value << "{\"backend\":\"" << impl_->backend << "\",\"position\":\"" << impl_->style.position
          << "\",\"transparency\":" << impl_->style.transparency
          << ",\"active\":" << (impl_->active ? "true" : "false")
          << ",\"gnomeLayoutV2\":" << (impl_->gnome.available() ? "true" : "false")
          << ",\"x11Alpha\":" << (impl_->visual.alpha ? "true" : "false") << "}";
    return value.str();
}
} // namespace openasrinput
