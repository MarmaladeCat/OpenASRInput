// A disposable native frontend for black-box addon/daemon tests. No desktop UI.
#include "compat.h"
#include "socket_server.h"

#include <cstdlib>
#include <fcitx/addonmanager.h>
#include <fcitx/inputcontext.h>
#include <fcitx/inputcontextmanager.h>
#include <fcitx/inputpanel.h>
#include <fcitx/instance.h>
#include <fcitx/surroundingtext.h>
#include <iostream>
#include <sstream>
#include <string>
#include <unistd.h>
#include <vector>

class Context final : public fcitx::InputContext {
  public:
    explicit Context(fcitx::InputContextManager &manager)
        : InputContext(manager, "OpenASRInputIPCFixture") {
        setCapabilityFlags(fcitx::CapabilityFlag::Preedit);
        setCursorRect(fcitx::Rect().setPosition(80, 120).setSize(2, 24));
        created();
    }
    ~Context() override { destroy(); }
    const char *frontend() const override { return "openasrinput-test"; }
    std::vector<std::string> commits;
    int deletions = 0;

  protected:
    void commitStringImpl(const std::string &text) override {
        // The fixture records document insertions. Core may send an empty
        // commit after the addon filters its automatic unfocus commit.
        if (!text.empty()) {
            commits.push_back(text);
        }
    }
    void deleteSurroundingTextImpl(int, unsigned int) override { ++deletions; }
    void forwardKeyImpl(const fcitx::ForwardKeyEvent &) override {}
    void updatePreeditImpl() override {}
};

int main(int argc, char **argv) {
    if (argc == 2 && std::string(argv[1]) == "--addon-dir") {
        std::cout << openasrinput::compat::addonDirectory() << std::endl;
        return 0;
    }
    fcitx::Instance instance(argc, argv);
    instance.addonManager().registerDefaultLoader(nullptr);
    instance.initialize();
    if (!instance.addonManager().addon("openasrinput")) {
        std::cerr << "native addon did not load\n";
        return 1;
    }
    if (std::getenv("DISPLAY") &&
        (!instance.addonManager().addon("xcb") || !instance.addonManager().addon("classicui"))) {
        std::cerr << "isolated visual test requires the real XCB and Classic UI addons\n";
        return 1;
    }
    Context first(instance.inputContextManager()), second(instance.inputContextManager());
    if (std::getenv("DISPLAY")) {
        auto *group = instance.defaultFocusGroup("x11:");
        first.setFocusGroup(group);
        second.setFocusGroup(group);
    }
    first.focusIn();
    Context *focused = &first;
    bool lastKeyAccepted = false;
    std::string pending;
    auto input = instance.eventLoop().addIOEvent(
        STDIN_FILENO, fcitx::IOEventFlag::In, [&](auto *, int fd, auto) {
            char buffer[4096];
            auto size = ::read(fd, buffer, sizeof(buffer));
            if (size <= 0) {
                instance.eventLoop().exit();
                return false;
            }
            pending.append(buffer, static_cast<size_t>(size));
            size_t end;
            while ((end = pending.find('\n')) != std::string::npos) {
                auto command = pending.substr(0, end);
                pending.erase(0, end + 1);
                if (command == "SNAPSHOT") {
                    instance.flushUI();
                    std::cout << "S\t"
                              << openasrinput::hexEncode(
                                     focused->inputPanel().clientPreedit().toString())
                              << '\t'
                              << openasrinput::hexEncode(focused->inputPanel().auxUp().toString())
                              << '\t' << focused->deletions;
                    for (const auto &text : focused->commits) {
                        std::cout << '\t' << openasrinput::hexEncode(text);
                    }
                    std::cout << std::endl;
                } else if (command == "FOCUS1" || command == "FOCUS2") {
                    focused->focusOut();
                    focused = command == "FOCUS1" ? &first : &second;
                    focused->focusIn();
                    std::cout << "OK" << std::endl;
                } else if (command.starts_with("SURROUNDING ")) {
                    std::string text;
                    unsigned int cursor, anchor;
                    std::istringstream values(command.substr(12));
                    values >> text >> cursor >> anchor;
                    focused->surroundingText().setText(openasrinput::hexDecode(text), cursor,
                                                       anchor);
                    focused->updateSurroundingText();
                    std::cout << "OK" << std::endl;
                } else if (command == "RESET") {
                    focused->reset();
                    std::cout << "OK" << std::endl;
                } else if (command == "PASSWORD") {
                    focused->setCapabilityFlags(focused->capabilityFlags() |
                                                fcitx::CapabilityFlag::Password);
                    std::cout << "OK" << std::endl;
                } else if (command == "EDITABLE") {
                    focused->setCapabilityFlags(fcitx::CapabilityFlag::Preedit);
                    std::cout << "OK" << std::endl;
                } else if (command.starts_with("DOWN ") || command.starts_with("UP ")) {
                    const bool release = command.starts_with("UP ");
                    fcitx::KeyEvent event(focused, fcitx::Key(command.substr(release ? 3 : 5)),
                                          release);
                    lastKeyAccepted = focused->keyEvent(event);
                    std::cout << "OK" << std::endl;
                } else if (command == "KEYRESULT") {
                    std::cout << (lastKeyAccepted ? "1" : "0") << std::endl;
                } else if (command == "RELATIVE") {
                    focused->setCapabilityFlags(
                        fcitx::CapabilityFlags(fcitx::CapabilityFlag::Preedit) |
                        fcitx::CapabilityFlag::RelativeRect);
                    std::cout << "OK" << std::endl;
                } else if (command == "CAP_REPEAT") {
                    focused->setCapabilityFlags(focused->capabilityFlags() |
                                                fcitx::CapabilityFlag::ReportKeyRepeat);
                    std::cout << "OK" << std::endl;
                } else if (command.starts_with("RECT ") || command.starts_with("RECT_ONLY ")) {
                    int x, y, width, height;
                    const bool only = command.starts_with("RECT_ONLY ");
                    std::istringstream position(command.substr(only ? 10 : 5));
                    if (position >> x >> y >> width >> height) {
                        focused->setCursorRect(
                            fcitx::Rect().setPosition(x, y).setSize(width, height));
                        if (!only) {
                            focused->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel);
                            instance.flushUI();
                        }
                    }
                    std::cout << "OK" << std::endl;
                } else if (command.starts_with("SCALE ")) {
                    double scale;
                    std::istringstream value(command.substr(6));
                    if (value >> scale) {
                        focused->setCursorRect(focused->cursorRect(), scale);
                        focused->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel);
                        instance.flushUI();
                    }
                    std::cout << "OK" << std::endl;
                } else {
                    instance.eventLoop().exit();
                    std::cout << "OK" << std::endl;
                }
            }
            return true;
        });
    std::cout << "READY" << std::endl;
    instance.setRunning(true);
    instance.eventLoop().exec();
    instance.setRunning(false);
    return 0;
}
