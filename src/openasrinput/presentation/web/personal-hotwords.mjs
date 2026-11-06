// Standalone UI component; the Portal v1 wire format remains manualTerms + excludedTerms.
export const wordIdentity = (text) =>
  text
    .normalize('NFKC')
    .trim()
    .replace(/\s+/g, ' ')
    .toLowerCase()
    .replaceAll('ß', 'ss')
    .replaceAll('ς', 'σ');

export function validateTerms(terms) {
  if (!Array.isArray(terms) || terms.length > 2000) throw new Error('个人热词表最多 2000 词');
  const seen = new Set();
  return terms.map((term) => {
    if (!term || typeof term.text !== 'string') throw new Error('热词必须包含 text 文本');
    const text = term.text.normalize('NFKC').trim().replace(/\s+/g, ' ');
    if (
      [...text].length < 2 ||
      [...text].length > 64 ||
      !/[\p{L}\p{N}]/u.test(text) ||
      !/^[\p{L}\p{N} .+#\-/_']+$/u.test(text)
    )
      throw new Error("热词须为 2–64 字符，可使用文字、数字、空格及 .+#-/_'");
    const weight = term.weight === undefined ? 4 : term.weight,
      enabled = term.enabled === undefined ? true : term.enabled;
    if (!Number.isInteger(weight) || weight < 1 || weight > 5)
      throw new Error('权重须为 1–5 的整数');
    if (typeof enabled !== 'boolean') throw new Error('启用状态 enabled 须为布尔值');
    const identity = wordIdentity(text);
    if (seen.has(identity)) throw new Error('热词不可重复：' + text);
    seen.add(identity);
    return { text, weight, enabled };
  });
}

export function mergeTerms(current, incoming) {
  const merged = new Map(current.map((term) => [wordIdentity(term.text), term]));
  for (const term of validateTerms(incoming)) merged.set(wordIdentity(term.text), term);
  return validateTerms([...merged.values()]);
}

export class PersonalHotwords {
  constructor(prefix, { changed, report, run }) {
    this.field = (name) => document.getElementById(prefix + '-' + name);
    this.changed = changed;
    this.terms = [];
    this.page = 0;
    this.locked = false;
    this.generation = 0;
    this.field('add').onclick = () => {
      if (this.locked) return;
      try {
        this.add({
          text: this.field('new-text').value,
          weight: Number(this.field('new-weight').value)
        });
        this.field('new-text').value = '';
      } catch (error) {
        report(error.message);
      }
    };
    this.field('new-text').onkeydown = (event) => {
      if (event.key === 'Enter' && !event.isComposing) {
        event.preventDefault();
        this.field('add').click();
      }
    };
    this.field('search').oninput = () => {
      this.page = 0;
      this.render();
    };
    this.field('prev').onclick = () => {
      this.page--;
      this.render();
    };
    this.field('next').onclick = () => {
      this.page++;
      this.render();
    };
    this.field('download').onclick = () => {
      const url = URL.createObjectURL(
        new Blob(
          [
            JSON.stringify(
              {
                format: 'OpenASRPortal.PersonalHotwords',
                version: 1,
                terms: this.terms
              },
              null,
              2
            )
          ],
          { type: 'application/json' }
        )
      );
      const link = document.createElement('a');
      link.href = url;
      link.download = 'personal-hotwords.json';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    this.field('import').onclick = () =>
      run(async () => {
        const generation = this.generation;
        const file = this.field('file').files[0];
        if (!file) throw new Error('请选择个人热词表 JSON 文件');
        if (file.size > 4 * 1024 * 1024) throw new Error('文件最多 4 MiB');
        const data = JSON.parse(
          new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
        );
        if (generation !== this.generation) throw new Error('热词表已切换，请重新导入');
        if (
          !Array.isArray(data) &&
          (!data || data.version !== 1 || data.format !== 'OpenASRPortal.PersonalHotwords')
        )
          throw new Error('请选择下载的个人热词表，或包含 text / weight / enabled 的 JSON 数组');
        this.terms = mergeTerms(this.terms, Array.isArray(data) ? data : data.terms);
        this.render();
        changed('个人热词已导入，保存后同步到 Portal。');
      });
  }

  load(settings) {
    this.generation++;
    const excluded = new Set(settings.excludedTerms.map(wordIdentity));
    this.terms = settings.manualTerms.map((term) => ({
      ...term,
      enabled: !excluded.has(wordIdentity(term.text))
    }));
    this.page = 0;
    this.field('search').value = '';
    this.field('file').value = '';
    this.field('new-text').value = '';
    this.field('new-weight').value = '4';
    this.render();
  }

  patch() {
    const terms = validateTerms(this.terms);
    return {
      manualTerms: terms.map(({ text, weight }) => ({ text, weight })),
      excludedTerms: terms.filter((term) => !term.enabled).map((term) => term.text),
      autoLearn: false,
      maxWords: 2000
    };
  }

  add(term) {
    const [value] = validateTerms([term]);
    if (this.terms.some((row) => wordIdentity(row.text) === wordIdentity(value.text)))
      throw new Error('热词已在表中：' + value.text);
    this.terms = validateTerms([...this.terms, value]);
    this.field('search').value = '';
    this.page = Math.floor((this.terms.length - 1) / 50);
    this.render();
    this.changed();
  }

  working(value) {
    this.locked = value;
    this.render();
  }

  render() {
    const query = wordIdentity(this.field('search').value);
    const terms = this.terms.filter((term) => wordIdentity(term.text).includes(query));
    const pages = Math.max(1, Math.ceil(terms.length / 50));
    this.page = Math.max(0, Math.min(this.page, pages - 1));
    this.field('count').textContent =
      `共 ${this.terms.length} 词 · 启用 ${this.terms.filter((term) => term.enabled).length} 词 · 搜索结果 ${terms.length} 词 · 第 ${this.page + 1} / ${pages} 页`;
    this.field('personal').replaceChildren();
    for (const term of terms.slice(this.page * 50, (this.page + 1) * 50)) {
      const row = document.createElement('tr');
      row.dataset.word = term.text;
      const cell = () => {
        const td = document.createElement('td');
        row.append(td);
        return td;
      };
      const word = cell();
      word.translate = false;
      word.textContent = term.text;
      const weight = document.createElement('input');
      Object.assign(weight, {
        type: 'number',
        min: '1',
        max: '5',
        step: '1',
        required: true,
        value: term.weight,
        disabled: this.locked
      });
      weight.setAttribute('aria-label', term.text + ' 权重');
      weight.oninput = () => {
        const value = Number(weight.value);
        if (Number.isInteger(value) && value >= 1 && value <= 5) {
          term.weight = value;
          this.changed();
        }
      };
      weight.onchange = () => {
        const value = Number(weight.value);
        if (!Number.isInteger(value) || value < 1 || value > 5) {
          weight.value = term.weight;
          return;
        }
        term.weight = value;
        this.changed();
      };
      cell().append(weight);
      const enabled = document.createElement('input'),
        label = document.createElement('label');
      Object.assign(enabled, { type: 'checkbox', checked: term.enabled, disabled: this.locked });
      enabled.setAttribute('aria-label', term.text + ' 启用状态');
      label.append(enabled, term.enabled ? '已启用' : '已停用');
      enabled.onchange = () => {
        term.enabled = enabled.checked;
        this.render();
        this.changed();
      };
      cell().append(label);
      const remove = document.createElement('button');
      Object.assign(remove, { type: 'button', textContent: '删除', disabled: this.locked });
      remove.onclick = () => {
        this.terms = this.terms.filter((item) => item !== term);
        this.render();
        this.changed();
      };
      cell().append(remove);
      this.field('personal').append(row);
    }
    if (!terms.length) {
      const row = document.createElement('tr'),
        cell = document.createElement('td');
      cell.colSpan = 4;
      cell.textContent = this.terms.length
        ? '没有匹配的热词。'
        : '暂无热词，可手动新增、导入或从公共推荐候选区添加。';
      row.append(cell);
      this.field('personal').append(row);
    }
    this.field('prev').disabled = this.locked || this.page === 0;
    this.field('next').disabled = this.locked || this.page >= pages - 1;
  }
}
