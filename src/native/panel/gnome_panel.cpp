#include "gnome_panel.h"

#include <cstdlib>
#include <iomanip>
#include <sstream>

namespace openasrinput {
namespace {
constexpr const char *Service = "org.openasrinput.Panel";
constexpr const char *Object = "/org/openasrinput/Panel";
constexpr const char *Interface = "org.openasrinput.Panel1";

std::string jsonString(const std::string &value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') {
            out << '\\' << c;
        } else if (c < 32) {
            out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(c);
        } else {
            out << c;
        }
    }
    out << '"';
    return out.str();
}
} // namespace

GnomePanel::GnomePanel(fcitx::EventLoop &loop) {
    // No desktop bus in isolated/headless contexts: let another backend handle it.
    if (!std::getenv("DBUS_SESSION_BUS_ADDRESS")) {
        return;
    }
    try {
        bus_ = std::make_unique<fcitx::dbus::Bus>(fcitx::dbus::BusType::Session);
        bus_->attachEventLoop(&loop);
        watcher_ = std::make_unique<fcitx::dbus::ServiceWatcher>(*bus_);
        subscription_ =
            watcher_->watchService(Service, [this](const auto &, const auto &, const auto &owner) {
                owner_ = owner;
                visible_ = false;
                compatible_ = false;
                probe_.reset();
                if (!owner.empty()) {
                    auto describe =
                        bus_->createMethodCall(owner.c_str(), Object, Interface, "Describe");
                    probe_ = describe.callAsync(1000000, [this, owner](auto &reply) {
                        if (!reply.isError() && owner == owner_) {
                            std::string value;
                            reply >> value;
                            compatible_ = value.find("panel-layout-v2") != std::string::npos;
                        }
                        return true;
                    });
                }
            });
    } catch (const std::exception &) {
        subscription_.reset();
        watcher_.reset();
        bus_.reset();
    }
}

GnomePanel::~GnomePanel() { hide(); }
bool GnomePanel::available() const { return bus_ && !owner_.empty() && compatible_; }

void GnomePanel::show(const PanelContext &context, const PanelStyle &style,
                      const PreviewBuffer &preview, const std::string &wave,
                      const std::string &state) {
    if (!available()) {
        return;
    }
    std::ostringstream data;
    data << "{\"version\":1,\"text\":" << jsonString(preview.text) << ",\"words\":" << preview.words
         << ",\"wave\":" << jsonString(wave) << ",\"state\":" << jsonString(state)
         << ",\"width\":" << style.width << ",\"scale\":" << style.scale
         << ",\"fontSize\":" << style.fontSize << ",\"radius\":" << style.radius
         << ",\"position\":" << jsonString(style.position)
         << ",\"transparency\":" << style.transparency
         << ",\"globalCursor\":" << (context.globalCursor ? "true" : "false") << ",\"cursor\":["
         << context.x << ',' << context.y << ',' << context.width << ',' << context.height
         << "],\"colors\":[";
    for (size_t i = 0; i < style.colors.size(); ++i) {
        data << (i ? "," : "") << style.colors[i];
    }
    data << "]}";
    // One-way send: shell repaint is coalesced by its frame clock, never blocks Fcitx.
    auto message = bus_->createMethodCall(owner_.c_str(), Object, Interface, "Show");
    message << data.str();
    visible_ = message.send();
}

void GnomePanel::hide() {
    if (visible_ && available()) {
        auto message = bus_->createMethodCall(owner_.c_str(), Object, Interface, "Hide");
        message.send();
        bus_->flush();
    }
    visible_ = false;
}
} // namespace openasrinput
