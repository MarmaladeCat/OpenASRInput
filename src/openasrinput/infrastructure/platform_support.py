"""Small OS boundary for paths and advisory configuration locks."""

import os
from contextlib import contextmanager
from pathlib import Path


def config_home():
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData/Roaming") / "OpenASRInput"
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "openasrinput"


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
