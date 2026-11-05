# OpenASRInput 功能测试

[English](README.md) | **简体中文**

[manifest.json](manifest.json) 定义业务场景和预期结果；[requirements.txt](requirements.txt)
固定协议/设置服务依赖，不安装麦克风或大模型运行时。

- `settings-service`：真实 HTTP 设置服务、鉴权、配置保存/读取与占用端口拒绝。
- `connection-preflight`：真实 CLI 预检、端点覆盖的 Key 隔离及每轮配置快照。
- `legacy-windows-encoding`（Windows 专项）：关闭 Python UTF-8 模式，验证本机代码页下中文模型卡保存、迁移及缓存。
- `settings-workflow`：实际设置页面和模型卡的完整操作流程。
- `portal-cards`：逐卡测试、Key 隔离、切换、保存、重载和删除。
- `microphone-calibration`：实际页面完成校准、复测、独立验证、取消和保存；使用合成 PCM/模拟识别。
- `native-editor`（Windows 专项）：实际 helper/UI Automation 与专用 TextBox/RichTextBox/WebView2
  编辑器验证文字上屏、修订、取消、选区替换及焦点保护；缺环境或跳过不能算通过。

在本产品仓库根目录执行，Python 3.10+：

```bash
python scripts/test.py setup --suite core
python scripts/test.py run --suite core
python scripts/test.py setup --suite ui
python scripts/test.py run --suite ui
# 在隔离 Windows 交互桌面执行
python scripts/test.py setup --suite windows-native
python scripts/test.py run --suite windows-native --execution-host virtual-machine
```

入口自动准备本产品测试环境、UI 工具和搜索路径 `src`、`tests`；UI 使用 Electron 44.4.5，执行时将 `OPENASRINPUT_TEST_PYTHON` 指向本产品 venv。直接调试清单命令时需自行设置相同环境。物理 Windows 主机把 execution-host 改为 physical。
原生专项 setup 调用 `prepare_windows.ps1`，run 调用 `check_windows_editor.py`。
.NET SDK 固定版本并校验 SHA-512，放本产品 `.cache/functional/windows/`。
执行器等待 WebView2 就绪并核验窗口进程身份；Windows 拒绝后台激活时，只在命中检测确认
属于专用编辑器的坐标点击，再核验前台进程。退出前保存 `test-results/native-editor-desktop.png`。
测试驱动声明 Per-Monitor V2 DPI 感知，避免高 DPI 下窗口位置与点击命中检测使用不同坐标。
`native-editor-environment.json` 记录 .NET/WebView2、DPI 和显示器区域；
`native-editor-result.json` 保存执行数量、失败与跳过明细，虚拟机工作进程也回传这些证据。

实机需要额外验证真实麦克风时，显式运行（不属于默认 `windows-native`）：

```powershell
$env:PYTHONPATH = 'src;tests'
& .cache/functional/win32-amd64/venv/Scripts/python.exe tests/functional/check_windows_editor.py `
  --microphone --portal-checkout '<Portal源码目录>' --portal-python '<Portal测试环境python.exe>'
```

该入口只运行 `test_windows_session` 的三个场景，创建自己的本地 Portal/模拟上游及专用编辑器，
退出时回收两者的进程树。报告为 `test-results/native-microphone-*`；
验证真实音频缓存、停止、听写/指令实际上屏，不测试云端识别准确率或物理按键。

环境、下载和构建结果归 `.cache/`；测试配置、专用编辑器和截图归 `test-results/`，均不进 Git。
设置/UI 场景不切换宿主输入法。ARM64 `core` 不等于 Fcitx 插件或 deb 安装验收；
真实录音、Office 与安装升级按 [测试约束](../../docs/testing.zh-CN.md) 单独验收；构建环境见 [开发文档](../../docs/development.zh-CN.md)。
