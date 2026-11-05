#pragma once

#include <fcitx-utils/event.h>
#include <functional>
#include <memory>
#include <string>

namespace openasrinput {

// Newline framed, tab-separated protocol; arbitrary UTF-8 text is hex encoded.
// All IO and host calls run on the Fcitx event loop, with bounded buffers.
class SocketServer {
  public:
    using Handler = std::function<std::string(const std::string &)>;
    SocketServer(fcitx::EventLoop &loop, std::string path, Handler handler,
                 std::function<void()> disconnected);
    ~SocketServer();
    void send(std::string line);
    bool connected();

  private:
    void disconnect();
    void flush();
    fcitx::EventLoop &loop_;
    std::string path_, input_, output_;
    Handler handler_;
    std::function<void()> disconnected_;
    int listener_ = -1, client_ = -1;
    std::unique_ptr<fcitx::EventSourceIO> listenerEvent_, clientEvent_;
};

std::string hexEncode(const std::string &text);
std::string hexDecode(const std::string &text);

} // namespace openasrinput
