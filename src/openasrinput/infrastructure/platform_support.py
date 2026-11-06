"""Small OS boundary for paths and advisory configuration locks."""

import os
from contextlib import contextmanager
from pathlib import Path


def legacy_config_home():
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData/Roaming") / "OpenASRInput"
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "openasrinput"


def user_identity():
    """Use a stable OS identity, including when a Windows account is renamed."""
    if os.name != "nt":
        return str(os.getuid())
    import ctypes
    from ctypes import wintypes

    token = wintypes.HANDLE()
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        data = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, data, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0]
        text = wintypes.LPWSTR()
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel.CloseHandle(token)


def installed_config_root():
    override = os.environ.get("OPENASR_DATA_ROOT")
    if override:
        base = Path(override).expanduser()
    elif os.name == "nt":
        base = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "OpenASR"
    else:
        base = Path("/var/lib/openasr")
    return base / ("Input" if os.name == "nt" else "input")


def config_home():
    # Source-only use retains XDG/APPDATA. Installers provision the shared root;
    # every installed desktop user then owns a private identity subdirectory.
    root = installed_config_root()
    if os.name == "nt" and not os.environ.get("OPENASR_DATA_ROOT"):
        import winreg

        for hive, key, field in (
            (winreg.HKEY_CURRENT_USER, r"Software\OpenASRInput", "StateDir"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\OpenASRInputPortal", "InputStateDir"),
        ):
            try:
                with winreg.OpenKey(
                    hive, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
                ) as handle:
                    directory = Path(winreg.QueryValueEx(handle, field)[0])
                    if (
                        hive == winreg.HKEY_LOCAL_MACHINE
                        and winreg.QueryValueEx(handle, "InputStateUser")[0] != user_identity()
                    ):
                        continue
                    if directory != legacy_config_home() and directory.is_absolute():
                        return directory
            except FileNotFoundError:
                pass
    if root.is_dir() or os.environ.get("OPENASR_DATA_ROOT"):
        directory = root / user_identity()
        if directory.is_symlink() or (
            os.name != "nt" and directory.exists() and directory.stat().st_uid != os.getuid()
        ):
            raise PermissionError("Input configuration directory belongs to another user")
        return directory
    return legacy_config_home()


def socket_default():
    if os.name == "nt":
        return str(config_home() / "native-process")  # Compatibility field; Windows uses stdio IPC.
    return str(
        Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "openasrinput.sock"
    )


@contextmanager
def exclusive_lock(path, *, blocking=True):
    with open(path, "a+b") as stream:
        os.chmod(path, 0o600)
        if os.name == "nt":
            import msvcrt

            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            yield
