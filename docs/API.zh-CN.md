# OpenASRInput 接口与行为契约

[English](API.md) | **简体中文**

面向接入方和桥接开发者。Input 是 Portal 的客户端，不提供识别服务 HTTP API；跨产品协议的权威定义是 OpenASRPortal 的《识别与个人热词 API v1》。本文规定 Input 如何消费协议以及本地输入边界。

## Portal 连接

配置保存 Portal HTTP(S) origin、客户端 ASR Key 与可选 profileId。管理密码、Notes token 和云厂商 Key 不能替代 ASR Key。HTTP 使用 `Authorization: Bearer <ASR_KEY>`；拒绝重定向，WS 路径必须同源且属于创建所得 sessionId。

调用顺序：GET `/v1/capabilities` 和 `/v1/profiles` → POST `/v1/sessions` → 使用一次性 ticket 连接返回 streamPath → 等 `session.ready` → 上传 PCM 并消费事件 → `audio.end` → 等最终事件。创建体含 `purpose:"dictation"`、可选 clientRequestId/profileId 和 `audio:{encoding:"pcm_s16le",sampleRate:16000,channels:1}`。

音频为裸 PCM16 小端单声道 16kHz，二进制 WS 消息，不能发送 WAV 文件头。未 ready 不上传；收尾后停止上传但继续接收定稿。失败后建立新会话，不自动重放旧音频。

## 结果与提交

| 字段/事件              | Input 的处理                                           |
| ---------------------- | ------------------------------------------------------ |
| sessionId / seq        | 拒绝旧会话；消费递增序号，重复可忽略，缺口视为协议错误 |
| utteranceId / revision | 按语句更新完整替换文本；旧修订不覆盖新修订             |
| transcript.partial     | 更新预编辑，不作为永久上屏文字                         |
| transcript.final       | 每个语句最多提交一次；空 final 仍纳入数量              |
| session.finished       | 核对 finalCount，不应遗留非空未定稿 preview            |
| session.cancelled      | 放弃本轮，不把取消标成成功                             |
| session.error          | 保留可诊断错误，清理本轮采集和连接                     |

`finalizeTimeoutMs` 是一次性的收尾截止时间，不能被连续 partial 无限延长。仅 WS 关闭而没有终态不算成功；retryable 允许新会话尝试，不表示可安全重复提交已有文字。

## 本地桥接契约

Linux 桥接由输入法框架提供上下文；Windows 桥接使用原生进程与 stdio IPC。`generation` 标识本轮，`lease/contextId/focusEpoch` 固定目标，`commitId` 和 ACK 标识本地提交。它们不是 Portal 字段，也不是向第三方承诺的稳定网络 API。

新桥接必须实现目标获取/失效、预编辑更新/清理、稳定文本提交与确认、结束回收。旧 generation、失焦或目标切换后的结果不能写入新窗口；未确认提交不能自动重试到另一个目标。取消不能撤回已经成功上屏的文字。

Shift+Space 控制普通听写；Enter 正常收尾，Esc 取消。文本指令修改默认 Linux Alt+Z、Windows Alt+X，属于独立模型连接，不是 Portal WS 控制指令。

## 设置与个人热词

本地设置页默认回环端口 10088，启动生成短期私有 token，受保护的 `/api/` 请求检查 token 和来源。它是产品内部配置界面，不用于远程管理或第三方数据库访问。配置保存具有并发版本检查，冲突应刷新再编辑。

个人热词走 Portal `/v1/hotwords`：GET 读取 revision，PATCH 更新 settings，数组整体替换；409 刷新后协调。公共目录 `/v1/hotwords/catalog` 和单表下载只产生候选，逐词加入并保存个人表后才启用。同 Key 共用个人表，不同 Key 隔离。

配置和本地 IPC 变更需相应 [单元、UI 和原生检查](testing.zh-CN.md)。不要把内部模块导出为跨产品共享库。
