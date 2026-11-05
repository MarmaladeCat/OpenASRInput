#pragma once
#include "panel_geometry.h"

#include <X11/Xlib.h>
#include <dlfcn.h>

namespace openasrinput {
// Focus windows can disappear between queries. Trap errors on our own panel
// connection while leaving errors from other X11 clients to their handler.
class X11QueryErrors {
    Display *display_;
    XErrorHandler previous_;
    inline static X11QueryErrors *current_ = nullptr;
    static int handle(Display *display, XErrorEvent *event) {
        if (current_ && current_->display_ == display) {
            current_->failed = true;
            return 0;
        }
        return current_ && current_->previous_ ? current_->previous_(display, event) : 0;
    }

  public:
    bool failed = false;
    explicit X11QueryErrors(Display *display) : display_(display) {
        XSync(display_, False);
        current_ = this;
        previous_ = XSetErrorHandler(handle);
    }
    ~X11QueryErrors() {
        XSync(display_, False);
        XSetErrorHandler(previous_);
        current_ = nullptr;
    }
};

inline bool x11FocusPoint(Display *display, int &x, int &y) {
    Window focus = None, child = None;
    int revert = 0, rootX = 0, rootY = 0;
    X11QueryErrors errors(display);
    XGetInputFocus(display, &focus, &revert);
    if (focus == None || focus == PointerRoot || focus == DefaultRootWindow(display))
        return false;
    XWindowAttributes attributes{};
    if (!XGetWindowAttributes(display, focus, &attributes) || attributes.map_state != IsViewable ||
        !XTranslateCoordinates(display, focus, DefaultRootWindow(display), attributes.width / 2,
                               attributes.height / 2, &rootX, &rootY, &child) ||
        errors.failed)
        return false;
    x = rootX;
    y = rootY;
    return true;
}

// Optional RandR 1.5 discovery through its stable public ABI. No new header or
// runtime minimum is imposed on the Fcitx4 baseline. Query afresh after hotplug.
inline std::vector<MonitorRect> x11Monitors(Display *display) {
    struct MonitorInfo {
        Atom name;
        Bool primary, automatic;
        int noutput, x, y, width, height, mwidth, mheight;
        XID *outputs;
    };
    using Query = Status (*)(Display *, int *, int *);
    using Get = MonitorInfo *(*)(Display *, Window, Bool, int *);
    using Free = void (*)(MonitorInfo *);
    static void *library = dlopen("libXrandr.so.2", RTLD_LAZY | RTLD_LOCAL);
    static auto query =
        library ? reinterpret_cast<Query>(dlsym(library, "XRRQueryVersion")) : nullptr;
    static auto get = library ? reinterpret_cast<Get>(dlsym(library, "XRRGetMonitors")) : nullptr;
    static auto free =
        library ? reinterpret_cast<Free>(dlsym(library, "XRRFreeMonitors")) : nullptr;
    std::vector<MonitorRect> result;
    int major = 1, minor = 5, count = 0;
    if (query && get && free && query(display, &major, &minor) &&
        (major > 1 || (major == 1 && minor >= 5))) {
        auto *monitors = get(display, DefaultRootWindow(display), True, &count);
        for (int i = 0; monitors && i < count; ++i)
            if (monitors[i].width > 0 && monitors[i].height > 0)
                result.push_back(
                    {monitors[i].x, monitors[i].y, monitors[i].width, monitors[i].height});
        if (monitors)
            free(monitors);
    }
    if (result.empty()) {
        XWindowAttributes root{};
        XGetWindowAttributes(display, DefaultRootWindow(display), &root);
        result.push_back({0, 0, std::max(root.width, 1), std::max(root.height, 1)});
    }
    return result;
}
} // namespace openasrinput
