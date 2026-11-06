import { confirm } from './i18n.mjs';
const $ = (id) => document.getElementById(id);
const fields = ['id', 'name', 'url', 'apiKey', 'profileId'];
const wire = (card) => Object.fromEntries(fields.map((key) => [key, card[key] || '']));

export class PortalCards {
  constructor(api, committed, report, revision, canChange = () => true) {
    Object.assign(this, {
      api,
      committed,
      report,
      revision,
      canChange,
      cards: [],
      active: '',
      views: new Map(),
      saving: false
    });
  }
  isDirty() {
    return [...this.views.values()].some((view) => view.dirty);
  }
  working() {
    return this.saving;
  }
  load(config, metadata = {}, preserve = false) {
    this.cards = structuredClone(config.cards || []);
    this.active = config.activePortalCardId || '';
    const old = this.views;
    this.views = new Map();
    $('portal-card-list').replaceChildren();
    for (const card of this.cards) {
      const view =
        preserve && old.get(card.id)?.dirty
          ? old.get(card.id)
          : this.create(card, metadata[card.id]);
      this.views.set(card.id, view);
      this.selection(view);
      $('portal-card-list').append(view.form);
    }
    if (!this.cards.length)
      $('portal-card-list').textContent =
        '暂无 Portal 卡，请在下方新增；联合安装会自动添加本机 Portal。';
    const view =
      preserve && old.get('new')?.dirty
        ? old.get('new')
        : this.create(
            {
              id: crypto.randomUUID(),
              name: '',
              url: 'http://127.0.0.1:10087',
              apiKey: '',
              profileId: ''
            },
            {},
            true
          );
    this.views.set('new', view);
    $('portal-card-new').replaceChildren(view.form);
    for (const view of old.values())
      if (![...this.views.values()].includes(view)) view.generation++;
  }
  create(card, metadata = {}, isNew = false) {
    const form = $('portal-card-template').content.firstElementChild.cloneNode(true);
    const view = {
      form,
      id: card.id,
      original: card,
      isNew,
      dirty: false,
      pending: false,
      generation: 0
    };
    form.dataset.cardId = card.id;
    const field = (name) => form.elements.namedItem(name);
    view.field = field;
    for (const name of ['name', 'url', 'profileId']) field(name).value = card[name] || '';
    field('apiKey').required = !card.hasApiKey;
    field('apiKey').placeholder = card.hasApiKey
      ? '已保存；留空保留本卡 Key'
      : '此 Portal 的独立识别 Key';
    form.querySelector('[data-role=title]').textContent = isNew ? '配置新 Portal 卡' : card.name;
    form.querySelector('[data-role=title]').translate = isNew;
    form.querySelector('[data-action=save]').textContent = isNew
      ? '保存并新增 Portal 卡'
      : '保存此卡';
    for (const action of ['use', 'delete'])
      form.querySelector(`[data-action=${action}]`).hidden = isNew;
    this.message(view, metadata?.ok !== undefined ? this.resultText(metadata) : '尚未测试');
    form.oninput = () => {
      view.dirty = true;
      view.generation++;
      this.message(view, '配置已修改，请重新测试并保存。');
      this.selection(view);
    };
    form.onsubmit = (event) => {
      event.preventDefault();
      if (!this.valid(view)) return;
      const value = this.value(view);
      const cards = isNew
        ? [...this.cards, value]
        : this.cards.map((card) => (card.id === view.id ? value : card));
      this.persist(cards, this.active || value.id, view);
    };
    form.querySelector('[data-action=test]').onclick = () => this.test(view);
    form.querySelector('[data-action=use]').onclick = () => {
      if (view.dirty) return this.message(view, '请先保存此卡，再使用。');
      this.persist(this.cards, view.id, view);
    };
    form.querySelector('[data-action=delete]').onclick = () => {
      if (
        !confirm(
          this.active === view.id
            ? '删除当前 Portal 卡？删除后需要选择其他卡才能录音。'
            : '删除此 Portal 卡？'
        )
      )
        return;
      this.persist(
        this.cards.filter((card) => card.id !== view.id),
        this.active === view.id ? '' : this.active,
        view
      );
    };
    return view;
  }
  value(view) {
    return {
      id: view.id,
      ...Object.fromEntries(
        ['name', 'url', 'apiKey', 'profileId'].map((name) => [name, view.field(name).value.trim()])
      )
    };
  }
  valid(view) {
    const value = this.value(view);
    if (!value.name || !value.url || (!value.apiKey && !view.original.hasApiKey)) {
      this.message(view, '请填写名称、Portal 地址和此卡的识别 Key。');
      return false;
    }
    return view.form.reportValidity();
  }
  message(view, text) {
    view.form.querySelector('[data-role=result]').textContent = text;
  }
  resultText(result) {
    const at = result.updatedAt ? ' · ' + new Date(result.updatedAt * 1000).toLocaleString() : '';
    return (
      (result.ok
        ? `连接通过 · ${result.elapsedMs} ms`
        : `连接失败 · ${result.elapsedMs} ms · ${result.error}`) + at
    );
  }
  selection(view) {
    const active = !view.isNew && view.id === this.active;
    view.form.classList.toggle('selected', active);
    view.form.querySelector('[data-role=active]').textContent = active ? '当前使用' : '';
    const use = view.form.querySelector('[data-action=use]');
    use.textContent = active ? '当前使用' : '使用此 Portal';
    use.disabled = active || view.dirty || this.saving;
  }
  async persist(cards, active, view) {
    if (this.saving || !this.canChange()) return;
    this.saving = true;
    for (const item of this.views.values())
      item.form.querySelectorAll('button,input').forEach((control) => (control.disabled = true));
    try {
      const value = await this.api('config', 'PATCH', {
        revision: this.revision(),
        patch: { portal: { cards: cards.map(wire), activePortalCardId: active } }
      });
      // Preserve other unsaved cards, but not the card just committed/deleted.
      view.dirty = false;
      this.committed(value);
      this.load(value.config.portal, value.portalCardMetadata, true);
      this.report('Portal 卡已保存，当前选择在下一轮录音生效。', 'success');
    } catch (error) {
      this.message(view, error.message);
      this.report(error.message, 'error');
    } finally {
      this.saving = false;
      for (const item of this.views.values()) {
        item.form.querySelectorAll('button,input').forEach((control) => (control.disabled = false));
        this.selection(item);
      }
    }
  }
  async test(view) {
    if (view.pending || this.saving || !this.valid(view)) return;
    const generation = ++view.generation;
    view.pending = true;
    const button = view.form.querySelector('[data-action=test]');
    button.disabled = true;
    this.message(view, '正在测试连接与 HTTP 往返时延…');
    try {
      const result = await this.api('portal/test', 'POST', {
        revision: this.revision(),
        card: this.value(view)
      });
      if (generation !== view.generation) return;
      this.message(view, this.resultText({ ...result, updatedAt: Date.now() / 1000 }));
      if (result.ok) {
        const choices = view.form.querySelector('[data-role=profiles]');
        choices.replaceChildren(new Option('跟随 Portal 默认', ''));
        for (const profile of result.profiles || [])
          choices.add(new Option(profile.title, profile.id));
        if (
          view.field('profileId').value &&
          ![...choices.options].some((option) => option.value === view.field('profileId').value)
        )
          choices.add(new Option(view.field('profileId').value, view.field('profileId').value));
        choices.value = view.field('profileId').value;
        choices.hidden = false;
        choices.onchange = () => {
          view.field('profileId').value = choices.value;
          view.form.dispatchEvent(new Event('input'));
        };
      }
    } catch (error) {
      if (generation === view.generation) this.message(view, error.message);
    } finally {
      view.pending = false;
      button.disabled = this.saving;
    }
  }
}
