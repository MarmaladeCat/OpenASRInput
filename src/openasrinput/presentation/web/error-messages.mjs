export const errorMessages = {
  'Portal 接入凭据无效': 'Invalid Portal credentials',
  '此 Key 已撤销': 'This key has been revoked',
  识别配置不存在: 'Recognition profile not found',
  '热词设置或词库已更新，请刷新后重试': 'Hotwords or dictionaries changed. Refresh and retry.',
  '热词设置已更新，请刷新后重试': 'Hotword settings changed. Refresh and retry.',
  公共热词表不存在或未发布: 'Public dictionary missing or unpublished',
  '公开词库下载失败，可下载原文件后上传':
    'Dictionary download failed. Download the original file and upload it.',
  未知的公开词库来源: 'Unknown public dictionary source',
  '公开词库来源 ID 无效': 'Invalid public dictionary source ID',
  '公开词库超过 4 MiB，请下载并拆分后上传':
    'Public dictionary exceeds 4 MiB. Download, split, and upload it.',
  '请提供 UTF-8 文本词库': 'Provide a UTF-8 text dictionary',
  未知的词表格式: 'Unknown dictionary format',
  不支持此词库格式或二进制文件: 'Unsupported dictionary format or binary file',
  '单个词库文件最多 4 MiB，请拆分大词库':
    'Dictionary files must not exceed 4 MiB. Split larger files.',
  '一个词库最多 50000 个有效词，请拆分后导入':
    'A dictionary allows up to 50,000 valid words. Split it before importing.',
  '没有有效热词；RIME 入口文件须导入其 import_tables 引用的正文词库':
    'No valid hotwords. Import the dictionaries referenced by the RIME entry file’s import_tables.',
  词库没有正文: 'Dictionary has no contents',
  '词库不存在或不属于此 Key': 'Dictionary not found or owned by another key',
  '词库名称须为 1–100 字符': 'Dictionary name must be 1–100 characters',
  '每个 Key 最多 8 个词库，请先删除不需要的词库':
    'Each key supports up to 8 dictionaries. Remove unused ones first.',
  '所有上游 ASR 已停用或额度耗尽，请管理员补充额度':
    'All upstreams are disabled or exhausted. Ask an administrator to adjust quotas.',
  '指定上游 ASR 已停用，请选择其他配置或跟随默认':
    'Selected upstream disabled. Choose another profile or follow the default.',
  '{0}的剩余额度已用尽，请管理员补充额度': [
    '{0} quota exhausted. Ask an administrator to replenish it.',
    [0]
  ],
  '客户端 Key': 'Client key',
  '上游 ASR': 'Upstream ASR',
  '上游剩余时长不足以完成当前片段，请管理员调整额度':
    'Upstream time budget is insufficient for this segment. Ask an administrator to adjust it.',
  '此上游不提供 Token 用量；请改用时长限额或选择支持 Token 的上游':
    'This upstream does not report tokens. Use time limits or select a metered upstream.',
  '上游识别失败，请检查 Portal 配置与网络':
    'Upstream recognition failed. Check Portal configuration and network.',
  '麦克风正在被语音输入或校准使用，请先结束当前录音。':
    'The microphone is in use by dictation or calibration. Finish the current recording first.',
  '无法读取音频设备，请检查 PulseAudio / PipeWire 连接':
    'Cannot list audio devices. Check the PulseAudio / PipeWire connection.',
  '麦克风不可用或无法确认身份，请检查系统默认输入设备；不能使用扬声器监听源。':
    'Microphone unavailable or unidentified. Check the default input device; speaker monitor sources are not supported.',
  '当前应用不提供选区读取；请使用支持选区的编辑器，或用 Shift+Space 听写':
    'This app does not expose its selection. Use a supported editor or Shift+Space for dictation.',
  '选区已变化，未开始文本修改': 'Selection changed. Text editing was not started.',
  识别后端启动失败: 'Recognition backend failed to start',
  '请在设置 → 文本指令修改中选择模型卡': 'Select a model card in Settings → Voice text editing',
  '请补全模型卡的 API 地址和模型': 'Complete the model card’s API address and model',
  '请在设置 → 文本指令修改中填写 DeepSeek API Key':
    'Enter a DeepSeek API key in Settings → Voice text editing',
  '选区或语音指令为空、过长，未修改原文':
    'Selection or instruction is empty or too long. Original text retained.',
  '请填写 API 地址': 'Enter an API address',
  '文本模型返回结果不完整、为空或过长，未修改原文':
    'Model result incomplete, empty, or too long. Original text retained.',
  '无法连接文本模型或请求超时，未修改原文':
    'Model connection failed or timed out. Original text retained.',
  '文本模型响应格式无效，未修改原文': 'Invalid model response format. Original text retained.',
  模型目录格式无效: 'Invalid model catalog format',
  '无法获取模型列表或请求超时；已保存配置不受影响':
    'Model list unavailable or request timed out. Saved configuration is retained.',
  '文本模型请求失败（HTTP {0}），未修改原文；请检查 Key、额度和模型':
    'Model request failed (HTTP {0}). Original text retained; check the key, quota, and model.',
  '文本模型返回内容过长，未修改原文': 'Model response too long. Original text retained.',
  '模型列表刷新失败（HTTP {0}），请检查 Key 和地址':
    'Model list refresh failed (HTTP {0}). Check the key and address.',
  模型目录过大: 'Model catalog too large',
  'Windows 原生组件不存在，请使用完整安装包或设置 OPENASRINPUT_WINDOWS_HELPER':
    'Windows native component missing. Use the complete installer or set OPENASRINPUT_WINDOWS_HELPER.',
  'Windows 未确认文字输入，请检查目标窗口权限；不会自动重复输入。':
    'Windows did not confirm text delivery. Check target window permissions. Text will not be resent automatically.',
  '系统默认麦克风不可用，请检查 Windows 输入设备设置':
    'Default microphone unavailable. Check Windows input device settings.',
  '当前应用无法可靠读取选区，请换用支持选区的编辑器':
    'This app cannot reliably expose its selection. Use a supported editor.',
  '请在设置页重新选择 Windows 麦克风': 'Select the Windows microphone again in settings',
  'Windows 麦克风返回了不完整的 PCM16 数据': 'Windows microphone returned incomplete PCM16 data',
  'Windows 桥接协议不匹配': 'Windows bridge protocol mismatch',
  '快捷键被其他应用占用：{0}': 'Shortcut already used by another app: {0}',
  'Windows 原生桥接响应超时': 'Windows native bridge timed out',
  'Windows 原生桥接已退出：{0}': 'Windows native bridge exited: {0}',
  'Windows 桥接拒绝请求': 'Windows bridge rejected the request',
  'Windows 桥接返回了意外响应': 'Unexpected Windows bridge response',
  'Windows 麦克风未确认开始采集': 'Windows microphone did not confirm recording',
  'Windows 麦克风采集提前结束，请检查设备和权限':
    'Windows recording ended early. Check device and permissions.',
  '校准任务已变化，请重新载入': 'Calibration task changed. Reload.',
  '设置在校准期间已变化，请重新开始校准': 'Settings changed during calibration. Start again.',
  '正在检查设备与识别配置…': 'Checking device and recognition profile…',
  '识别配置或热词在校准期间已变化，请重新开始':
    'Recognition profile or hotwords changed during calibration. Start again.',
  '设备或系统输入音量已变化，请重新开始校准':
    'Device or system input volume changed. Restart calibration.',
  '录音期间设备或系统音量发生变化，请重录':
    'Device or volume changed during recording. Record again.',
  '复测当前配置与推荐候选，排除偶然差异…':
    'Retesting current and recommended settings to rule out chance differences…',
  '已有校准任务，请先取消': 'Cancel the existing calibration task first',
  '设置已变化，请重新载入后校准': 'Settings changed. Reload before calibration.',
  '请先配置并保存 Portal 接入 Key': 'Configure and save a Portal access key first',
  '请保持安静三秒，测量背景噪声…':
    'Stay quiet for three seconds while background noise is measured…',
  '麦克风意外停止，请检查设备后重试':
    'Microphone stopped unexpectedly. Check the device and retry.',
  '校准失败，请检查设备和连接后重试':
    'Calibration failed. Check device and connection, then retry.',
  '识别服务提前结束，未比较完整录音':
    'Recognition ended early; the complete recording was not compared.',
  '设置页已离开，校准已结束。': 'Settings page closed. Calibration ended.',
  '已取消校准。': 'Calibration cancelled.',
  '正在比较云端识别结果…': 'Comparing recognition results…',
  '比较候选：{0}': ['Comparing candidate: {0}', [0]],
  '已自动选择增益并完成复测，请再读另一段短文验证效果。':
    'Gain selected and retested. Read another passage to validate the result.',
  识别会话已取消: 'Recognition session cancelled',
  请等待环境测量结束后朗读: 'Wait for background measurement to finish before reading',
  '请完整朗读，至少录制五秒语音':
    'Read the entire passage, recording at least five seconds of speech',
  '请自然朗读下方文字，读完点击结束录音。': 'Read the passage naturally, then stop recording.',
  当前配置: 'Current settings',
  '独立验证：{0}': ['Independent validation: {0}', [0]],
  '复测差异不稳定或朗读匹配度不足，请检查朗读后重试。':
    'Retest differences are unstable or reading match is too low. Check the passage and retry.',
  请先完成候选比较: 'Complete candidate comparison first',
  '准备独立验证录音…': 'Preparing independent validation recording…',
  未知的校准操作: 'Unknown calibration action',
  '独立验证未显示可靠改善，保留当前配置。':
    'Independent validation found no reliable improvement. Current settings retained.',
  '朗读与原文差异较大，请检查是否读错、漏读或选错识别语言后重试。':
    'Reading differs substantially from the passage. Check for omissions, reading errors, or the wrong recognition language.',
  '没有可靠改善，保留当前配置。': 'No reliable improvement. Current settings retained.',
  此校准尚未通过独立验证: 'This calibration has not passed independent validation',
  '麦克风或系统音量已变化，请重新校准': 'Microphone or volume changed. Recalibrate.',
  '校准已保存，下一轮语音输入生效。': 'Calibration saved for the next recording.',
  '独立验证通过：自动增益使电平更合适，识别结果未退步，可应用推荐配置。':
    'Validation passed: gain improved levels without reducing recognition quality. You can apply the recommendation.',
  '独立验证通过，可应用推荐配置。': 'Validation passed. You can apply the recommendation.',
  '尚未配置当前 Portal 接入 Key。请打开 OpenASRInput 设置 → 语音识别，为该地址配置并选择 Portal 卡，或显式设置 OPENASRINPUT_PORTAL_KEY。':
    'No access key configured for this Portal. Open Settings → Speech recognition, configure and select a Portal card, or set OPENASRINPUT_PORTAL_KEY.',
  '即将达到录音时限，已自动暂停；按快捷键可恢复':
    'Recording limit approaching. Automatically paused; press the shortcut to resume.',
  '请先聚焦可编辑输入框，并结束当前输入法的候选':
    'Focus an editable input field and finish input-method candidates first',
  '输入目标已变化，未修改原文': 'Input target changed. Original text retained.',
  '没有识别到修改指令，未修改原文': 'No editing instruction recognized. Original text retained.',
  '光标预编辑不可用: {0}': ['Cursor preedit unavailable: {0}', [0]],
  '文本提交失败: {0}': ['Text delivery failed: {0}', [0]],
  '选区超过 16000 字符，请缩小选区': 'Selection exceeds 16,000 characters. Select less text.',
  '修改指令过长，未修改原文': 'Editing instruction too long. Original text retained.',
  '无法连接 Portal。请确认服务已启动，并在设置中检查 Portal 地址。':
    'Cannot connect to Portal. Check that it is running and verify the address in settings.',
  '语音输入启动失败，请检查设置。': 'Voice input failed to start. Check settings.',
  'Portal 接入 Key 无效。请打开 OpenASRInput 设置检查连接信息。':
    'Invalid Portal access key. Check connection settings in OpenASRInput.',
  '识别服务当前繁忙，请稍后按 Shift+Space 重试。':
    'Recognition service busy. Press Shift+Space to retry later.',
  'Portal 尚未设置有效的默认识别配置。请在 Portal 管理页添加配置并设为默认。':
    'Portal has no valid default recognition profile. Add one in administration and make it the default.',
  'Portal 尚未配置识别档案': 'Portal has no recognition profiles',
  '{0}。请在 Portal 管理页添加并保存配置。': [
    '{0}. Add and save a profile in Portal administration.',
    [0]
  ],
  '麦克风意外停止，已结束本轮录音': 'Microphone stopped unexpectedly. Recording ended.',
  '音频缓存已满（30 秒），已停止录音；请检查后端连接后重试':
    'Audio buffer full (30 seconds). Recording stopped. Check the backend connection and retry.',
  文本修改模型尚未配置: 'Text editing model not configured',
  '原生面板没有接受外观设置，请使用更新后的插件':
    'Native panel rejected appearance settings. Update the plugin.',
  原生插件没有接受键盘兼容设置: 'Native plugin rejected keyboard compatibility settings',
  '无法确认麦克风身份，使用备用增益；请检查系统输入设备。':
    'Cannot identify microphone. Using fallback gain; check system input devices.',
  'PCM16 数据不完整': 'Incomplete PCM16 data',
  '原始录音存在削波，数字增益无法修复；请降低系统麦克风音量或增加距离后重录。':
    'Source audio is clipped; digital gain cannot repair it. Lower microphone volume or increase distance and record again.',
  '录音过短，请在环境测量结束后完整朗读至少五秒。':
    'Recording too short. Read for at least five seconds after background measurement.',
  '几乎未收到声音，请检查麦克风静音、权限或系统默认输入设备。':
    'Almost no audio detected. Check microphone mute, permissions, and the default input device.',
  '能量估计中的明显声音片段较少，将继续用朗读识别结果核验，不据此判定没有语音。':
    'Few clear sound segments detected. Recognition results will be used to verify speech.',
  '估算人声与背景较接近，将继续比较识别结果；数字增益不能消除背景噪声。':
    'Estimated speech and background levels are close. Recognition comparison will continue; digital gain cannot remove noise.',
  评分文本长度无效: 'Invalid scoring text length',
  原音对照: 'Original audio reference',
  校准固定增益: 'Calibrated fixed gain',
  固定增益与轻度高通: 'Fixed gain with mild high-pass',
  输入目标已变化: 'Input target changed',
  '设备、音量或识别配置已变化，使用手动增益；请重新校准。':
    'Device, volume, or profile changed. Using manual gain; recalibrate.',
  '最多保存 20 个麦克风校准档案': 'Up to 20 microphone calibration profiles can be saved',
  '请先在 Portal 设置有效的识别配置': 'Set a valid recognition profile in Portal first',
  '请先在个人热词页保存设置以关闭自动词频统计，再运行麦克风校准。':
    'Disable automatic word-frequency tracking and save personal hotwords before calibration.',
  已应用此麦克风的验证校准: 'Validated calibration applied for this microphone',
  麦克风校准档案格式无效: 'Invalid microphone calibration profile format',
  麦克风高通参数无效: 'Invalid microphone high-pass settings',
  录音设备状态已变化: 'Recording device state changed',
  麦克风校准标识无效: 'Invalid microphone calibration identity',
  麦克风校准数值无效: 'Invalid microphone calibration values',
  输入增益: 'Input gain',
  面板透明度: 'Panel transparency',
  面板圆角: 'Panel corner radius',
  'Portal 地址必须是 HTTP(S) 地址': 'Portal address must use HTTP(S)',
  'Portal 地址请填写 HTTP(S) 根地址，例如 http://127.0.0.1:10087':
    'Enter a Portal HTTP(S) origin, for example http://127.0.0.1:10087',
  '配置必须是 JSON 对象': 'Configuration must be a JSON object',
  不支持的配置版本: 'Unsupported configuration version',
  'Portal 接入 Key 无效': 'Invalid Portal access key',
  '识别配置 ID 无效': 'Invalid recognition profile ID',
  麦克风设备名称无效: 'Invalid microphone device name',
  '当前只支持 PCM16 / 16000 Hz / 单声道': 'Only PCM16 / 16000 Hz / mono is supported',
  请选择支持的主题和亮暗模式: 'Select a supported theme and color mode',
  请选择支持的面板位置: 'Select a supported panel position',
  请选择支持的设置页面主题和亮暗模式: 'Select a supported settings theme and color mode',
  '当前语音缓冲固定为 20 词': 'The voice preview buffer is fixed at 20 words',
  普通键盘内联预编辑选项无效: 'Invalid keyboard inline preedit option',
  '输入框架必须是 auto、ibus、fcitx4 或 fcitx5':
    'Input framework must be auto, ibus, fcitx4, or fcitx5',
  '桥接 socket 需要填写长度小于 108 字节的绝对路径':
    'Bridge socket must be an absolute path shorter than 108 bytes',
  'Portal 端口无效': 'Invalid Portal port',
  '{0}必须在 {1} 之间': ['{0} must be between {1}', [0]],
  '{0}必须是整数': ['{0} must be an integer', [0]],
  未知的设置分类: 'Unknown settings category',
  '配置文件不是有效的 UTF-8 JSON；原文件已保留':
    'Configuration is not valid UTF-8 JSON. Original file retained.',
  '设置已在其他窗口修改，请重新载入后保存':
    'Settings changed in another window. Reload before saving.',
  '{0} 配置必须是对象': '{0} configuration must be an object',
  '{0} 中存在未知设置': 'Unknown settings in {0}',
  清除密钥选项无效: 'Invalid clear-key option',
  '文本模型设置已升级为模型卡，请重新打开设置页面': 'Text models now use cards. Reopen settings.',
  '联合安装的 Portal 连接文件无效': 'Invalid combined-installer Portal handoff',
  模型卡字段无效: 'Invalid model card field',
  '请填写模型卡名称和 ID': 'Enter a model card name and ID',
  请选择支持的文本模型提供商: 'Select a supported text model provider',
  文本模型名称无效: 'Invalid text model name',
  '模型卡列表最多支持 100 张': 'Up to 100 model cards are supported',
  '模型卡 ID 重复或当前模型卡不存在': 'Duplicate model card ID or active card missing',
  模型卡必须是列表: 'Model cards must be a list',
  模型卡字段必须是有效文本: 'Model card fields must be valid text',
  '文本模型地址需要是 HTTP(S) API 地址': 'Text model address must be an HTTP(S) API address',
  'DeepSeek 请选择官方地址；自定义网关请使用 OpenAI 兼容类型':
    'Use the official DeepSeek address, or choose OpenAI-compatible for custom gateways.',
  '请先配置完整模型卡：缺少{0}': ['Complete the model card; missing {0}', [0]],
  模型卡必须是对象: 'Model card must be an object',
  文本模型端口无效: 'Invalid text model port',
  'Portal 卡字段无效': 'Invalid Portal card field',
  '请填写 Portal 卡名称和 ID': 'Enter a Portal card name and ID',
  'Portal 地址请填写 HTTP(S) 根地址': 'Enter a Portal HTTP(S) origin',
  '请填写此 Portal 卡的识别 Key': 'Enter this Portal card’s recognition key',
  'Portal 卡列表最多支持 100 张': 'Up to 100 Portal cards are supported',
  'Portal 卡 ID 重复或当前卡不存在': 'Duplicate Portal card ID or active card missing',
  'Portal 卡必须是列表': 'Portal cards must be a list',
  'Portal 卡字段必须是有效文本': 'Portal card fields must be valid text',
  'Portal 卡必须是对象': 'Portal card must be an object',
  'Portal 测试请求必须是 JSON 对象': 'Portal test request must be a JSON object',
  '请填写 Portal 接入 Key': 'Enter a Portal access key',
  '校准请求必须是 JSON 对象': 'Calibration request must be a JSON object',
  '模型卡已更新，请重新载入后重试': 'Model card updated. Reload and retry.',
  '请先在语音识别中保存 Portal 地址和接入 Key':
    'Save a Portal address and access key in Speech recognition first',
  'Portal 设置地址必须为 HTTP/HTTPS 网页': 'Portal settings address must be an HTTP/HTTPS page',
  'Portal 卡已更新，请重新载入后测试': 'Portal card updated. Reload before testing.',
  '热词请求必须为 JSON 对象': 'Hotword request must be a JSON object',
  'Portal 连接配置已更新，请刷新热词后重试':
    'Portal connection updated. Refresh hotwords and retry.',
  '此 Portal 尚不支持热词 API，请升级 Portal':
    'This Portal does not support hotword APIs. Upgrade Portal.',
  请先取消校准任务: 'Cancel calibration first',
  '设置已变化，请重新载入后恢复': 'Settings changed. Reload before restoring.',
  '已恢复手动增益。': 'Manual gain restored.',
  '此 Portal 尚不支持词库导入，请升级 Portal':
    'This Portal does not support dictionary imports. Upgrade Portal.',
  '设置会话已失效，请重新打开设置': 'Settings session expired. Reopen settings.',
  设置请求来源无效: 'Invalid settings request origin',
  '连接或配置操作失败：{0}': ['Connection or configuration failed: {0}', [0]],
  连接超时或请求失败: 'Connection timed out or request failed',
  当前本地模型接口不支持会话级热词增强:
    'The current local model does not support per-session hotwords',
  '双向流式热词上限 100 tokens；Portal 保守按 UTF-8 字节预算选词，非 100 个词':
    'Streaming hotwords have a 100-token limit. Portal selects conservatively by UTF-8 bytes, not 100 words.',
  'Qwen Audio 3.1 即时热词最多 2000 个；普通权重 1–5':
    'Qwen Audio 3.1 supports up to 2,000 instant hotwords with weights 1–5'
};
