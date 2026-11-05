"""Installed entry point for the bundled Windows Python interpreter."""

import os
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    os.environ["OPENASRINPUT_WINDOWS_HELPER"] = str(root / "native/OpenASRInputBridge.exe")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    from openasrinput.entrypoints.windows import main as run

    run()


if __name__ == "__main__":
    main()
