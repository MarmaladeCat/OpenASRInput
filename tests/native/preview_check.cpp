#include "preview_buffer.h"

#include <iostream>
#include <stdexcept>
#include <unicode/unistr.h>

namespace {
void require(bool value, const char *message) {
    if (!value) {
        throw std::runtime_error(message);
    }
}
} // namespace

int main() {
    try {
        auto empty = openasrinput::previewBuffer("");
        require(empty.words == 0 && empty.text.empty(), "empty preview changed");
        std::string text;
        for (int i = 1; i <= 25; ++i) {
            text += "word" + std::to_string(i) + " ";
        }
        auto longText = openasrinput::previewBuffer(text);
        require(longText.words == 20 && longText.clipped, "preview is not bounded to 20 words");
        require(longText.text.rfind("word6 ", 0) == 0 &&
                    longText.text.compare(longText.text.size() - 6, 6, "word25") == 0,
                "rolling window did not retain the latest words in left-to-right order");
        require(text.rfind("word1 ", 0) == 0, "display buffer modified complete preedit");

        std::string chinese;
        for (int i = 0; i < 25; ++i) {
            chinese += "中国 ";
        }
        auto chineseBuffer = openasrinput::previewBuffer(chinese);
        require(chineseBuffer.words == 20 && chineseBuffer.clipped,
                "Chinese words were not segmented");
        require(icu::UnicodeString::fromUTF8(chineseBuffer.text).countChar32() == 59,
                "Chinese buffer counted characters rather than words");
        auto sentence = openasrinput::previewBuffer("今天我们一起测试语音输入");
        require(sentence.words > 1 && sentence.words < 12,
                "unspaced Chinese requires dictionary word breaks");
        auto whitespace = openasrinput::previewBuffer("hello\n\t世界。  ");
        require(whitespace.text == "hello 世界。", "display did not remain one row");
        auto revised = openasrinput::previewBuffer("我要去公园。");
        require(revised.text == "我要去公园。", "revision is not an exact replacement");
        std::cout
            << "PASS 20-word preview: English, Chinese, rolling order, revisions, whitespace\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
