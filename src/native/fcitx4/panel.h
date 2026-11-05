#pragma once
#include "panel_style.h"
#include "preview_buffer.h"
#include "x11_panel_surface.h"

#include <X11/Xlib.h>
#include <string>

namespace openasrinput {
class X11Panel {
  public:
    X11Panel();
    ~X11Panel();
    bool available() const { return display_ != nullptr; }
    int fd() const { return display_ ? ConnectionNumber(display_) : -1; }
    unsigned int keyCode(unsigned long symbol) const;
    bool keyHeld(unsigned int code) const;
    void process();
    void hide();
    void show(int x, int y, std::string text, std::string wave, std::string state);
    void configure(const PanelStyle &style);

  private:
    void paint();
    void refresh();
    void unmap();
    Display *display_ = nullptr;
    Window window_ = 0;
    PanelStyle style_;
    X11PanelVisual visual_;
    int anchorX_ = 0, anchorY_ = 0;
    bool active_ = false;
    PreviewBuffer buffer_;
    std::string wave_, state_;
    double scale_ = 1;
    int width_ = 760, height_ = 156;
    bool visible_ = false;
};
} // namespace openasrinput
