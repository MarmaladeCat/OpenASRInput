# 合体安装与持久化设置

[English](installation.md) | **简体中文**

本页描述供维护者审核与手动测试的 1.0.1 候选。已发布的 1.0.0 安装包早于这些安装与语言改动；候选通过审核后再正式发布。

## 选择安装方式

- **Input + Portal 合体安装**：Windows x64 为一个 MSI；Linux amd64/ARM64 为包含两个 DEB 和 `install.sh` 的归档包，计划放在 [Input Release 下载页](https://github.com/MarmaladeCat/OpenASRInput/releases)。Windows 保持勾选 Portal；Linux 解压后以桌面用户运行 `./install.sh`，通过 sudo 和 APT 一次安装两产品。发行版依赖可能需要联网下载。
- **仅安装 Input**：已有 Portal 时可使用独立包。[Portal 项目](https://github.com/MarmaladeCat/OpenASRPortal)、[下载页](https://github.com/MarmaladeCat/OpenASRPortal/releases) 和 [配置手册](https://github.com/MarmaladeCat/OpenASRPortal/blob/main/docs/user-guide.zh-CN.md) 说明部署步骤。Input 需要可用的本机或远程 Portal 才能识别。

同时下载安装包及其同名 `文件名.sha256`。每份校验文件只包含对应安装包的一行记录；Linux 执行 `sha256sum -c 文件名.sha256`，Windows 用 `Get-FileHash 文件名 -Algorithm SHA256` 对照该记录。

## 首次安装、升级与重装

合体安装器为安装时的桌面账户创建独立 ASR Key，通过 Input 的公开配置命令导入；后续安装复用同一有效安装身份。管理员密码不是 Input 的识别 Key。

- **首次安装**：Portal 启动后，交互式安装在尚无管理员时打开本机 `/admin/setup`。设置管理密码、配置上游，再测试输入。安装器不提供默认管理密码。
- **升级**：保留配置、管理员身份、客户端 Key 和热词；已经初始化时不再打开首次设置页。
- **卸载但保留配置后重装**：复用保留的配置；若之前没有完成管理密码设置，则继续进入初始化页面。

Windows 静默安装（`/qn` 或 `OPENASRINPUT_NO_LAUNCH=1`）和 Linux `./install.sh --no-open` 由用户自行打开页面。Linux 直接使用 root 时须指定 `--user 账户`。没有图形会话时手动访问 Portal，通常为 `http://127.0.0.1:10087/admin`；自定义端口会保留。Linux 安装不会重启桌面或输入框架，按 [用户手册](user-guide.zh-CN.md) 启动和选择引擎。

## 固定持久目录

| 平台 | Input | Portal | 安装交接 |
| --- | --- | --- | --- |
| Windows | `%ProgramData%\OpenASR\Input\<SID>\input.json` | `%ProgramData%\OpenASR\Portal\service.json` 与 `data\` | `%ProgramData%\OpenASR\Installer\provisioning\<SID>\` |
| Linux | `/var/lib/openasr/input/<uid>/input.json` | `/var/lib/openasr/portal/service.env` 与 `data/` | `/var/lib/openasr/installer/<uid>/` |

SID/UID 是系统账户标识，不依赖显示名称。各用户 Input 文件私有，Portal 自主管理服务数据；共同父目录不意味着共享 Key 或数据库。Windows 安装需要提权以准备公共数据根目录。

旧默认 `%APPDATA%\OpenASRInput` 或 XDG 目录中的 Input 配置与卡片元数据只复制一次，运行会话标记不迁移。Portal 停止服务后迁移旧默认配置与数据。旧副本保留供恢复，确认新安装正常后再清理备份。显式 `OPENASRINPUT_CONFIG` 实例保持隔离，Portal 自定义数据路径保留。

未安装公共数据根目录时，源码运行继续使用 APPDATA/XDG。“连接与关于”显示实际配置路径。备份完整的实际配置目录；Portal 须同时保留 `portal.db` 与 `asr-key-vault.key`。Windows 卸载提供保留或明确删除选项，Linux `apt remove` 保留数据。

## 中英文切换

Input 设置页、Portal 管理页及首次设置页右上角均有 **中文 / English**。默认跟随浏览器/系统语言，两产品分别记住当前浏览器的选择；切换时不刷新页面，也不丢失未保存表单。用户名称、热词、凭据、识别文本及校准朗读材料属于数据，保留原内容。
