#include "cursor_bridge.h"

#include "panel_context_adapter.h"

#include <fcitx-utils/utf8.h>
#include <fcitx/inputpanel.h>
#include <fcitx/surroundingtext.h>
#include <fcitx/text.h>

namespace openasrinput {

CursorBridge::~CursorBridge() {
    dismissNotice();
    clear(lease_);
}

void CursorBridge::NoticeCallback::operator()(fcitx::InputContext *context) const {
    if (owner->noticeContext_.get() == context && context->hasFocus()) {
        owner->panel_->show(panelContext(context), owner->noticeMessage_, "", "needs-config");
    } else {
        owner->panel_->hide();
    }
}

void CursorBridge::configurePanel(const PanelStyle &style) {
    if (panel_) {
        panel_->setStyle(style);
        if (owns(context_.get())) {
            render(false);
        } else if (auto *ic = noticeContext_.get(); ic && ic->hasFocus()) {
            if (panel_->suppressed() || panel_->available(panelContext(ic))) {
                ic->inputPanel().setAuxUp(fcitx::Text());
                ic->inputPanel().setAuxDown(fcitx::Text());
                panel_->show(panelContext(ic), noticeMessage_, "", "needs-config");
            } else {
                ic->inputPanel().setAuxUp(fcitx::Text("语音输入未开始\n" + noticeMessage_));
                ic->inputPanel().setAuxDown(
                    fcitx::Text("打开 OpenASRInput 设置 / Portal 管理页 · Shift+Space 重试"));
            }
            ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel, true);
        }
    }
}

void CursorBridge::refreshPanelContext(fcitx::InputContext *context) {
    if (!panel_)
        return;
    if (owns(context))
        panel_->show(panelContext(context), displayText_, displayWave_, displayState_);
    else if (noticeContext_.get() == context && context->hasFocus())
        panel_->show(panelContext(context), noticeMessage_, "", "needs-config");
}

void CursorBridge::attach(fcitx::Instance &instance) {
    instance_ = &instance;
    panel_ = std::make_unique<VoicePanel>(instance.eventLoop());
    commitFilter_ = instance.connect<fcitx::Instance::CommitFilter>(
        [this](fcitx::InputContext *ic, std::string &text) {
            // Core's unfocus commit can run before public FocusOut watchers.
            // The voice lease authorizes only final commits through commit().
            if (context_.get() == ic && !authorizedCommit_) {
                text.clear();
            }
        });
}

std::string CursorBridge::selection(const std::string &lease) {
    if (!valid(lease))
        return "stale";
    const auto &surrounding = context_.get()->surroundingText();
    if (!surrounding.isValid())
        return "unsupported";
    const auto text = surrounding.selectedText();
    if (text.size() > 64000 || surrounding.text().size() > 512 * 1024)
        return "unsupported";
    editing_ = !text.empty();
    if (editing_) {
        selectedSurrounding_ = surrounding.text();
        selectedCursor_ = surrounding.cursor();
        selectedAnchor_ = surrounding.anchor();
        selectedRect_ = context_.get()->cursorRect();
    }
    std::string encoded;
    const char *digits = "0123456789abcdef";
    for (unsigned char c : text) {
        encoded += digits[c >> 4];
        encoded += digits[c & 15];
    }
    return encoded;
}

bool CursorBridge::selectionValid() const {
    if (!editing_)
        return true;
    const auto *ic = context_.get();
    if (!ic)
        return false;
    const auto &surrounding = ic->surroundingText();
    return ic->cursorRect() == selectedRect_ && surrounding.isValid() &&
           surrounding.text() == selectedSurrounding_ && surrounding.cursor() == selectedCursor_ &&
           surrounding.anchor() == selectedAnchor_;
}

std::string CursorBridge::begin(fcitx::InputContext *context) {
    dismissNotice();
    if (!context || !context->hasFocus() || !context->isPreeditEnabled() ||
        !context->capabilityFlags().test(fcitx::CapabilityFlag::Preedit) ||
        compat::disabled(context)) {
        return {};
    }
    // No simultaneous RIME composition. Never confirm or cancel its candidate.
    const auto &panel = context->inputPanel();
    if (!panel.preedit().empty() || !panel.clientPreedit().empty() ||
        (panel.candidateList() && panel.candidateList()->size() > 0)) {
        return {};
    }
    if (context_.get()) {
        clearPanel();
    }
    context_ = context->watch();
    editing_ = false;
    selectionCommitted_ = false;
    selectedSurrounding_.clear();
    lease_ = std::to_string(++epoch_);
    revision_ = 0;
    displayText_.clear();
    displayWave_.clear();
    displayState_.clear();
    preview_ = {};
    previousPanelCallback_ = compat::panelCallback(context->inputPanel());
    // Remove transient IM information from the previous host UI before taking
    // ownership. Otherwise a Classic UI notification can overlap our card.
    context->inputPanel().reset();
    compat::setPanelCallback(context->inputPanel(), previousPanelCallback_);
    context->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel, true);
    installPanelCallback(context);
    return lease_;
}

