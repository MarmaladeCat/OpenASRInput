# OpenASRInput 接口与行为契约

[English](API.md) | **简体中文**

面向接入方和桥接开发者。Input 是 Portal 的客户端，不提供识别服务 HTTP API；跨产品协议的权威定义是 OpenASRPortal 的《识别与个人热词 API v1》。本文规定 Input 如何消费协议以及本地输入边界。

## Portal 连接

配置保存 Portal HTTP(S) origin、客户端 ASR Key 与可选 profileId。管理密码、Notes token 和云厂商 Key 不能替代 ASR Key。HTTP 使用 `Authorization: Bearer <ASR_KEY>`；拒绝重定向，WS 路径必须同源且属于创建所得 sessionId。

调用顺序：GET `/v1/capabilities` 和 `/v1/profiles` → POST `/v1/sessions` → 使用一次性 ticket 连接返回 streamPath → 等 `session.ready` → 上传 PCM 并消费事件 → `audio.end` → 等最终事件。创建体含 `purpose:"dictation"`、可选 clientRequestId/profileId 和 `audio:{encoding:"pcm_s16le",sampleRate:16000,channels:1}`。

音频为裸 PCM16 小端单声道 16kHz，二进制 WS 消息，不能发送 WAV 文件头。未 ready 不上传；收尾后停止上传但继续接收定稿。失败后建立新会话，不自动重放旧音频。

服务公布时，Input 协商 `effectiveSessionLimits`、`recognitionCapabilities`；创建和 ready 的 `profileId`、`limits`、`capabilities` 必须一致。录音使用 295 秒与 `maxRecordingMs` 较小值，从采集启动计时并包含预录音，ready 不重置。累计 PCM 预算同样包含停止尾帧，到限仅截取完整样本。新发现的较短限制若已被预录缓存超过，本轮明确拒绝且不上传；正常到限则停止采集、按序发送已接收音频再 audio.end。待上传缓存最多 60 秒。验证并采用 `readyTimeoutMs`，旧服务回退 45 秒；取消可中断启动与上传。

设置保留识别能力快照，显示录音中预览、停止后逐步出字、停止后识别或时机未知。运行状态的 `previewPhase`、`recordingLimitMs` 来自活动会话。未知能力不推断为实时预览，SSE／WS 或 `partialResults` 本身不足以说明出字时机。

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

Portal 保证按音频顺序的不可变前缀和可替换尾部，包括交错的二遍结果。Input 每个唯一公共 final 只提交一次；final 可以短于先前预览，剩余尾部随后使用新 ID。不通过回滚原生提交修补上游乱序。

缓存 PCM 发完、发送 audio.end 时启用一次性 `finalizeTimeoutMs`，当时已经等待中的 receive 也采用新截止时间；partial 不续期。WS 关闭但无终态不算成功；retryable 仅允许新会话尝试，不表示可安全重提已有文字。

## 本地桥接契约

Linux 桥接由输入法框架提供上下文；Windows 桥接使用原生进程与 stdio IPC。`generation` 标识本轮，`lease/contextId/focusEpoch` 固定目标，`commitId` 和 ACK 标识本地提交。它们不是 Portal 字段，也不是向第三方承诺的稳定网络 API。

新桥接必须实现目标获取/失效、预编辑更新/清理、稳定文本提交与确认、结束回收。旧 generation、失焦或目标切换后的结果不能写入新窗口；未确认提交不能自动重试到另一个目标。取消不能撤回已经成功上屏的文字。

Shift+Space 控制普通听写；Enter 正常收尾，Esc 取消。文本指令修改默认 Linux Alt+Z、Windows Alt+X，属于独立模型连接，不是 Portal WS 控制指令。

Alt 仅在成功读取非空选区时执行修改；无选区或可选选区读取能力不受支持时，退回等价于 Shift+Space 的普通听写。失焦、明确只读、超大选区及传输失败仍报错。可选提供者查询后重新核验目标。

仅普通听写的展示/提交会清除中文 `。！？` 后的 ASCII 填充空格，覆盖同一轮跨 final 的边界；英文词间空格和换行保留。协议账本保留原文校验修订和定稿；选区修改模型结果不做此处理。

## 设置与个人热词

本地设置页默认回环端口 10088。本机启动凭证通过 `POST /api/settings/session` 换取独立页面 token；`GET` 读取该页面原有截止时间。受保护的 `/api/` 请求检查 token、有效期和来源。`settings.timeoutMinutes` 为 0–525600 的整数，默认 20，0 表示不限时。该页面保存修改后的时长会重置自身截止时间；普通请求及刷新不续期。过期页面 token 不能打开或签发新会话。本机启动凭证在设置服务生命周期内保留有效，供 settings 命令重新打开页面。它是产品内部配置界面，不用于远程管理或第三方数据库访问。配置保存具有并发版本检查，冲突应刷新再编辑。

个人热词走 Portal `/v1/hotwords`：GET 读取 revision，PATCH 更新 settings，数组整体替换；409 刷新后协调。公共目录 `/v1/hotwords/catalog` 和单表下载只产生候选，逐词加入并保存个人表后才启用。同 Key 共用个人表，不同 Key 隔离。

配置和本地 IPC 变更需相应 [单元、UI 和原生检查](testing.zh-CN.md)。不要把内部模块导出为跨产品共享库。
