// Real Wayland wire/shm lifecycle check against an isolated minimal compositor.
#include "layer_shell_protocol.h"
#include "wayland_panel.h"

#include <atomic>
#include <cstring>
#include <fcitx-utils/event.h>
#include <iostream>
#include <stdexcept>
#include <sys/eventfd.h>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <wayland-server-protocol.h>
#include <wayland-server.h>

namespace {
struct Compositor;
struct Layer;
struct Surface {
    Compositor *owner;
    wl_resource *resource;
    wl_resource *buffer = nullptr;
    wl_resource *callback = nullptr;
    Layer *layer = nullptr;
    bool inputEmpty = false;
};
struct Layer {
    Surface *surface;
    wl_resource *resource;
    bool sentConfigure = false, acknowledged = false;
    uint32_t width = 0, height = 0, keyboard = 99, anchor = 0;
};
struct LayerInterface {
    void (*size)(wl_client *, wl_resource *, uint32_t, uint32_t);
    void (*anchor)(wl_client *, wl_resource *, uint32_t);
    void (*zone)(wl_client *, wl_resource *, int32_t);
    void (*margin)(wl_client *, wl_resource *, int32_t, int32_t, int32_t, int32_t);
    void (*keyboard)(wl_client *, wl_resource *, uint32_t);
    void (*popup)(wl_client *, wl_resource *, wl_resource *);
    void (*ack)(wl_client *, wl_resource *, uint32_t);
    void (*destroy)(wl_client *, wl_resource *);
};

void destroy(wl_client *, wl_resource *resource) { wl_resource_destroy(resource); }
void noopRegion(wl_client *, wl_resource *, int32_t, int32_t, int32_t, int32_t) {}
const struct wl_region_interface RegionImpl = {destroy, noopRegion, noopRegion};

struct Compositor {
    wl_display *display = wl_display_create();
    wl_resource *output = nullptr;
    std::atomic<int> frames = 0, destroyed = 0, errors = 0, lastWidth = 0;
    std::atomic<int> lastAnchor = 0, lastAlpha = 0;
    int wake = eventfd(0, EFD_CLOEXEC), clientFd = -1;
    std::thread thread;

