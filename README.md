# OpenASRInput

**English** | [简体中文](README.zh-CN.md)

**1.0.0** · System-wide voice input. Capture microphone audio, recognize through Portal, preview, and commit to the active input target. Linux supports IBus, Fcitx5, and Fcitx4 on X11; Windows uses an independent native bridge.

## Start here

- **Install and use:** [illustrated Windows / Linux guide](docs/user-guide.md). You need a Portal address and client ASR key.
- **Integrate:** [interfaces and input semantics](docs/API.md), covering external connections and local bridge boundaries.
- **Understand:** [architecture](docs/architecture.md).
- **Modify and package:** [development and releases](docs/development.md).
- **Verify:** [test environments and requirements](docs/testing.md).
- **Release:** [1.0.0 release notes](docs/release.md).

This product can be cloned, developed, tested, and released independently, without a shared product database. Source requires Python 3.10+; native bridges need platform toolchains. Packaged Input includes a private Python runtime. Test Electron is not a product runtime dependency.

Documentation is manually maintained in English and Chinese. Selected real captures live in `docs/images/`. Personal configuration, raw test data, and release binaries are excluded by `.gitignore`.

## License

Copyright (C) 2026 OpenASRInput contributors.

Original code and documentation use **GNU GPL v3 (`GPL-3.0-only`)**, permitting use, modification, and redistribution, including commercial use, under its terms, without warranty. See [LICENSE](LICENSE). Third-party components retain their copyrights/licenses. Distribute matching source and build instructions with software packages as required by the license.
