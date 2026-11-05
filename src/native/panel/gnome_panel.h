#pragma once

#include "panel_context.h"
#include "panel_style.h"
#include "preview_buffer.h"

#include <fcitx-utils/dbus/bus.h>
#include <fcitx-utils/dbus/servicewatcher.h>
#include <memory>
#include <string>

namespace openasrinput {
class GnomePanel {
  public:
    explicit GnomePanel(fcitx::EventLoop &loop);
    ~GnomePanel();
    bool available() const;
    void show(const PanelContext &context, const PanelStyle &style, const PreviewBuffer &preview,
              const std::string &wave, const std::string &state);
    void hide();

  private:
    std::unique_ptr<fcitx::dbus::Bus> bus_;
    std::unique_ptr<fcitx::dbus::ServiceWatcher> watcher_;
    std::unique_ptr<fcitx::dbus::ServiceWatcherEntry> subscription_;
    std::unique_ptr<fcitx::dbus::Slot> probe_;
    std::string owner_;
    bool compatible_ = false;
    bool visible_ = false;
};
} // namespace openasrinput
