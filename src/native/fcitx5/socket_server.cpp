#include "socket_server.h"

#include <cerrno>
#include <cstring>
#include <stdexcept>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace openasrinput {
namespace {
constexpr size_t Limit = 1024 * 1024;
}

std::string hexEncode(const std::string &text) {
    static const char digits[] = "0123456789abcdef";
    std::string result;
    result.reserve(text.size() * 2);
    for (unsigned char c : text) {
        result += digits[c >> 4];
        result += digits[c & 15];
    }
    return result;
}

std::string hexDecode(const std::string &text) {
    if (text.size() % 2) {
        throw std::invalid_argument("invalid hex field");
    }
    auto digit = [](char c) -> int {
        if (c >= '0' && c <= '9') {
            return c - '0';
        }
        if (c >= 'a' && c <= 'f') {
            return c - 'a' + 10;
        }
        throw std::invalid_argument("invalid hex digit");
    };
    std::string result;
    for (size_t i = 0; i < text.size(); i += 2) {
        result += static_cast<char>((digit(text[i]) << 4) | digit(text[i + 1]));
    }
    return result;
}

SocketServer::SocketServer(fcitx::EventLoop &loop, std::string path, Handler handler,
                           std::function<void()> disconnected)
    : loop_(loop), path_(std::move(path)), handler_(std::move(handler)),
      disconnected_(std::move(disconnected)) {
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    if (path_.empty() || path_.size() >= sizeof(address.sun_path)) {
        throw std::runtime_error("socket path is empty or too long");
    }
    std::memcpy(address.sun_path, path_.c_str(), path_.size() + 1);
    listener_ = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (listener_ < 0) {
        throw std::runtime_error("socket creation failed");
    }
    // Do not remove an existing path or an existing server's socket.
    if (::bind(listener_, reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0) {
        ::close(listener_);
        listener_ = -1;
        throw std::runtime_error("socket bind failed; choose an unused project-local path");
    }
    if (::chmod(path_.c_str(), 0600) < 0 || ::listen(listener_, 1) < 0) {
        ::close(listener_);
        listener_ = -1;
        ::unlink(path_.c_str());
        throw std::runtime_error("socket setup failed");
    }
    listenerEvent_ =
        loop_.addIOEvent(listener_, fcitx::IOEventFlag::In, [this](auto *, int fd, auto) {
            int peer = ::accept4(fd, nullptr, nullptr, SOCK_CLOEXEC | SOCK_NONBLOCK);
            if (peer < 0) {
                return true;
            }
            if (connected()) {
                char peek;
                if (::recv(client_, &peek, 1, MSG_PEEK | MSG_DONTWAIT) == 0) {
                    disconnect();
                }
            }
            ucred credential{};
            socklen_t size = sizeof(credential);
            if (::getsockopt(peer, SOL_SOCKET, SO_PEERCRED, &credential, &size) < 0 ||
                credential.uid != ::getuid() || connected()) {
                ::close(peer);
                return true;
            }
            client_ = peer;
            clientEvent_ = loop_.addIOEvent(
                client_, fcitx::IOEventFlag::In,
                [this](auto *, int client, fcitx::IOEventFlags flags) {
                    if (flags.test(fcitx::IOEventFlag::Out)) {
                        flush();
                    }
                    if (client_ < 0) {
                        return true;
                    }
                    if (flags.test(fcitx::IOEventFlag::In)) {
                        char buffer[8192];
                        for (;;) {
                            auto count = ::recv(client, buffer, sizeof(buffer), 0);
                            if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
                                break;
                            }
                            if (count <= 0) {
                                disconnect();
                                return true;
                            }
                            input_.append(buffer, static_cast<size_t>(count));
                            if (input_.size() > Limit) {
                                disconnect();
                                return true;
                            }
                        }
                        size_t end;
                        while ((end = input_.find('\n')) != std::string::npos) {
                            auto line = input_.substr(0, end);
                            input_.erase(0, end + 1);
                            send(handler_(line));
                            if (client_ < 0) {
                                return true;
                            }
                        }
                    }
                    if (flags.test(fcitx::IOEventFlag::Hup) ||
                        flags.test(fcitx::IOEventFlag::Err)) {
                        disconnect();
                    }
                    return true;
                });
            send("0\tHELLO\tOpenASRInput.Bridge\t1");
            return true;
        });
}

SocketServer::~SocketServer() {
    // Owner clears its context before destroying the server.
    disconnected_ = [] {};
    disconnect();
    listenerEvent_.reset();
    if (listener_ >= 0) {
        ::close(listener_);
        ::unlink(path_.c_str());
    }
}

bool SocketServer::connected() {
    if (client_ < 0) {
        return false;
    }
    char peek;
    auto count = ::recv(client_, &peek, 1, MSG_PEEK | MSG_DONTWAIT);
    if (count == 0 || (count < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) {
        disconnect();
        return false;
    }
    return true;
}

void SocketServer::disconnect() {
    clientEvent_.reset();
    if (client_ >= 0) {
        ::close(client_);
        client_ = -1;
        input_.clear();
        output_.clear();
        disconnected_();
    }
}

void SocketServer::send(std::string line) {
    if (!connected()) {
        return;
    }
    if (output_.size() + line.size() + 1 > Limit) {
        disconnect();
        return;
    }
    output_ += line + '\n';
    flush();
}

void SocketServer::flush() {
    while (connected() && !output_.empty()) {
        auto count = ::send(client_, output_.data(), output_.size(), MSG_NOSIGNAL);
        if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            break;
        }
        if (count <= 0) {
            disconnect();
            return;
        }
        output_.erase(0, static_cast<size_t>(count));
    }
    if (clientEvent_) {
        auto flags = fcitx::IOEventFlags(fcitx::IOEventFlag::In);
        if (!output_.empty()) {
            flags |= fcitx::IOEventFlag::Out;
        }
        clientEvent_->setEvents(flags);
    }
}

} // namespace openasrinput