void CursorBridge::installPanelCallback(fcitx::InputContext *context) {
    if (panel_ && panel_->available(panelContext(context))) {
        compat::setPanelCallback(context->inputPanel(), [this](fcitx::InputContext *ic) {
            if (owns(ic)) {
                panel_->show(panelContext(ic), displayText_, displayWave_, displayState_);
            } else {
                panel_->hide();
            }
        });
    }
}

std::string CursorBridge::showNotice(const std::string &lease, const std::string &message) {
    if (!valid(lease)) {
        return "stale";
    }
    if (message.empty() || message.size() > 4096 || !fcitx::utf8::validate(message)) {
        return "failed";
    }
    auto *ic = context_.get();
    clear(lease); // Release keyboard ownership and client preedit BEFORE showing information.
    noticeContext_ = ic->watch();
    noticePreviousCallback_ = compat::panelCallback(ic->inputPanel());
    noticeMessage_ = message;
    const bool directPanel =
        panel_ && (panel_->suppressed() || panel_->available(panelContext(ic)));
    if (!directPanel) {
        ic->inputPanel().setAuxUp(fcitx::Text("语音输入未开始\n" + message));
        ic->inputPanel().setAuxDown(
            fcitx::Text("打开 OpenASRInput 设置 / Portal 管理页 · Shift+Space 重试"));
    }
    if (directPanel) {
        compat::setPanelCallback(ic->inputPanel(), NoticeCallback{this});
        panel_->show(panelContext(ic), message, "", "needs-config");
    }
    if (!directPanel)
        ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel, true);
    if (instance_) {
        noticeTimer_ = instance_->eventLoop().addTimeEvent(CLOCK_MONOTONIC,
                                                           fcitx::now(CLOCK_MONOTONIC) + 8000000, 0,
                                                           [this](auto *source, uint64_t) {
                                                               source->setEnabled(false);
                                                               dismissNotice(nullptr, false);
                                                               return false;
                                                           });
        noticeTimer_->setOneShot();
    }
    return "accepted";
}

void CursorBridge::dismissNotice(fcitx::InputContext *context, bool cancelTimer) {
    auto *ic = noticeContext_.get();
    if (context && context != ic) {
        return;
    }
    if (cancelTimer) {
        noticeTimer_.reset();
    }
    if (panel_) {
        panel_->hide();
    }
    if (ic) {
        bool changed = false;
        const auto currentCallback = compat::panelCallback(ic->inputPanel());
        const auto *callback = currentCallback.target<NoticeCallback>();
        if (callback && callback->owner == this) {
            compat::setPanelCallback(ic->inputPanel(), noticePreviousCallback_);
            changed = true;
        }
        // Never erase a RIME composition that may have superseded this notice.
        if (ic->inputPanel().clientPreedit().empty() && ic->inputPanel().preedit().empty() &&
            (!ic->inputPanel().candidateList() || ic->inputPanel().candidateList()->size() == 0) &&
            ic->inputPanel().auxUp().toString() == "语音输入未开始\n" + noticeMessage_) {
            ic->inputPanel().reset();
            compat::setPanelCallback(ic->inputPanel(), noticePreviousCallback_);
            changed = true;
        }
        if (changed) {
            ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel, true);
        }
    }
    noticeContext_.unwatch();
    noticePreviousCallback_ = {};
    noticeMessage_.clear();
}

bool CursorBridge::valid(const std::string &lease) const {
    auto *ic = context_.get();
    return ic && !lease.empty() && lease == lease_ && ic->hasFocus() &&
           ic->capabilityFlags().test(fcitx::CapabilityFlag::Preedit) && !compat::disabled(ic);
}

bool CursorBridge::owns(fcitx::InputContext *context) const {
    return context && context_.get() == context && valid(lease_);
}

std::string CursorBridge::show(const std::string &lease, uint64_t revision, const std::string &text,
                               const std::string &wave, const std::string &state) {
    if (!valid(lease)) {
        return "stale";
    }
    if (!fcitx::utf8::validate(text) || !fcitx::utf8::validate(wave) ||
        !fcitx::utf8::validate(state)) {
        return "failed";
    }
    if (revision <= revision_) {
        return "accepted";
    }
    const bool textChanged =
        revision_ == 0 || displayText_ != text ||
        (!text.empty() && context_.get()->inputPanel().clientPreedit().empty());
    revision_ = revision;
    if (displayText_ != text) {
        preview_ = previewBuffer(text);
    }
    displayText_ = text;
    displayWave_ = wave;
    displayState_ = state;
    render(textChanged);
    return "accepted";
}

