#include "chord_guard.h"
#include "cursor_bridge.h"
#include "keyboard_policy.h"

#include <fcitx-config/rawconfig.h>
#include <fcitx-utils/event.h>
#include <fcitx/addonmanager.h>
#include <fcitx/inputcontextmanager.h>
#include <fcitx/inputpanel.h>
#include <fcitx/instance.h>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
void require(bool condition, const char *message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

class TestContext final : public fcitx::InputContext {
  public:
    explicit TestContext(fcitx::InputContextManager &manager)
        : InputContext(manager, "OpenASRInputNativeTest") {
        setCapabilityFlags(fcitx::CapabilityFlags(fcitx::CapabilityFlag::Preedit) |
                           fcitx::CapabilityFlag::FormattedPreedit);
        setCursorRect(fcitx::Rect().setPosition(80, 120).setSize(2, 24));
        created();
    }
    ~TestContext() override { destroy(); }
    const char *frontend() const override { return "openasrinput-test"; }
    std::vector<std::string> commits, preedits;
    std::vector<fcitx::Key> forwards;
    int deletions = 0;

  protected:
    void commitStringImpl(const std::string &text) override { commits.push_back(text); }
    void deleteSurroundingTextImpl(int, unsigned int) override { ++deletions; }
    void forwardKeyImpl(const fcitx::ForwardKeyEvent &key) override {
        forwards.push_back(key.rawKey());
    }
    void updatePreeditImpl() override {
        preedits.push_back(inputPanel().clientPreedit().toString());
    }
};

bool key(TestContext &ic, fcitx::KeySym sym, bool release = false,
         fcitx::KeyStates states = fcitx::KeyStates()) {
    fcitx::KeyEvent event(&ic, fcitx::Key(sym, states), release);
    return ic.keyEvent(event);
}

void testSink(fcitx::Instance &instance, TestContext &ic) {
    openasrinput::CursorBridge bridge;
    bridge.attach(instance);
    auto lease = bridge.begin(&ic);
    require(ic.cursorRect().width() == 2 && ic.cursorRect().height() == 24,
            "cursor geometry does not use position/size semantics");
    require(!lease.empty(), "cannot acquire focused native context");
    require(bridge.show(lease, 1, "我要去工圆", "▁▂▄▆█▆▄▂", "listening") == "accepted",
            "first preedit failed");
    require(ic.inputPanel().clientPreedit().toString() == "我要去工圆", "initial preedit missing");
    require(ic.inputPanel().clientPreedit().toStringForCommit().empty(),
            "ASR preview permits client-side reset/unfocus commit");
    openasrinput::keyboardPreeditPolicy(instance, &ic, false, true);
    require(ic.inputPanel().clientPreedit().toString() == "我要去工圆",
            "keyboard compatibility setting suppressed voice preedit");
    require(ic.commits.empty(), "preview unexpectedly committed");
    require(bridge.show(lease, 2, "我要去公园。", "▂▄▆█▆▄▂▁", "listening") == "accepted",
            "revision failed");
    require(ic.inputPanel().clientPreedit().toString() == "我要去公园。",
            "revision appended instead of replaced");
    require(ic.inputPanel().clientPreedit().cursor() == 18,
            "UTF8 preedit cursor is not a byte offset");
    require(ic.inputPanel().auxUp().toString() == "语音 ▂▄▆█▆▄▂▁\n我要去公园。",
            "waveform and preview are not separate rows");
    require(ic.inputPanel().preedit().empty(), "popup duplicates client text on its waveform row");
    require(ic.inputPanel().auxDown().toString() == "Shift+Space 暂停/恢复 · Enter 收尾 · Esc 取消",
            "shortcut hints are not on the third row");
    const auto preeditCount = ic.preedits.size();
    require(bridge.show(lease, 3, "我要去公园。", "▁▁▁▃▅▇█▂", "listening") == "accepted",
            "audio-only frame failed");
    require(ic.preedits.size() == preeditCount, "audio-only frame resent application preedit");
    require(ic.inputPanel().auxUp().toString().starts_with("语音 ▁▁▁▃▅▇█▂\n"),
            "audio-only frame did not update the panel");
    bridge.show(lease, 1, "过期文字", "▁", "listening");
    require(ic.inputPanel().clientPreedit().toString() == "我要去公园。",
            "stale revision overwritten");
    require(bridge.commit(lease, "c1", "我要去公园。") == "accepted", "final commit failed");
    require(ic.inputPanel().clientPreedit().empty(), "preedit not cleared on commit");
    require(bridge.commit(lease, "c1", "我要去公园。") == "accepted",
            "duplicate commit not acknowledged");
    require(bridge.commit(lease, "c1", "不准回改") == "failed",
            "commit identifier not payload-bound");
    require(ic.commits == std::vector<std::string>{"我要去公园。"},
            "final was not submitted exactly once");
    require(ic.deletions == 0, "preedit revision deleted application text");
    require(bridge.show(lease, 4, "我要去公园。", "▁▃▅", "listening") == "accepted",
            "identical next utterance preview failed");
    require(ic.inputPanel().clientPreedit().toString() == "我要去公园。",
            "identical next utterance did not restore cleared preedit");
    bridge.clear(lease);
    require(ic.inputPanel().empty(), "voice panel not released");

    auto second = bridge.begin(&ic);
    require(second != lease, "lease reused");
    bridge.show(second, 1, "失焦前预览", "▁▃▆", "listening");
    bridge.invalidate(&ic); // Native addon does this before core focus-out handling.
    ic.focusOut();
    ic.focusIn();
    require(!bridge.valid(second), "refocusing resurrected the old lease");
    require(bridge.commit(second, "c2", "迟到结果") == "stale", "stale result accepted");
    require(ic.commits.size() == 1, "unfocus automatically committed an unconfirmed preview");
    require(ic.inputPanel().empty(), "unfocus left the waveform/preedit behind");
    std::cout
        << "PASS native cursor: inline replacement, final once, waveform panel, focus lease\n";
}

void testChord(fcitx::Instance &instance, TestContext &ic) {
    int toggles = 0;
    openasrinput::ChordGuard guard(instance, [&](auto *) { ++toggles; });
    auto watcher = instance.watchEvent(
        fcitx::EventType::InputContextKeyEvent, fcitx::EventWatcherPhase::PreInputMethod,
        [&](fcitx::Event &event) { guard.handle(static_cast<fcitx::KeyEvent &>(event)); });
    int shiftEvents = 0, altEvents = 0;
    auto observer = instance.watchEvent(
        fcitx::EventType::InputContextKeyEvent, fcitx::EventWatcherPhase::InputMethod,
        [&](fcitx::Event &base) {
            auto &event = static_cast<fcitx::KeyEvent &>(base);
            if (event.rawKey().sym() == FcitxKey_Shift_L ||
                event.rawKey().sym() == FcitxKey_Shift_R) {
                ++shiftEvents;
            }
            if (event.rawKey().sym() == FcitxKey_Alt_L || event.rawKey().sym() == FcitxKey_Alt_R)
                ++altEvents;
        });
    for (auto sym : {FcitxKey_Shift_L, FcitxKey_Shift_R}) {
        key(ic, sym);
        key(ic, FcitxKey_space, false, fcitx::KeyState::Shift);
        key(ic, FcitxKey_space, false,
            fcitx::KeyStates(fcitx::KeyState::Shift) | fcitx::KeyState::Repeat);
        key(ic, FcitxKey_space, true, fcitx::KeyState::Shift);
        key(ic, sym, true);
    }
    require(toggles == 2 && shiftEvents == 0, "voice chord/repeat leaked Shift events to RIME");
    key(ic, FcitxKey_Shift_L);
    key(ic, FcitxKey_Shift_L, true);
    require(shiftEvents == 2, "Shift tap was not replayed through public event pipeline");
    key(ic, FcitxKey_Shift_L);
    key(ic, FcitxKey_Shift_L, true); // Restore RIME's original ASCII setting.
    key(ic, FcitxKey_Shift_L);
    key(ic, FcitxKey_A, false, fcitx::KeyState::Shift);
    key(ic, FcitxKey_A, true, fcitx::KeyState::Shift);
    key(ic, FcitxKey_Shift_L, true);
    require(shiftEvents == 6, "uppercase sequence did not retain Shift event order");
    key(ic, FcitxKey_Alt_L);
    require(key(ic, FcitxKey_z, false, fcitx::KeyState::Alt), "Alt+Z was not consumed");
    key(ic, FcitxKey_z, false, fcitx::KeyStates(fcitx::KeyState::Alt) | fcitx::KeyState::Repeat);
    guard.reset(&ic);
    require(key(ic, FcitxKey_z, true), "Alt+Z release leaked after context change");
    key(ic, FcitxKey_Alt_L, true);
    require(toggles == 3, "Alt+Z repeated or did not toggle");
    key(ic, FcitxKey_z, false, fcitx::KeyStates(fcitx::KeyState::Alt) | fcitx::KeyState::Ctrl);
    key(ic, FcitxKey_z, true);
    require(toggles == 3, "Ctrl+Alt+Z should not toggle voice");
    auto timed = [&](fcitx::KeySym sym, bool release, int time,
                     fcitx::KeyStates states = fcitx::KeyStates()) {
        fcitx::KeyEvent event(&ic, fcitx::Key(sym, states), release, time);
        return ic.keyEvent(event);
    };
    timed(FcitxKey_Alt_L, false, 100);
    timed(FcitxKey_z, false, 110, fcitx::KeyState::Alt);
    timed(FcitxKey_z, true, 610, fcitx::KeyState::Alt);
    timed(FcitxKey_z, false, 610, fcitx::KeyState::Alt);
    timed(FcitxKey_z, true, 650, fcitx::KeyState::Alt);
    timed(FcitxKey_Alt_L, true, 660);
    require(toggles == 4, "synthetic repeat release/press generated a second toggle");
    require(altEvents == 0, "voice Alt+Z leaked Alt into application menus");
    std::cout << "PASS native chord: both Shift keys, repeat, public replay, normal uppercase\n";
}

void testRimeTyping(fcitx::Instance &instance, TestContext &ic) {
    openasrinput::ChordGuard guard(instance, [](auto *) {});
    auto watcher = instance.watchEvent(
        fcitx::EventType::InputContextKeyEvent, fcitx::EventWatcherPhase::PreInputMethod,
        [&](fcitx::Event &event) { guard.handle(static_cast<fcitx::KeyEvent &>(event)); });
    auto *rime = instance.addonManager().addon("rime");
    require(rime != nullptr, "RIME addon unavailable");
    for (const auto &mode : {"ComposingText", "CommitPreview", "No"}) {
        fcitx::RawConfig configuration;
        configuration.setValueByPath("PreeditMode", mode);
        rime->setConfig(configuration); // Only the isolated HOME is written.
        for (bool inlinePreedit : {true, false}) {
            auto preeditWatcher = instance.watchEvent(
                fcitx::EventType::InputContextUpdatePreedit,
                fcitx::EventWatcherPhase::PreInputMethod, [&](fcitx::Event &base) {
                    auto &event = static_cast<fcitx::InputContextEvent &>(base);
                    openasrinput::keyboardPreeditPolicy(instance, event.inputContext(),
                                                        inlinePreedit, false);
                });
            for (bool orderFix : {false, true}) {
                auto flags = fcitx::CapabilityFlags(fcitx::CapabilityFlag::Preedit) |
                             fcitx::CapabilityFlag::FormattedPreedit;
                if (orderFix) {
                    flags |= fcitx::CapabilityFlag::KeyEventOrderFix;
                }
                ic.setCapabilityFlags(flags);
                for (const auto &sample :
                     {std::pair<std::string, std::string>{"nihao", "你好"}, {"chongfu", "重复"}}) {
                    for (int selection = 0; selection < 3; ++selection) {
                        ic.reset();
                        ic.commits.clear();
                        for (char character : sample.first) {
                            auto sym = fcitx::Key::keySymFromString(std::string(1, character));
                            key(ic, sym);
                            key(ic, sym, true);
                        }
                        require(ic.inputPanel().candidateList() &&
                                    ic.inputPanel().candidateList()->size() > 0,
                                "normal RIME candidates disappeared");
                        if (!inlinePreedit) {
                            require(ic.inputPanel().clientPreedit().empty(),
                                    "compatibility mode left inline preedit");
                            require(!ic.inputPanel().preedit().empty(),
                                    "compatibility mode hid pinyin from the candidate panel");
                            const auto pinyin = ic.inputPanel().preedit().toString();
                            require(pinyin.find(sample.first == "nihao" ? "ni" : "chong") !=
                                        std::string::npos,
                                    "candidate panel shows converted text instead of pinyin");
                        }
                        if (selection == 2) {
                            // Public candidate select() is the click-selection path.
                            auto candidates = ic.inputPanel().candidateList();
                            candidates->candidate(0).select(&ic);
                        } else {
                            const auto sym = selection == 0 ? FcitxKey_space : FcitxKey_1;
                            key(ic, sym);
                            key(ic, sym, true);
                        }
                        require(ic.commits == std::vector<std::string>{sample.second},
                                "normal RIME selection was not committed exactly once");
                        require(ic.inputPanel().preedit().empty() &&
                                    ic.inputPanel().clientPreedit().empty(),
                                "selected word left stale pinyin behind");
                    }
                }
            }
        }
    }
    fcitx::RawConfig configuration;
    configuration.setValueByPath("PreeditMode", "ComposingText");
    rime->setConfig(configuration);
    ic.reset();
    ic.commits.clear();
    std::cout << "PASS RIME text: visible pinyin, space/digit/click selection, single commit, "
                 "inline/panel-only, frontend order fix\n";
}

void testEnglishModeVoice(fcitx::Instance &instance, TestContext &ic) {
    ic.reset();
    ic.commits.clear();
    key(ic, FcitxKey_Shift_L);
    key(ic, FcitxKey_Shift_L, true);
    key(ic, FcitxKey_n);
    key(ic, FcitxKey_n, true);
    require(ic.inputPanel().preedit().empty() && ic.inputPanel().clientPreedit().empty(),
            "Shift tap did not enter an ASCII keyboard state");
    openasrinput::CursorBridge bridge;
    bridge.attach(instance);
    auto lease = bridge.begin(&ic);
    require(!lease.empty(), "ASCII keyboard state rejected voice context");
    require(bridge.show(lease, 1, "英文状态仍可语音", "▁▆▁", "listening") == "accepted",
            "ASCII state rejected voice preedit");
    require(bridge.commit(lease, "english-mode-voice", "英文状态仍可语音") == "accepted",
            "ASCII state rejected voice final");
    require(ic.commits == std::vector<std::string>{"英文状态仍可语音"},
            "ASCII voice commit duplicated");
    bridge.clear(lease);
    key(ic, FcitxKey_Shift_L);
    key(ic, FcitxKey_Shift_L, true);
    ic.commits.clear();
    std::cout << "PASS RIME ASCII state: independent voice preedit and final, engine unchanged\n";
}
} // namespace

