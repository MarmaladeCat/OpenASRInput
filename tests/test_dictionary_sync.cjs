// Two real management pages and independent Python processes; no cloud ASR or microphone.
const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { createInterface } = require('node:readline');
const root = path.resolve(__dirname, '..');
const temporary = fs.mkdtempSync(path.join(root, 'test-results', 'dictionary-sync-'));
app.setPath('userData', path.join(temporary, 'browser'));
app.disableHardwareAcceleration();
if (process.platform === 'linux') app.commandLine.appendSwitch('ozone-platform', 'x11');
app.on('window-all-closed', () => {});
const children = [],
  windows = [];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const js = (window, code) => window.webContents.executeJavaScript(code);
async function wait(window, code) {
  for (let i = 0; i < 240; i++) {
    if (await js(window, code)) return;
    await sleep(25);
  }
  throw new Error(
    'UI timeout: ' +
      code +
      ' · ' +
      (await js(
        window,
        'document.getElementById("status")?.textContent || document.getElementById("feedback")?.textContent'
      ))
  );
}
async function processReady(directory, arguments_, source, python) {
  const child = spawn(python || process.env.OPENASRINPUT_TEST_PYTHON || 'python3', arguments_, {
    cwd: directory,
    env: { ...process.env, PYTHONPATH: source, PYTHONDONTWRITEBYTECODE: '1' }
  });
  children.push(child);
  child.stderr.pipe(process.stderr);
  const lines = createInterface({ input: child.stdout });
  return Promise.race([
    once(lines, 'line').then(([line]) => JSON.parse(line)),
    once(child, 'exit').then(([code]) => {
      throw new Error('fixture exited: ' + code);
    })
  ]);
}
async function run() {
  await app.whenReady();
  const portal = process.env.OPENASRINPUT_TEST_PORTAL_CHECKOUT;
  if (!portal) throw new Error('OPENASRINPUT_TEST_PORTAL_CHECKOUT is required');
  const server = await processReady(
    portal,
    ['tests/serve_management_ui.py'],
    path.join(portal, 'src'),
    process.env.OPENASRPORTAL_TEST_PYTHON
  );
  const settings = await processReady(
    root,
    [
      '-m',
      'openasrinput',
      'settings',
      '--no-open',
      '--port',
      '0',
      '--config',
      path.join(temporary, 'input.json')
    ],
    path.join(root, 'src')
  );
  const admin = new BrowserWindow({
    show: false,
    webPreferences: { nodeIntegration: false, contextIsolation: true }
  });
  const input = new BrowserWindow({
    show: false,
    webPreferences: { nodeIntegration: false, contextIsolation: true }
  });
  windows.push(admin, input);
  await admin.loadURL(server.url + '/admin');
  await input.loadURL(settings.settingsUrl);
  await js(
    admin,
    'document.getElementById("admin-key").value="test-admin-password";document.getElementById("connect").click()'
  );
  await wait(admin, '!document.getElementById("workspace").hidden');
  assert.equal(
    await js(
      admin,
      `fetch('/v1/admin/profiles', {
    method:'POST', headers:{Authorization:'Bearer '+sessionStorage.getItem('openasrportal-admin-session'),'Content-Type':'application/json'},
    body:JSON.stringify({id:'hotwords-test',title:'热词测试',provider:'bailian_qwen_asr',configuration:{apiKey:'fake-upstream'}})
  }).then(response=>response.status)`
    ),
    201
  );
  await js(
    admin,
    'document.getElementById("tab-downstream").click();document.querySelector(".key-hotwords-open").click()'
  );
  await wait(admin, '!document.getElementById("key-hotwords").hidden');
  await wait(input, 'document.getElementById("feedback").textContent==="设置已载入。"');
  await js(
    input,
    `document.getElementById('tab-portal').click();
    for (const [id,value] of [['portal-url',${JSON.stringify(server.url)}],['portal-key','test-asr']]) {
      const field=document.getElementById(id);field.value=value;field.dispatchEvent(new Event('input'));
    }document.getElementById('save').click();`
  );
  await wait(
    input,
    'document.getElementById("portal-key").value==="" && document.getElementById("dirty-indicator").hidden'
  );
  await js(
    input,
    'document.getElementById("tab-hotwords").click();document.getElementById("hotwords-refresh").click()'
  );
  await wait(input, 'document.getElementById("dictionary-source").options.length>1');
  assert.equal(await js(input, 'document.getElementById("hotwords-enabled").checked'), false);
  // Candidates never mutate the saved user table until explicitly added and saved.
  await js(
    input,
    'document.getElementById("dictionary-source").value="tech-ai";document.getElementById("dictionary-online").click()'
  );
  await wait(
    input,
    'document.querySelector(\'#dictionary-recommendations [data-word="机器学习"]\') !== null'
  );
  await js(
    input,
    'document.querySelector(\'#dictionary-recommendations [data-word="机器学习"] button\').click()'
  );
  assert.equal(
    await js(
      input,
      'document.querySelector(\'#hotwords-personal [data-word="机器学习"] input[type=number]\').value'
    ),
    '4'
  );
  assert.deepEqual(
    await js(
      admin,
      'fetch("/v1/hotwords",{headers:{Authorization:"Bearer test-asr"}}).then(r=>r.json()).then(v=>v.settings.manualTerms)'
    ),
    []
  );
  await js(
    input,
    'document.getElementById("hotwords-enabled").checked=true;document.getElementById("hotwords-form").requestSubmit()'
  );
  await wait(input, 'document.getElementById("feedback").textContent.includes("热词设置已保存")');
  await js(admin, 'document.getElementById("key-hotwords-refresh").click()');
  await wait(
    admin,
    'document.querySelector(\'#key-hotwords-personal [data-word="机器学习"]\') !== null'
  );
  // Per-row weight and enabled state survive client/admin synchronization.
  await js(
    admin,
    `(() => {
    const row=document.querySelector('#key-hotwords-personal [data-word="机器学习"]');
    const weight=row.querySelector('input[type=number]');weight.value='2';weight.dispatchEvent(new Event('change'));
    row.querySelector('input[type=checkbox]').click();document.getElementById('key-hotwords-form').requestSubmit();
  })()`
  );
  await wait(admin, 'document.getElementById("status").textContent.includes("个人热词已保存")');
  await js(input, 'document.getElementById("hotwords-refresh").click()');
  await wait(
    input,
    'document.querySelector(\'#hotwords-personal [data-word="机器学习"] input[type=number]\')?.value==="2"'
  );
  assert.equal(
    await js(
      input,
      'document.querySelector(\'#hotwords-personal [data-word="机器学习"] input[type=checkbox]\').checked'
    ),
    false
  );
  assert.equal(
    await js(
      admin,
      'fetch("/v1/hotwords",{headers:{Authorization:"Bearer test-asr"}}).then(r=>r.json()).then(v=>v.selection.appliedCount)'
    ),
    0
  );

  // Exported personal JSON includes disabled words and can be imported by the admin.
  const personalFile = path.join(temporary, 'personal.json');
  const personalDownloaded = new Promise((resolve, reject) =>
    input.webContents.session.once('will-download', (event, item) => {
      item.setSavePath(personalFile);
      item.once('done', (event, state) =>
        state === 'completed' ? resolve() : reject(new Error(state))
      );
    })
  );
  await js(input, 'document.getElementById("hotwords-download").click()');
  await personalDownloaded;
  const personalExport = JSON.parse(fs.readFileSync(personalFile));
  assert.deepEqual(personalExport.terms, [{ text: '机器学习', weight: 2, enabled: false }]);
  await js(admin, 'document.querySelector("#key-hotwords-personal button").click()');
  await js(
    admin,
    `(() => {
    const transfer=new DataTransfer();transfer.items.add(new File([${JSON.stringify(JSON.stringify(personalExport))}], 'personal.json'));
    document.getElementById('key-hotwords-file').files=transfer.files;document.getElementById('key-hotwords-import').click();
  })()`
  );
  await wait(admin, 'document.getElementById("status").textContent.includes("个人热词已导入")');
  assert.equal(
    await js(
      admin,
      'document.querySelector(\'#key-hotwords-personal [data-word="机器学习"] input[type=checkbox]\').checked'
    ),
    false
  );
  await js(admin, 'document.getElementById("key-hotwords-form").requestSubmit()');
  await wait(admin, 'document.getElementById("status").textContent.includes("个人热词已保存")');
  await js(
    admin,
    `document.querySelector('#key-hotwords-personal input[type=checkbox]').click();
    document.getElementById('key-hotwords-enabled').checked=false;
    document.getElementById('key-hotwords-form').requestSubmit()`
  );
  await wait(admin, 'document.getElementById("status").textContent.includes("个人热词已保存")');
  await js(input, 'document.getElementById("hotwords-refresh").click()');
  await wait(input, 'document.getElementById("hotwords-enabled").checked===false');
  assert.equal(
    await js(input, 'document.querySelector("#hotwords-personal input[type=checkbox]").checked'),
    true
  );
  assert.equal(
    await js(
      admin,
      'fetch("/v1/hotwords",{headers:{Authorization:"Bearer test-asr"}}).then(r=>r.json()).then(v=>v.selection.appliedCount)'
    ),
    0
  );
  await js(
    input,
    'document.getElementById("hotwords-enabled").checked=true;document.getElementById("hotwords-form").requestSubmit()'
  );
  await wait(input, 'document.getElementById("feedback").textContent.includes("热词设置已保存")');
  await js(admin, 'document.getElementById("key-hotwords-refresh").click()');
  await wait(admin, 'document.getElementById("key-hotwords-enabled").checked===true');
  const second = new BrowserWindow({
    show: false,
    webPreferences: { nodeIntegration: false, contextIsolation: true }
  });
  windows.push(second);
  await second.loadURL(settings.settingsUrl);
  await wait(second, 'document.getElementById("feedback").textContent==="设置已载入。"');
  await js(
    second,
    'document.getElementById("tab-hotwords").click();document.getElementById("hotwords-refresh").click()'
  );
  await wait(
    second,
    'document.querySelector(\'#hotwords-personal [data-word="机器学习"]\') !== null'
  );
  await js(
    admin,
    'document.querySelector("#key-hotwords-personal button").click();document.getElementById("key-hotwords-new-text").value="人工智能";document.getElementById("key-hotwords-new-weight").value="3";document.getElementById("key-hotwords-add").click();document.getElementById("key-hotwords-form").requestSubmit()'
  );
  await wait(admin, 'document.getElementById("status").textContent.includes("个人热词已保存")');
  // A second device's stale save must not overwrite the first device's edits.
  await js(
    second,
    'document.getElementById("hotwords-new-text").value="旧客户端";document.getElementById("hotwords-add").click();document.getElementById("hotwords-form").requestSubmit()'
  );
  await wait(second, 'document.getElementById("feedback").textContent.includes("刷新后重试")');
  await js(input, 'document.getElementById("hotwords-refresh").click()');
  await wait(
    input,
    'document.querySelector(\'#hotwords-personal [data-word="人工智能"] input[type=number]\')?.value==="3"'
  );
  // Import merges matching identities atomically and never changes the global switch.
  const imported = [
    { text: '人工智能', weight: 5, enabled: false },
    { text: 'OpenASR', weight: 3, enabled: true }
  ];
  await js(
    input,
    `(() => {
    const transfer=new DataTransfer();transfer.items.add(new File([${JSON.stringify(JSON.stringify(imported))}], 'personal.json'));
    document.getElementById('hotwords-file').files=transfer.files;document.getElementById('hotwords-import').click();
  })()`
  );
  await wait(input, 'document.getElementById("feedback").textContent.includes("个人热词已导入")');
  assert.equal(
    await js(input, 'document.querySelectorAll("#hotwords-personal [data-word]").length'),
    2
  );
  assert.equal(
    await js(
      input,
      'document.querySelector(\'#hotwords-personal [data-word="人工智能"] input[type=checkbox]\').checked'
    ),
    false
  );
  await js(
    input,
    'document.getElementById("hotwords-new-text").value="ＯｐｅｎＡＳＲ";document.getElementById("hotwords-add").click()'
  );
  await wait(input, 'document.getElementById("feedback").textContent.includes("热词已在表中")');
  assert.equal(
    await js(input, 'document.querySelectorAll("#hotwords-personal [data-word]").length'),
    2
  );
  const invalid = [
    { text: '正常词', weight: 4 },
    { text: '非法词', weight: 9 }
  ];
  await js(
    input,
    `(() => {
    const transfer=new DataTransfer();transfer.items.add(new File([${JSON.stringify(JSON.stringify(invalid))}], 'invalid.json'));
    document.getElementById('hotwords-file').files=transfer.files;document.getElementById('hotwords-import').click();
  })()`
  );
  await wait(input, 'document.getElementById("feedback").textContent.includes("权重须为")');
  assert.equal(
    await js(input, 'document.querySelectorAll("#hotwords-personal [data-word]").length'),
    2
  );
  await js(
    input,
    'document.querySelectorAll("#hotwords-personal button").forEach(button=>button.click());document.getElementById("hotwords-form").requestSubmit()'
  );
  await wait(input, 'document.getElementById("feedback").textContent.includes("热词设置已保存")');
  await js(admin, 'document.getElementById("key-hotwords-refresh").click()');
  await wait(admin, 'document.querySelectorAll("#key-hotwords-personal [data-word]").length===0');
  await js(
    admin,
    'document.getElementById("key-dictionary-source").value="tech-ai";document.getElementById("key-dictionary-online").click()'
  );
  await wait(admin, 'document.getElementById("key-dictionary-recommendations").children.length>30');
  await js(
    admin,
    'document.querySelector(\'#key-dictionary-recommendations [data-word="人工智能"] button\').click()'
  );
  assert.equal(
    await js(
      admin,
      'document.querySelector(\'#key-hotwords-personal [data-word="人工智能"] input[type=number]\').value'
    ),
    '4'
  );
  await js(admin, 'document.getElementById("key-hotwords-form").requestSubmit()');
  await wait(admin, 'document.getElementById("status").textContent.includes("个人热词已保存")');
  await js(input, 'document.getElementById("hotwords-refresh").click()');
  await wait(
    input,
    'document.querySelector(\'#hotwords-personal [data-word="人工智能"] input[type=number]\')?.value==="4"'
  );
  await wait(input, '!document.getElementById("dictionary-online").disabled');
  await js(
    input,
    'document.getElementById("dictionary-source").value="tech-ai";document.getElementById("dictionary-online").click()'
  );
  await wait(
    input,
    'document.querySelector(\'#dictionary-recommendations [data-word="人工智能"] span\')?.textContent.includes("已在热词表中")'
  );
  await js(
    input,
    'document.getElementById("dictionary-search").value="人工智能";document.getElementById("dictionary-search").dispatchEvent(new Event("input"))'
  );
  assert.equal(
    await js(
      input,
      '[...document.querySelectorAll("#dictionary-recommendations [data-word]")].every(row=>row.dataset.word.includes("人工智能"))'
    ),
    true
  );
  assert.equal(
    await js(input, 'document.getElementById("dictionary-recommendations").children.length'),
    2
  );
  // Administrators maintain shared tables; clients reload the same live catalog.
  await js(admin, 'document.getElementById("tab-public").click()');
  await wait(admin, 'document.getElementById("public-list").children.length===3');
  await js(
    admin,
    'document.getElementById("public-new").click();document.getElementById("public-title").value="自建医学推荐"'
  );
  const medical = '---\nname: medical\n...\n医学成像\tyi xue\t100\n神经调控\tshen jing\t50\n';
  await js(
    admin,
    `(() => {const transfer=new DataTransfer();transfer.items.add(new File([${JSON.stringify(medical)}],'medical.dict.yaml'));document.getElementById('public-file').files=transfer.files;document.getElementById('public-file').dispatchEvent(new Event('change'));})()`
  );
  await wait(
    admin,
    'document.getElementById("public-report").textContent.includes("有效 2 词") && !document.getElementById("public-preview").disabled'
  );
  await js(admin, 'document.getElementById("public-form").requestSubmit()');
  await wait(
    admin,
    'document.getElementById("public-id").value.startsWith("public-") && document.getElementById("public-list").children.length===4'
  );
  const publicId = await js(admin, 'document.getElementById("public-id").value');
  await js(input, 'document.getElementById("hotwords-refresh").click()');
  await wait(
    input,
    `document.querySelector('#dictionary-source option[value="${publicId}"]') !== null`
  );
  await js(
    input,
    `document.getElementById('dictionary-source').value=${JSON.stringify(publicId)};document.getElementById('dictionary-online').click()`
  );
  await wait(
    input,
    'document.querySelector(\'#dictionary-recommendations [data-word="医学成像"]\') !== null'
  );
  await js(
    input,
    'document.querySelector(\'#dictionary-recommendations [data-word="医学成像"] button\').click();document.getElementById("hotwords-form").requestSubmit()'
  );
  await wait(input, 'document.getElementById("feedback").textContent.includes("热词设置已保存")');
  // The public table can be viewed, exported and modified independently.
  const exportedFile = path.join(temporary, 'public-table.json');
  const downloaded = new Promise((resolve, reject) =>
    admin.webContents.session.once('will-download', (event, item) => {
      item.setSavePath(exportedFile);
      item.once('done', (event, state) =>
        state === 'completed' ? resolve() : reject(new Error(state))
      );
    })
  );
  await js(
    admin,
    `document.querySelector('#public-list [data-id="${publicId}"] .public-download').click()`
  );
  await downloaded;
  assert.equal(JSON.parse(fs.readFileSync(exportedFile)).words.length, 2);
  await js(admin, 'document.getElementById("public-cancel").click()');
  await js(
    admin,
    `document.querySelector('#public-list [data-id="${publicId}"] .public-open').click()`
  );
  await wait(
    admin,
    `!document.getElementById('public-editor').hidden && document.getElementById('public-id').value===${JSON.stringify(publicId)}`
  );
  await js(
    admin,
    'document.getElementById("public-title").value="自建医学新版";document.getElementById("public-content").value="神经调控|3";document.getElementById("public-format").value="text";document.getElementById("public-content").dispatchEvent(new Event("input"));document.getElementById("public-form").requestSubmit()'
  );
  await wait(
    admin,
    `document.querySelector('#public-list [data-id="${publicId}"] h3').textContent.includes('自建医学新版') && !document.getElementById('public-preview').disabled`
  );
  await js(input, 'document.getElementById("hotwords-refresh").click()');
  await wait(
    input,
    `document.querySelector('#dictionary-source option[value="${publicId}"]').textContent==='自建医学新版'`
  );
  assert.equal(
    await js(
      input,
      'document.querySelector(\'#hotwords-personal [data-word="医学成像"]\') !== null'
    ),
    true
  );
  await js(
    admin,
    'document.getElementById("public-enabled").checked=false;document.getElementById("public-form").requestSubmit()'
  );
  await wait(
    admin,
    `document.querySelector('#public-list [data-id="${publicId}"] h3').textContent.includes('未发布') && !document.getElementById('public-preview').disabled`
  );
  await js(input, 'document.getElementById("hotwords-refresh").click()');
  await wait(
    input,
    `document.querySelector('#dictionary-source option[value="${publicId}"]') === null`
  );
  await js(
    admin,
    `document.querySelector('#public-list [data-id="${publicId}"] .public-delete').click()`
  );
  await wait(admin, `document.querySelector('#public-list [data-id="${publicId}"]') === null`);
  assert.equal(
    await js(
      input,
      'document.querySelector(\'#hotwords-personal [data-word="医学成像"]\') !== null'
    ),
    true
  );
  await js(admin, 'document.getElementById("tab-downstream").click()');
  await js(
    admin,
    'document.getElementById("key-title").value="隔离用户";document.getElementById("key-form").requestSubmit()'
  );
  await wait(admin, 'document.getElementById("new-key-value").value.startsWith("asr_")');
  const other = await js(admin, 'document.getElementById("new-key-value").value');
  assert.deepEqual(
    await js(
      admin,
      `fetch('/v1/hotwords',{headers:{Authorization:'Bearer '+${JSON.stringify(other)}}}).then(r=>r.json()).then(value=>value.settings.manualTerms)`
    ),
    []
  );
  console.log(
    'PASS hotwords UI: manual add/weight/disable/delete, personal JSON download/import/atomic validation, public candidates, shared-Key/conflict/isolation, admin public create/import/view/export/edit/unpublish/delete and live catalog'
  );
}
run()
  .then(() => finish(0))
  .catch((error) => {
    console.error(error);
    finish(1);
  });
async function finish(code) {
  for (const window of windows) window.destroy();
  for (const child of children)
    if (child.exitCode === null) {
      const exited = once(child, 'exit');
      child.kill('SIGINT');
      await exited;
    }
  // The Windows Chromium profile is released only after Electron exits.
  if (process.platform !== 'win32') fs.rmSync(temporary, { recursive: true, force: true });
  app.exit(code);
}
