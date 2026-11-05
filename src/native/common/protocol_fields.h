#pragma once

#include <string>
#include <vector>

namespace openasrinput {
// Empty final fields carry meaning (for example an empty selection replacement).
// Keep the wire format identical for both Fcitx adapters and the panel host.
inline std::vector<std::string> protocolFields(const std::string &line, char delimiter = '\t') {
    std::vector<std::string> result;
    size_t start = 0, end;
    while ((end = line.find(delimiter, start)) != std::string::npos) {
        result.push_back(line.substr(start, end - start));
        start = end + 1;
    }
    result.push_back(line.substr(start));
    return result;
}
} // namespace openasrinput
