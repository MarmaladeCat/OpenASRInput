#pragma once
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <cairo/cairo-xlib.h>
#include <string>

namespace openasrinput {
// Use real premultiplied alpha. Mutter/XWayland need not honor
// _NET_WM_WINDOW_OPACITY on override-redirect windows.
struct X11PanelVisual {
    Visual *visual = nullptr;
    Colormap colormap = 0;
    int depth = 0;
    bool alpha = false;
    void open(Display *display) {
        const int screen = DefaultScreen(display);
        visual = DefaultVisual(display, screen);
        depth = DefaultDepth(display, screen);
        XVisualInfo info{};
        const auto selection = "_NET_WM_CM_S" + std::to_string(screen);
        alpha =
            XGetSelectionOwner(display, XInternAtom(display, selection.c_str(), False)) != None &&
            XMatchVisualInfo(display, screen, 32, TrueColor, &info);
        if (alpha) {
            visual = info.visual;
            depth = info.depth;
        }
        colormap = XCreateColormap(display, RootWindow(display, screen), visual, AllocNone);
    }
    void close(Display *display) {
        if (colormap)
            XFreeColormap(display, colormap);
        colormap = 0;
    }
    void paint(cairo_t *target, cairo_surface_t *frame, double opacity) const {
        cairo_set_operator(target, CAIRO_OPERATOR_SOURCE);
        cairo_set_source_rgba(target, 0, 0, 0, 0);
        cairo_paint(target);
        cairo_set_source_surface(target, frame, 0, 0);
        cairo_paint_with_alpha(target, alpha ? opacity : 1);
    }
};
} // namespace openasrinput
