#pragma once

#include "panel_context.h"
#include "panel_style.h"

#include <fcitx-utils/event.h>
#include <memory>
#include <string>

namespace openasrinput {
// Non-focusable X11, GNOME Shell, or native Wayland layer-shell surface,
// driven by presentation snapshots, independent of Fcitx input ownership.
class VoicePanel {
  public:
    explicit VoicePanel(fcitx::EventLoop &loop);
    ~VoicePanel();
    bool available(const PanelContext &context);
    void show(const PanelContext &context, const std::string &text, const std::string &wave,
              const std::string &state);
    void hide();
    void setStyle(const PanelStyle &style);
    std::string backendName() const;
    std::string diagnostics() const;
    bool suppressed() const;

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    void refresh();
};
} // namespace openasrinput
