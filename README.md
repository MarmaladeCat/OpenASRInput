# OpenASRInput

**English** | [简体中文](README.zh-CN.md)

**1.1.1** · System-wide voice input. Capture microphone audio, recognize through Portal, preview, and commit to the active input target. Linux supports IBus, Fcitx5, and Fcitx4 on X11; Windows uses an independent native bridge.

## Start here

Input needs [OpenASRPortal](https://github.com/MarmaladeCat/OpenASRPortal) for recognition. Install it locally from [Portal downloads](https://github.com/MarmaladeCat/OpenASRPortal/releases), or connect to an existing remote Portal. Follow the [Portal configuration guide](https://github.com/MarmaladeCat/OpenASRPortal/blob/main/docs/user-guide.md) to set an administrator password, add an upstream, and issue a client ASR key.

For one installation of both products, see [combined installation, persistent configuration, and language selection](docs/installation.md). Combined installers target Windows x64 and Linux amd64/ARM64 and contain Input 1.1.1 + Portal 1.1.1.

- **Install and use:** [illustrated Windows / Linux guide](docs/user-guide.md). You need a Portal address and client ASR key.
- **Integrate:** [interfaces and input semantics](docs/API.md), covering external connections and local bridge boundaries.
- **Understand:** [architecture](docs/architecture.md).
- **Modify and package:** [development and releases](docs/development.md).
- **Verify:** [test environments and requirements](docs/testing.md).
- **Release:** [1.1.1 release notes](docs/release.md).

This product can be cloned, developed, tested, and released independently, without a shared product database. Source requires Python 3.10+; native bridges need platform toolchains. Packaged Input includes a private Python runtime. Test Electron is not a product runtime dependency.

Documentation is manually maintained in English and Chinese. Selected real captures live in `docs/images/`. Personal configuration, raw test data, and release binaries are excluded by `.gitignore`.

## License

Copyright (C) 2026 OpenASRInput contributors.

Original code and documentation use **GNU GPL v3 (`GPL-3.0-only`)**, permitting use, modification, and redistribution, including commercial use, under its terms, without warranty. See [LICENSE](LICENSE). Third-party components retain their copyrights/licenses. Distribute matching source and build instructions with software packages as required by the license.
