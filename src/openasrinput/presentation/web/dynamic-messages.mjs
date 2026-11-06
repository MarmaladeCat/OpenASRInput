// Nested positions contain authored messages; other placeholders are opaque user data.
export const dynamicMessages = {
  '权重 {0}': 'Weight {0}',
  已在热词表中: 'Already in dictionary',
  候选词: 'Candidate',
  'Portal 卡已更新，请测试并刷新当前卡的识别配置。':
    'Portal card updated. Test and refresh its recognition profiles.',
  '已保存，留空保持原值': 'Saved; leave blank to keep the current value',
  '填写 Portal 接入 Key': 'Enter a Portal access key',
  'Portal 卡已更新，请刷新当前连接的个人热词。':
    'Portal card updated. Refresh personal hotwords for this connection.',
  '请先保存或放弃其他设置/热词修改，再切换或保存 Portal 卡。':
    'Save or discard other settings and hotword edits before changing Portal cards.',
  空闲: 'Idle',
  '录音中（等待后端，音频缓存）': 'Recording (waiting for backend, buffering audio)',
  录音中: 'Recording',
  收尾中: 'Finishing',
  正在按语音指令修改选区: 'Editing selection with voice instructions',
  '待命（快捷键开始录音）': 'Ready (press shortcut to record)',
  故障: 'Failed',
  未启动: 'Stopped',
  '设置请求失败（{0}）': 'Settings request failed ({0})',
  '预览已更新，保存后应用设置。': 'Preview updated. Save to apply settings.',
  '面板已隐藏（不影响输入）': 'Panel hidden (input continues)',
  '{0} · 三行预览': ['{0} · Three-line preview', [0]],
  '清晰克制的中性色与蓝色强调。': 'Clear neutral colors with blue accents.',
  '柔和圆角、浅色表面与青绿到靛蓝的操作色。':
    'Soft corners and light surfaces with teal and indigo accents.',
  '雾蓝与冰川青，安静清爽的北欧配色。': 'Quiet Nordic colors in misty blue and glacial teal.',
  '奶油纸色与柔和玫瑰，暗色模式呈现深紫夜色。':
    'Cream paper and soft rose, with deep purple nights in dark mode.',
  '使用已保存的 Portal 连接，点击“刷新 Portal 热词状态”。':
    'Use the saved Portal connection by clicking “Refresh Portal hotword status”.',
  'Windows 独立语音输入，保留原有键盘输入法。':
    'Independent Windows voice input, alongside your existing input method.',
  '统一语音输入，可自动识别或手动选择 IBus、Fcitx4、Fcitx5。':
    'Unified voice input with automatic or manual IBus, Fcitx4, and Fcitx5 selection.',
  'Windows 独立后台 · 原有输入法保留 · 悬浮预览与定稿输入':
    'Independent Windows background app · Existing input method retained · Floating preview and final text',
  '独立语音输入 · Portal v1 · IBus / Fcitx4 / Fcitx5':
    'Independent voice input · Portal v1 · IBus / Fcitx4 / Fcitx5',
  '先结束原输入法候选再开始语音。语音面板显示时，Enter 收尾并提交剩余定稿，Esc 取消尚未提交的内容；普通字符、带修饰键的 Enter/Esc 和空闲时按键保留给原应用。':
    'Finish existing input-method candidates before recording. While the voice panel is visible, Enter finishes and commits remaining text; Esc cancels uncommitted text. Ordinary characters, modified Enter/Esc, and idle keys go to the original app.',
  '本界面只管理本应用，不替换原有输入法，也不包含 Portal 服务。':
    'This page manages Input. Your existing input method and the separate Portal service are managed independently.',
  '从开始菜单启动 OpenASRInput；托盘可打开设置或退出。':
    'Start OpenASRInput from the Start menu. Use its tray icon for settings or exit.',
  '跟随 Portal 默认': 'Follow Portal default',
  '当前默认：{0} · 每轮录音使用 Portal 当时的默认配置':
    'Current default: {0} · Each recording uses the current Portal default',
  'Portal 尚未设置默认配置，请到管理页设置后刷新。':
    'Portal has no default profile. Set one in administration, then refresh.',
  '不指定配置 ID；每轮录音由 Portal 选择默认配置。':
    'No profile ID specified. Portal chooses its default for each recording.',
  当前指定配置: 'Currently selected profile',
  '{0} · 此配置不在当前 Portal 列表中，请重新选择。':
    '{0} · This profile is not in the current Portal list. Choose another.',
  '{0} · 测试并刷新后可查看配置名称。': '{0} · Test and refresh to view the profile name.',
  实时流式: 'Real-time streaming',
  分段识别: 'Segmented recognition',
  延迟以服务能力为准: 'Latency depends on the service',
  已选择: 'Selected',
  使用此配置: 'Use this profile',
  '请先保存热词设置，或刷新热词以放弃编辑，再保存应用设置。':
    'Save hotwords, or refresh to discard their edits, before saving application settings.',
  '设置已保存。外观按后端能力更新，识别与设备参数在下一轮录音生效；Linux 输入框架更改需执行 openasrinput start。':
    'Settings saved. Appearance follows backend capabilities; recognition and device settings apply to the next recording. Run openasrinput start to apply Linux framework changes.',
  '当前后端：{0}': ['Current backend: {0}', [0]],
  原生桥接: 'Native bridge',
  未运行: 'Not running',
  '配置已更改，请执行 openasrinput start': 'Configuration changed; run openasrinput start',
  '等待激活 IBus 语音输入源并聚焦输入框':
    'Activate the IBus voice input source and focus an input field',
  '输入服务未运行；设置将在启动时应用。':
    'Input service is not running; settings apply on startup.',
  '原生面板：{0} · {1} · 透明度 {2}%': ['Native panel: {0} · {1} · Transparency {2}%', [1]],
  当前没有显示会话: 'No visible session',
  'GNOME 面板未提供新版布局接口，使用独立 XWayland 面板':
    'GNOME has no current layout interface; using an independent XWayland panel',
  '当前 X11 合成环境不支持透明通道': 'The X11 compositor does not support alpha transparency',
  '自定义面板暂不可用，已回退至 IBus 系统辅助面板。请检查面板组件或桌面扩展。':
    'The custom panel is unavailable. Using the IBus auxiliary panel; check panel components or desktop extensions.',
  输入服务: 'Input service',
  输入服务未启动: 'Input service stopped',
  守护进程正在运行: 'Background service running',
  连接设置等待下一轮生效: 'Connection changes apply to the next recording',
  '守护进程未启动。保存的设置会在下一次启动时读取。':
    'Background service stopped. Saved settings will load on startup.',
  '命令行覆盖项：{0}': 'Command-line overrides: {0}',
  再次按下快捷键: 'Shortcut pressed again',
  '按下 Enter 收尾': 'Enter pressed to finish',
  输入焦点或输入上下文失效: 'Input focus or context lost',
  当前不是可输入目标: 'Current target is not editable',
  达到录音时限: 'Recording time limit reached',
  'Portal 主动结束会话': 'Portal ended the session',
  取消录音: 'Recording cancelled',
  '连接、设备或协议错误': 'Connection, device, or protocol error',
  '最近停止原因：{0}': ['Last stop reason: {0}', [0]],
  输入框失焦: 'Input field lost focus',
  输入框销毁: 'Input field destroyed',
  切换输入法: 'Input method changed',
  输入框不可编辑: 'Input field is not editable',
  '原生事件：{0}': ['Native event: {0}', [0]],
  '第 {0} 轮': 'Round {0}',
  '请先保存热词设置，或刷新热词以放弃编辑，再重新载入应用设置。':
    'Save hotwords, or refresh to discard edits, before reloading settings.',
  '已重新载入保存的设置。': 'Saved settings reloaded.',
  '正在测试连接…': 'Testing connection…',
  '连接正常 · {0} 个识别配置 · 录音上限 {1} 分钟':
    'Connected · {0} recognition profiles · Recording limit {1} minutes',
  'Portal 测试通过；尚未保存的表单不会写入配置。':
    'Portal test passed. Unsaved form values have not been written to configuration.',
  '已读取 {0} 个设备。设备列表不触发录音。':
    'Found {0} devices. Listing devices does not start recording.',
  'Portal 热词{0} · 版本 {1} · {2}': ['Portal hotwords {0} · Revision {1} · {2}', [0, 2]],
  已开启: 'enabled',
  已关闭: 'disabled',
  '尚无默认识别配置，个人表仍可保存。':
    'No default recognition profile; personal hotwords can still be saved.',
  'Portal 当前保存状态：上游选用 {0} 个，未选用 {1} 个。实际选词受总开关、逐词状态及上游格式和容量限制。':
    'Saved Portal state: {0} selected upstream, {1} omitted. Selection depends on enabled states, upstream format, and capacity.',
  '配置上游后可查看实际选词。': 'Configure an upstream to view selected words.',
  '{0} 个推荐词 · 第 {1} / {2} 页 · 状态以当前个人表编辑为准':
    '{0} recommended words · Page {1} / {2} · States reflect current personal edits',
  '{0} · 权重 {1} · 已在热词表中': '{0} · Weight {1} · Already in dictionary',
  '{0} · 权重 {1} · 候选词': '{0} · Weight {1} · Candidate',
  已加入: 'Added',
  加入热词表: 'Add to dictionary',
  '没有匹配的候选词。': 'No matching candidates.',
  '选择公共推荐表，加载后在此查看候选词。':
    'Select and load a public dictionary to view candidates here.',
  '此 Portal 尚不支持完整推荐列表，请升级 Portal':
    'This Portal does not support full recommendation lists. Upgrade Portal.',
  '有效 {0} 词，忽略 {1} 行，去重 {2} 行。{3} 样例：{4}': [
    '{0} valid words, {1} skipped lines, {2} duplicates. {3} Examples: {4}',
    [3]
  ],
  '推荐表已载入候选区，点击“加入热词表”后保存生效。':
    'Recommendations loaded. Add words to your dictionary, then save.',
  请选择公开词库来源: 'Select a public dictionary source',
  请先查询热词: 'Load hotwords first',
  '热词设置已保存，下一轮录音生效。': 'Hotwords saved; they apply to the next recording.',
  '个人热词已刷新。': 'Personal hotwords refreshed.',
  '热词已编辑，点击“保存热词设置”生效。':
    'Hotwords edited. Click “Save hotword settings” to apply.',
  '有未保存的修改；保存后更新 Portal 状态，下一轮录音生效。':
    'Unsaved changes. Save to update Portal; changes apply to the next recording.',
  '请先保存或放弃其他设置修改，再运行校准。': 'Save or discard other edits before calibration.',
  '设置已载入。': 'Settings loaded.',
  '暂无 Portal 卡，请在下方新增；联合安装会自动添加本机 Portal。':
    'No Portal cards. Add one below; the combined installer adds the local Portal automatically.',
  '已保存；留空保留本卡 Key': 'Saved; leave blank to keep this card’s key',
  '此 Portal 的独立识别 Key': 'This Portal’s independent recognition key',
  '配置新 Portal 卡': 'Configure a new Portal card',
  '保存并新增 Portal 卡': 'Save and add Portal card',
  '配置已修改，请重新测试并保存。': 'Configuration changed. Test again and save.',
  '请先保存此卡，再使用。': 'Save this card before using it.',
  '删除当前 Portal 卡？删除后需要选择其他卡才能录音。':
    'Delete the active Portal card? Select another card before recording again.',
  '删除此 Portal 卡？': 'Delete this Portal card?',
  '请填写名称、Portal 地址和此卡的识别 Key。':
    'Enter a name, Portal address, and this card’s recognition key.',
  '连接通过 · {0} ms{1}': 'Connection passed · {0} ms{1}',
  '连接失败 · {0} ms · {1}': ['Connection failed · {0} ms · {1}', [1]],
  当前使用: 'Active',
  'Portal 卡已保存，当前选择在下一轮录音生效。':
    'Portal card saved. The selected card applies to the next recording.',
  '正在测试连接与 HTTP 往返时延…': 'Testing connection and HTTP round-trip latency…',
  '暂无已保存的模型卡，请在下方完成配置后新增。':
    'No saved model cards. Complete a new card below.',
  '已保存；留空保留本卡 Key，填写新值替换':
    'Saved; leave blank to keep this card’s key, or enter a replacement',
  'Key 已保存，不回显；其他模型卡不会继承此 Key。':
    'Key saved and hidden. Other model cards do not inherit it.',
  '新增卡必须手动填写 Key。': 'Enter a key manually for each new card.',
  配置新模型卡: 'Configure a new model card',
  保存并新增模型卡: 'Save and add model card',
  保存此卡配置: 'Save this card',
  '测试通过 · {0} ms': 'Test passed · {0} ms',
  '测试失败 · {0}': ['Test failed · {0}', [0]],
  '目录缓存：{0}': 'Catalog cached: {0}',
  '配置已修改，尚未保存；请保存此卡后再使用。':
    'Unsaved configuration changes. Save this card before using it.',
  '请先保存此卡配置，再使用。': 'Save this card’s configuration before using it.',
  '删除此模型卡并停用文本修改？': 'Delete this model card and disable text editing?',
  '删除此模型卡？': 'Delete this model card?',
  请刷新并选择模型名称: 'Refresh and select a model',
  '{0}（原配置 / 尚未刷新确认）': '{0} (previous setting / not yet refreshed)',
  'API 地址': 'API address',
  '请先填写：{0}': ['Complete these fields: {0}', [0]],
  '模型卡名称、API 地址、Key、模型名称': 'Model card name, API address, key, model name',
  '请填写有效的 HTTP(S) API 地址': 'Enter a valid HTTP(S) API address',
  '模型卡已保存；当前选择在下一轮录音生效。':
    'Model card saved; selection applies to the next recording.',
  '正在刷新模型名称…': 'Refreshing model names…',
  '正在测试此模型卡…': 'Testing this model card…',
  '已刷新 {0} 个模型，请选择 · {1}': 'Loaded {0} models. Select a model · {1}',
  '配置完整时仍可保存。': 'A complete configuration can still be saved.',
  '个人热词表最多 2000 词': 'Personal dictionaries allow up to 2,000 words',
  '热词必须包含 text 文本': 'A hotword must contain a text value',
  "热词须为 2–64 字符，可使用文字、数字、空格及 .+#-/_'":
    "Hotwords must be 2–64 characters: letters, numbers, spaces, or .+#-/_'",
  '权重须为 1–5 的整数': 'Weight must be an integer from 1 to 5',
  '启用状态 enabled 须为布尔值': 'The enabled state must be a boolean',
  '热词不可重复：{0}': 'Duplicate hotword: {0}',
  '请选择个人热词表 JSON 文件': 'Select a personal dictionary JSON file',
  '文件最多 4 MiB': 'Files must not exceed 4 MiB',
  '热词表已切换，请重新导入': 'Dictionary changed; import again',
  '请选择下载的个人热词表，或包含 text / weight / enabled 的 JSON 数组':
    'Select an exported personal dictionary or a JSON array with text / weight / enabled fields',
  '个人热词已导入，保存后同步到 Portal。': 'Personal hotwords imported. Save to sync to Portal.',
  '热词已在表中：{0}': 'Hotword already exists: {0}',
  '共 {0} 词 · 启用 {1} 词 · 搜索结果 {2} 词 · 第 {3} / {4} 页':
    '{0} words · {1} enabled · {2} matches · Page {3} / {4}',
  '{0} 权重': '{0} weight',
  '{0} 启用状态': '{0} enabled state',
  已启用: 'Enabled',
  已停用: 'Disabled',
  '没有匹配的热词。': 'No matching hotwords.',
  '暂无热词，可手动新增、导入或从公共推荐候选区添加。':
    'No hotwords. Add manually, import a file, or choose public recommendations.',
  '准备好后开始，录音仅由本机输入法采集。':
    'Start when ready. Recording is captured only by the local input app.',
  '本次设备：{0} · 识别配置：{1}': 'Device: {0} · Recognition profile: {1}',
  '环境声测量 · 请保持安静，约 {0} 秒后朗读':
    'Measuring background noise · Stay quiet; read in about {0} seconds',
  独立验证朗读: 'Independent validation passage',
  '{0} 秒 / 最多 45 秒': '{0} s / maximum 45 s',
  重新校准: 'Recalibrate',
  '声音电平估计 {0} dBFS · 背景 {1} dBFS · 峰值 {2} dBFS · 削波 {3}% · 自动增益候选 {4}×。 {5}': [
    'Estimated speech {0} dBFS · Background {1} dBFS · Peak {2} dBFS · Clipping {3}% · Suggested gain {4}×. {5}',
    [5]
  ],
  候选比较: 'Candidate comparison',
  复测: 'Retest',
  独立验证: 'Independent validation',
  '{0} · 错误 {1}/{2} 字 · CER {3}%': ['{0} · {1}/{2} character errors · CER {3}%', [0]],
  '{0} Hz 高通': '{0} Hz high-pass',
  无滤波: 'No filter',
  '出现削波，不推荐': 'Clipping detected; not recommended',
  '（无识别文本）': '(No recognized text)',
  '尚无匹配的校准档案。直接开始校准，程序自动选择增益，无需先手动调节。':
    'No matching calibration profile. Start calibration to choose gain automatically; no manual adjustment is needed.',
  '自动跟随系统默认麦克风。已保存设备档案：{0}': [
    'Following the system default microphone. Saved profiles: {0}',
    [0]
  ],
  '{0}。录音时核对设备与识别配置，匹配后应用。': [
    '{0}. Applied when the device and recognition profile match at recording time.',
    [0]
  ]
};
