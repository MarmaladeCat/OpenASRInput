# 合体安装与持久化设置

[English](installation.md) | **简体中文**

本页说明 Input 1.2.0 安装及 Input 1.2.0 + Portal 1.2.0 组合安装包，各组件保持独立产品版本。

## 选择安装方式

- **Input + Portal 合体安装**：Windows x64 为一个 MSI；Linux amd64/ARM64 为内置两个应用及私有运行时的单个 DEB，计划放在 [Input Release 下载页](https://github.com/MarmaladeCat/OpenASRInput/releases)。Windows 保持勾选 Portal；Linux 用图形包管理器打开 DEB，或运行 `sudo apt install ./OpenASRInput_1.2.0_linux_amd64_OpenASRPortal_1.2.0.deb`（ARM64 将 `amd64` 换为 `arm64`）。发行版依赖可能需要联网下载。
- **仅安装 Input**：已有 Portal 时可使用独立包。[Portal 项目](https://github.com/MarmaladeCat/OpenASRPortal)、[下载页](https://github.com/MarmaladeCat/OpenASRPortal/releases) 和 [配置手册](https://github.com/MarmaladeCat/OpenASRPortal/blob/main/docs/user-guide.zh-CN.md) 说明部署步骤。Input 需要可用的本机或远程 Portal 才能识别。

同时下载安装包及其同名 `文件名.sha256`。每份校验文件只包含对应安装包的一行记录；Linux 执行 `sha256sum -c 文件名.sha256`，Windows 用 `Get-FileHash 文件名 -Algorithm SHA256` 对照该记录。

## 首次安装、升级与重装

合体安装器为安装时的桌面账户创建独立 ASR Key，通过 Input 的公开配置命令导入；后续安装复用同一有效安装身份。管理员密码不是 Input 的识别 Key。

- **首次安装**：Portal 启动后，Windows 交互式安装或 Linux 配置入口在尚无管理员时打开本机 `/admin/setup`。设置管理密码、配置上游，再测试输入。安装器不提供默认管理密码。
- **升级**：保留配置、管理员身份、客户端 Key 和热词；已经初始化时不再打开首次设置页。
- **卸载但保留配置后重装**：复用保留的配置；若之前没有完成管理密码设置，则继续进入初始化页面。

Windows 静默安装（`/qn` 或 `OPENASRINPUT_NO_LAUNCH=1`）由用户自行打开页面。Linux 包安装不打开浏览器：sudo 安装会连接调用账户；图形/root 安装后从应用菜单打开 **OpenASR Input + Portal 配置**，或执行 `sudo openasrinput-portal-setup --user 账户 --no-open`。没有图形会话时手动访问 Portal，通常为 `http://127.0.0.1:10087/admin`；自定义端口会保留。Linux 安装不会重启桌面或输入框架，按 [用户手册](user-guide.zh-CN.md) 启动和选择引擎。

APT 用 `openasrinput-portal` 管理两个应用。安装合体包会替换独立的 `openasrinput` 与 `openasrportal`，也适用于旧归档安装器装入的独立包，并保留数据。用 `sudo apt remove openasrinput-portal` 一次卸载；`purge` 也保留产品数据。改回独立安装时，用 APT 同时安装两个独立 DEB，替换合体包。

## 固定持久目录

| 平台 | Input | Portal | 安装交接 |
| --- | --- | --- | --- |
| Windows | `%ProgramData%\OpenASR\input\<SID>\input.json` | `%ProgramData%\OpenASR\portal\service.json` 与 `data\` | `%ProgramData%\OpenASR\installer\provisioning\<SID>\` |
| Linux | `/var/lib/OpenASR/input/<uid>/input.json` | `/var/lib/OpenASR/portal/service.env` 与 `data/` | `/var/lib/OpenASR/installer/<uid>/` |

SID/UID 是系统账户标识，不依赖显示名称。各用户 Input 文件私有，Portal 自主管理服务数据；共同父目录不意味着共享 Key 或数据库。Windows 安装需要提权以准备公共数据根目录。

旧默认 `%APPDATA%\OpenASRInput` 或 XDG 目录中的 Input 配置与卡片元数据只复制一次，运行会话标记不迁移。Portal 停止服务后迁移旧默认配置与数据。旧副本保留供恢复，确认新安装正常后再清理备份。显式 `OPENASRINPUT_CONFIG` 实例保持隔离，Portal 自定义数据路径保留。

源码、独立版和合体版使用相同默认目录。安装器准备权限；隔离开发可指定 `OPENASRINPUT_CONFIG`，或通过 `OPENASR_DATA_ROOT` 指定公共命名空间。Linux 还会一次性复制旧 `/var/lib/openasr/input/<uid>` 配置，包启用状态迁入配置旁的 `package/`。系统要求的服务文件与 `/run/user` 临时 socket 保留在系统集成位置。“连接与关于”显示实际路径；Portal 备份须包含 `portal.db` 与 `asr-key-vault.key`。

Windows 维护与卸载使用登记的实际程序目录，也支持自定义安装路径。是否保留配置与程序安装位置是独立选项。

### 清理旧 Input 目录

在“连接与关于”核对实际配置路径、确认 1.2.0 的卡片和设置正常，并退出旧 Input 实例后，可删除这些旧默认位置：Windows `%APPDATA%\OpenASRInput`；Linux `${XDG_CONFIG_HOME:-$HOME/.config}/openasrinput` 与 `/var/lib/openasr/input/<uid>`。若 `OPENASRINPUT_CONFIG` 或已登记的自定义安装路径仍指向其中某处，它仍是有效目录，不能只凭旧名称判定无用。

要全新安装，先将需要的设置另存备份，再于首次启动前清除已确认的旧默认目录，否则一次性迁移可能恢复旧设置。当前安装的 `/var/lib/OpenASR/input/<uid>` 或 `%ProgramData%\OpenASR\input\<SID>` 应保留，Linux 路径区分大小写。包管理器维护的 `/usr`、`/etc` 文件及 `/run/user` 临时 socket 属于系统集成，不是过时配置备份。

## 可选万象完整包

工作区可组成含万象 Pure 18.1.9 和必需 LTS 语法模型的完整包，保留轻量包。Linux 使用 `..._Wanxiang.deb`，由 APT 安装前端依赖；Windows 使用 `..._Wanxiang.zip`，含 `Install.cmd`、合体 MSI 与官方小狼毫 0.17.4。Pure 提供无需 Lua 的全拼，已有 Rime 用户目录保留。安装、构建及许可见[完整包指南](https://github.com/MarmaladeCat/OpenASRSoftwares/blob/main/packaging/rime/README.zh-CN.md)。

受管理 Rime 数据也位于 OpenASR 根下：Windows `Rime\<SID>`、`Rime\Resources`；Linux `rime/<uid>/<framework>`、`rime/resources`。Linux 标准 Rime 目录仅为链接。拼音本地可用，语音仍需配置 Portal 上游。

## 彻底清理

Windows 默认卸载保留配置。在产品卸载程序取消勾选“保留配置”，删除受管理的配置、Key、数据库、缓存及识别出的旧默认目录。完整包在“已安装的应用”中有独立入口，“彻底删除本包数据”默认不勾选，勾选后还清理其 Rime 数据及由本包安装的小狼毫。已有独立 Rime、显式外部路径及源码运行目录需另行处理。

Linux 先停止 Input，再用 `sudo apt remove openasrinput-portal`（或独立包名）卸载。remove 和 purge 均保留用户数据。只删除自己 Input 数据：`sudo rm -rf -- "/var/lib/OpenASR/input/$(id -u)"`。整个 `/var/lib/OpenASR` 还包含 Notes、Drafts、LocalASR、Rime 和安装记录；删除整个根目录会清除所有账号、所有产品的 Key、数据库与模型。

删除 Rime 数据前，检查标准目录链接，仅 unlink 指向自己 `/var/lib/OpenASR/rime/<uid>/` 的链接。旧副本可能仍在 `/var/lib/openasr`、XDG Input 目录、`/etc/openasrportal` 和 `/var/lib/openasrportal`，确认不用后分别删除。显式自定义路径及旧 Docker 卷单独管理。

## 中英文切换

Input 设置页、Portal 管理页及首次设置页右上角均有 **中文 / English** 下拉框。默认跟随浏览器/系统语言，两产品分别记住当前浏览器的选择；切换时不刷新页面，也不丢失未保存表单。用户名称、热词、凭据、识别文本及校准朗读材料属于数据，保留原内容。
