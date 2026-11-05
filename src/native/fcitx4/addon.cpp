// Fcitx 4.2.9.8 public API adapter. All operations run on Fcitx's event thread.
#include "panel.h"
#include "protocol_fields.h"
#include "unix_server.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <fcitx-utils/utf8.h>
#include <fcitx/candidate.h>
#include <fcitx/frontend.h>
#include <fcitx/hook.h>
#include <fcitx/instance.h>
#include <fcitx/module.h>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <vector>

namespace openasrinput {
namespace {
std::string decode(const std::string &hex) {
    if (hex.size() % 2)
        throw std::invalid_argument("hex");
    std::string value;
    auto digit = [](char c) {
        if (c >= '0' && c <= '9')
            return c - '0';
        if (c >= 'a' && c <= 'f')
            return c - 'a' + 10;
        throw std::invalid_argument("hex");
    };
    for (size_t i = 0; i < hex.size(); i += 2)
        value += static_cast<char>((digit(hex[i]) << 4) | digit(hex[i + 1]));
    if (value.find('\0') != std::string::npos || !fcitx_utf8_check_string(value.c_str()))
        throw std::invalid_argument("text");
    return value;
}
using Life = std::shared_ptr<int>;
std::string encode(const std::string &value) {
    const char *digits = "0123456789abcdef";
    std::string result;
    for (unsigned char c : value) {
        result += digits[c >> 4];
        result += digits[c & 15];
    }
    return result;
}
void *allocateLife(void *) { return new Life(std::make_shared<int>(0)); }
void freeLife(void *, void *value) { delete static_cast<Life *>(value); }
} // namespace

class Bridge {
  public:
    explicit Bridge(FcitxInstance *instance) : instance_(instance) {
        lifeSlot_ = FcitxInstanceAllocDataForIC(instance, allocateLife, nullptr, freeLife, nullptr);
        FcitxInstanceRegisterPreInputFilter(instance, {press, this});
        FcitxInstanceRegisterPreReleaseInputFilter(instance, {release, this});
        FcitxInstanceRegisterInputUnFocusHook(instance, {lost, this});
        FcitxInstanceRegisterResetInputHook(instance, {lost, this});
        FcitxInstanceRegisterIMChangedHook(instance, {lost, this});
        FcitxInstanceRegisterICStateChangedHook(instance, {stateChanged, this});
        FcitxInstanceRegisterCommitFilter(instance, {filterCommit, this});
        reload();
    }
    ~Bridge() {
        FcitxInstanceRemoveTimeoutByFunc(instance_, hideNotice);
        clear();
    }
    void reload() {
        // Remain inert until this user explicitly activates the installed app.
        std::string path;
        if (const auto *value = std::getenv("OPENASRINPUT_SOCKET"))
            path = value;
        if (path.empty()) {
            const char *xdg = std::getenv("XDG_CONFIG_HOME"), *home = std::getenv("HOME");
            const std::string config = xdg ? xdg : std::string(home ? home : "") + "/.config";
            std::ifstream stream(config + "/fcitx/conf/openasrinput.conf");
            std::string line;
            while (std::getline(stream, line))
                if (line.rfind("SocketPath=", 0) == 0)
                    path = line.substr(11);
        }
        if (path == socketPath_)
            return;
        clear();
        server_.reset();
        socketPath_.clear();
        if (!path.empty())
            server_ = std::make_unique<UnixServer>(
                path, [this](const auto &line) { return request(line); }, [this] { clear(); });
        socketPath_ = path;
    }
    void watch() {
        int maximum = FcitxInstanceGetMaxFD(instance_);
        if (server_)
            server_->watch(FcitxInstanceGetReadFDSet(instance_),
                           FcitxInstanceGetWriteFDSet(instance_), maximum);
        const int fd = panel_.fd();
        if (fd >= 0 && fd < FD_SETSIZE) {
            FD_SET(fd, FcitxInstanceGetReadFDSet(instance_));
            maximum = std::max(maximum, fd);
        }
        FcitxInstanceSetMaxFD(instance_, maximum);
    }
    void process() {
        if (server_)
            server_->process();
        if (!lease_.empty() && !valid(lease_))
            invalidate();
        panel_.process();
    }

