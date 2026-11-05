#pragma once

#include <cerrno>
#include <cstring>
#include <functional>
#include <stdexcept>
#include <string>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace openasrinput {
// Nonblocking transport driven by the host's select loop. No worker thread may
// touch an input context. One same-uid client, bounded buffers, no stale unlink.
class UnixServer {
  public:
    using Handler = std::function<std::string(const std::string &)>;
    UnixServer(std::string path, Handler handler, std::function<void()> disconnected)
        : path_(std::move(path)), handler_(std::move(handler)),
          disconnected_(std::move(disconnected)) {
        sockaddr_un address{};
        address.sun_family = AF_UNIX;
        if (path_.empty() || path_.size() >= sizeof(address.sun_path))
            throw std::runtime_error("invalid socket path");
        std::memcpy(address.sun_path, path_.c_str(), path_.size() + 1);
        listener_ = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
        if (listener_ < 0)
            throw std::runtime_error("cannot create socket");
        if (listener_ >= FD_SETSIZE) {
            close(listener_);
            throw std::runtime_error("too many open descriptors");
        }
        if (bind(listener_, reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0) {
            close(listener_);
            throw std::runtime_error("socket already exists or cannot be bound");
        }
        if (chmod(path_.c_str(), 0600) < 0 || listen(listener_, 1) < 0) {
            close(listener_);
            unlink(path_.c_str());
            throw std::runtime_error("cannot listen on socket");
        }
    }
    ~UnixServer() {
        if (client_ >= 0)
            close(client_);
        close(listener_);
        unlink(path_.c_str());
    }
    bool connected() const { return client_ >= 0; }
    void watch(fd_set *read, fd_set *write, int &maximum) const {
        auto add = [&](int fd, fd_set *set) {
            if (fd < 0 || fd >= FD_SETSIZE)
                return;
            FD_SET(fd, set);
            if (fd > maximum)
                maximum = fd;
        };
        add(listener_, read);
        if (client_ >= 0) {
            add(client_, read);
            if (!output_.empty())
                add(client_, write);
        }
    }
    void disconnect() {
        if (client_ < 0)
            return;
        close(client_);
        client_ = -1;
        input_.clear();
        output_.clear();
        disconnected_();
    }
    void send(const std::string &line) {
        if (!connected())
            return;
        if (output_.size() + line.size() + 1 > Limit) {
            disconnect();
            return;
        }
        output_ += line + '\n';
        flush();
    }
    void process() {
        const int peer = accept4(listener_, nullptr, nullptr, SOCK_NONBLOCK | SOCK_CLOEXEC);
        if (peer >= 0) {
            ucred credential{};
            socklen_t size = sizeof(credential);
            if (connected() || peer >= FD_SETSIZE ||
                getsockopt(peer, SOL_SOCKET, SO_PEERCRED, &credential, &size) < 0 ||
                credential.uid != getuid())
                close(peer);
            else {
                client_ = peer;
                send("0\tHELLO\tOpenASRInput.Bridge\t1");
            }
        }
        if (!connected())
            return;
        char buffer[8192];
        while (connected()) {
            const auto count = recv(client_, buffer, sizeof(buffer), 0);
            if (count < 0 && errno == EINTR)
                continue;
            if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
                break;
            if (count <= 0) {
                disconnect();
                return;
            }
            input_.append(buffer, static_cast<size_t>(count));
            if (input_.size() > Limit) {
                disconnect();
                return;
            }
        }
        size_t end;
        while (connected() && (end = input_.find('\n')) != std::string::npos) {
            auto line = input_.substr(0, end);
            input_.erase(0, end + 1);
            send(handler_(line));
        }
        flush();
    }

  private:
    void flush() {
        while (connected() && !output_.empty()) {
            const auto count = ::send(client_, output_.data(), output_.size(), MSG_NOSIGNAL);
            if (count < 0 && errno == EINTR)
                continue;
            if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
                break;
            if (count <= 0) {
                disconnect();
                return;
            }
            output_.erase(0, static_cast<size_t>(count));
        }
    }
    static constexpr size_t Limit = 1024 * 1024;
    std::string path_, input_, output_;
    Handler handler_;
    std::function<void()> disconnected_;
    int listener_ = -1, client_ = -1;
};
} // namespace openasrinput