    Compositor() {
        if (!display || wake < 0 || wl_display_init_shm(display) < 0)
            throw std::runtime_error("server setup");
        wl_global_create(
            display, &wl_output_interface, 2, this,
            [](wl_client *client, void *data, uint32_t version, uint32_t id) {
                auto *owner = static_cast<Compositor *>(data);
                owner->output = wl_resource_create(client, &wl_output_interface, version, id);
                wl_resource_set_implementation(owner->output, nullptr, nullptr, nullptr);
                wl_output_send_geometry(owner->output, 0, 0, 300, 200, WL_OUTPUT_SUBPIXEL_UNKNOWN,
                                        "OpenASRInput", "HiDPI fixture",
                                        WL_OUTPUT_TRANSFORM_NORMAL);
                wl_output_send_mode(owner->output, WL_OUTPUT_MODE_CURRENT, 2400, 1800, 60000);
                wl_output_send_scale(owner->output, 2);
                wl_output_send_done(owner->output);
            });
        wl_global_create(
            display, &wl_compositor_interface, 4, this,
            [](wl_client *client, void *data, uint32_t version, uint32_t id) {
                auto *resource = wl_resource_create(client, &wl_compositor_interface, version, id);
                static const struct wl_compositor_interface impl = {
                    [](wl_client *client, wl_resource *resource, uint32_t id) {
                        auto *owner =
                            static_cast<Compositor *>(wl_resource_get_user_data(resource));
                        auto *surface = new Surface{
                            owner, wl_resource_create(client, &wl_surface_interface, 4, id)};
                        wl_resource_set_implementation(
                            surface->resource, &surfaceImpl(), surface, [](wl_resource *resource) {
                                auto *surface =
                                    static_cast<Surface *>(wl_resource_get_user_data(resource));
                                if (surface->layer)
                                    surface->layer->surface = nullptr;
                                delete surface;
                            });
                        if (owner->output)
                            wl_surface_send_enter(surface->resource, owner->output);
                    },
                    [](wl_client *client, wl_resource *, uint32_t id) {
                        auto *resource = wl_resource_create(client, &wl_region_interface, 1, id);
                        wl_resource_set_implementation(resource, &RegionImpl, nullptr, nullptr);
                    },
#ifdef WL_COMPOSITOR_RELEASE_SINCE_VERSION
                    nullptr, // wl_compositor.release is newer than the bound v4.
#endif
                };
                wl_resource_set_implementation(resource, &impl, data, nullptr);
            });
        wl_global_create(
            display, &openasrinput::LayerShellInterface, 1, this,
            [](wl_client *client, void *data, uint32_t, uint32_t id) {
                auto *resource =
                    wl_resource_create(client, &openasrinput::LayerShellInterface, 1, id);
                static const struct {
                    void (*getLayer)(wl_client *, wl_resource *, uint32_t, wl_resource *,
                                     wl_resource *, uint32_t, const char *);
                } impl = {[](wl_client *client, wl_resource *resource, uint32_t id,
                             wl_resource *surfaceResource, wl_resource *, uint32_t role,
                             const char *name) {
                    auto *owner = static_cast<Compositor *>(wl_resource_get_user_data(resource));
                    auto *surface =
                        static_cast<Surface *>(wl_resource_get_user_data(surfaceResource));
                    if (role != 3 || std::strcmp(name, "openasrinput") || surface->buffer)
                        ++owner->errors;
                    auto *layer = new Layer{
                        surface,
                        wl_resource_create(client, &openasrinput::LayerSurfaceInterface, 1, id)};
                    surface->layer = layer;
                    wl_resource_set_implementation(
                        layer->resource, &layerImpl(), layer, [](wl_resource *resource) {
                            auto *layer = static_cast<Layer *>(wl_resource_get_user_data(resource));
                            if (layer->surface) {
                                ++layer->surface->owner->destroyed;
                                layer->surface->layer = nullptr;
                            }
                            delete layer;
                        });
                }};
                wl_resource_set_implementation(resource, &impl, data, nullptr);
            });
        int pair[2];
        if (socketpair(AF_UNIX, SOCK_STREAM, 0, pair) < 0)
            throw std::runtime_error("socketpair");
        wl_client_create(display, pair[0]);
        clientFd = pair[1];
        setenv("WAYLAND_SOCKET", std::to_string(clientFd).c_str(), 1);
        setenv("WAYLAND_DISPLAY", "openasrinput-isolated", 1);
        wl_event_loop_add_fd(
            wl_display_get_event_loop(display), wake, WL_EVENT_READABLE,
            [](int fd, uint32_t, void *data) -> int {
                uint64_t value;
                if (::read(fd, &value, sizeof(value)) != sizeof(value))
                    return -1;
                wl_display_terminate(static_cast<Compositor *>(data)->display);
                return 0;
            },
            this);
        thread = std::thread([this] { wl_display_run(display); });
    }

    ~Compositor() {
        uint64_t value = 1;
        if (::write(wake, &value, sizeof(value)) != sizeof(value))
            std::terminate();
        thread.join();
        wl_display_destroy_clients(display);
        wl_display_destroy(display);
        ::close(wake);
        unsetenv("WAYLAND_SOCKET");
        unsetenv("WAYLAND_DISPLAY");
    }

    static const struct wl_surface_interface &surfaceImpl() {
        static const auto impl = [] {
            struct wl_surface_interface result{};
            result.destroy = destroy;
            result.attach = [](wl_client *, wl_resource *resource, wl_resource *buffer, int32_t,
                               int32_t) {
                static_cast<Surface *>(wl_resource_get_user_data(resource))->buffer = buffer;
            };
            result.damage = noopRegion;
            result.frame = [](wl_client *client, wl_resource *resource, uint32_t id) {
                static_cast<Surface *>(wl_resource_get_user_data(resource))->callback =
                    wl_resource_create(client, &wl_callback_interface, 1, id);
            };
            result.set_opaque_region = [](wl_client *, wl_resource *, wl_resource *) {};
            result.set_input_region = [](wl_client *, wl_resource *resource, wl_resource *region) {
                static_cast<Surface *>(wl_resource_get_user_data(resource))->inputEmpty =
                    region != nullptr;
            };
            result.commit = [](wl_client *client, wl_resource *resource) {
                auto *surface = static_cast<Surface *>(wl_resource_get_user_data(resource));
                auto *layer = surface->layer;
                if (layer && !layer->sentConfigure) {
                    if (surface->buffer)
                        ++surface->owner->errors;
                    wl_resource_post_event(layer->resource, 0, 1u, layer->width, layer->height);
                    layer->sentConfigure = true;
                } else if (surface->buffer) {
                    if (!layer || !layer->acknowledged || layer->keyboard != 0 ||
                        !surface->inputEmpty)
                        ++surface->owner->errors;
                    if (layer)
                        surface->owner->lastAnchor = layer->anchor;
                    auto *buffer = wl_shm_buffer_get(surface->buffer);
                    if (!buffer)
                        ++surface->owner->errors;
                    else {
                        wl_shm_buffer_begin_access(buffer);
                        const auto *pixels =
                            static_cast<const uint32_t *>(wl_shm_buffer_get_data(buffer));
                        surface->owner->lastAlpha = pixels[0] >> 24;
                        surface->owner->lastWidth = wl_shm_buffer_get_width(buffer);
                        wl_shm_buffer_end_access(buffer);
                    }
                    ++surface->owner->frames;
                    wl_buffer_send_release(surface->buffer);
                    surface->buffer = nullptr;
                    if (surface->callback) {
                        wl_callback_send_done(surface->callback, 1);
                        wl_resource_destroy(surface->callback);
                        surface->callback = nullptr;
                    }
                }
                wl_client_flush(client);
            };
            result.set_buffer_transform = [](wl_client *, wl_resource *, int32_t) {};
            result.set_buffer_scale = [](wl_client *, wl_resource *, int32_t) {};
            return result;
        }();
        return impl;
    }