  private:
    FcitxInputState *input() const { return FcitxInstanceGetInputState(instance_); }
    bool valid(const std::string &lease) const {
        return !lease.empty() && lease == lease_ && !life_.expired() &&
               context_ == FcitxInstanceGetCurrentIC(instance_) && context_ &&
               context_->state != IS_CLOSED && !(context_->contextCaps & CAPACITY_PASSWORD);
    }
    std::string begin() {
        auto *context = FcitxInstanceGetCurrentIC(instance_);
        if (!context || context->state == IS_CLOSED || !panel_.available() ||
            (context->contextCaps & (CAPACITY_PASSWORD | CAPACITY_RELATIVE_CURSOR_RECT)) ||
            !FcitxInstanceICSupportPreedit(instance_, context))
            return "unavailable";
        if (!lease_.empty())
            return "unavailable";
        if (FcitxMessagesGetMessageCount(FcitxInputStateGetPreedit(input())) ||
            FcitxMessagesGetMessageCount(FcitxInputStateGetClientPreedit(input())) ||
            FcitxCandidateWordGetListSize(FcitxInputStateGetCandidateList(input())) ||
            FcitxInputStateGetRawInputBufferSize(input()))
            return "unavailable";
        auto *life = static_cast<Life *>(FcitxInstanceGetICData(instance_, context, lifeSlot_));
        if (!life)
            return "unavailable";
        FcitxInstanceRemoveTimeoutByFunc(instance_, hideNotice);
        context_ = context;
        life_ = *life;
        lease_ = std::to_string(++epoch_);
        revision_ = 0;
        editing_ = false;
        FcitxUICloseInputWindow(instance_);
        return lease_;
    }
    void emptyPreedit() {
        if (editing_)
            return;
        if (!context_ || life_.expired() || context_ != FcitxInstanceGetCurrentIC(instance_))
            return;
        FcitxMessagesSetMessageCount(FcitxInputStateGetClientPreedit(input()), 0);
        FcitxInputStateSetClientCursorPos(input(), 0);
        FcitxInstanceUpdatePreedit(instance_, context_);
    }
    void clear() {
        emptyPreedit();
        panel_.hide();
        context_ = nullptr;
        life_.reset();
        lease_.clear();
        revision_ = 0;
        editing_ = false;
        selectedSurrounding_.clear();
    }
    void invalidate() {
        if (!lease_.empty()) {
            clear();
            notify("context-lost");
        }
    }
    void notify(const std::string &kind) {
        if (server_)
            server_->send("0\tEVENT\t" + kind);
    }
    std::string show(const std::string &lease, uint64_t revision, const std::string &text,
                     const std::string &wave, const std::string &state) {
        if (!valid(lease))
            return "stale";
        if (revision <= revision_)
            return "accepted";
        revision_ = revision;
        // Some frontends commit their cached preedit on focus-out without
        // asking the server. Use our non-focusable preview only in that case.
        if (!editing_ && !(context_->contextCaps & CAPACITY_CLIENT_UNFOCUS_COMMIT)) {
            auto *preedit = FcitxInputStateGetClientPreedit(input());
            FcitxMessagesSetMessageCount(preedit, 0);
            FcitxMessagesAddMessageAtLast(
                preedit, static_cast<FcitxMessageType>(MSG_INPUT | MSG_DONOT_COMMIT_WHEN_UNFOCUS),
                "%s", text.c_str());
            FcitxInputStateSetClientCursorPos(input(), static_cast<int>(text.size()));
            FcitxInstanceUpdatePreedit(instance_, context_);
        }
        int x = 0, y = 0;
        FcitxInstanceGetWindowPosition(instance_, context_, &x, &y);
        panel_.show(x, y, text, wave, state);
        return "accepted";
    }
    std::string commit(const std::string &lease, const std::string &id, const std::string &text) {
        if (id.empty())
            return "failed";
        auto found = commits_.find(id);
        if (found != commits_.end())
            return found->second == std::make_pair(lease, text) ? "accepted" : "failed";
        if (!valid(lease))
            return "stale";
        if (editing_) {
            std::string surrounding;
            unsigned int cursor, anchor;
            if (!surroundingText(surrounding, cursor, anchor) ||
                surrounding != selectedSurrounding_ || cursor != selectedCursor_ ||
                anchor != selectedAnchor_)
                return "stale";
            int x = 0, y = 0;
            FcitxInstanceGetWindowPosition(instance_, context_, &x, &y);
            if (x != selectedX_ || y != selectedY_)
                return "stale";
        }
        emptyPreedit();
        commits_.emplace(id, std::make_pair(lease, text));
        authorized_ = true;
        FcitxInstanceCommitString(instance_, context_, text.c_str());
        authorized_ = false;
        return "accepted";
    }
    void theme(const std::vector<std::string> &f) {
        PanelStyle style;
        const auto split = f[2].find(':');
        const auto name = f[2].substr(0, split), mode = f[2].substr(split + 1);
        if ((name != "github" && name != "material" && name != "nord" && name != "rose-pine") ||
            (mode != "light" && mode != "dark"))
            throw std::invalid_argument("theme");
        style.name = f[2];
        size_t used;
        style.scale = std::stod(f[3], &used);
        if (used != f[3].size() || !std::isfinite(style.scale) || style.scale < .8 ||
            style.scale > 1.5)
            throw std::invalid_argument("scale");
        auto number = [](const std::string &value, int low, int high) {
            size_t used;
            const int result = std::stoi(value, &used);
            if (used != value.size() || result < low || result > high)
                throw std::invalid_argument("size");
            return result;
        };
        style.width = number(f[4], 480, 960);
        style.fontSize = number(f[5], 12, 22);
        style.radius = number(f[6], 8, 24);
        if (f.size() == 10)
            style.placement(f[8], f[9]);
        std::istringstream palette(f[7]);
        std::string rgb;
        size_t index = 0;
        while (std::getline(palette, rgb, ',')) {
            if (index >= style.colors.size() || rgb.size() != 6 ||
                rgb.find_first_not_of("0123456789abcdefABCDEF") != std::string::npos)
                throw std::invalid_argument("palette");
            style.colors[index++] = static_cast<uint32_t>(std::stoul(rgb, nullptr, 16));
        }
        if (index != style.colors.size())
            throw std::invalid_argument("palette");
        panel_.configure(style);
    }
    bool surroundingText(std::string &text, unsigned int &cursor, unsigned int &anchor) const {
        char *raw = nullptr;
        if (!FcitxInstanceGetSurroundingText(instance_, context_, &raw, &cursor, &anchor))
            return false;
        if (raw) {
            text = raw;
            free(raw);
        }
        return text.size() <= 512 * 1024;
    }
    std::string selection(const std::string &lease) {
        if (!valid(lease))
            return "stale";
        std::string text;
        unsigned int cursor, anchor;
        if (!surroundingText(text, cursor, anchor))
            return "unsupported";
        std::vector<size_t> positions;
        for (size_t i = 0; i < text.size(); ++i)
            if ((static_cast<unsigned char>(text[i]) & 0xc0) != 0x80)
                positions.push_back(i);
        positions.push_back(text.size());
        if (cursor >= positions.size() || anchor >= positions.size())
            return "unsupported";
        const auto start = positions[std::min(cursor, anchor)],
                   end = positions[std::max(cursor, anchor)];
        if (end - start > 64000)
            return "unsupported";
        editing_ = start != end;
        selectedSurrounding_ = text;
        selectedCursor_ = cursor;
        selectedAnchor_ = anchor;
        FcitxInstanceGetWindowPosition(instance_, context_, &selectedX_, &selectedY_);
        return encode(text.substr(start, end - start));
    }
    std::string request(const std::string &line) {
        const auto f = protocolFields(line);
        const auto id = f.empty() ? "0" : f[0];
        try {
            if (f.size() < 2)
                throw std::invalid_argument("request");
            std::string result;
            if (f[1] == "BEGIN" && f.size() == 2)
                result = begin();
            else if (f[1] == "VALID" && f.size() == 3)
                result = valid(f[2]) ? "true" : "false";
            else if (f[1] == "SELECTION" && f.size() == 3)
                result = selection(f[2]);
            else if (f[1] == "PANEL_BACKEND" && f.size() == 2)
                result = "x11";
            else if (f[1] == "KEYBOARD_PREEDIT" && f.size() == 3 && (f[2] == "0" || f[2] == "1"))
                result = "accepted"; // Fcitx4 retains the keyboard engine's own preedit policy.
            else if (f[1] == "THEME" && (f.size() == 8 || f.size() == 10)) {
                theme(f);
                result = "accepted";
            } else if (f[1] == "CLEAR" && f.size() == 3) {
                if (f[2] == lease_)
                    clear();
                result = "accepted";
            } else if (f[1] == "SHOW" && f.size() == 7)
                result = show(f[2], std::stoull(f[3]), decode(f[4]), decode(f[5]), decode(f[6]));
            else if (f[1] == "COMMIT" && f.size() == 5)
                result = commit(f[2], f[3], decode(f[4]));
            else if (f[1] == "NOTICE" && f.size() == 4) {
                result = "stale";
                if (valid(f[2])) {
                    const auto message = decode(f[3]);
                    int x = 0, y = 0;
                    FcitxInstanceGetWindowPosition(instance_, context_, &x, &y);
                    clear(); // No failure message is published as client preedit.
                    panel_.show(x, y, message, "", "needs-config");
                    FcitxInstanceRemoveTimeoutByFunc(instance_, hideNotice);
                    FcitxInstanceAddTimeout(instance_, 8000, hideNotice, this);
                    result = "accepted";
                }
            } else
                throw std::invalid_argument("command");
            return id + "\tOK\t" + result;
        } catch (const std::exception &) {
            return id + "\tERROR\tinvalid-request";
        }
    }
    bool key(FcitxKeySym sym, unsigned int state, bool released) {
        auto physical = FcitxInputStateGetKeyCode(input());
        if (!physical)
            physical = panel_.keyCode(sym);
        const auto code = physical ? physical : sym + 0x10000u;
        if (!released && lease_.empty() && !consumed_.count(code))
            panel_.hide();
        const bool shift = sym == FcitxKey_Shift_L || sym == FcitxKey_Shift_R;
        const bool alt = sym == FcitxKey_Alt_L || sym == FcitxKey_Alt_R;
        if (!released) {
            // An ordered unmodified event also recovers a modifier release
            // missed while this frontend did not own focus.
            if (!(state & FcitxKeyState_Shift))
                blockedShortcuts_ &= ~FcitxKeyState_Shift;
            if (!(state & FcitxKeyState_Alt))
                blockedShortcuts_ &= ~FcitxKeyState_Alt;
        }
        if (shift || alt) {
            auto &held = shift ? shifts_ : alts_;
            if (released)
                held.erase(code);
            else
                held.insert(code);
            if (released && held.empty())
                blockedShortcuts_ &= ~(shift ? FcitxKeyState_Shift : FcitxKeyState_Alt);
        }
        if (released && consumed_.count(code)) {
            // Classic X11 autorepeat generates synthetic release/press pairs.
            // Keep suppression until the physical key is actually released.
            if (!panel_.keyHeld(physical))
                consumed_.erase(code);
            return true;
        }
        if (!released && consumed_.count(code))
            return true;
        if (!server_ || !server_->connected())
            return false;
        constexpr unsigned int modifiers = FcitxKeyState_Shift | FcitxKeyState_Ctrl |
                                           FcitxKeyState_Alt | FcitxKeyState_Super |
                                           FcitxKeyState_Hyper;
        const bool shortcut =
            (sym == FcitxKey_space && (state & modifiers) == FcitxKeyState_Shift) ||
            ((sym == FcitxKey_z || sym == FcitxKey_Z) && (state & modifiers) == FcitxKeyState_Alt);
        if (!released && shortcut) {
            if (sym == FcitxKey_space)
                consumed_.insert(shifts_.begin(), shifts_.end());
            consumed_.insert(code);
            // Fcitx4's public filter API has no event timestamp/repeat flag.
            // XQueryKeymap observes *now*, not the queued event: after a stall,
            // every old repeat release can look like the final physical one.
            // Rearm a chord on its ordered modifier release, never that query.
            const auto modifier = sym == FcitxKey_space ? FcitxKeyState_Shift : FcitxKeyState_Alt;
            if (!(blockedShortcuts_ & modifier)) {
                blockedShortcuts_ |= modifier;
                notify(sym == FcitxKey_space ? "toggle" : "command");
            }
            return true;
        }
        if (valid(lease_)) {
            if (!released) {
                consumed_.insert(code);
                if (sym == FcitxKey_Escape) {
                    notify("cancel");
                    clear();
                } else if (sym == FcitxKey_Return)
                    notify("pause");
            }
            return true;
        }
        return false;
    }
    static boolean press(void *self, FcitxKeySym sym, unsigned int state,
                         INPUT_RETURN_VALUE *result) {
        if (!static_cast<Bridge *>(self)->key(sym, state, false))
            return false;
        *result = IRV_DO_NOTHING;
        return true;
    }
    static boolean release(void *self, FcitxKeySym sym, unsigned int state,
                           INPUT_RETURN_VALUE *result) {
        if (!static_cast<Bridge *>(self)->key(sym, state, true))
            return false;
        *result = IRV_DO_NOTHING;
        return true;
    }
    static void hideNotice(void *self) { static_cast<Bridge *>(self)->panel_.hide(); }
    static void lost(void *self) {
        auto *bridge = static_cast<Bridge *>(self);
        bridge->panel_.hide();
        bridge->invalidate();
    }
    static void stateChanged(void *self, FcitxInputContext *context) {
        auto *bridge = static_cast<Bridge *>(self);
        if (bridge->context_ == context)
            bridge->invalidate();
    }
    static char *filterCommit(void *self, const char *) {
        const auto *bridge = static_cast<Bridge *>(self);
        return !bridge->lease_.empty() && !bridge->authorized_ ? strdup("") : nullptr;
    }
    FcitxInstance *instance_;
    int lifeSlot_ = -1;
    FcitxInputContext *context_ = nullptr;
    std::weak_ptr<int> life_;
    X11Panel panel_;
    std::unique_ptr<UnixServer> server_;
    std::set<unsigned int> consumed_, shifts_, alts_;
    unsigned int blockedShortcuts_ = 0;
    std::map<std::string, std::pair<std::string, std::string>> commits_;
    std::string lease_, socketPath_;
    uint64_t epoch_ = 0, revision_ = 0;
    bool authorized_ = false;
    bool editing_ = false;
    std::string selectedSurrounding_;
    unsigned int selectedCursor_ = 0, selectedAnchor_ = 0;
    int selectedX_ = 0, selectedY_ = 0;
};

void *create(FcitxInstance *instance) {
    const auto *session = std::getenv("XDG_SESSION_TYPE");
    if (!std::getenv("DISPLAY") || (session && std::string(session) == "wayland"))
        return nullptr;
    try {
        return new Bridge(instance);
    } catch (const std::exception &error) {
        std::cerr << "OpenASRInput: " << error.what() << '\n';
        return nullptr;
    }
}
void watch(void *self) { static_cast<Bridge *>(self)->watch(); }
void process(void *self) { static_cast<Bridge *>(self)->process(); }
void destroy(void *self) { delete static_cast<Bridge *>(self); }
void reload(void *self) {
    try {
        static_cast<Bridge *>(self)->reload();
    } catch (const std::exception &error) {
        std::cerr << "OpenASRInput: " << error.what() << '\n';
    }
}
} // namespace openasrinput

extern "C" {
FCITX_DEFINE_PLUGIN(fcitx_openasrinput, module, FcitxModule) = {
    openasrinput::create, openasrinput::watch, openasrinput::process, openasrinput::destroy,
    openasrinput::reload};
}
