# OpenASRInput

[English](README.md) | **简体中文**

**1.1.0** · 系统语音输入。采集麦克风，经 Portal 识别后预览并提交到当前输入目标；Linux 支持 IBus、Fcitx5 和 X11 下的 Fcitx4，Windows 使用独立原生桥接。

## 从这里开始

Input 需要 [OpenASRPortal](https://github.com/MarmaladeCat/OpenASRPortal) 提供识别服务。可从 [Portal 下载页](https://github.com/MarmaladeCat/OpenASRPortal/releases) 安装到本机，或连接现有远程 Portal。按照 [Portal 配置手册](https://github.com/MarmaladeCat/OpenASRPortal/blob/main/docs/user-guide.zh-CN.md) 设置管理密码、添加上游并创建客户端 ASR Key。

希望一次安装两产品，请看 [合体安装、持久配置与语言选择](docs/installation.zh-CN.md)。合体安装包覆盖 Windows x64、Linux amd64/ARM64，包含 Input 1.1.0 + Portal 1.1.0。

- **安装和使用**：[Windows / Linux 图文手册](docs/user-guide.zh-CN.md)。需要 Portal 地址和客户端识别 Key。
- **开发对接**：[接口与输入语义](docs/API.zh-CN.md)，描述外部连接和本地桥接边界。
- **理解实现**：[架构设计](docs/architecture.zh-CN.md)。
- **修改与打包**：[开发和发布流程](docs/development.zh-CN.md)。
- **执行验收**：[测试环境与约束](docs/testing.zh-CN.md)。
- **查看版本**：[1.1.0 版本说明](docs/release.zh-CN.md)。

本产品能独立克隆、开发、测试和发布；没有共享产品数据库。源码运行需要 Python 3.10+，原生桥接另需对应平台工具链；已打包的 Input 携带私有 Python 运行时。测试用 Electron 不属于产品运行依赖。

文档由维护者撰写；精选的演示截图保存在 `docs/images/`。个人配置、测试原始数据和发布二进制由 `.gitignore` 排除。

## 许可证

Copyright (C) 2026 OpenASRInput contributors.

原创代码与文档按 **GNU GPL v3（GPL-3.0-only）** 授权，允许在该许可条件下使用、修改和再分发，包括商业用途；不提供担保。完整条款见 [LICENSE](LICENSE)。第三方组件保留各自版权和许可。分发软件包时应提供与其对应的源码和构建说明。
