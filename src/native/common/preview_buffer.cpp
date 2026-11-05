#include "preview_buffer.h"

#include <memory>
#include <stdexcept>
#include <unicode/brkiter.h>
#include <unicode/locid.h>
#include <unicode/uchar.h>
#include <unicode/unistr.h>
#include <vector>

namespace openasrinput {
PreviewBuffer previewBuffer(const std::string &text) {
    if (text.empty()) {
        return {};
    }
    auto unicode = icu::UnicodeString::fromUTF8(text);
    UErrorCode status = U_ZERO_ERROR;
    std::unique_ptr<icu::BreakIterator> iterator(
        icu::BreakIterator::createWordInstance(icu::Locale("zh"), status));
    if (U_FAILURE(status) || !iterator) {
        throw std::runtime_error("cannot initialize Unicode word segmentation");
    }
    iterator->setText(unicode);
    std::vector<int32_t> starts;
    int32_t start = iterator->first();
    for (int32_t end = iterator->next(); end != icu::BreakIterator::DONE;
         start = end, end = iterator->next()) {
        if (iterator->getRuleStatus() >= UBRK_WORD_NONE_LIMIT) {
            starts.push_back(start);
        }
    }
    PreviewBuffer result;
    result.words = std::min(starts.size(), PreviewWordLimit);
    result.clipped = starts.size() > PreviewWordLimit;
    const int32_t offset = result.clipped ? starts[starts.size() - PreviewWordLimit] : 0;
    // Collapse whitespace for a single display row; never alter clientPreedit.
    icu::UnicodeString line;
    bool space = false;
    for (int32_t i = offset; i < unicode.length();) {
        UChar32 character = unicode.char32At(i);
        i += U16_LENGTH(character);
        if (u_isUWhiteSpace(character)) {
            space = !line.isEmpty();
        } else {
            if (space) {
                line.append(static_cast<UChar32>(' '));
            }
            line.append(character);
            space = false;
        }
    }
    line.toUTF8String(result.text);
    return result;
}
} // namespace openasrinput
