import { PersonalHotwords, wordIdentity } from './personal-hotwords.mjs';
import { ModelCards } from './model-cards.mjs';
import { PortalCards } from './portal-cards.mjs';
import { AudioCalibration } from './audio-calibration.mjs';

const byId = (id) => document.getElementById(id);
const params = new URLSearchParams(location.hash.slice(1));
const token = params.get('token') || sessionStorage.getItem('openasrinput-settings-token');
if (token) {
  sessionStorage.setItem('openasrinput-settings-token', token);
  history.replaceState(null, '', location.pathname);
}
let config,
  revision,
  configPath,
  themes = [],
  profiles = [],
  selectedProfileId = '',
  defaultProfileId = '',
  profilesLoaded = false,
  dirty = false,
  busy = false;
let hotwords,
  hotwordsDirty = false,
  hotwordsBusy = false;
let dictionaryCatalog;
let calibration;
const modelCards = new ModelCards(
  api,
  (value) => {
    config.textEdit = value.config.textEdit;
    revision = value.revision;
  },
  notice,
  () => revision
);
let recommendationWords = [],
  recommendationPage = 0;
const portalCards = new PortalCards(
  api,
  (value) => {
    config.portal = value.config.portal;
    revision = value.revision;
    profiles = [];
    defaultProfileId = '';
    profilesLoaded = false;
    byId('portal-status').textContent = 'Portal 卡已更新，请测试并刷新当前卡的识别配置。';
    selectedProfileId = config.portal.profileId || '';
    byId('portal-url').value = config.portal.url;
    byId('portal-key').value = '';
    byId('portal-key').placeholder = config.portal.hasApiKey
      ? '已保存，留空保持原值'
      : '填写 Portal 接入 Key';
    byId('clear-key').checked = false;
    hotwords = null;
    dictionaryCatalog = null;
    byId('hotwords-form').hidden = true;
    byId('hotwords-dictionaries').hidden = true;
    byId('hotwords-status').textContent = 'Portal 卡已更新，请刷新当前连接的个人热词。';
    renderProfiles();
    preview();
  },
  notice,
  () => revision,
  () => {
    if (
      dirty ||
      hotwordsDirty ||
      busy ||
      hotwordsBusy ||
      modelCards.working() ||
      calibration?.working()
    ) {
      notice('请先保存或放弃其他设置/热词修改，再切换或保存 Portal 卡。', 'error');
      return false;
    }
    return true;
  }
);
const personalTable = new PersonalHotwords('hotwords', {
  changed: hotwordsChanged,
  report: (message) => notice(message, 'error'),
  run: async (operation) => {
    if (!hotwords || busy || hotwordsBusy) return;
    hotwordWorking(true);
    try {
      await operation();
    } catch (error) {
      notice(error.message, 'error');
    } finally {
      hotwordWorking(false);
    }
  }
});
const names = {
  idle: '空闲',
  connecting: '录音中（等待后端，音频缓存）',
  listening: '录音中',
  pausing: '收尾中',
  processing: '正在按语音指令修改选区',
  paused: '待命（快捷键开始录音）',
  failed: '故障',
  stopped: '未启动'
};

function notice(message, tone = '') {
  byId('feedback').textContent = message;
  byId('feedback').dataset.tone = tone;
}

