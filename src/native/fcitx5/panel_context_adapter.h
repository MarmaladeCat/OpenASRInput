#pragma once
#include "panel_context.h"

#include <fcitx/inputcontext.h>

namespace openasrinput {
inline PanelContext panelContext(fcitx::InputContext *ic) {
    if (!ic)
        return {};
    const auto rect = ic->cursorRect();
    return {ic->display(),
            rect.left(),
            rect.top(),
            rect.width(),
            rect.height(),
            ic->scaleFactor(),
            ic->hasFocus(),
            rect.height() > 0 && !ic->capabilityFlags().test(fcitx::CapabilityFlag::RelativeRect)};
}
} // namespace openasrinput
