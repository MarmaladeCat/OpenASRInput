#include "chord_guard.h"

namespace openasrinput {

ChordGuard::ChordGuard(fcitx::Instance &instance, std::function<void(fcitx::InputContext *)> toggle,
                       std::function<void(fcitx::InputContext *)> command)
    : instance_(instance), toggle_(std::move(toggle)), command_(std::move(command)) {}

std::string ChordGuard::diagnostics() const {
    return "{\"blocked\":" + std::string(blocked_ ? "true" : "false") +
           ",\"recovered\":" + std::to_string(recovered_) +
           ",\"heldModifiers\":" + std::to_string(down_.size()) +
           ",\"pendingModifiers\":" + std::to_string(pending_.size()) +
           ",\"forwardedModifiers\":" + std::to_string(forwarded_.size()) +
           ",\"suppressedModifiers\":" + std::to_string(suppressed_.size()) +
           ",\"spaceDown\":" + (space_ ? "true" : "false") +
           ",\"zDown\":" + (z_ ? "true" : "false") + "}";
}

void ChordGuard::replay(const Saved &saved) {
    if (auto *ic = saved.context.get()) {
        fcitx::KeyEvent replay(ic, saved.key, false, saved.time);
        replaying_ = true;
        const bool accepted = instance_.postEvent(replay);
        replaying_ = false;
        if (!accepted) {
            ic->forwardKey(saved.key, false, saved.time);
        }
    }
}

void ChordGuard::flush() {
    auto pending = std::move(pending_);
    pending_.clear();
    for (const auto &[sym, saved] : pending) {
        forwarded_.insert(sym);
        replay(saved);
    }
}

void ChordGuard::reset(fcitx::InputContext *context) {
    // Replay only pending keys that belong to the context being detached.
    bool affected = false;
    for (const auto &[sym, saved] : pending_) {
        (void)sym;
        affected |= saved.context.get() == context;
    }
    if (affected) {
        flush();
    }
    blocked_ = !down_.empty() || space_ || z_;
}

void ChordGuard::discardPending() {
    pending_.clear();
    suppressed_.insert(down_.begin(), down_.end());
}

void ChordGuard::quiesce() {
    pending_.clear();
    for (auto sym : down_) {
        if (!forwarded_.contains(sym)) {
            suppressed_.insert(sym);
        }
    }
    blocked_ = !down_.empty() || space_ || z_;
}

void ChordGuard::reconcile(fcitx::KeyEvent &event) {
    if (!blocked_ || event.isRelease() || event.rawKey().states().test(fcitx::KeyState::Repeat)) {
        return;
    }
    // Focus can leave this frontend before key-up (e.g. Alt+Tab). A later
    // event's modifier mask is evidence that an old modifier is no longer held.
    // Do not invent a release on focus-out: a physically held chord must remain
    // blocked, and a delivered release must still match its suppressed press.
    const auto raw = event.rawKey();
    bool recovered = false;
    for (auto it = down_.begin(); it != down_.end();) {
        const auto held = *it;
        const auto state = held == FcitxKey_Shift_L || held == FcitxKey_Shift_R
                               ? fcitx::KeyState::Shift
                               : fcitx::KeyState::Alt;
        if (raw.states().test(state)) {
            ++it;
            continue;
        }
        pending_.erase(held);
        forwarded_.erase(held);
        suppressed_.erase(held);
        it = down_.erase(it);
        recovered = true;
    }
    // After a focus gap, a fresh unmodified press also ends an orphaned chord.
    // Repeats and releases cannot initiate this recovery or toggle recording.
    if (!raw.states().test(fcitx::KeyState::Shift) && !raw.states().test(fcitx::KeyState::Alt) &&
        down_.empty()) {
        recovered |= space_ || z_;
        space_ = z_ = false;
    }
    if (down_.empty() && !space_ && !z_) {
        blocked_ = false;
        spaceReleaseTime_ = zReleaseTime_ = -1;
        spaceReleaseAt_ = zReleaseAt_ = {};
    }
    if (recovered) {
        ++recovered_;
    }
}

void ChordGuard::handleDisconnected(fcitx::KeyEvent &event) {
    reconcile(event);
    const auto sym = event.rawKey().sym();
    if ((sym == FcitxKey_z || sym == FcitxKey_Z) && z_) {
        if (event.isRelease())
            z_ = false;
        event.filterAndAccept();
        return;
    }
    if (sym == FcitxKey_Shift_L || sym == FcitxKey_Shift_R || sym == FcitxKey_Alt_L ||
        sym == FcitxKey_Alt_R) {
        if (event.isRelease()) {
            down_.erase(sym);
            forwarded_.erase(sym);
            if (suppressed_.erase(sym)) {
                event.filterAndAccept();
            }
        } else if (suppressed_.contains(sym)) {
            event.filterAndAccept();
        }
    } else if (sym == FcitxKey_space && space_) {
        event.filterAndAccept();
        if (event.isRelease()) {
            space_ = false;
        }
    }
    if (down_.empty() && !space_ && !z_) {
        blocked_ = false;
    }
}

void ChordGuard::handle(fcitx::KeyEvent &event, bool exclusive) {
    if (replaying_) {
        return;
    }
    reconcile(event);
    const auto raw = event.rawKey();
    const auto sym = raw.sym();
    const bool release = event.isRelease();
    const bool repeat = raw.states().test(fcitx::KeyState::Repeat);
    const auto modifiers =
        raw.states() & (fcitx::KeyStates(fcitx::KeyState::Shift) | fcitx::KeyState::Ctrl |
                        fcitx::KeyState::Alt | fcitx::KeyState::Super | fcitx::KeyState::Hyper);
    const bool shift = sym == FcitxKey_Shift_L || sym == FcitxKey_Shift_R;
    const bool alt = sym == FcitxKey_Alt_L || sym == FcitxKey_Alt_R;
    if (sym == FcitxKey_z || sym == FcitxKey_Z) {
        if (z_) {
            if (release) {
                z_ = false;
                zReleaseTime_ = event.time();
                zReleaseAt_ = std::chrono::steady_clock::now();
            }
            event.filterAndAccept();
            return;
        }
        // X11-style synthetic release/press pairs share the event timestamp.
        if (!release && ((event.time() != 0 && event.time() == zReleaseTime_) ||
                         (event.time() == 0 && std::chrono::steady_clock::now() - zReleaseAt_ <
                                                   std::chrono::milliseconds(10)))) {
            z_ = true;
            event.filterAndAccept();
            return;
        }
        const bool altDown = down_.contains(FcitxKey_Alt_L) || down_.contains(FcitxKey_Alt_R);
        if (!release && !repeat && !blocked_ && altDown && forwarded_.empty() &&
            modifiers == fcitx::KeyStates(fcitx::KeyState::Alt)) {
            pending_.clear();
            suppressed_.insert(down_.begin(), down_.end());
            z_ = true;
            event.filterAndAccept();
            (command_ ? command_ : toggle_)(event.inputContext());
            return;
        }
    }
    if (shift || alt) {
        if (!release) {
            if (suppressed_.contains(sym)) {
                event.filterAndAccept();
                return;
            }
            if (repeat || down_.contains(sym)) {
                if (!forwarded_.contains(sym)) {
                    event.filterAndAccept();
                }
                return;
            }
            down_.insert(sym);
            if (space_ || z_) {
                suppressed_.insert(sym);
                event.filterAndAccept();
            } else if (!forwarded_.empty() ||
                       (modifiers &
                        ~fcitx::KeyStates(shift ? fcitx::KeyState::Shift : fcitx::KeyState::Alt))) {
                flush();
                forwarded_.insert(sym);
            } else {
                pending_.emplace(sym, Saved{raw, event.time(), event.inputContext()->watch()});
                event.filterAndAccept();
            }
            return;
        }
        if (exclusive && pending_.contains(sym)) {
            discardPending();
        }
        down_.erase(sym);
        if (down_.empty() && !space_ && !z_) {
            blocked_ = false;
            spaceReleaseTime_ = zReleaseTime_ = -1;
            spaceReleaseAt_ = zReleaseAt_ = {};
        }
        if (suppressed_.erase(sym)) {
            event.filterAndAccept();
        } else {
            flush();
            forwarded_.erase(sym);
        }
        return;
    }
    if (sym == FcitxKey_space && space_) {
        if (release) {
            space_ = false;
            spaceReleaseTime_ = event.time();
            spaceReleaseAt_ = std::chrono::steady_clock::now();
            if (down_.empty()) {
                blocked_ = false;
            }
        }
        event.filterAndAccept();
        return;
    }
    if (sym == FcitxKey_space && !release &&
        ((event.time() != 0 && event.time() == spaceReleaseTime_) ||
         (event.time() == 0 &&
          std::chrono::steady_clock::now() - spaceReleaseAt_ < std::chrono::milliseconds(10)))) {
        space_ = true;
        event.filterAndAccept();
        return;
    }
    const bool shiftDown = down_.contains(FcitxKey_Shift_L) || down_.contains(FcitxKey_Shift_R);
    if (sym == FcitxKey_space && !release && !repeat && !blocked_ &&
        modifiers == fcitx::KeyStates(fcitx::KeyState::Shift) && shiftDown && forwarded_.empty()) {
        pending_.clear();
        suppressed_.insert(down_.begin(), down_.end());
        space_ = true;
        event.filterAndAccept();
        toggle_(event.inputContext());
        return;
    }
    flush();
    // This prototype is exclusive while recording. Outside recording, callers
    // must not deliver normal keys with a still-suppressed Shift after a chord.
    // Restore a held Shift via the public path before that normal key.
    for (auto held : suppressed_) {
        replay(Saved{fcitx::Key(held), event.time(), event.inputContext()->watch()});
        forwarded_.insert(held);
    }
    suppressed_.clear();
}

} // namespace openasrinput
