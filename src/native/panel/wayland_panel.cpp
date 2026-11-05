#include "wayland_panel.h"

#include "layer_shell_protocol.h"
#include "panel_layout.h"

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <sys/mman.h>
#include <unistd.h>
#include <vector>
#include <wayland-client.h>

namespace openasrinput {
namespace {
constexpr int Height = 156;
void destroyLayer(wl_proxy *proxy, uint32_t opcode) {
    if (proxy) {
        wl_proxy_marshal_flags(proxy, opcode, nullptr, 1, WL_MARSHAL_FLAG_DESTROY);
    }
}
} // namespace

struct WaylandPanel::Impl {
    struct Output {
        Impl *owner;
        wl_output *output;
        int scale = 1;
        bool entered = false;
        Output(Impl *owner, wl_output *output) : owner(owner), output(output) {}
        ~Output() { wl_output_destroy(output); }
    };
    struct Buffer {
        Impl *owner;
        wl_buffer *buffer = nullptr;
        void *memory = MAP_FAILED;
        size_t bytes = 0;
        int width = 0, height = 0, stride = 0;
        bool busy = false;
        ~Buffer() {
            if (buffer) {
                wl_buffer_destroy(buffer);
            }
            if (memory != MAP_FAILED) {
                munmap(memory, bytes);
            }
        }
    };
    fcitx::EventLoop &loop;
    Painter painter;
    wl_display *display = nullptr;
    wl_registry *registry = nullptr;
    wl_compositor *compositor = nullptr;
    wl_shm *shm = nullptr;
    wl_proxy *shell = nullptr, *layer = nullptr;
    wl_surface *surface = nullptr;
    wl_callback *frame = nullptr;
    std::unique_ptr<fcitx::EventSourceIO> io;
    std::vector<std::unique_ptr<Buffer>> buffers;
    std::vector<std::unique_ptr<Output>> outputs;
    PanelStyle style;
    bool attempted = false, visible = false, configured = false, dirty = false;
    int logicalWidth = 760, logicalHeight = Height;
    int outputScale = 1;

    Impl(fcitx::EventLoop &loop, Painter painter) : loop(loop), painter(std::move(painter)) {}
    ~Impl() { close(); }

    void updateScale() {
        int next = 1;
        for (const auto &output : outputs) {
            if (output->entered)
                next = std::max(next, output->scale);
        }
        if (next != outputScale) {
            outputScale = next;
            dirty = true;
            render();
        }
    }

    void flush() {
        if (!display || !io) {
            return;
        }
        const bool pending = wl_display_flush(display) < 0 && errno == EAGAIN;
        auto flags = fcitx::IOEventFlags(fcitx::IOEventFlag::In);
        if (pending)
            flags |= fcitx::IOEventFlag::Out;
        io->setEvents(flags);
    }

    bool open() {
        if (attempted) {
            return display && compositor && shm && shell;
        }
        attempted = true;
        if (!std::getenv("WAYLAND_DISPLAY")) {
            return false;
        }
        display = wl_display_connect(nullptr);
        if (!display) {
            return false;
        }
        registry = wl_display_get_registry(display);
        static const wl_registry_listener listener = {
            [](void *data, wl_registry *registry, uint32_t name, const char *interface,
               uint32_t version) {
                auto *self = static_cast<Impl *>(data);
                if (!std::strcmp(interface, "wl_compositor")) {
                    self->compositor = static_cast<wl_compositor *>(wl_registry_bind(
                        registry, name, &wl_compositor_interface, std::min(version, 4u)));
                } else if (!std::strcmp(interface, "wl_shm")) {
                    self->shm = static_cast<wl_shm *>(
                        wl_registry_bind(registry, name, &wl_shm_interface, 1));
                } else if (!std::strcmp(interface, LayerShellInterface.name)) {
                    self->shell = static_cast<wl_proxy *>(
                        wl_registry_bind(registry, name, &LayerShellInterface, 1));
                } else if (!std::strcmp(interface, "wl_output")) {
                    auto output = std::make_unique<Output>(
                        self, static_cast<wl_output *>(wl_registry_bind(
                                  registry, name, &wl_output_interface, std::min(version, 2u))));
                    static const auto listener = [] {
                        wl_output_listener result{};
                        result.geometry = [](void *, wl_output *, int32_t, int32_t, int32_t,
                                             int32_t, int32_t, const char *, const char *,
                                             int32_t) {};
                        result.mode = [](void *, wl_output *, uint32_t, int32_t, int32_t, int32_t) {
                        };
                        result.done = [](void *, wl_output *) {};
                        result.scale = [](void *data, wl_output *, int32_t scale) {
                            auto *output = static_cast<Output *>(data);
                            output->scale = std::clamp(scale, 1, 4);
                            output->owner->updateScale();
                        };
                        return result;
                    }();
                    wl_output_add_listener(output->output, &listener, output.get());
                    self->outputs.push_back(std::move(output));
                }
            },
            [](void *, wl_registry *, uint32_t) {},
        };
        wl_registry_add_listener(registry, &listener, this);
        if (wl_display_roundtrip(display) < 0 || !compositor || !shm || !shell) {
            close();
            return false;
        }
        io = loop.addIOEvent(
            wl_display_get_fd(display), fcitx::IOEventFlag::In,
            [this](auto *, int, fcitx::IOEventFlags flags) {
                if (flags.test(fcitx::IOEventFlag::Hup) || flags.test(fcitx::IOEventFlag::Err) ||
                    (flags.test(fcitx::IOEventFlag::In) && wl_display_dispatch(display) < 0)) {
                    close();
                    return false;
                }
                flush();
                return true;
            });
        flush();
        return true;
    }