async function api(path, method = 'GET', body) {
  const response = await fetch('/api/' + path, {
    method,
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal: AbortSignal.timeout(path.startsWith('text-model/') ? 70000 : 35000),
    redirect: 'error'
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `设置请求失败（${response.status}）`);
  return value;
}

function changed() {
  dirty = true;
  byId('dirty-indicator').hidden = false;
  notice('预览已更新，保存后应用设置。');
}

function saving(value) {
  busy = value;
  byId('save').disabled = value;
  byId('reload').disabled = value;
  document
    .querySelectorAll(
      'main input, main select, #portal-test, #devices-refresh, .profile-card button, #page-hotwords button, #page-text-edit button, #page-portal button'
    )
    .forEach((field) => {
      field.disabled = value;
    });
  personalTable.working(value);
  renderRecommendations();
  if (!value) renderProfiles();
}

function chooseValue(id, value, label = value) {
  const field = byId(id);
  if (
    field.tagName === 'SELECT' &&
    ![...field.options].some((option) => option.value === String(value))
  ) {
    field.add(new Option(String(label), String(value)));
  }
  field.value = String(value);
}

function appearance() {
  return {
    theme: byId('theme').value,
    colorMode: byId('color-mode').value,
    scale: Number(byId('scale').value),
    width: Number(byId('width').value),
    fontSize: Number(byId('font-size').value),
    radius: Number(byId('radius').value),
    position: byId('position').value,
    transparency: Number(byId('transparency').value)
  };
}

function portalForm() {
  const portal = {
    url: byId('portal-url').value.trim(),
    profileId: selectedProfileId
  };
  if (byId('clear-key').checked) portal.clearApiKey = true;
  else if (byId('portal-key').value.trim()) portal.apiKey = byId('portal-key').value.trim();
  return portal;
}

function preview() {
  const options = appearance(),
    theme = themes.find((item) => item.id === options.theme);
  if (!theme) return;
  const pageTheme = themes.find((item) => item.id === byId('settings-theme').value);
  const pageMode = byId('settings-color-mode').value;
  for (const [key, value] of Object.entries(pageTheme[pageMode])) {
    document.documentElement.style.setProperty('--' + key, value);
  }
  document.documentElement.style.colorScheme = pageMode;
  document.documentElement.style.setProperty(
    '--on-accent',
    pageMode === 'dark' ? pageTheme.dark.background : '#fff'
  );
  byId('theme-name').textContent = theme.title;
  byId('theme-description').textContent = theme.description;
  byId('width-value').textContent = options.width + ' px';
  byId('radius-value').textContent = options.radius + ' px';
  byId('gain-value').textContent = Number(byId('gain').value).toFixed(2) + '×';
  const card = byId('voice-preview');
  for (const [key, value] of Object.entries(theme[options.colorMode])) {
    card.style.setProperty('--' + key, value);
  }
  card.style.colorScheme = options.colorMode;
  card.style.opacity = 1 - options.transparency / 100;
  card.style.visibility = options.position === 'hidden' ? 'hidden' : 'visible';
  byId('preview-layout-label').textContent =
    options.position === 'hidden'
      ? '面板已隐藏（不影响输入）'
      : byId('position').selectedOptions[0].textContent + ' · 三行预览';
  card.style.setProperty('--panel-radius', options.radius + 'px');
  card.style.setProperty('--panel-font', options.fontSize + 'px');
  card.style.zoom = options.scale;
  card.style.width =
    Math.min(options.width, (card.parentElement.clientWidth - 24) / options.scale) + 'px';
  try {
    const origin = new URL(byId('portal-url').value);
    byId('portal-admin').href = ['http:', 'https:'].includes(origin.protocol)
      ? origin.origin + '/admin'
      : '#';
  } catch {
    byId('portal-admin').href = '#';
  }
}

function showPage(page, focus = true) {
  document.querySelectorAll('#settings-nav [role=tab]').forEach((tab) => {
    const active = tab.dataset.page === page;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    byId('page-' + tab.dataset.page).hidden = !active;
    if (active && focus) tab.focus();
  });
  byId('settings-body').scrollTop = 0;
  if (page === 'appearance') preview();
}

function populate(value, preserveModelEdits = false) {
  hotwords = null;
  hotwordsDirty = false;
  personalTable.load({ manualTerms: [], excludedTerms: [] });
  byId('hotwords-form').hidden = true;
  byId('hotwords-dictionaries').hidden = true;
  dictionaryCatalog = null;
  recommendationWords = [];
  recommendationPage = 0;
  byId('dictionary-search').value = '';
  byId('dictionary-report').textContent = '';
  renderRecommendations();
  byId('hotwords-status').textContent = '使用已保存的 Portal 连接，点击“刷新 Portal 热词状态”。';
  config = value.config;
  revision = value.revision;
  configPath = value.path;
  const windows = value.platform === 'win32';
  byId('socket-section').hidden = windows;
  byId('keyboard-native-section').hidden = windows;
  byId('linux-extra-keys').hidden = false;
  byId('preview-linux-keys').hidden = false;
  byId('preview-word-count').hidden = false;
  byId('preview-layout-label').textContent = '三行 · 20 词缓冲';
  byId('input-description').textContent = windows
    ? 'Windows 独立语音输入，保留原有键盘输入法。'
    : '统一语音输入，可自动识别或手动选择 IBus、Fcitx4、Fcitx5。';
  byId('platform-description').textContent = windows
    ? 'Windows 独立后台 · 原有输入法保留 · 悬浮预览与定稿输入'
    : '独立语音输入 · Portal v1 · IBus / Fcitx4 / Fcitx5';
  byId('keyboard-policy').textContent = windows
    ? '先结束原输入法候选再开始语音。语音面板显示时，Enter 收尾并提交剩余定稿，Esc 取消尚未提交的内容；普通字符、带修饰键的 Enter/Esc 和空闲时按键保留给原应用。'
    : '已有输入法候选时先结束候选，再开始语音。录音中普通字符与编辑键由语音模式消费；暂停收尾后恢复普通键盘输入。';
  byId('preview-policy').textContent =
    '中文按 ICU 词典分词。20 词限制只影响面板显示，完整预编辑和最终上屏内容不截断。';
  byId('preview-size-text').textContent = '第二行：最近 20 词，左到右更新';
  byId('platform-boundary').textContent = windows
    ? '本界面只管理本应用，不替换原有输入法，也不包含 Portal 服务。'
    : '本界面只管理 OpenASRInput，不安装或重启输入框架，不改动输入法方案。';
  selectedProfileId = config.portal.profileId || '';
  for (const [id, data] of Object.entries({
    theme: config.overlay.theme,
    'settings-theme': config.settings.theme,
    'settings-color-mode': config.settings.colorMode,
    position: config.overlay.position,
    transparency: config.overlay.transparency,
    'color-mode': config.overlay.colorMode,
    scale: config.overlay.scale,
    width: config.overlay.width,
    'font-size': config.overlay.fontSize,
    radius: config.overlay.radius,
    'portal-url': config.portal.url,
    'socket-path': config.runtime.socketPath,
    gain: config.audio.gain
  }))
    chooseValue(id, data);
  chooseValue('device', config.audio.deviceId || '', config.audio.deviceId || '系统默认设备');
  modelCards.load(config.textEdit, value.modelCardMetadata, preserveModelEdits ? '' : null);
  portalCards.load(config.portal, value.portalCardMetadata, preserveModelEdits);
  byId('portal-key').value = '';
  byId('keyboard-inline').checked = config.input.keyboardInlinePreedit;
  byId('input-framework').value = config.input.framework || 'auto';
  byId('clear-key').checked = false;
  byId('portal-key').placeholder = config.portal.hasApiKey
    ? '已保存，留空保持原值'
    : '填写 Portal 接入 Key';
  byId('config-path').textContent = configPath;
  byId('launch-command').textContent = windows
    ? '从开始菜单启动 OpenASRInput；托盘可打开设置或退出。'
    : `python -m openasrinput daemon --config '${configPath.replaceAll("'", "'\\''")}'`;
  dirty = false;
  byId('dirty-indicator').hidden = true;
  byId('save').disabled = busy;
  preview();
  renderProfiles();
  calibration?.load(config);
}

function renderProfiles() {
  byId('profile-list').replaceChildren();
  const defaultProfile = profiles.find((profile) => profile.id === defaultProfileId);
  const choices = [
    {
      id: '',
      title: '跟随 Portal 默认',
      note: defaultProfile
        ? `当前默认：${defaultProfile.title} · 每轮录音使用 Portal 当时的默认配置`
        : profilesLoaded
          ? 'Portal 尚未设置默认配置，请到管理页设置后刷新。'
          : '不指定配置 ID；每轮录音由 Portal 选择默认配置。'
    },
    ...profiles
  ];
  if (selectedProfileId && !profiles.some((profile) => profile.id === selectedProfileId)) {
    choices.push({
      id: selectedProfileId,
      title: '当前指定配置',
      note: `${selectedProfileId} · ${profilesLoaded ? '此配置不在当前 Portal 列表中，请重新选择。' : '测试并刷新后可查看配置名称。'}`
    });
  }
  for (const profile of choices) {
    const selected = profile.id === selectedProfileId;
    const card = document.createElement('div');
    card.className = 'profile-card' + (selected ? ' selected' : '');
    const details = document.createElement('div'),
      title = document.createElement('strong'),
      note = document.createElement('p');
    title.textContent = profile.title;
    note.textContent =
      profile.note ||
      `${profile.id} · ${profile.provider} · ${profile.latencyClass === 'streaming' ? '实时流式' : profile.latencyClass === 'segmented' ? '分段识别' : '延迟以服务能力为准'}`;
    details.append(title, note);
    const button = document.createElement('button');
    button.textContent = selected ? '已选择' : '使用此配置';
    button.setAttribute('aria-pressed', String(selected));
    button.disabled = selected || busy;
    button.onclick = () => {
      selectedProfileId = profile.id;
      changed();
      renderProfiles();
    };
    card.append(details, button);
    byId('profile-list').append(card);
  }
}

async function save() {
  if (busy || !config) return;
  if (modelCards.working() || portalCards.working()) return;
  if (hotwordsBusy) return;
  if (hotwordsDirty) {
    notice('请先保存热词设置，或刷新热词以放弃编辑，再保存应用设置。', 'error');
    return;
  }
  saving(true);
  try {
    const portal = portalForm();
    const portalChanged =
      portal.url !== config.portal.url ||
      portal.profileId !== config.portal.profileId ||
      !!portal.apiKey ||
      (portal.clearApiKey && config.portal.hasApiKey);
    const value = await api('config', 'PATCH', {
      revision,
      patch: {
        overlay: appearance(),
        settings: {
          theme: byId('settings-theme').value,
          colorMode: byId('settings-color-mode').value
        },
        ...(portalChanged ? { portal } : {}),
        audio: { deviceId: byId('device').value || null, gain: Number(byId('gain').value) },
        runtime: { socketPath: byId('socket-path').value.trim() },
        input: {
          keyboardInlinePreedit: byId('keyboard-inline').checked,
          framework: byId('input-framework').value
        }
      }
    });
    populate(value, true);
    notice(
      '设置已保存。外观按后端能力更新，识别与设备参数在下一轮录音生效；Linux 输入框架更改需执行 openasrinput start。',
      'success'
    );
    await refreshStatus();
  } catch (error) {
    notice(error.message, 'error');
  } finally {
    saving(false);
  }
}

async function refreshStatus() {
  try {
    const status = await api('status');
    byId('framework-status').textContent =
      `当前后端：${status.running ? status.inputFramework || '原生桥接' : '未运行'}` +
      (status.frameworkRestartRequired ? ' · 配置已更改，请执行 openasrinput start' : '') +
      (status.inputFramework === 'ibus' && !status.nativeContext?.focused
        ? ' · 等待激活 IBus 语音输入源并聚焦输入框'
        : '');
    const panel = status.nativeContext?.panel;
    let panelStatus = status.running
      ? '保存后实时应用，无需重启输入法。'
      : '输入服务未运行；设置将在启动时应用。';
    if (panel) {
      const label =
        [...byId('position').options].find((option) => option.value === panel.position)
          ?.textContent || panel.position;
      panelStatus = `原生面板：${panel.backend} · ${label} · 透明度 ${panel.transparency}%`;
      if (!panel.active) panelStatus += ' · 当前没有显示会话';
      if (panel.backend === 'xwayland-status' && !panel.gnomeLayoutV2)
        panelStatus += ' · GNOME 面板未提供新版布局接口，使用独立 XWayland 面板';
      if (['x11', 'xwayland-status'].includes(panel.backend) && !panel.x11Alpha)
        panelStatus += ' · 当前 X11 合成环境不支持透明通道';
    }
    byId('panel-live-status').textContent =
      panel?.backend === 'ibus'
        ? '自定义面板暂不可用，已回退至 IBus 系统辅助面板。请检查面板组件或桌面扩展。'
        : panelStatus;
    byId('daemon-dot').classList.toggle('running', status.running);
    byId('daemon-state').textContent = status.running
      ? '输入服务 · ' + (names[status.state] || status.state)
      : '输入服务未启动';
    byId('runtime-status').textContent = status.running
      ? `守护进程正在运行 · ${names[status.state] || status.state}${status.pendingConnection ? ' · 连接设置等待下一轮生效' : ''}`
      : '守护进程未启动。保存的设置会在下一次启动时读取。';
    byId('runtime-error').textContent =
      status.error ||
      (status.overrides?.length ? '命令行覆盖项：' + status.overrides.join('、') : '');
    if (status.audioCalibration)
      byId('runtime-error').textContent += ' · ' + status.audioCalibration;
    const reasons = {
      shortcut: '再次按下快捷键',
      enter: '按下 Enter 收尾',
      'context-lost': '输入焦点或输入上下文失效',
      'target-unavailable': '当前不是可输入目标',
      'recording-limit': '达到录音时限',
      'remote-finished': 'Portal 主动结束会话',
      cancelled: '取消录音',
      error: '连接、设备或协议错误'
    };
    byId('stop-reason').textContent = status.stopReason
      ? '最近停止原因：' + (reasons[status.stopReason] || status.stopReason)
      : '';
    const nativeReasons = {
      'focus-out': '输入框失焦',
      destroyed: '输入框销毁',
      'input-method-switch': '切换输入法',
      'not-editable': '输入框不可编辑'
    };
    if (status.stopReason === 'context-lost' && status.nativeContext?.lastInvalidation)
      byId('stop-reason').textContent +=
        ' · 原生事件：' +
        (nativeReasons[status.nativeContext.lastInvalidation] ||
          status.nativeContext.lastInvalidation);
    byId('runtime-events').textContent = (status.transitions || [])
      .map(
        (item) => `${item.at.toFixed(3)} · ${item.cause} · ${item.state} · 第 ${item.generation} 轮`
      )
      .join('\n');
  } catch (error) {
    byId('runtime-error').textContent = error.message;
  }
}

const tabs = [...document.querySelectorAll('#settings-nav [role=tab]')];
tabs.forEach((tab, index) => {
  tab.onclick = () => showPage(tab.dataset.page);
  tab.onkeydown = (event) => {
    const offset = ['ArrowDown', 'ArrowRight'].includes(event.key)
      ? 1
      : ['ArrowUp', 'ArrowLeft'].includes(event.key)
        ? -1
        : 0;
    if (!offset && !['Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? tabs.length - 1
          : (index + offset + tabs.length) % tabs.length;
    showPage(tabs[next].dataset.page);
  };
});
document.querySelectorAll('main input, main select').forEach((field) => {
  if (field.closest('#page-hotwords')) return;
  field.addEventListener('input', () => {
    changed();
    preview();
    if (['portal-url', 'portal-key', 'clear-key'].includes(field.id)) {
      profiles = [];
      defaultProfileId = '';
      profilesLoaded = false;
      renderProfiles();
    }
  });
  field.addEventListener('change', () => {
    changed();
    preview();
  });
});
byId('save').onclick = save;
byId('reload').onclick = async () => {
  if (hotwordsBusy || calibration?.working()) return;
  if (hotwordsDirty) {
    notice('请先保存热词设置，或刷新热词以放弃编辑，再重新载入应用设置。', 'error');
    return;
  }
  try {
    populate(await api('config'));
    notice('已重新载入保存的设置。');
  } catch (error) {
    notice(error.message, 'error');
  }
};
byId('portal-test').onclick = async () => {
  const button = byId('portal-test');
  button.disabled = true;
  byId('portal-status').textContent = '正在测试连接…';
  try {
    const result = await api('portal/test', 'POST', { portal: portalForm() });
    profiles = result.profiles;
    defaultProfileId = result.defaultProfileId || '';
    profilesLoaded = true;
    renderProfiles();
    byId('portal-status').textContent =
      `连接正常 · ${profiles.length} 个识别配置 · 录音上限 ${Math.round(result.maxRecordingMs / 60000)} 分钟`;
    notice('Portal 测试通过；尚未保存的表单不会写入配置。', 'success');
  } catch (error) {
    byId('portal-status').textContent = error.message;
    notice(error.message, 'error');
  } finally {
    button.disabled = false;
  }
};
byId('devices-refresh').onclick = async () => {
  const button = byId('devices-refresh'),
    selected = byId('device').value;
  button.disabled = true;
  try {
    const result = await api('audio/devices', 'POST', {});
    byId('device').replaceChildren(new Option('系统默认设备', ''));
    result.devices.forEach((device) => byId('device').add(new Option(device.title, device.id)));
    chooseValue('device', selected);
    byId('devices-status').textContent =
      `已读取 ${result.devices.length} 个设备。设备列表不触发录音。`;
  } catch (error) {
    byId('devices-status').textContent = error.message;
  } finally {
    button.disabled = false;
  }
};
byId('portal-admin').onclick = (event) => {
  if (byId('portal-admin').getAttribute('href') === '#') event.preventDefault();
};

function renderHotwords(value) {
  hotwords = value;
  hotwordsDirty = false;
  const settings = value.settings;
  byId('hotwords-form').hidden = false;
  byId('hotwords-enabled').checked = settings.enabled;
  personalTable.load(settings);
  const selection = value.selection;
  byId('hotwords-status').textContent =
    `Portal 热词${settings.enabled ? '已开启' : '已关闭'} · 版本 ${value.revision} · ${selection ? `${value.profileId} · ${selection.capability.note}` : '尚无默认识别配置，个人表仍可保存。'}`;
  byId('hotwords-selection').textContent = selection
    ? `Portal 当前保存状态：上游选用 ${selection.appliedCount} 个，未选用 ${selection.omitted.length} 个。实际选词受总开关、逐词状态及上游格式和容量限制。`
    : '配置上游后可查看实际选词。';
  byId('hotwords-dictionaries').hidden = !value.dictionarySupport;
  renderRecommendations();
}

function renderRecommendations() {
  const query = wordIdentity(byId('dictionary-search').value);
  const words = recommendationWords.filter((word) => wordIdentity(word.text).includes(query));
  const pages = Math.max(1, Math.ceil(words.length / 50));
  recommendationPage = Math.min(recommendationPage, pages - 1);
  const selected = new Set(personalTable.terms.map((term) => wordIdentity(term.text)));
  byId('dictionary-count').textContent =
    `${words.length} 个推荐词 · 第 ${recommendationPage + 1} / ${pages} 页 · 状态以当前个人表编辑为准`;
  byId('dictionary-recommendations').replaceChildren();
  for (const term of words.slice(recommendationPage * 50, (recommendationPage + 1) * 50)) {
    const row = document.createElement('div');
    row.className = 'profile-card';
    row.dataset.word = term.text;
    const label = document.createElement('span');
    const enabled = selected.has(wordIdentity(term.text));
    label.textContent = `${term.text} · 权重 ${term.weight || 4} · ${enabled ? '已在热词表中' : '候选词'}`;
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.textContent = enabled ? '已加入' : '加入热词表';
    toggle.disabled = busy || hotwordsBusy || enabled;
    toggle.onclick = () => {
      try {
        personalTable.add(term);
      } catch (error) {
        notice(error.message, 'error');
      }
    };
    row.append(label, toggle);
    byId('dictionary-recommendations').append(row);
  }
  if (!words.length)
    byId('dictionary-recommendations').textContent = recommendationWords.length
      ? '没有匹配的候选词。'
      : '选择公共推荐表，加载后在此查看候选词。';
  byId('dictionary-prev').disabled = busy || hotwordsBusy || recommendationPage === 0;
  byId('dictionary-next').disabled = busy || hotwordsBusy || recommendationPage >= pages - 1;
}
function showRecommendations(result) {
  if (!Array.isArray(result.words))
    throw new Error('此 Portal 尚不支持完整推荐列表，请升级 Portal');
  recommendationWords = result.words;
  recommendationPage = 0;
  byId('dictionary-search').value = '';
  renderRecommendations();
}
byId('dictionary-search').oninput = () => {
  recommendationPage = 0;
  renderRecommendations();
};
byId('dictionary-prev').onclick = () => {
  recommendationPage--;
  renderRecommendations();
};
byId('dictionary-next').onclick = () => {
  recommendationPage++;
  renderRecommendations();
};

async function loadDictionaryCatalog(force = false) {
  if (!hotwords?.dictionarySupport || (dictionaryCatalog && !force)) return;
  const previous = byId('dictionary-source').value;
  dictionaryCatalog = await api('portal/hotwords/catalog');
  byId('dictionary-source').replaceChildren(new Option('选择公共推荐表', ''));
  for (const source of dictionaryCatalog.sources.filter(
    (source) => source.kind === 'portal-public'
  ))
    byId('dictionary-source').add(new Option(source.title, source.id));
  if (dictionaryCatalog.sources.some((source) => source.id === previous))
    byId('dictionary-source').value = previous;
  byId('dictionary-source').onchange();
}

function dictionaryReport(report) {
  return `有效 ${report.wordCount} 词，忽略 ${report.skipped} 行，去重 ${report.duplicates} 行。${report.warnings.join('；')} 样例：${report.sample.map((word) => word.text).join('、')}`;
}

async function loadRecommendations(sourceId) {
  if (!hotwords || hotwordsBusy || busy) return;
  hotwordWorking(true);
  try {
    const result = await api('portal/hotwords/dictionaries', 'POST', {
      sourceId,
      preview: true,
      configRevision: hotwords.configRevision
    });
    showRecommendations(result);
    byId('dictionary-report').textContent =
      `${result.source.title} · ${dictionaryReport(result.report)}`;
    notice('推荐表已载入候选区，点击“加入热词表”后保存生效。');
  } catch (error) {
    notice(error.message, 'error');
    byId('dictionary-report').textContent = error.message;
  } finally {
    hotwordWorking(false);
  }
}
byId('dictionary-source').onchange = () => {
  const source = dictionaryCatalog?.sources.find(
    (value) => value.id === byId('dictionary-source').value
  );
  byId('dictionary-source-note').textContent = source
    ? `${source.description} · ${source.license}`
    : '';
};
byId('dictionary-online').onclick = () => {
  const sourceId = byId('dictionary-source').value;
  if (!sourceId) {
    notice('请选择公开词库来源', 'error');
    return;
  }
  loadRecommendations(sourceId);
};

function hotwordWorking(value) {
  hotwordsBusy = value;
  document
    .querySelectorAll('#page-hotwords button, #page-hotwords input, #page-hotwords select')
    .forEach((control) => (control.disabled = value));
  personalTable.working(value);
  renderRecommendations();
}

async function hotwordAction(method = 'GET') {
  if (busy || hotwordsBusy) return;
  hotwordWorking(true);
  try {
    let body;
    if (method !== 'GET') {
      if (!hotwords) throw new Error('请先查询热词');
      body = { configRevision: hotwords.configRevision };
      if (method === 'PATCH') {
        body.revision = hotwords.revision;
        body.settings = {
          enabled: byId('hotwords-enabled').checked,
          ...personalTable.patch()
        };
      }
    }
    const value = await api('portal/hotwords', method, body);
    if (method === 'GET') {
      recommendationWords = [];
      recommendationPage = 0;
      byId('dictionary-search').value = '';
      byId('dictionary-report').textContent = '';
    }
    renderHotwords(value);
    await loadDictionaryCatalog(method === 'GET');
    notice(method === 'PATCH' ? '热词设置已保存，下一轮录音生效。' : '个人热词已刷新。', 'success');
  } catch (error) {
    byId('hotwords-status').textContent = error.message;
    notice(error.message, 'error');
  } finally {
    hotwordWorking(false);
  }
}
function hotwordsChanged(message = '热词已编辑，点击“保存热词设置”生效。') {
  hotwordsDirty = true;
  renderRecommendations();
  byId('hotwords-selection').textContent =
    '有未保存的修改；保存后更新 Portal 状态，下一轮录音生效。';
  notice(message);
}
byId('hotwords-enabled').onchange = () => hotwordsChanged();
byId('hotwords-refresh').onclick = () => hotwordAction();
byId('hotwords-form').onsubmit = (event) => {
  event.preventDefault();
  hotwordAction('PATCH');
};
window.addEventListener('resize', preview);
window.addEventListener('beforeunload', (event) => {
  if (
    dirty ||
    hotwordsDirty ||
    modelCards.isDirty() ||
    portalCards.isDirty() ||
    calibration?.working()
  ) {
    event.preventDefault();
    event.returnValue = '';
  }
});
for (let index = 0; index < 48; index++) {
  const bar = document.createElement('span');
  bar.style.height = 3 + 21 * Math.sin((Math.PI * index) / 47) ** 3 + 'px';
  byId('preview-wave').append(bar);
}

try {
  const [value, themeData] = await Promise.all([api('config'), api('themes')]);
  themes = themeData.themes;
  populate(value);
  calibration = new AudioCalibration(api, {
    ready: () => {
      if (
        busy ||
        dirty ||
        hotwordsDirty ||
        modelCards.isDirty() ||
        portalCards.isDirty() ||
        hotwordsBusy ||
        modelCards.working() ||
        portalCards.working()
      ) {
        notice('请先保存或放弃其他设置修改，再运行校准。', 'error');
        return false;
      }
      return true;
    },
    revision: () => revision,
    saved: (value) => populate(value, true),
    notice,
    lock: (value) => {
      if (busy !== value) saving(value);
    }
  });
  calibration.load(config);
  notice('设置已载入。');
  await refreshStatus();
  setInterval(refreshStatus, 2000);
} catch (error) {
  notice(error.message, 'error');
}
