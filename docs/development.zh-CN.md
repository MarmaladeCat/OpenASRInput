# OpenASRInput 开发与发布

[English](development.md) | **简体中文**

面向源码维护者。普通用户安装见 [使用手册](user-guide.zh-CN.md)，验收标准见 [测试约束](testing.zh-CN.md)。本仓库独立管理环境，不借用 Portal 或工作区的依赖。

## 源码环境

Python 3.10+，在仓库根目录创建虚拟环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[portal]'
bash scripts/start.sh demo
bash scripts/start.sh settings
```

Windows 使用 `py -3.12 -m venv .venv`，随后执行 `.venv\Scripts\python.exe -m pip install -e ".[portal]"` 和 `.venv\Scripts\python.exe -m openasrinput settings`。开发配置使用 `OPENASRINPUT_CONFIG` 指向忽略目录内的文件。demo 只验证内存预编辑，不进行原生上屏。

Linux 原生编译需要对应输入法开发库；Windows 桥接需要 .NET/C++ 工具链。Node/Electron 仅用于网页和面板回归，不是 Python 服务运行前提。源码职责见 [架构](architecture.zh-CN.md)。

## 修改与检查

```bash
python scripts/test.py setup --suite unit
python scripts/test.py run --suite unit --allow-skips
node tests/test_wayland_panel.mjs
node tests/test_gnome_lifecycle.mjs
```

按改动再选择 core、ui、原生或包级场景；条件跳过保留为 incomplete。Python 格式与静态检查使用本仓库 pyproject.toml 的 Ruff 配置，前端遵循现有格式化配置。不要为了测试重启用户桌面或输入法。

## 固定环境构建

```bash
python scripts/build.py --platform linux --arch amd64
python scripts/build.py --platform linux --arch arm64
# 在隔离 Windows 环境执行
python scripts/build.py --platform windows --arch amd64 --wix-bin <WiX目录>
```

Linux 使用 Ubuntu 22.04 基线容器和 PyInstaller 6.16.0；Windows 使用 Python 3.12.10、.NET SDK 8.0.408、WiX 3.14.1，以及 LLVM-MinGW 20261104 UCRT x86_64 或已安装的 Visual Studio C++/Windows SDK。`LLVM_MINGW_ROOT` 指向已校验解压目录；该 LLVM-MinGW ZIP 的 SHA256 为 `552191b5754c49a5a20723276a6fc56541ea1922c4c50b7b669022333fc1b40f`。

`build.py` 是公开入口；`build_portable_deb.py` 组装 Linux 固定环境，`build_deb.py/build_runtime.py` 组装包与私有 Python，`build_windows.py` 构建 Windows 桥接及 MSI，`windows_replacement.py` 处理替换和卸载。`build-native.sh` 用于单独原生开发，`package_gnome.py` 管理扩展包。

`container_matrix.py`、`desktop_matrix.py/desktop_targets.py` 分别运行系统和桌面矩阵；`check_gnome_panel.py/check_settings.py/check_electron.py` 是隔离图形检查组件，`check_git_payload.py` 检查独立源码载荷。

## 发布与文档维护

单独预览文档时，先创建 `test-results/`，再运行 `python scripts/release.py --docs test-results/product-docs.zip`。全部人工 Markdown、图片和链接附件保留原始字节与相对目录。平铺发行目录在相同内容的 README 副本旁保留 `release.md` / `release.zh-CN.md`，确保语言链接有效。

产品版本与工具元数据由 VERSION 指定为 **1.0.0**。候选包位于 `.cache/build/artifacts/<系统>/<架构>/<变体>/`，成功后由 `scripts/release.py` 发布到 `release/1.0.0/`，不生成产品 dist/。版本目录平铺软件包、完整 docs ZIP、中英文 README、清单与 SHA256SUMS。

发布器校验版本、架构、唯一候选和哈希，同源的其他平台包可合并。源码或文档变化后不能拿旧收据证明新候选；应重新构建相应目标。平台验收和构建分开记录。

人工修改六类文档，版本面向用户的变化写入 [版本说明](release.zh-CN.md)，不要复制测试流水账。文档归档保留图片和相对目录，发行目录 README 逐字复制版本说明；脚本不得拼接或生成产品说明。精选截图须注明平台、版本、演示步骤与模拟边界。

Git 管理源码、依赖清单、配置模板、构建配方、测试和人工文档；真实配置、凭据、数据库、录音、测试原图、构建缓存与安装包由 `.gitignore` 排除。发布时先推送本产品提交，再由外层固定 gitlink；提交与上传由维护者确认。
