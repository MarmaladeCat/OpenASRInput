"""Select the platform's input transport; the daemon uses the same bridge contract."""

import sys


def bridge_for_platform(socket_path):
    if sys.platform == "win32":
        from .windows import WindowsBridge

        return WindowsBridge()
    from .native import NativeBridge

    return NativeBridge(socket_path)
