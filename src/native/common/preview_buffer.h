#pragma once

#include <cstddef>
#include <string>

namespace openasrinput {
inline constexpr size_t PreviewWordLimit = 20;

struct PreviewBuffer {
    std::string text;
    size_t words = 0;
    bool clipped = false;
};

// A display-only rolling window. The full client preedit and final are untouched.
PreviewBuffer previewBuffer(const std::string &text);
} // namespace openasrinput
