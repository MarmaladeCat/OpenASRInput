// Real X11 surfaces in an isolated Xvfb; no Fcitx core or input context required.
#include "panel_layout.h"
#include "x11_geometry.h"
#ifdef FCITX4_PANEL
#include "panel.h"
#else
#include "voice_panel.h"
#endif
#include <X11/Xutil.h>
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <thread>
using namespace openasrinput;
void require(bool value) {
    if (!value)
        throw std::runtime_error("panel hot-update regression");
}
int main() {
    unsetenv("WAYLAND_DISPLAY");
    unsetenv("DBUS_SESSION_BUS_ADDRESS");
    auto *display = XOpenDisplay(nullptr);
    require(display);
    auto root = DefaultRootWindow(display);
    auto owner = XCreateSimpleWindow(display, root, 0, 0, 1, 1, 0, 0, 0);
    auto atom = XInternAtom(display, "_NET_WM_CM_S0", False);
    XSetSelectionOwner(display, atom, owner, CurrentTime);
    XSync(display, False);
#ifdef FCITX4_PANEL
    X11Panel panel;
    auto configure = [&](const PanelStyle &style) { panel.configure(style); };
    auto show = [&] { panel.show(100, 200, "preview", "", "listening"); };
#else
    fcitx::EventLoop loop;
    VoicePanel panel(loop);
    auto configure = [&](const PanelStyle &style) { panel.setStyle(style); };
    auto show = [&] {
        panel.show({std::string("x11:") + getenv("DISPLAY"), 100, 200, 1, 20, 1, true, true},
                   "preview", "", "listening");
    };
#endif
    PanelStyle style;
    style.width = 480;
    style.position = "top-right";
    configure(style);
    show();
    Window window = 0;
    for (int i = 0; i < 100 && !window; ++i) {
        Window parent, ignored, *children = nullptr;
        unsigned count;
        XQueryTree(display, root, &ignored, &parent, &children, &count);
        for (unsigned n = 0; n < count; ++n) {
            char *name = nullptr;
            if (XFetchName(display, children[n], &name) && name) {
                if (std::string(name) == "OpenASRInput Voice Panel")
                    window = children[n];
                XFree(name);
            }
        }
        if (children)
            XFree(children);
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    require(window);
    auto check = [&](int x, int y, int alpha, bool visible) {
        for (int i = 0; i < 100; ++i) {
            XWindowAttributes a{};
            XGetWindowAttributes(display, window, &a);
            if (!visible && a.map_state == IsUnmapped)
                return;
            if (visible && a.map_state == IsViewable && a.x == x && a.y == y) {
                auto *image =
                    XGetImage(display, window, a.width / 2, a.height / 2, 1, 1, AllPlanes, ZPixmap);
                require(image);
                int actual = (XGetPixel(image, 0, 0) >> 24) & 255;
                XDestroyImage(image);
                if (std::abs(actual - alpha) <= 1)
                    return;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        throw std::runtime_error("actual geometry/alpha/mapping did not hot-update");
    };
    const int w = DisplayWidth(display, 0), h = DisplayHeight(display, 0);
    // A relative-caret fallback belongs to the input window, not the pointer.
    const auto editor = XCreateSimpleWindow(display, root, 30, 40, 100, 60, 0, 0, 0);
    XMapWindow(display, editor);
    XSetInputFocus(display, editor, RevertToParent, CurrentTime);
    XWarpPointer(display, None, root, 0, 0, 0, 0, w - 10, h - 10);
    XSync(display, False);
    int focusX = 0, focusY = 0;
    require(x11FocusPoint(display, focusX, focusY));
    require(focusX == 80 && focusY == 70);
    XDestroyWindow(display, editor);
    XSync(display, False);
    check(w - 480 - 12, 12, 255, true);
    // No new SHOW/audio/preview between these changes.
    style.position = "bottom-left";
    style.transparency = 50;
    configure(style);
    check(12, h - 156 - 12, 128, true);
    style.position = "hidden";
    configure(style);
    check(0, 0, 0, false);
    style.position = "top";
    configure(style);
    check((w - 480) / 2, 12, 128, true);
    style.transparency = 100;
    configure(style);
    check(0, 0, 0, false);
    style.transparency = 0;
    configure(style);
    check((w - 480) / 2, 12, 255, true);
    style.position = "cursor";
    configure(style);
#ifdef FCITX4_PANEL
    check(100, 208, 255, true);
#else
    check(100, 228, 255, true);
#endif
    panel.hide();
    configure(style);
    check(0, 0, 0, false); // Ended sessions must not reappear.
    XDestroyWindow(display, owner);
    XCloseDisplay(display);
    std::cout << "PASS live panel hot position/alpha/hide/unhide without new frames\n";
}
