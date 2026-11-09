# OpenASRInput 测试约束

[English](testing.md) | **简体中文**

本文件是本产品开发与发布的验收约束；测试清单见 [可执行场景](../tests/functional/manifest.json)。
必须能在只克隆本仓库的环境运行，不依赖父仓库或其他产品的源码/解释器。

## 本仓库内启动测试

Python 3.10+；设置网页/面板回归使用 Node/Electron 测试工具（Node.js 22.13+）。Linux UI 使用 Xvfb，Windows 使用隔离交互桌面；原生桥接还需要对应系统与输入法框架。

```bash
python scripts/test.py list --suite core
python scripts/test.py setup --suite unit
python scripts/test.py run --suite unit --allow-skips
python scripts/test.py setup --suite core
python scripts/test.py run --suite core
python scripts/test.py setup --suite ui
python scripts/test.py run --suite ui
```

`setup` 只在本产品 `.cache/functional/` 建立 Python 测试环境；桌面依赖放本产品 node_modules/，浏览器测试工具放本产品 `.cache/test-lab/ui/`。
实际应用运行仍使用自己的运行时。每次 run 在本产品 test-results/functional/ 下产生新的报告与日志。
`--case <ID>` 可以定位单项，不能用单项通过代表整个产品通过。

### Windows 编辑器兼容性

`windows-native` 包含实际 TextBox/RichTextBox/WebView2 操作、已有文字光标时注入 Shift+Space 发起录音请求、在名为 `POWERPNT` 的可丢弃夹具中运行同样控件（`native-office-controls`），以及无桌面的目标/原生选区规则（`native-target-rules`）。同名夹具用于发现按整个进程误选输入路径的问题，不是 Microsoft Office。规则测试覆盖可选接口异常、位置缺失、Office 原生文字选区回退、明确只读拒绝、焦点切换、Unicode 范围替换与写入异常。

包内原生验收使用本产品测试 Python、设置 `PYTHONPATH=src;tests`，运行 `tests/functional/check_windows_editor.py --bridge '<候选目录>/native/OpenASRInputBridge.exe'`，再加 `--office-host` 重复执行。环境报告记录实际桥接程序集哈希。

专用编辑器还包含真实 WPF 文本框，可让可选 Value getter 在写入前或写入后失败，同时保留 TextPattern。核验指定位置的 Unicode 输入、幂等重放、全部确认通道不可用时的面板预览与零写入，以及 WinForms、WPF、Chromium 的只读/恢复切换。无桌面规则分别注入值/文本/选区/计数故障，并在提供者调用中触发焦点变化，运行实际的证据与续写代码。缺少能力不允许绕过明确保护，也不允许重发不确定的写入。

Windows 安装器验收还必须使用隔离的非默认程序目录与配置目录，覆盖原生卸载保留配置、重装和明确删除配置，并核验自定义程序文件与指定数据均被删除。包检查要求在目录计算前查找当前用户登记的安装目录，防止维护时静默回退到默认路径。

解包运行时检查须同时指定可丢弃的 `OPENASR_DATA_ROOT` 和配置文件；已有公共安装根目录可能使运行状态不再写入 APPDATA。Chromium 只读夹具命令独立等待 UIA 发布状态或相应焦点丢失，再检查桥接租约；DOM 修改应答本身不代表辅助功能接口已就绪。

真实 Office 专项必须在已安装 Microsoft PowerPoint 的隔离交互桌面中显式执行：

```powershell
python scripts/test.py setup --suite windows-office
python scripts/test.py run --suite windows-office --execution-host virtual-machine
# 使用本次候选包解出的桥接，而非源码构建的桥接：
python tests/functional/check_windows_powerpoint.py --bridge '<候选目录>/native/OpenASRInputBridge.exe'
```

