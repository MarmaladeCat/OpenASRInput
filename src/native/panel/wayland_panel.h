#pragma once

#include "panel_style.h"

#include <cairo.h>
#include <fcitx-utils/event.h>
#include <functional>
#include <memory>

namespace openasrinput {
// Native layer-shell status surface. It never obtains a keyboard/pointer grab.
class WaylandPanel {
  public:
    using Painter = std::function<void(cairo_t *, int)>;
    WaylandPanel(fcitx::EventLoop &loop, Painter painter);
    ~WaylandPanel();
    bool available();
    void show(const PanelStyle &style);
    void hide();

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace openasrinput
