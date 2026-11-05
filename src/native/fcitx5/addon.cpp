#include "chord_guard.h"
#include "cursor_bridge.h"
#include "keyboard_policy.h"
#include "protocol_fields.h"
#include "socket_server.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <fcitx/addonfactory.h>
#include <fcitx/addonmanager.h>
#include <fstream>
#include <sstream>
#include <vector>

namespace openasrinput {

class VoiceAddon final : public fcitx::AddonInstance {
  public:
    explicit VoiceAddon(fcitx::Instance &instance)
        : instance_(instance), chord_(
                                   instance, [this](auto *) { notify("toggle"); },
                                   [this](auto *) { notify("command"); }) {
        const char *environmentPath = std::getenv("OPENASRINPUT_SOCKET");
        std::string path = environmentPath ? environmentPath : "";
        if (path.empty()) {
            const auto config = compat::configFile();
            std::ifstream input(config);
            std::string line;
            while (std::getline(input, line)) {
                if (line.starts_with("SocketPath=")) {
                    path = line.substr(11);
                }
            }
        }
        if (path.empty()) {
            return;
        } // No installation config, no key interception.
        sink_.attach(instance);
        watchers_.push_back(instance.watchEvent(
            fcitx::EventType::InputContextCursorRectChanged, fcitx::EventWatcherPhase::Default,
            [this](fcitx::Event &base) {
                sink_.refreshPanelContext(
                    static_cast<fcitx::InputContextEvent &>(base).inputContext());
            }));
        server_ = std::make_unique<SocketServer>(
            instance.eventLoop(), path, [this](const auto &line) { return request(line); },
            [this] {
                chord_.quiesce();
                sink_.dismissNotice();
                sink_.clear(sink_.lease());
            });
        watchers_.push_back(instance.watchEvent(
            fcitx::EventType::InputContextKeyEvent, fcitx::EventWatcherPhase::PreInputMethod,
            [this](fcitx::Event &base) {
                auto &event = static_cast<fcitx::KeyEvent &>(base);
                auto sym = event.rawKey().sym();
                ++keyEvents_;
                if (!event.isRelease()) {
                    if (sym == FcitxKey_Shift_L || sym == FcitxKey_Shift_R ||
                        sym == FcitxKey_Alt_L || sym == FcitxKey_Alt_R)
                        ++modifierPresses_;
                    if ((sym == FcitxKey_space &&
                         event.rawKey().states().test(fcitx::KeyState::Shift)) ||
                        ((sym == FcitxKey_z || sym == FcitxKey_Z) &&
                         event.rawKey().states().test(fcitx::KeyState::Alt)))
                        ++shortcutCandidates_;
                }
                if (event.isRelease() && consumed_.erase(sym)) {
                    event.filterAndAccept();
                    return;
                }
                if (!server_->connected()) {
                    chord_.handleDisconnected(event);
                    return;
                }
                const bool voice = sink_.owns(event.inputContext());
                if (!event.isRelease() && !event.rawKey().isModifier() && sym != FcitxKey_space) {
                    sink_.dismissNotice(event.inputContext());
                }
                const auto extras =
                    event.rawKey().states() &
                    (fcitx::KeyStates(fcitx::KeyState::Ctrl) | fcitx::KeyState::Alt |
                     fcitx::KeyState::Super | fcitx::KeyState::Hyper);
                const bool voiceSpace =
                    sym == FcitxKey_space &&
                    (event.isRelease() ||
                     (event.rawKey().states().test(fcitx::KeyState::Shift) && !extras));
                const bool voiceShift = (sym == FcitxKey_Shift_L || sym == FcitxKey_Shift_R) &&
                                        (event.isRelease() || !extras);
                const bool voiceAlt = sym == FcitxKey_Alt_L || sym == FcitxKey_Alt_R;
                const bool voiceZ = sym == FcitxKey_z || sym == FcitxKey_Z;
                if (voice && !voiceShift && !voiceSpace && !voiceAlt && !voiceZ) {
                    chord_.discardPending();
                    if (!event.isRelease()) {
                        consumed_.insert(sym);
                        if (sym == FcitxKey_Escape) {
                            notify("cancel");
                            sink_.clear(sink_.lease());
                        } else if (sym == FcitxKey_Return) {
                            notify("pause");
                        }
                    }
                    event.filterAndAccept();
                    return;
                }
                chord_.handle(event, voice);
                if (voice && !event.filtered()) {
                    // Space without the dedicated chord is not a RIME candidate action.
                    if (!event.isRelease()) {
                        consumed_.insert(sym);
                    }
                    event.filterAndAccept();
                }
            }));
        watchers_.push_back(instance.watchEvent(
            fcitx::EventType::InputContextUpdatePreedit, fcitx::EventWatcherPhase::PreInputMethod,
            [this](fcitx::Event &base) {
                auto &event = static_cast<fcitx::InputContextEvent &>(base);
                auto *ic = event.inputContext();
                if (server_->connected()) {
                    keyboardPreeditPolicy(instance_, ic, keyboardInline_, sink_.owns(ic));
                }
            }));
        for (auto type :
             {fcitx::EventType::InputContextFocusOut, fcitx::EventType::InputContextDestroyed,
              fcitx::EventType::InputContextSwitchInputMethod,
              fcitx::EventType::InputContextCapabilityAboutToChange}) {
            watchers_.push_back(instance.watchEvent(
                type, fcitx::EventWatcherPhase::PreInputMethod, [this](fcitx::Event &event) {
                    auto *ic = static_cast<fcitx::InputContextEvent &>(event).inputContext();
                    if (event.type() == fcitx::EventType::InputContextCapabilityAboutToChange) {
                        const auto flags =
                            static_cast<fcitx::CapabilityAboutToChangeEvent &>(event).newFlags();
                        // DPI, repeat reporting and panel capabilities can change
                        // when crossing monitors without changing the input target.
                        if (flags.test(fcitx::CapabilityFlag::Preedit) &&
                            !flags.test(fcitx::CapabilityFlag::Password) &&
                            !flags.test(static_cast<fcitx::CapabilityFlag>(1ull << 40)))
                            return;
                    }
                    const bool wasOwned = sink_.context() == ic;
                    if (wasOwned) {
                        chord_.discardPending();
                    }
                    chord_.reset(ic);
                    sink_.invalidate(ic);
                    if (wasOwned) {
                        lastInvalidation_ =
                            event.type() == fcitx::EventType::InputContextFocusOut    ? "focus-out"
                            : event.type() == fcitx::EventType::InputContextDestroyed ? "destroyed"
                            : event.type() == fcitx::EventType::InputContextSwitchInputMethod
                                ? "input-method-switch"
                                : "not-editable";
                        notify("context-lost");
                    }
                }));
        }
        watchers_.push_back(instance.watchEvent(
            fcitx::EventType::InputContextReset, fcitx::EventWatcherPhase::PostInputMethod,
            [this](fcitx::Event &event) {
                auto *ic = static_cast<fcitx::InputContextEvent &>(event).inputContext();
                if (sink_.owns(ic)) {
                    if (sink_.editing()) {
                        sink_.invalidate(ic);
                        lastInvalidation_ = "selection-reset";
                        notify("context-lost");
                        return;
                    }
                    sink_.restoreAfterReset(ic);
                    ++preservedResets_;
                }
            }));
    }

