"""Current-user consumption of a protected unified-installer handoff."""

import argparse
from pathlib import Path

from ..infrastructure.config import ConfigStore
from ..infrastructure.installed_portal import import_handoff


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if not args.handoff.is_file():
        parser.error("联合安装交接文件不存在；不会静默创建空连接")
    store = ConfigStore(args.config)
    import_handoff(store, args.handoff)


if __name__ == "__main__":
    main()
