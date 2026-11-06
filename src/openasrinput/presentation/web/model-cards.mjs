import { confirm } from './i18n.mjs';
const $ = (id) => document.getElementById(id);
const fields = ['id', 'name', 'provider', 'url', 'model', 'apiKey'];
const wire = (card) => Object.fromEntries(fields.map((key) => [key, card[key] || '']));

export class ModelCards {
  constructor(api, committed, report, revision) {
    Object.assign(this, {
      api,
      committed,
      report,
      revision,
      cards: [],
      active: '',
      views: new Map(),
      saving: false
    });
    $('model-card-disable').onclick = () => this.persist(this.cards, '', null);
  }

  isDirty() {
    return [...this.views.values()].some((view) => view.dirty);
  }
  working() {
    return this.saving;
  }

  load(config, metadata = {}, savedId = null) {
    this.cards = structuredClone(config.cards || []);
    this.active = config.activeModelCardId || '';
    const previous = this.views;
    this.views = new Map();
    const list = $('model-card-list');
    list.replaceChildren();
    for (const card of this.cards) {
      const kept = savedId !== null && card.id !== savedId ? previous.get(card.id) : null;
      const view = kept || this.create(card, metadata[card.id]);
      this.views.set(card.id, view);
      this.selection(view);
      list.append(view.form);
    }
    if (!this.cards.length) list.textContent = '暂无已保存的模型卡，请在下方完成配置后新增。';
    const oldNew = previous.get('new');
    const newView = savedId !== null && oldNew?.id !== savedId ? oldNew : null;
    const view =
      newView ||
      this.create(
        {
          id: crypto.randomUUID(),
          name: '',
          provider: 'deepseek',
          url: 'https://api.deepseek.com',
          model: '',
          apiKey: ''
        },
        {},
        true
      );
    this.views.set('new', view);
    $('model-card-new').replaceChildren(view.form);
    for (const old of previous.values()) {
      if (![...this.views.values()].includes(old)) old.generation++;
    }
    $('model-card-disable').disabled = !this.active || this.saving;
  }

  create(card, metadata = {}, isNew = false) {
    const form = $('model-card-template').content.firstElementChild.cloneNode(true);
    const view = {
      form,
      id: card.id,
      original: card,
      isNew,
      dirty: false,
      generation: 0,
      pending: false,
      catalog: metadata?.models?.models || []
    };
    form.dataset.cardId = card.id;
    const field = (name) => form.elements.namedItem(name);
    view.field = field;
    for (const name of ['name', 'provider', 'url', 'model']) field(name).value = card[name] || '';
    field('official-url').value =
      card.provider === 'deepseek' ? card.url : 'https://api.deepseek.com';
    field('apiKey').required = !card.hasApiKey;
    field('apiKey').placeholder = card.hasApiKey
      ? '已保存；留空保留本卡 Key，填写新值替换'
      : '手动填写此模型卡的 Key';
    form.querySelector('[data-role="key-note"]').textContent = card.hasApiKey
      ? 'Key 已保存，不回显；其他模型卡不会继承此 Key。'
      : '新增卡必须手动填写 Key。';
    form.querySelector('[data-role="title"]').textContent = isNew ? '配置新模型卡' : card.name;
    form.querySelector('[data-role="title"]').translate = isNew;
    form.querySelector('[data-action="save"]').textContent = isNew
      ? '保存并新增模型卡'
      : '保存此卡配置';
    for (const action of ['use', 'delete'])
      form.querySelector(`[data-action="${action}"]`).hidden = isNew;
    this.choices(view, card.model);
    this.visibility(view);
    const test = metadata?.test;
    this.message(
      view,
      test ? (test.ok ? `测试通过 · ${test.elapsedMs} ms` : `测试失败 · ${test.error}`) : '尚未测试'
    );
    if (metadata?.models?.updatedAt)
      form.querySelector('[data-role="result"]').textContent +=
        ' · 目录缓存：' + new Date(metadata.models.updatedAt * 1000).toLocaleString();
    form.addEventListener('input', (event) => {
      view.dirty = true;
      view.generation++;
      const name = event.target.name;
      if (['provider', 'url', 'official-url', 'apiKey'].includes(name)) {
        view.catalog = [];
        this.choices(view, field('model').value);
      }
      if (name === 'model-choice') field('model').value = field('model-choice').value;
      if (name === 'provider' || name === 'mode') this.visibility(view);
      this.message(view, '配置已修改，尚未保存；请保存此卡后再使用。');
      this.selection(view);
    });
    form.onsubmit = (event) => {
      event.preventDefault();
      if (!this.valid(view)) return;
      const value = this.value(view);
      const cards = isNew
        ? [...this.cards, value]
        : this.cards.map((c) => (c.id === view.id ? value : c));
      this.persist(cards, this.active, view);
    };
    form.querySelector('[data-action="models"]').onclick = () => this.request(view, 'models');
    form.querySelector('[data-action="test"]').onclick = () => this.request(view, 'test');
    form.querySelector('[data-action="use"]').onclick = () => {
      if (view.dirty) {
        this.message(view, '请先保存此卡配置，再使用。');
        return;
      }
      this.persist(this.cards, view.id, view);
    };
    form.querySelector('[data-action="delete"]').onclick = () => {
      if (!confirm(this.active === view.id ? '删除此模型卡并停用文本修改？' : '删除此模型卡？'))
        return;
      this.persist(
        this.cards.filter((c) => c.id !== view.id),
        this.active === view.id ? '' : this.active,
        view
      );
    };
    return view;
  }