void CursorBridge::render(bool updateClientPreedit) {
    auto *ic = context_.get();
    if (!editing_ && updateClientPreedit &&
        (!displayText_.empty() || !ic->inputPanel().clientPreedit().empty())) {
        // GTK can commit cached preedit before forwarding Reset or FocusOut.
        // ASR previews never authorize such client-side commits.
        fcitx::Text preedit(displayText_, fcitx::TextFormatFlags(fcitx::TextFormatFlag::Underline) |
                                              fcitx::TextFormatFlag::DontCommit);
        preedit.setCursor(static_cast<int>(displayText_.size()));
        ic->inputPanel().setClientPreedit(preedit);
        ic->updatePreedit();
    }
    // Native fallback has the same strict row order: waveform, bounded preview,
    // shortcuts. clientPreedit separately retains the complete recognition text.
    ic->inputPanel().setPreedit(fcitx::Text());
    if (panel_ && (panel_->suppressed() || panel_->available(panelContext(ic)))) {
        // Baseline-built addons have no custom callback, even on newer cores.
        // Leaving fallback text here lets cursor/scale updates also show the
        // host's Classic UI alongside our graphical card.
        ic->inputPanel().setAuxUp(fcitx::Text());
        ic->inputPanel().setAuxDown(fcitx::Text());
        ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel, true);
        panel_->show(panelContext(ic), displayText_, displayWave_, displayState_);
    } else {
        ic->inputPanel().setAuxUp(
            fcitx::Text("语音 " + displayWave_ + "\n" +
                        (preview_.text.empty() ? "等待语音识别…" : preview_.text)));
        ic->inputPanel().setAuxDown(fcitx::Text("Shift+Space 暂停/恢复 · Enter 收尾 · Esc 取消"));
        ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel);
    }
}

void CursorBridge::restoreAfterReset(fcitx::InputContext *context) {
    if (!owns(context)) {
        return;
    }
    // Reset is composition synchronization, not a focus change. Restore after
    // the keyboard engine's reset without changing the lease or SHOW revision.
    installPanelCallback(context);
    render(true);
}

std::string CursorBridge::commit(const std::string &lease, const std::string &commitId,
                                 const std::string &text) {
    if (commitId.empty() || !fcitx::utf8::validate(text)) {
        return "failed";
    }
    auto found = commits_.find(commitId);
    if (found != commits_.end()) {
        return found->second == std::make_pair(lease, text) ? "accepted" : "failed";
    }
    if (!valid(lease)) {
        return "stale";
    }
    auto *ic = context_.get();
    if ((editing_ && selectionCommitted_) || !selectionValid())
        return "stale";
    const bool hadPreedit = !ic->inputPanel().clientPreedit().empty();
    // Remove only OUR preedit. The final is inserted through the public API once.
    ic->inputPanel().setClientPreedit(fcitx::Text());
    ic->inputPanel().setPreedit(fcitx::Text());
    displayText_.clear();
    preview_ = {};
    if (!editing_ && hadPreedit)
        ic->updatePreedit();
    commits_.emplace(commitId, std::make_pair(lease, text));
    if (editing_)
        selectionCommitted_ = true;
    if (editing_ || !text.empty()) {
        authorizedCommit_ = true;
        try {
            ic->commitString(text);
            if (editing_ && text.empty()) {
                // Commit FIRST: GTK3/4 delete the existing selection here, including
                // overwrite mode. Qt ignores an empty commit, so start and clear a
                // non-committable preedit to remove its remaining selection. Never
                // commit after preedit: GTK4 has already collapsed the selection and
                // would delete the next character in overwrite mode. No key forwarding
                // (GTK4 does not implement it), guessed offsets or document placeholder.
                fcitx::Text deletion(" ", fcitx::TextFormatFlag::DontCommit);
                deletion.setCursor(0);
                ic->inputPanel().setClientPreedit(deletion);
                ic->updatePreedit();
                ic->inputPanel().setClientPreedit(fcitx::Text());
                ic->updatePreedit();
            }
        } catch (...) {
            authorizedCommit_ = false;
            throw;
        }
        authorizedCommit_ = false;
    }
    return "accepted";
}

void CursorBridge::clearPanel() {
    if (panel_) {
        panel_->hide();
    }
    if (auto *ic = context_.get()) {
        const bool hadPreedit = !ic->inputPanel().clientPreedit().empty();
        ic->inputPanel().reset();
        compat::setPanelCallback(ic->inputPanel(), previousPanelCallback_);
        if (!editing_ && hadPreedit)
            ic->updatePreedit();
        ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel);
    }
}

void CursorBridge::clear(const std::string &lease) {
    if (lease != lease_) {
        return;
    }
    clearPanel();
    context_.unwatch();
    lease_.clear();
    revision_ = 0;
    previousPanelCallback_ = {};
    displayText_.clear();
    displayWave_.clear();
    displayState_.clear();
    editing_ = false;
    selectedSurrounding_.clear();
}

void CursorBridge::invalidate(fcitx::InputContext *context) {
    dismissNotice(context);
    if (context_.get() == context) {
        clear(lease_);
        ++epoch_;
    }
}

} // namespace openasrinput