测试仅在 test-results/ 下新建可丢弃演示文稿，覆盖文本框、空标题占位符、表格单元格、普通视图/备注页、Unicode/段落、仅替换选区、预览修订/取消、长定稿及跨形状/单元格焦点隔离。未安装 PowerPoint 时非零退出并记录阻塞，不算跳过或通过。保留 `native-powerpoint-result.json`、执行器日志和沙盒截图，记录准确 Office 版本与桥接哈希。Office 永久版和 Microsoft 365 分开执行；已有闪烁光标时的实体 Shift+Space 与真实麦克风须在桥接协议测试之外另验。

## 必须覆盖的行为

| 层次               | 必测内容                                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------------------------------- |
| unit / core        | 录音轮次、连接卡与密钥隔离、预览/revision/final、失焦与取消、配置热更新、快捷键不重复/不吞普通输入            |
| UI                 | Settings、Portal 卡、麦克风校准页面；音频/上游用合成夹具                                                      |
| 原生 / 安装 / 服务 | Linux 的 Fcitx4/X11、Fcitx5/IBus 与 X11/Wayland；Windows UI Automation 原生编辑器；必须使用本次候选包中的桥接 |
| 性能               | 开始录音至 ready、首个 partial、结束至稳定上屏、事件丢失/重复数、长录音内存                                   |

包级检查入口示例（须先构建匹配平台的候选包）：

```bash
python tests/test_portable_deb.py .cache/build/artifacts/linux/amd64/auto/openasrinput_1.1.1_amd64.deb
```

## 结果规则

- 测试失败返回非零；环境、依赖或真实设备不足记录为阻塞，不能改为 passed。
- unittest 的 skipped 计入报告，状态为 incomplete；默认返回非零。日常 `--allow-skips` 可允许退出成功，但报告仍不完整，不能作为平台发布验收。
- 仅测试模拟上游/合成音频时，只能声明业务/协议通过，不能声明真实识别、真实麦克风或实机输入通过。
- 发布目标按 OS、CPU、桌面/输入框架、安装形态分别验收。未测的平台不能复制其他平台的通过状态。
- 构建后源码、依赖锁或资源变化应重新确认候选包与源码的一致性。不能用历史报告替代当前候选。
- 测试使用临时 HOME、端口、配置、数据库和虚构 Key，不访问正式用户数据，不重启用户桌面/输入法。

## 性能回归约束

同一机器/系统/解释器/依赖、固定输入和固定资源哈希；固定 CPU 线程与服务配置。
先预热，再交错运行基线与候选各至少 5 次，记录全部原始样本以及中位数、p95、错误率和峰值内存。
功能与准确率必须同时满足。核心指标中位数劣化超过 10% 或 p95 超过 15% 时，阻止“性能无退化”结论并调查；噪声或样本不足标为未确认。
`core` 的整套执行耗时只是回归耗时，不能代替用户操作延迟或真实 ASR RTF。
基线、测量报告和性能采样放 test-results/，不在源码中保存旧产品发布状态。

## 测试环境归属

Dockerfile、Compose 模板、测试脚本与依赖锁属于可复现源码，可以提交。
容器导出、镜像层、VM 磁盘、ISO、快照、配置秘密、录音和运行报告均放 `.cache/` 或 test-results/，不得纳入 Git。
仅回收本次测试创建的进程、容器和卷；共享 VM 必须隔离实例与正式数据。

## 使用手册配图来源

`docs/images/linux-settings.png`：1.0 源码设置服务，Linux amd64/Chrome，无输入守护进程；`windows-settings.png`：1.0.0 MSI 解包运行的私有 Python 设置服务，Windows 11 amd64/Edge。两图均使用临时 input.json 和浏览器 profile，进入“输入与快捷键”后直接捕获页面，不修改界面像素。

演示只验证配置页面和平台布局，未启动用户输入法、采集真实麦克风或原生上屏。Windows 图保留旧 Alt+Z 提示，手册说明实际 Alt+X。重新取图时使用新临时目录和回环端口，检查无路径/Key 后再替换公开图；原始脚本与日志留 test-results/。
