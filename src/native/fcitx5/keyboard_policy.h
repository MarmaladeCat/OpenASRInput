#pragma once
#include <fcitx/inputcontext.h>
#include <fcitx/inputpanel.h>
#include <fcitx/instance.h>

namespace openasrinput {
inline void keyboardPreeditPolicy(fcitx::Instance &instance, fcitx::InputContext *context,
                                  bool inlinePreedit, bool voiceOwned) {
    if (!inlinePreedit && !voiceOwned && instance.inputMethod(context) == "rime") {
        auto &panel = context->inputPanel();
        // ComposingText puts pinyin only in clientPreedit. Move it to the
        // candidate panel before suppressing the application-side preview.
        // CommitPreview already provides panel pinyin: never replace it with
        // its converted Chinese client preview.
        if (panel.preedit().empty() && !panel.clientPreedit().empty()) {
            panel.setPreedit(panel.clientPreedit());
        }
        panel.setClientPreedit(fcitx::Text());
    }
}
} // namespace openasrinput
