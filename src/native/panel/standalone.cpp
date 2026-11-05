// Private socketpair transport for non-Fcitx input adapters. No input ownership.
#include "protocol_fields.h"
#include "voice_panel.h"

#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <sys/socket.h>
#include <unistd.h>
#include <vector>

namespace {
std::string decode(const std::string &text) {
    if (text.size() % 2)
        throw std::invalid_argument("hex");
    std::string result;
    for (size_t i = 0; i < text.size(); i += 2) {
        size_t used;
        auto value = std::stoul(text.substr(i, 2), &used, 16);
        if (used != 2)
            throw std::invalid_argument("hex");
        result += static_cast<char>(value);
    }
    return result;
}
} // namespace

int main(int argc, char **argv) {
    if (argc != 3 || std::string(argv[1]) != "--fd")
        return 2;
    const int fd = std::stoi(argv[2]);
    fcitx::EventLoop loop;
    openasrinput::VoicePanel panel(loop);
    openasrinput::PanelContext context;
    if (const auto *display = std::getenv("DISPLAY"))
        context.display = std::string("x11:") + display;
    std::string input, text, wave, state;
    auto io = loop.addIOEvent(fd, fcitx::IOEventFlag::In, [&](auto *, int, auto) {
        char buffer[8192];
        auto count = ::recv(fd, buffer, sizeof(buffer), 0);
        if (count <= 0) {
            loop.exit();
            return false;
        }
        input.append(buffer, count);
        if (input.size() > 1024 * 1024) {
            loop.exit();
            return false;
        }
        size_t end;
        while ((end = input.find('\n')) != std::string::npos) {
            auto fields = openasrinput::protocolFields(input.substr(0, end));
            input.erase(0, end + 1);
            std::string result;
            try {
                if (fields[0] == "THEME" && fields.size() == 9) {
                    openasrinput::PanelStyle style;
                    style.name = fields[1];
                    style.scale = std::clamp(std::stod(fields[2]), 0.5, 3.0);
                    style.width = std::clamp(std::stoi(fields[3]), 280, 1600);
                    style.fontSize = std::clamp(std::stoi(fields[4]), 10, 32);
                    style.radius = std::clamp(std::stoi(fields[5]), 0, 48);
                    auto colors = openasrinput::protocolFields(fields[6], ',');
                    if (colors.size() != style.colors.size())
                        throw std::invalid_argument("colors");
                    for (size_t i = 0; i < colors.size(); ++i)
                        style.colors[i] = std::stoul(colors[i], nullptr, 16);
                    style.placement(fields[7], fields[8]);
                    panel.setStyle(style);
                } else if (fields[0] == "SHOW" && fields.size() == 4) {
                    text = decode(fields[1]);
                    wave = decode(fields[2]);
                    state = decode(fields[3]);
                    context.focused = true;
                    panel.show(context, text, wave, state);
                } else if (fields[0] == "ANCHOR" && fields.size() == 6) {
                    context.x = std::stoi(fields[1]);
                    context.y = std::stoi(fields[2]);
                    context.width = std::stoi(fields[3]);
                    context.height = std::stoi(fields[4]);
                    context.globalCursor = fields[5] == "1";
                    if (context.focused)
                        panel.show(context, text, wave, state);
                } else if (fields[0] == "HIDE") {
                    context.focused = false;
                    panel.hide();
                } else if (fields[0] != "STATUS")
                    throw std::invalid_argument("command");
                panel.available(context);
                result = panel.diagnostics();
            } catch (const std::exception &) {
                result = "{\"error\":\"invalid panel command\"}";
            }
            result += '\n';
            if (::send(fd, result.data(), result.size(), MSG_NOSIGNAL) !=
                static_cast<ssize_t>(result.size())) {
                loop.exit();
                return false;
            }
        }
        return true;
    });
    loop.exec();
    panel.hide();
    ::close(fd);
}
