// Disposable real XIM client; drives the public X11 frontend, not mock Fcitx APIs.
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <clocale>
#include <codecvt>
#include <cstdlib>
#include <iostream>
#include <locale>
#include <string>
#include <sys/select.h>
#include <unistd.h>

std::wstring preview;
std::wstring_convert<std::codecvt_utf8<wchar_t>> utf8;
std::string hex(const std::string &value) {
    const char *digits = "0123456789abcdef";
    std::string result;
    for (unsigned char c : value) {
        result += digits[c >> 4];
        result += digits[c & 15];
    }
    return result;
}
int start(XIC, XPointer, XPointer) {
    preview.clear();
    return -1;
}
void done(XIC, XPointer, XPointer) {
    preview.clear();
    std::cout << "PREEDIT\t" << std::endl;
}
void draw(XIC, XPointer, XPointer data) {
    auto *event = reinterpret_cast<XIMPreeditDrawCallbackStruct *>(data);
    std::wstring text;
    if (event->text) {
        if (event->text->encoding_is_wchar)
            text.assign(event->text->string.wide_char, event->text->length);
        else
            text = utf8.from_bytes(event->text->string.multi_byte);
    }
    preview.replace(event->chg_first, event->chg_length, text);
    std::cout << "PREEDIT\t" << hex(utf8.to_bytes(preview)) << std::endl;
}
void caret(XIC, XPointer, XPointer) {}

int main() {
    std::setlocale(LC_ALL, "");
    XSetLocaleModifiers("@im=fcitx");
    auto *display = XOpenDisplay(nullptr);
    if (!display)
        return 2;
    XIM im = nullptr;
    for (int i = 0; i < 100 && !im; ++i) {
        im = XOpenIM(display, nullptr, nullptr, nullptr);
        usleep(50000);
    }
    if (!im) {
        std::cerr << "XOpenIM failed\n";
        return 3;
    }
    Window windows[2];
    XIC contexts[2];
    XIMCallback begin{nullptr, reinterpret_cast<XIMProc>(start)};
    XIMCallback end{nullptr, reinterpret_cast<XIMProc>(done)};
    XIMCallback paint{nullptr, reinterpret_cast<XIMProc>(draw)};
    XIMCallback cursor{nullptr, reinterpret_cast<XIMProc>(caret)};
    auto attributes = XVaCreateNestedList(0, XNPreeditStartCallback, &begin, XNPreeditDoneCallback,
                                          &end, XNPreeditDrawCallback, &paint,
                                          XNPreeditCaretCallback, &cursor, nullptr);
    for (int i = 0; i < 2; ++i) {
        windows[i] = XCreateSimpleWindow(display, DefaultRootWindow(display), 50 + i * 350, 50, 320,
                                         180, 0, 0, 0xffffff);
        XStoreName(display, windows[i], i ? "OpenASRInput test second" : "OpenASRInput test first");
        contexts[i] = XCreateIC(im, XNInputStyle, XIMPreeditCallbacks | XIMStatusNothing,
                                XNClientWindow, windows[i], XNFocusWindow, windows[i],
                                XNPreeditAttributes, attributes, nullptr);
        if (!contexts[i])
            return 4;
        long mask = 0;
        XGetICValues(contexts[i], XNFilterEvents, &mask, nullptr);
        XSelectInput(display, windows[i],
                     mask | KeyPressMask | KeyReleaseMask | StructureNotifyMask);
        XMapWindow(display, windows[i]);
    }
    XFree(attributes);
    // A real WM handles MapRequest asynchronously; focusing before MapNotify
    // produces BadMatch even though the same fixture works on bare Xvfb.
    bool mapped[2] = {false, false};
    while (!mapped[0] || !mapped[1]) {
        XEvent event;
        XNextEvent(display, &event);
        if (event.type == MapNotify) {
            for (int i = 0; i < 2; ++i)
                if (event.xmap.window == windows[i])
                    mapped[i] = true;
        }
    }
    int active = 0;
    const bool trace = std::getenv("OPENASRINPUT_TRACE_IPC") != nullptr;
    XSetInputFocus(display, windows[0], RevertToParent, CurrentTime);
    XSetICFocus(contexts[0]);
    XFlush(display);
    std::cout << "READY\t" << windows[0] << '\t' << windows[1] << std::endl;
    std::string pending;
    for (;;) {
        while (XPending(display)) {
            XEvent event;
            XNextEvent(display, &event);
            if (trace && (event.type == KeyPress || event.type == KeyRelease))
                std::cerr << "XIM_KEY type=" << event.type << " time=" << event.xkey.time
                          << " code=" << event.xkey.keycode << " state=" << event.xkey.state
                          << " synthetic=" << event.xkey.send_event << std::endl;
            const bool filtered = XFilterEvent(&event, None);
            if (trace && (event.type == KeyPress || event.type == KeyRelease))
                std::cerr << "XIM_FILTER " << filtered << std::endl;
            if (filtered)
                continue;
            if (event.type == KeyPress) {
                char buffer[65536];
                KeySym sym;
                Status status;
                int n = Xutf8LookupString(contexts[active], &event.xkey, buffer, sizeof(buffer),
                                          &sym, &status);
                if (n > 0 && status != XBufferOverflow)
                    std::cout << "TEXT\t" << hex(std::string(buffer, n)) << std::endl;
            }
        }
        fd_set read;
        FD_ZERO(&read);
        FD_SET(STDIN_FILENO, &read);
        FD_SET(ConnectionNumber(display), &read);
        if (select(ConnectionNumber(display) + 1, &read, nullptr, nullptr, nullptr) < 0)
            return 5;
        if (!FD_ISSET(STDIN_FILENO, &read))
            continue;
        char buffer[256];
        const auto count = ::read(STDIN_FILENO, buffer, sizeof(buffer));
        if (count <= 0)
            break;
        pending.append(buffer, count);
        size_t eol;
        while ((eol = pending.find('\n')) != std::string::npos) {
            auto command = pending.substr(0, eol);
            pending.erase(0, eol + 1);
            if (command == "QUIT")
                return 0;
            if (command == "FOCUS1" || command == "FOCUS2") {
                XUnsetICFocus(contexts[active]);
                active = command == "FOCUS1" ? 0 : 1;
                XSetInputFocus(display, windows[active], RevertToParent, CurrentTime);
                XSetICFocus(contexts[active]);
                XFlush(display);
                std::cout << "FOCUSED" << std::endl;
            }
            if (command == "RESET") {
                auto *value = Xutf8ResetIC(contexts[active]);
                XFree(value);
                std::cout << "RESET" << std::endl;
            }
            if (command == "FOCUS?") {
                Window current;
                int revert;
                XGetInputFocus(display, &current, &revert);
                std::cout << "FOCUS\t" << (current == windows[active] ? "yes" : "no") << std::endl;
            }
        }
    }
    return 0;
}
