# OpenASRInput 架构与设计

[English](architecture.md) | **简体中文**

本文面向修改客户端的开发者；网络字段见 [API](API.zh-CN.md)，安装操作见 [使用手册](user-guide.zh-CN.md)。

## 分层与依赖方向

`src/openasrinput/entrypoints` 组装命令行、守护进程与设置服务。`application` 控制录音轮次、快捷键、输入目标和提交时序；`domain` 保存状态机、识别账本等不依赖 GUI 的规则。`adapters` 连接 Portal 和平台输入能力；`infrastructure` 负责配置、进程、音频与系统差异；`presentation` 提供预览、面板和设置网页。

原生桥接位于 `src/native/`，对应 IBus、Fcitx4、Fcitx5、Windows。GNOME 扩展是 Wayland 面板集成资源。桥接与 Python 控制器同属 Input，不能让 Portal 操作桌面焦点或发送按键。

## 一轮输入的数据流

快捷键触发 → 固定目标上下文 → 建立 Portal 会话 → ready 后开始 PCM 上传 → partial 更新预编辑 → final 入账并排队提交 → 结束上传并等 finished → 清理本轮资源。

网络接收与音频采集并行，本地提交回到宿主允许的事件循环。`sessionId/seq/utteranceId/revision` 防止网络结果乱序与重复；`generation` 区分本地录音轮次；`lease/contextId/focusEpoch` 区分输入目标；`commitId` 与 ACK 约束本地提交。这几种身份不能互相替代。

失焦或切换目标时，旧结果不得流入新编辑框。ACK 不确定的文字保留为未确认状态，不盲目重发。取消不会撤销之前已经上屏的稳定文字。录音暂停通过结束当前会话实现，再录音建立新会话，v1 没有音频续传。

## 平台设计

- Linux 在输入法框架中维持预编辑和提交；Fcitx4 限 X11。Wayland 下的焦点、光标矩形与面板取决于桌面协议，不能套用 X11 全局注入假设。
- Windows 原生进程与控制器使用受限 IPC；目标控件能力决定预览和提交策略，不承诺所有应用具有相同能力。
- Windows 将可编辑性与可选的 UIA 值/位置接口分开判断。PowerPoint 可通过当前焦点 `paneClassDC`（或其焦点子窗口）的原生对象模型确认文字选区；明确只读、密码或禁用的目标仍拒绝输入。PowerPoint 进程里的普通控件保留对应的通用输入路径。缺少 UIA 文本范围时仅在面板预览，使用经过核验的原生选区提交；写入结果不确定时不重发。查询提供者后重新核对原生窗口及 UIA 控件身份，也覆盖同一窗口内切换输入目标。
- 设置页由本地配置服务提供，修改配置不要求重启整个用户桌面。演示模式只使用内存目标。

`InsertionEvidence` 在 Windows 字符输入前后分别隔离值读取、限长文档快照和计数/光标证据，单个可选提供者失败不会屏蔽其他可用方式。完全没有可用基线时，字符输入路径在写入前返回失败；写入后可以重复只读核验，但不重发字符。续写检查点与逐字符授权在 UIA 调用后再次核对焦点，因为提供者调用可能重入处理焦点变化。

## 配置与产品边界

Input 保存自己的设备、外观、快捷键、Portal 连接及文本修改连接配置；个人热词通过 Portal API 持久化。连接切换必须重新确认目标 origin、Key 和档案，旧回调不能覆盖新连接。

Input 不实现模型推理，不需要 Notes/Drafts 数据库。文本指令修改连接与普通 ASR 连接分开；两者凭据不混用。构建与原生验收见 [开发](development.zh-CN.md) 和 [测试约束](testing.zh-CN.md)。
