const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function language(window, value) {
  await window.webContents.executeJavaScript(`import('/i18n.mjs').then(() => {
    const control = document.querySelector('[data-language-select]');
    control.value = '${value}';
    control.dispatchEvent(new Event('change'));
    return new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  })`);
}

async function verifyLanguages(window) {
  const js = (code) => window.webContents.executeJavaScript(code);
  await js(`document.getElementById('portal-url').value='http://127.0.0.1:19876';
    document.getElementById('portal-url').dispatchEvent(new Event('input', {bubbles:true}));`);
  await language(window, 'en');
  assert.equal(await js('document.documentElement.lang'), 'en');
  assert.equal(await js('document.getElementById("portal-url").value'), 'http://127.0.0.1:19876');
  assert.equal(await js('document.getElementById("dirty-indicator").hidden'), false);
  for (const page of [
    'appearance',
    'audio',
    'portal',
    'text-edit',
    'input',
    'hotwords',
    'runtime'
  ]) {
    const tab = await js(`document.querySelector('[data-page="${page}"]')?.id`);
    if (!tab) throw new Error('Missing language test tab: ' + page);
    await js(`document.getElementById('${tab}').click()`);
    await language(window, 'en');
    const untranslated = await js(`(() => {
      const result=[];
      const walker=document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      while(walker.nextNode()) {
        const node=walker.currentNode, parent=node.parentElement;
        if (!parent || parent.closest('script,style,textarea,[translate="no"],[data-user-content]') || !parent.getClientRects().length) continue;
        if (/[\u3400-\u9fff]/.test(node.data)) result.push(node.data.trim());
      }
      return result;
    })()`);
    assert.deepEqual(untranslated, [], page + ': untranslated visible text');
  }
  await js(`document.querySelector('[data-page="appearance"]').click()`);
  await language(window, 'en');
  fs.writeFileSync(
    path.join(__dirname, '../test-results/settings-english.png'),
    (await window.webContents.capturePage()).toPNG()
  );
  const size = window.getContentSize();
  window.setContentSize(390, 844);
  await language(window, 'en');
  assert.equal(
    await js('document.documentElement.scrollWidth <= innerWidth'),
    true,
    'English mobile width'
  );
  fs.writeFileSync(
    path.join(__dirname, '../test-results/settings-english-mobile.png'),
    (await window.webContents.capturePage()).toPNG()
  );
  window.setContentSize(...size);
  await language(window, 'zh-CN');
  assert.equal(await js('document.getElementById("save").textContent.trim()'), '保存设置');
  assert.equal(await js('document.getElementById("portal-url").value'), 'http://127.0.0.1:19876');
  await language(window, 'en');
  await window.loadURL(await js('location.href'));
  assert.equal(
    await js('import("/i18n.mjs").then(() => document.documentElement.lang)'),
    'en',
    'Remember language after reload'
  );
  await language(window, 'zh-CN');
  await js(`document.getElementById('reload').click()`);
}

module.exports = { language, verifyLanguages };
