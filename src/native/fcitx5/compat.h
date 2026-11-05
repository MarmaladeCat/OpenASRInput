#pragma once

#include <fcitx/inputcontext.h>
#include <fcitx/inputpanel.h>
#include <functional>
#if __has_include(<fcitx-utils/standardpaths.h>)
#include <fcitx-utils/standardpaths.h>
#else
#include <fcitx-utils/standardpath.h>
#endif

namespace openasrinput::compat {
inline bool disabled(fcitx::InputContext *context) {
    // Disable was named in 5.0.20. Its published bit remains meaningful when
    // a baseline-built plugin runs inside a newer core.
    return context->capabilityFlags().test(static_cast<fcitx::CapabilityFlag>(1ull << 40)) ||
           context->capabilityFlags().test(fcitx::CapabilityFlag::Password);
}
inline std::string configFile() {
#if __has_include(<fcitx-utils/standardpaths.h>)
    return fcitx::StandardPaths::global()
        .locate(fcitx::StandardPathsType::PkgConfig, "conf/openasrinput.conf")
        .string();
#else
    return fcitx::StandardPath::global().locate(fcitx::StandardPath::Type::PkgConfig,
                                                "conf/openasrinput.conf");
#endif
}
inline std::string addonDirectory() {
#if __has_include(<fcitx-utils/standardpaths.h>)
    return fcitx::StandardPaths::fcitxPath("addondir").string();
#else
    return fcitx::StandardPath::fcitxPath("addondir");
#endif
}
using PanelCallback = std::function<void(fcitx::InputContext *)>;

// Custom panel callbacks were added in 5.0.24. Older cores can render our
// non-focusable surface directly without changing the input/commit protocol.
template <typename T>
concept CustomPanel = requires(T &panel, PanelCallback callback) {
    panel.customInputPanelCallback();
    panel.setCustomInputPanelCallback(callback);
};
inline constexpr bool customPanels = CustomPanel<fcitx::InputPanel>;

template <typename T> PanelCallback panelCallback(T &panel) {
    if constexpr (CustomPanel<T>)
        return panel.customInputPanelCallback();
    return {};
}
template <typename T> void setPanelCallback(T &panel, PanelCallback callback) {
    if constexpr (CustomPanel<T>)
        panel.setCustomInputPanelCallback(std::move(callback));
}

// Optional explanatory popup; the daemon also handles the "unavailable" reply.
// This method was added in 5.1.11, not in 5.1.23.
template <typename T> void unavailable(T &instance, fcitx::InputContext *context) {
    if constexpr (requires { instance.showCustomInputMethodInformation(context, ""); }) {
        instance.showCustomInputMethodInformation(context, "请聚焦可预编辑的输入框，并先结束候选");
    }
}
} // namespace openasrinput::compat
