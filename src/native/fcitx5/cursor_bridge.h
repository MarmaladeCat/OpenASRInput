#pragma once

#include "compat.h"
#include "preview_buffer.h"
#include "voice_panel.h"

#include <cstdint>
#include <fcitx/inputcontext.h>
#include <fcitx/inputpanel.h>
#include <fcitx/instance.h>
#include <string>
#include <unordered_map>

namespace openasrinput {

class CursorBridge {
  public:
    ~CursorBridge();
    void attach(fcitx::Instance &instance);
    void configurePanel(const PanelStyle &style);
    void refreshPanelContext(fcitx::InputContext *context);
    std::string showNotice(const std::string &lease, const std::string &message);
    void dismissNotice(fcitx::InputContext *context = nullptr, bool cancelTimer = true);
    std::string begin(fcitx::InputContext *context);
    bool valid(const std::string &lease) const;
    std::string selection(const std::string &lease);
    bool selectionValid() const;
    bool editing() const { return editing_; }
    std::string show(const std::string &lease, uint64_t revision, const std::string &text,
                     const std::string &wave, const std::string &state);
    std::string commit(const std::string &lease, const std::string &commitId,
                       const std::string &text);
    void clear(const std::string &lease);
    void invalidate(fcitx::InputContext *context);
    void restoreAfterReset(fcitx::InputContext *context);
    bool owns(fcitx::InputContext *context) const;
    const std::string &lease() const { return lease_; }
    fcitx::InputContext *context() const { return context_.get(); }
    std::string panelBackend() const { return panel_ ? panel_->backendName() : "text"; }
    std::string panelStatus() const { return panel_ ? panel_->diagnostics() : "{}"; }

  private:
    void clearPanel();
    void installPanelCallback(fcitx::InputContext *context);
    void render(bool updateClientPreedit);
    struct NoticeCallback {
        CursorBridge *owner;
        void operator()(fcitx::InputContext *context) const;
    };
    std::unique_ptr<VoicePanel> panel_;
    compat::PanelCallback previousPanelCallback_;
    std::string displayText_, displayWave_, displayState_;
    PreviewBuffer preview_;
    fcitx::TrackableObjectReference<fcitx::InputContext> context_;
    std::string lease_;
    uint64_t epoch_ = 0;
    uint64_t revision_ = 0;
    std::unordered_map<std::string, std::pair<std::string, std::string>> commits_;
    bool authorizedCommit_ = false;
    bool editing_ = false;
    bool selectionCommitted_ = false;
    std::string selectedSurrounding_;
    unsigned int selectedCursor_ = 0, selectedAnchor_ = 0;
    fcitx::Rect selectedRect_;
    fcitx::ScopedConnection commitFilter_;
    fcitx::Instance *instance_ = nullptr;
    fcitx::TrackableObjectReference<fcitx::InputContext> noticeContext_;
    compat::PanelCallback noticePreviousCallback_;
    std::string noticeMessage_;
    std::unique_ptr<fcitx::EventSourceTime> noticeTimer_;
};

} // namespace openasrinput