int main(int argc, char **argv) {
    const bool rime = argc == 2 && std::string(argv[1]) == "--rime";
    std::vector<std::string> arguments = {argv[0], "-D", "--disable=all"};
    if (rime) {
        arguments.push_back("--enable=keyboard,rime");
    }
    std::vector<char *> pointers;
    for (auto &arg : arguments) {
        pointers.push_back(arg.data());
    }
    fcitx::Instance instance(static_cast<int>(pointers.size()), pointers.data());
    instance.addonManager().registerDefaultLoader(nullptr);
    instance.initialize();
    TestContext ic(instance.inputContextManager());
    ic.focusIn();
    if (!rime) {
        try {
            testSink(instance, ic);
            testChord(instance, ic);
            return 0;
        } catch (const std::exception &error) {
            std::cerr << error.what() << '\n';
            return 1;
        }
    }
    instance.setCurrentInputMethod(&ic, "rime", true);
    int attempts = 0;
    int result = 0;
    auto timer = instance.eventLoop().addTimeEvent(
        CLOCK_MONOTONIC, fcitx::now(CLOCK_MONOTONIC) + 200000, 0,
        [&](fcitx::EventSourceTime *source, uint64_t) {
            try {
                require(instance.inputMethod(&ic) == "rime",
                        "isolated profile did not select RIME");
                key(ic, FcitxKey_n);
                if (ic.inputPanel().preedit().empty() && ic.inputPanel().clientPreedit().empty()) {
                    if (++attempts > 400) {
                        throw std::runtime_error(
                            "RIME deployment/Chinese preedit did not become ready");
                    }
                    ic.reset();
                    source->setNextInterval(200000);
                    source->setOneShot();
                    return true;
                }
                openasrinput::CursorBridge bridge;
                require(bridge.begin(&ic).empty(), "voice took over an existing RIME candidate");
                ic.reset();
                ic.commits.clear();
                testRimeTyping(instance, ic);
                testEnglishModeVoice(instance, ic);
                testSink(instance, ic);
                testChord(instance, ic);
                std::cout << "PASS isolated fcitx5-rime with copied rime_ice configuration\n";
                instance.eventLoop().exit();
            } catch (const std::exception &error) {
                std::cerr << error.what() << '\n';
                result = 1;
                instance.eventLoop().exit();
            }
            return false;
        });
    timer->setOneShot();
    instance.setRunning(true);
    instance.eventLoop().exec();
    instance.setRunning(false);
    return result;
}