    void close() {
        io.reset();
        hide();
        buffers.clear();
        outputs.clear();
        // The layer-shell destroy request was added in v3; v1 is local-only.
        if (shell)
            wl_proxy_destroy(shell);
        shell = nullptr;
        if (shm)
            wl_shm_destroy(shm);
        if (compositor)
            wl_compositor_destroy(compositor);
        if (registry)
            wl_registry_destroy(registry);
        shm = nullptr;
        compositor = nullptr;
        registry = nullptr;
        if (display)
            wl_display_disconnect(display);
        display = nullptr;
    }

    void hide() {
        visible = configured = dirty = false;
        if (frame) {
            wl_callback_destroy(frame);
            frame = nullptr;
        }
        destroyLayer(layer, 7);
        layer = nullptr;
        if (surface) {
            wl_surface_destroy(surface);
            surface = nullptr;
        }
        for (auto &output : outputs)
            output->entered = false;
        if (display)
            wl_display_flush(display);
    }

    Buffer *nextBuffer(int width, int height) {
        // Compositor-owned buffers are never overwritten, even across resize/hide.
        std::erase_if(buffers, [width, height](const auto &buffer) {
            return !buffer->busy && (buffer->width != width || buffer->height != height);
        });
        for (auto &buffer : buffers) {
            if (!buffer->busy && buffer->width == width && buffer->height == height) {
                return buffer.get();
            }
        }
        if (buffers.size() >= 3) {
            return nullptr;
        }
        auto buffer = std::make_unique<Buffer>();
        buffer->owner = this;
        buffer->width = width;
        buffer->height = height;
        buffer->stride = cairo_format_stride_for_width(CAIRO_FORMAT_ARGB32, width);
        buffer->bytes = static_cast<size_t>(buffer->stride) * height;
        const int fd = memfd_create("openasrinput-waveform", MFD_CLOEXEC);
        if (fd < 0)
            return nullptr;
        if (ftruncate(fd, buffer->bytes) < 0) {
            ::close(fd);
            return nullptr;
        }
        buffer->memory = mmap(nullptr, buffer->bytes, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
        if (buffer->memory == MAP_FAILED) {
            ::close(fd);
            return nullptr;
        }
        auto *pool = wl_shm_create_pool(shm, fd, static_cast<int>(buffer->bytes));
        buffer->buffer = wl_shm_pool_create_buffer(pool, 0, width, height, buffer->stride,
                                                   WL_SHM_FORMAT_ARGB8888);
        wl_shm_pool_destroy(pool);
        ::close(fd);
        static const wl_buffer_listener listener = {[](void *data, wl_buffer *) {
            auto *buffer = static_cast<Buffer *>(data);
            buffer->busy = false;
            // Do not delete the buffer in its own event callback.
            buffer->owner->render();
        }};
        wl_buffer_add_listener(buffer->buffer, &listener, buffer.get());
        auto *result = buffer.get();
        buffers.push_back(std::move(buffer));
        return result;
    }

    void render() {
        if (!visible || !configured || !dirty || frame || !surface)
            return;
        auto *buffer = nextBuffer(logicalWidth * outputScale, logicalHeight * outputScale);
        if (!buffer)
            return;
        auto *image = cairo_image_surface_create_for_data(
            static_cast<unsigned char *>(buffer->memory), CAIRO_FORMAT_ARGB32, buffer->width,
            buffer->height, buffer->stride);
        auto *cr = cairo_create(image);
        cairo_scale(cr, style.scale * outputScale, style.scale * outputScale);
        painter(cr, static_cast<int>(logicalWidth / style.scale));
        cairo_set_operator(cr, CAIRO_OPERATOR_DEST_IN);
        cairo_set_source_rgba(cr, 0, 0, 0, panelPlacement(style).opacity);
        cairo_paint(cr);
        cairo_destroy(cr);
        cairo_surface_flush(image);
        cairo_surface_destroy(image);
        buffer->busy = true;
        dirty = false;
        wl_surface_set_buffer_scale(surface, outputScale);
        wl_surface_attach(surface, buffer->buffer, 0, 0);
        wl_surface_damage(surface, 0, 0, logicalWidth, logicalHeight);
        frame = wl_surface_frame(surface);
        static const wl_callback_listener listener = {
            [](void *data, wl_callback *callback, uint32_t) {
                auto *self = static_cast<Impl *>(data);
                wl_callback_destroy(callback);
                self->frame = nullptr;
                self->render();
            }};
        wl_callback_add_listener(frame, &listener, this);
        wl_surface_commit(surface);
        flush();
    }

    void show(const PanelStyle &settings) {
        if (!panelPlacement(settings).visible) {
            hide();
            return;
        }
        if (!open())
            return;
        const int width = static_cast<int>(settings.width * settings.scale);
        const int height = static_cast<int>(Height * settings.scale);
        if (style.position != settings.position)
            hide();
        style = settings;
        if (width != logicalWidth || height != logicalHeight) {
            hide();
            logicalWidth = width;
            logicalHeight = height;
        }
        visible = dirty = true;
        if (!surface) {
            surface = wl_compositor_create_surface(compositor);
            static const auto surfaceListener = [] {
                wl_surface_listener result{};
                result.enter = [](void *data, wl_surface *, wl_output *entered) {
                    auto *self = static_cast<Impl *>(data);
                    for (auto &output : self->outputs) {
                        if (output->output == entered)
                            output->entered = true;
                    }
                    self->updateScale();
                };
                result.leave = [](void *data, wl_surface *, wl_output *left) {
                    auto *self = static_cast<Impl *>(data);
                    for (auto &output : self->outputs) {
                        if (output->output == left)
                            output->entered = false;
                    }
                    self->updateScale();
                };
                return result;
            }();
            wl_surface_add_listener(surface, &surfaceListener, this);
            auto *region = wl_compositor_create_region(compositor);
            wl_surface_set_input_region(surface, region); // Empty: click-through.
            wl_region_destroy(region);
            layer = wl_proxy_marshal_flags(shell, 0, &LayerSurfaceInterface, 1, 0, nullptr, surface,
                                           nullptr, 3u, "openasrinput");
            static void (*listener[])(void) = {
                reinterpret_cast<void (*)(void)>(+[](void *data, wl_proxy *, uint32_t serial,
                                                     uint32_t width, uint32_t height) {
                    auto *self = static_cast<Impl *>(data);
                    wl_proxy_marshal_flags(self->layer, 6, nullptr, 1, 0, serial);
                    self->logicalWidth =
                        std::clamp(static_cast<int>(width ? width : self->logicalWidth), 320, 1600);
                    self->logicalHeight = std::clamp(
                        static_cast<int>(height ? height : self->logicalHeight), 100, 300);
                    self->configured = true;
                    self->dirty = true;
                    self->render();
                }),
                reinterpret_cast<void (*)(void)>(
                    +[](void *data, wl_proxy *) { static_cast<Impl *>(data)->hide(); }),
            };
            wl_proxy_add_listener(layer, listener, this);
            wl_proxy_marshal_flags(layer, 0, nullptr, 1, 0, static_cast<uint32_t>(width),
                                   static_cast<uint32_t>(height));
            wl_proxy_marshal_flags(layer, 1, nullptr, 1, 0, panelPlacement(settings).layerAnchor);
            wl_proxy_marshal_flags(layer, 2, nullptr, 1, 0, 0); // No reserved work area.
            wl_proxy_marshal_flags(layer, 3, nullptr, 1, 0, 12, 12, 12, 12);
            wl_proxy_marshal_flags(layer, 4, nullptr, 1, 0, 0u); // No keyboard focus.
            wl_surface_commit(surface); // First commit has no buffer; await configure.
        }
        render();
        flush();
    }
};

WaylandPanel::WaylandPanel(fcitx::EventLoop &loop, Painter painter)
    : impl_(std::make_unique<Impl>(loop, std::move(painter))) {}
WaylandPanel::~WaylandPanel() = default;
bool WaylandPanel::available() { return impl_->open(); }
void WaylandPanel::show(const PanelStyle &style) { impl_->show(style); }
void WaylandPanel::hide() { impl_->hide(); }
} // namespace openasrinput
