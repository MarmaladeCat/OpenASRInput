# OpenASRInput 1.0.0 版本说明

[English](release.md) | **简体中文**

本产品版本与包工具元数据统一为 1.0.0，公开识别协议保持 v1。全部文档提供英文默认入口及对应中文链接。

## 本版能力

- 通过 Portal 统一识别，支持预编辑、稳定定稿、正常收尾与取消。
- Linux IBus/Fcitx5/Fcitx4 原生桥接，以及 Windows 独立桥接。
- 设置网页提供外观、输入框架、麦克风、Portal 连接、个人热词与文本指令修改。
- 输入目标和录音轮次隔离，识别账本与提交 ACK 防止重复/错目标提交。

## 下载与阅读

Linux 选择匹配 CPU 的 `*_linux_amd64_local-auto.deb` 或 `*_linux_arm64_local-auto.deb`；Windows 选择 `*_windows_amd64_native.msi`。安装包自带私有 Python，Linux 仍需对应桌面输入法框架。

同目录 `OpenASRInput_1.0.0_docs.zip` 是完整人工文档，解压后从 README.md 或 docs/user-guide.md 阅读。manifest.json 记录来源与平台，SHA256SUMS 用于完整性核对；构建清单不代表平台认证。

## 兼容与升级

Fcitx4 仅用于 X11；Wayland 按桌面和框架单独验收。不同应用的原生输入能力可能不同。demo 不向真实应用上屏。升级前退出应用、备份本地配置，保留已有 Portal Key；旧活动会话不续传。

Windows 设置页存在 Alt+Z 旧提示，实际原生快捷键为 Alt+X，使用手册按实现说明。

尚未验证的系统、原生目标、安装升级和真实录音须在交付验收中列明。后续版本在此按版本记录用户可见变化和兼容要求，不加入日常开发日志。