  selection(view) {
    const active = !view.isNew && this.active === view.id;
    view.form.classList.toggle('selected', active);
    view.form.querySelector('[data-role="active"]').textContent = active ? '当前使用' : '';
    const button = view.form.querySelector('[data-action="use"]');
    button.textContent = active ? '当前使用' : '使用此模型';
    button.disabled = active || view.dirty || this.saving;
  }

  visibility(view) {
    const official = view.field('provider').value === 'deepseek';
    const list = official || view.field('mode').value === 'list';
    for (const [name, visible] of Object.entries({
      'official-url': official,
      url: !official,
      mode: !official,
      model: !list,
      'model-choice': list
    })) {
      view.form.querySelector(`[data-field="${name}"]`).hidden = !visible;
    }
    view.field('url').required = !official;
    view.field('model').required = !list;
    view.field('model-choice').required = list;
    if (list) this.choices(view, view.field('model').value);
  }

  choices(view, current = '') {
    const select = view.field('model-choice');
    select.replaceChildren(new Option('请刷新并选择模型名称', ''));
    for (const id of view.catalog) select.add(new Option(id, id));
    if (current && !view.catalog.includes(current))
      select.add(new Option(current + '（原配置 / 尚未刷新确认）', current));
    select.value = current;
  }

  value(view) {
    const f = view.field;
    const list = f('provider').value === 'deepseek' || f('mode').value === 'list';
    return {
      id: view.id,
      name: f('name').value.trim(),
      provider: f('provider').value,
      url: (f('provider').value === 'deepseek' ? f('official-url').value : f('url').value).trim(),
      model: (list ? f('model-choice').value : f('model').value).trim(),
      apiKey: f('apiKey').value.trim()
    };
  }

  valid(view, models = false) {
    const card = this.value(view);
    const missing = [];
    if (!card.name) missing.push('模型卡名称');
    if (!card.url) missing.push('API 地址');
    if (!card.apiKey && !view.original.hasApiKey) missing.push('API Key');
    if (!models && !card.model) missing.push('模型名称');
    if (missing.length) {
      this.message(view, '请先填写：' + missing.join('、'));
      return false;
    }
    try {
      const url = new URL(card.url);
      if (!['http:', 'https:'].includes(url.protocol)) throw new Error();
    } catch {
      this.message(view, '请填写有效的 HTTP(S) API 地址');
      return false;
    }
    return true;
  }

  message(view, text) {
    view.form.querySelector('[data-role="result"]').textContent = text;
  }

  async persist(cards, active, view) {
    if (this.saving) return;
    this.saving = true;
    const savedId = view?.id || '';
    for (const current of this.views.values()) {
      current.generation++;
      current.form
        .querySelectorAll('input, select, button')
        .forEach((control) => (control.disabled = true));
    }
    $('model-card-disable').disabled = true;
    try {
      const value = await this.api('config', 'PATCH', {
        revision: this.revision(),
        patch: { textEdit: { cards: cards.map(wire), activeModelCardId: active } }
      });
      this.committed(value);
      this.load(value.config.textEdit, value.modelCardMetadata, savedId);
      this.report('模型卡已保存；当前选择在下一轮录音生效。', 'success');
    } catch (error) {
      if (view) this.message(view, error.message);
      this.report(error.message, 'error');
    } finally {
      this.saving = false;
      for (const current of this.views.values()) {
        current.form
          .querySelectorAll('input, select, button')
          .forEach((control) => (control.disabled = false));
        this.selection(current);
      }
      $('model-card-disable').disabled = !this.active;
    }
  }

  async request(view, action) {
    if (view.pending || this.saving || !this.valid(view, action === 'models')) return;
    const card = this.value(view);
    const generation = ++view.generation;
    view.pending = true;
    const button = view.form.querySelector(`[data-action="${action}"]`);
    button.disabled = true;
    this.message(view, action === 'models' ? '正在刷新模型名称…' : '正在测试此模型卡…');
    try {
      const result = await this.api('text-model/' + action, 'POST', {
        card,
        revision: this.revision()
      });
      if (generation !== view.generation) return;
      if (action === 'models') {
        view.catalog = result.models;
        this.choices(view, card.model);
        if (card.provider === 'openai-compatible') {
          view.field('mode').value = 'list';
          this.visibility(view);
        }
        this.message(
          view,
          `已刷新 ${result.models.length} 个模型，请选择 · ${new Date().toLocaleString()}`
        );
      } else this.message(view, `测试通过 · ${result.elapsedMs} ms`);
    } catch (error) {
      if (generation === view.generation)
        this.message(view, error.message + '；配置完整时仍可保存。');
    } finally {
      view.pending = false;
      button.disabled = this.saving;
    }
  }
}
