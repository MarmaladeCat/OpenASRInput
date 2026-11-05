#pragma once

#include <wayland-util.h>

namespace openasrinput {
// Stable wire layout of wlr-layer-shell-unstable-v1 version 1. Only the
// non-interactive layer surface role is used; no xdg_popup objects are created.
extern const wl_interface LayerShellInterface;
extern const wl_interface LayerSurfaceInterface;
} // namespace openasrinput
