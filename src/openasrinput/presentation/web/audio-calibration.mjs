const byId = (id) => document.getElementById(id);
const active = new Set([
  'preparing',
  'noise',
  'recording',
  'evaluating',
  'validation-noise',
  'validation-recording',
  'verifying',
  'await-validation'
]);

export class AudioCalibration {
  constructor(api, options) {
    this.api = api;
    this.options = options;
    this.job = { state: 'idle' };
    this.pending = false;
    this.timer = null;
    this.version = 0;
    for (const action of ['start', 'stop', 'cancel', 'validate', 'apply', 'reset']) {
      byId('calibration-' + action).onclick = () => this.action(action);
    }
    this.refresh();
  }

  working() {
    return this.pending || active.has(this.job.state);
  }

  load(config) {
    this.config = config;
    const followsDefault = !config.audio.deviceId;
    const profiles = config.audio.calibrations.filter(
      (x) => followsDefault || x.deviceId === config.audio.deviceId
    );
    byId('calibration-saved').textContent = profiles.length
      ? (followsDefault ? '自动跟随系统默认麦克风。已保存设备档案：' : '') +
        profiles
          .map(
            (x) =>
              `${x.deviceTitle} · ${x.gain.toFixed(2)}× · ${x.highpassHz ? x.highpassHz + ' Hz 高通' : '无滤波'} · ${new Date(x.verifiedAt * 1000).toLocaleDateString()}`
          )
          .join('；') +
        '。录音时核对设备与识别配置，匹配后应用。'
      : '尚无匹配的校准档案。直接开始校准，程序自动选择增益，无需先手动调节。';
    this.render();
  }

  async refresh() {
    clearTimeout(this.timer);
    const version = this.version;
    try {
      const job = await this.api('audio/calibration');
      if (version !== this.version || this.pending) return;
      this.job = job;
      this.render();
    } catch (error) {
      if (version !== this.version) return;
      byId('calibration-status').textContent = error.message;
    }
    if (active.has(this.job.state)) this.timer = setTimeout(() => this.refresh(), 500);
  }

  async action(action) {
    if (this.pending) return;
    if (['start', 'reset', 'apply'].includes(action) && !this.options.ready()) return;
    this.version++;
    clearTimeout(this.timer);
    this.pending = true;
    this.render();
    try {
      const result = await this.api('audio/calibration/' + action, 'POST', {
        id: this.job.id,
        revision: this.options.revision()
      });
      this.job = result.job;
      if (result.settings) this.options.saved(result.settings);
    } catch (error) {
      this.options.notice(error.message, 'error');
    } finally {
      this.pending = false;
      this.render();
      if (active.has(this.job.state)) this.refresh();
    }
  }

  render() {
    const state = this.job.state;
    this.options.lock(this.working());
    byId('calibration-status').textContent =
      this.job.message || '准备好后开始，录音仅由本机输入法采集。';
    byId('calibration-status').dataset.state = state;
    byId('calibration-context').textContent = this.job.device
      ? `本次设备：${this.job.device} · 识别配置：${this.job.profile}`
      : '';
    const validation =
      this.job.recommendation ||
      state.startsWith('validation') ||
      ['await-validation', 'verifying'].includes(state);
    byId('calibration-passage').textContent =
      this.job.passages?.[validation ? 'validation' : 'calibration'] || '';
    const measuringNoise = state.endsWith('noise');
    byId('calibration-passage').hidden = measuringNoise;
    byId('calibration-stage').textContent = measuringNoise
      ? `环境声测量 · 请保持安静，约 ${Math.max(0, Math.ceil(3 - (this.job.seconds || 0)))} 秒后朗读`
      : validation
        ? '独立验证朗读'
        : '校准朗读';
    const recording = state.includes('recording') || state.endsWith('noise');
    byId('calibration-meter').hidden = !recording;
    byId('calibration-level').value = Math.max(0, 100 + (this.job.levelDbfs ?? -100));
    byId('calibration-time').textContent = `${this.job.seconds || 0} 秒 / 最多 45 秒`;
    byId('calibration-start').disabled = this.working();
    byId('calibration-start').textContent = state === 'idle' ? '开始麦克风校准' : '重新校准';
    byId('calibration-stop').hidden = !recording;
    byId('calibration-stop').disabled =
      this.pending || !state.includes('recording') || (this.job.seconds || 0) < 8;
    byId('calibration-cancel').hidden = !active.has(state);
    byId('calibration-cancel').disabled = this.pending;
    byId('calibration-validate').hidden = state !== 'await-validation';
    byId('calibration-validate').disabled = this.pending;
    byId('calibration-apply').hidden = !this.job.canApply;
    byId('calibration-apply').disabled = this.pending;
    byId('calibration-reset').disabled =
      this.working() ||
      !this.config?.audio.calibrations.some(
        (x) => !this.config.audio.deviceId || x.deviceId === this.config.audio.deviceId
      );
    const metrics = this.job.metrics;
    byId('calibration-metrics').textContent = metrics
      ? `声音电平估计 ${metrics.speechDbfs} dBFS · 背景 ${metrics.noiseDbfs} dBFS · 峰值 ${metrics.peakDbfs} dBFS · 削波 ${(metrics.clippingRatio * 100).toFixed(2)}% · 自动增益候选 ${metrics.suggestedGain.toFixed(2)}×。 ${(metrics.warnings || []).join(' ')}`
      : '';
    const results = byId('calibration-results');
    results.replaceChildren();
    for (const [label, items] of [
      ['候选比较', this.job.results],
      ['复测', this.job.repeated],
      ['独立验证', this.job.validation]
    ]) {
      if (!items?.length) continue;
      const heading = document.createElement('h4');
      heading.textContent = label;
      results.append(heading);
      for (const item of items) {
        const card = document.createElement('div');
        card.className = 'calibration-result';
        const title = document.createElement('strong');
        title.textContent = `${item.name} · 错误 ${item.errors}/${item.characters} 字 · CER ${(item.cer * 100).toFixed(1)}%`;
        const details = document.createElement('p');
        details.textContent = `${item.gain.toFixed(2)}× · ${item.highpassHz ? item.highpassHz + ' Hz 高通' : '无滤波'}${item.clippedSamples ? ' · 出现削波，不推荐' : ''}`;
        const transcript = document.createElement('p');
        transcript.textContent = item.transcript || '（无识别文本）';
        card.append(title, details, transcript);
        results.append(card);
      }
    }
  }
}