    ~VoiceAddon() override {
        sink_.dismissNotice();
        sink_.clear(sink_.lease());
    }

  private:
    void notify(const std::string &kind) {
        if (kind == "toggle" || kind == "command")
            ++toggles_;
        if (server_) {
            server_->send("0\tEVENT\t" + kind);
        }
    }

    std::string request(const std::string &line) {
        const auto fields = protocolFields(line);
        const auto id = fields.empty() ? "0" : fields[0];
        try {
            if (fields.size() < 2) {
                throw std::invalid_argument("missing command");
            }
            const auto &verb = fields[1];
            if (verb == "CONTEXT_STATUS" && fields.size() == 2) {
                auto *focused = instance_.lastFocusedInputContext();
                return id + "\tOK\t{\"lastInvalidation\":\"" + lastInvalidation_ +
                       "\",\"preservedResets\":" + std::to_string(preservedResets_) +
                       ",\"active\":" + (sink_.owns(sink_.context()) ? "true" : "false") +
                       ",\"focused\":" + (focused && focused->hasFocus() ? "true" : "false") +
                       ",\"keyEvents\":" + std::to_string(keyEvents_) +
                       ",\"modifierPresses\":" + std::to_string(modifierPresses_) +
                       ",\"shortcutCandidates\":" + std::to_string(shortcutCandidates_) +
                       ",\"toggles\":" + std::to_string(toggles_) +
                       ",\"chord\":" + chord_.diagnostics() + ",\"panel\":" + sink_.panelStatus() +
                       "}";
            }
            if (verb == "PANEL_BACKEND" && fields.size() == 2) {
                return id + "\tOK\t" + sink_.panelBackend();
            }
            if (verb == "KEYBOARD_PREEDIT" && fields.size() == 3 &&
                (fields[2] == "0" || fields[2] == "1")) {
                keyboardInline_ = fields[2] == "1";
                return id + "\tOK\taccepted";
            }
            if (verb == "THEME" && (fields.size() == 8 || fields.size() == 10)) {
                PanelStyle style;
                style.name = fields[2];
                const auto separator = style.name.find(':');
                const auto theme = style.name.substr(0, separator);
                const auto mode =
                    separator == std::string::npos ? "" : style.name.substr(separator + 1);
                if ((theme != "github" && theme != "material" && theme != "nord" &&
                     theme != "rose-pine") ||
                    (mode != "light" && mode != "dark")) {
                    throw std::invalid_argument("theme");
                }
                size_t consumed;
                style.scale = std::stod(fields[3], &consumed);
                if (consumed != fields[3].size() || !std::isfinite(style.scale) ||
                    style.scale < 0.8 || style.scale > 1.5) {
                    throw std::invalid_argument("scale");
                }
                auto integer = [](const std::string &value, int low, int high) {
                    size_t parsed;
                    int result = std::stoi(value, &parsed);
                    if (parsed != value.size() || result < low || result > high) {
                        throw std::invalid_argument("panel dimension");
                    }
                    return result;
                };
                style.width = integer(fields[4], 480, 960);
                style.fontSize = integer(fields[5], 12, 22);
                style.radius = integer(fields[6], 8, 24);
                if (fields.size() == 10)
                    style.placement(fields[8], fields[9]);
                std::istringstream palette(fields[7]);
                std::string rgb;
                size_t index = 0;
                while (std::getline(palette, rgb, ',')) {
                    if (index >= style.colors.size() || rgb.size() != 6 ||
                        !std::all_of(rgb.begin(), rgb.end(),
                                     [](unsigned char c) { return std::isxdigit(c); })) {
                        throw std::invalid_argument("palette");
                    }
                    style.colors[index++] = static_cast<uint32_t>(std::stoul(rgb, nullptr, 16));
                }
                if (index != style.colors.size()) {
                    throw std::invalid_argument("palette size");
                }
                sink_.configurePanel(style);
                return id + "\tOK\taccepted";
            }
            if (verb == "BEGIN" && fields.size() == 2) {
                auto *ic = instance_.lastFocusedInputContext();
                const auto lease = sink_.begin(ic);
                if (lease.empty() && ic) {
                    compat::unavailable(instance_, ic);
                }
                return id + "\tOK\t" + (lease.empty() ? "unavailable" : lease);
            }
            if (verb == "NOTICE" && fields.size() == 4) {
                return id + "\tOK\t" + sink_.showNotice(fields[2], hexDecode(fields[3]));
            }
            if (verb == "VALID" && fields.size() == 3) {
                return id + "\tOK\t" + (sink_.valid(fields[2]) ? "true" : "false");
            }
            if (verb == "SELECTION" && fields.size() == 3) {
                return id + "\tOK\t" + sink_.selection(fields[2]);
            }
            if (verb == "SHOW" && fields.size() == 7) {
                return id + "\tOK\t" +
                       sink_.show(fields[2], std::stoull(fields[3]), hexDecode(fields[4]),
                                  hexDecode(fields[5]), hexDecode(fields[6]));
            }
            if (verb == "COMMIT" && fields.size() == 5) {
                return id + "\tOK\t" + sink_.commit(fields[2], fields[3], hexDecode(fields[4]));
            }
            if (verb == "CLEAR" && fields.size() == 3) {
                if (fields[2] == sink_.lease()) {
                    chord_.discardPending();
                }
                sink_.clear(fields[2]);
                return id + "\tOK\taccepted";
            }
            throw std::invalid_argument("unknown command");
        } catch (const std::exception &) {
            return id + "\tERROR\tinvalid-request";
        }
    }

    fcitx::Instance &instance_;
    CursorBridge sink_;
    ChordGuard chord_;
    bool keyboardInline_ = true;
    std::string lastInvalidation_;
    uint64_t preservedResets_ = 0;
    uint64_t keyEvents_ = 0, modifierPresses_ = 0, shortcutCandidates_ = 0, toggles_ = 0;
    std::set<fcitx::KeySym> consumed_;
    std::unique_ptr<SocketServer> server_;
    std::vector<std::unique_ptr<fcitx::HandlerTableEntry<fcitx::EventHandler>>> watchers_;
};

class Factory final : public fcitx::AddonFactory {
  public:
    fcitx::AddonInstance *create(fcitx::AddonManager *manager) override {
        return new VoiceAddon(*manager->instance());
    }
};

} // namespace openasrinput

FCITX_ADDON_FACTORY(openasrinput::Factory)