    static const LayerInterface &layerImpl() {
        static const LayerInterface impl = {
            [](wl_client *, wl_resource *resource, uint32_t width, uint32_t height) {
                auto *layer = static_cast<Layer *>(wl_resource_get_user_data(resource));
                layer->width = width;
                layer->height = height;
            },
            [](wl_client *, wl_resource *resource, uint32_t anchor) {
                static_cast<Layer *>(wl_resource_get_user_data(resource))->anchor = anchor;
            },
            [](wl_client *, wl_resource *, int32_t) {},
            [](wl_client *, wl_resource *, int32_t, int32_t, int32_t, int32_t) {},
            [](wl_client *, wl_resource *resource, uint32_t keyboard) {
                static_cast<Layer *>(wl_resource_get_user_data(resource))->keyboard = keyboard;
            },
            [](wl_client *, wl_resource *, wl_resource *) {},
            [](wl_client *, wl_resource *resource, uint32_t serial) {
                static_cast<Layer *>(wl_resource_get_user_data(resource))->acknowledged =
                    serial == 1;
            },
            destroy,
        };
        return impl;
    }
};
} // namespace

int main() {
    Compositor compositor;
    fcitx::EventLoop loop;
    openasrinput::WaylandPanel panel(loop, [](cairo_t *cr, int) {
        cairo_set_source_rgb(cr, 0x33 / 255.0, 0x66 / 255.0, 0x99 / 255.0);
        cairo_paint(cr);
    });
    if (!panel.available())
        throw std::runtime_error("native Wayland backend unavailable");
    openasrinput::PanelStyle style;
    panel.show(style);
    int stage = 0;
    bool passed = false;
    const auto deadline = fcitx::now(CLOCK_MONOTONIC) + 3000000;
    auto timer = loop.addTimeEvent(
        CLOCK_MONOTONIC, fcitx::now(CLOCK_MONOTONIC) + 10000, 0, [&](auto *source, uint64_t now) {
            if (now > deadline || compositor.errors) {
                loop.exit();
                return false;
            }
            if (stage == 0 && compositor.frames >= 1) {
                if (compositor.lastWidth != 1520)
                    ++compositor.errors;
                if (compositor.lastAnchor != 2 || compositor.lastAlpha != 255)
                    ++compositor.errors;
                style.position = "top-right";
                style.transparency = 50;
                panel.show(style);
                stage = 1;
            } else if (stage == 1 && compositor.frames >= 2) {
                if (compositor.lastAnchor != 9 || compositor.lastAlpha != 128)
                    ++compositor.errors;
                style.width = 480;
                style.scale = 1.25;
                panel.show(style);
                stage = 2;
            } else if (stage == 2 && compositor.frames >= 3 && compositor.lastWidth == 1200) {
                panel.hide();
                stage = 3;
            } else if (stage == 3 && compositor.destroyed >= 2) {
                panel.show(style);
                stage = 4;
            } else if (stage == 4 && compositor.frames >= 4) {
                panel.hide();
                passed = true;
                loop.exit();
                return false;
            }
            source->setTime(now + 10000);
            source->setEnabled(true);
            return true;
        });
    loop.exec();
    if (!passed || compositor.errors)
        throw std::runtime_error("Wayland configure/buffer/focus lifecycle failed");
    std::cout << "PASS native Wayland: configure before attach, graphical shm, HiDPI, frame "
                 "pacing, click-through, no keyboard focus, resize, hide/resume\n";
}
