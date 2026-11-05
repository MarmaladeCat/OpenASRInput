#include "layer_shell_protocol.h"

#include <wayland-client-protocol.h>

namespace openasrinput {
namespace {
const wl_interface *GetLayerTypes[] = {&LayerSurfaceInterface, &wl_surface_interface,
                                       &wl_output_interface, nullptr, nullptr};
const wl_message ShellRequests[] = {{"get_layer_surface", "no?ous", GetLayerTypes}};
const wl_message SurfaceRequests[] = {
    {"set_size", "uu", nullptr},
    {"set_anchor", "u", nullptr},
    {"set_exclusive_zone", "i", nullptr},
    {"set_margin", "iiii", nullptr},
    {"set_keyboard_interactivity", "u", nullptr},
    {"get_popup", "o", nullptr},
    {"ack_configure", "u", nullptr},
    {"destroy", "", nullptr},
};
const wl_message SurfaceEvents[] = {{"configure", "uuu", nullptr}, {"closed", "", nullptr}};
} // namespace
const wl_interface LayerShellInterface = {"zwlr_layer_shell_v1", 1, 1, ShellRequests, 0, nullptr};
const wl_interface LayerSurfaceInterface = {"zwlr_layer_surface_v1", 1, 8,
                                            SurfaceRequests,         2, SurfaceEvents};
} // namespace openasrinput
