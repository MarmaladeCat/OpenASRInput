#pragma once

#include <chrono>
#include <fcitx/inputcontext.h>
#include <fcitx/instance.h>
#include <functional>
#include <map>
#include <set>

namespace openasrinput {

class ChordGuard {
  public:
    ChordGuard(fcitx::Instance &instance, std::function<void(fcitx::InputContext *)> toggle,
               std::function<void(fcitx::InputContext *)> command = {});
    void handle(fcitx::KeyEvent &event, bool exclusive = false);
    void reset(fcitx::InputContext *context);
    void discardPending();
    void quiesce();
    void handleDisconnected(fcitx::KeyEvent &event);
    std::string diagnostics() const;

  private:
    struct Saved {
        fcitx::Key key;
        int time;
        fcitx::TrackableObjectReference<fcitx::InputContext> context;
    };
    void replay(const Saved &saved);
    void flush();
    void reconcile(fcitx::KeyEvent &event);
    fcitx::Instance &instance_;
    std::function<void(fcitx::InputContext *)> toggle_;
    std::function<void(fcitx::InputContext *)> command_;
    std::map<fcitx::KeySym, Saved> pending_;
    std::set<fcitx::KeySym> down_, suppressed_, forwarded_;
    bool space_ = false;
    bool z_ = false;
    bool replaying_ = false;
    bool blocked_ = false;
    uint64_t recovered_ = 0;
    int spaceReleaseTime_ = -1, zReleaseTime_ = -1;
    std::chrono::steady_clock::time_point spaceReleaseAt_{}, zReleaseAt_{};
};

} // namespace openasrinput
