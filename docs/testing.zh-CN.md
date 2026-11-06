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

## 必须覆盖的行为

| 层次               | 必测内容                                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------------------------------- |
| unit / core        | 录音轮次、连接卡与密钥隔离、预览/revision/final、失焦与取消、配置热更新、快捷键不重复/不吞普通输入            |
| UI                 | Settings、Portal 卡、麦克风校准页面；音频/上游用合成夹具                                                      |
| 原生 / 安装 / 服务 | Linux 的 Fcitx4/X11、Fcitx5/IBus 与 X11/Wayland；Windows UI Automation 原生编辑器；必须使用本次候选包中的桥接 |
| 性能               | 开始录音至 ready、首个 partial、结束至稳定上屏、事件丢失/重复数、长录音内存                                   |

包级检查入口示例（须先构建匹配平台的候选包）：

```bash
python tests/test_portable_deb.py .cache/build/artifacts/linux/amd64/auto/openasrinput_1.0.1_amd64.deb
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
