// Real settings page + real Python config service, with a disposable browser profile.
const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');
const root = path.resolve(__dirname, '..');
fs.mkdirSync(path.join(root, 'test-results'), { recursive: true });
const temporary = fs.mkdtempSync(path.join(root, 'test-results', 'settings-ui-'));
app.setPath('userData', path.join(temporary, 'browser'));
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('ozone-platform', 'x11');
let window, python, portal;
const calls = [];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const js = (expression) => window.webContents.executeJavaScript(expression);

async function wait(expression) {
  for (let index = 0; index < 200; index++) {
    if (await js(expression)) return;
    await sleep(25);
  }
  throw new Error(
    'UI timeout: ' +
      expression +
      ' · ' +
      (await js('document.getElementById("feedback").textContent'))
  );
}

async function field(id, value) {
  await js(
    `(() => {const field=document.getElementById(${JSON.stringify(id)});field.value=${JSON.stringify(String(value))};field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}));})()`
  );
}

async function screenshot(name) {
  await js(
    'document.fonts.ready.then(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))'
  );
  await sleep(100);
  const image = await window.webContents.capturePage();
  fs.writeFileSync(path.join(root, 'test-results', name), image.toPNG());
}

async function cardField(scope, name, value) {
  await js(
    `(() => { const field = document.querySelector(${JSON.stringify(scope + ' [name="' + name + '"]')}); field.value = ${JSON.stringify(value)}; field.dispatchEvent(new Event('input', {bubbles:true})); field.dispatchEvent(new Event('change', {bubbles:true})); })()`
  );
}
const clickCard = (scope, action) =>
  js(
    `document.querySelector(${JSON.stringify(scope + ' [data-action="' + action + '"]')}).click()`
  );

async function run() {
  await app.whenReady();
  const vocabulary = {
    version: 1,
    revision: 0,
    settings: {
      enabled: false,
      autoLearn: false,
      windowDays: 30,
      minFrequency: 3,
      maxWords: 100,
      manualTerms: [],
      excludedTerms: []
    },
    profileId: 'cloud',
    learnedTerms: [{ text: '麒麟', frequency: 5 }],
    terms: [],
    selection: {
      capability: { supported: true, note: '豆包热词限制 100 tokens' },
      appliedCount: 0,
      terms: [],
      omitted: []
    }
  };
  portal = http.createServer(async (request, response) => {
    if (['/v1/models', '/v1/chat/completions'].includes(request.url)) {
      response.setHeader('Content-Type', 'application/json');
      if (request.url === '/v1/models') {
        response.end(JSON.stringify({ data: [{ id: 'deepseek-flash' }] }));
      } else {
        let body = '';
        for await (const chunk of request) body += chunk;
        if (JSON.parse(body).model === 'unavailable') {
          response.statusCode = 403;
          response.end('{}');
        } else {
          response.end(
            JSON.stringify({ choices: [{ finish_reason: 'stop', message: { content: '您好！' } }] })
          );
        }
      }
      return;
    }
    calls.push(request.url);
    assert.equal(request.headers.authorization, 'Bearer test-secret');
    response.setHeader('Content-Type', 'application/json');
    if (request.url.startsWith('/v1/hotwords')) {
      if (request.method === 'PATCH') {
        let body = '';
        for await (const chunk of request) body += chunk;
        const value = JSON.parse(body);
        assert.equal(value.revision, vocabulary.revision);
        vocabulary.revision++;
        vocabulary.settings = { ...vocabulary.settings, ...value.settings };
        vocabulary.terms = value.settings.manualTerms;
        vocabulary.selection.terms = value.settings.manualTerms;
        vocabulary.selection.appliedCount = value.settings.manualTerms.length;
      }
      if (request.method === 'DELETE') vocabulary.learnedTerms = [];
      response.end(JSON.stringify(vocabulary));
      return;
    }
    assert.equal(request.method, 'GET');
    if (request.url === '/v1/capabilities')
      response.end(
        JSON.stringify({
          protocolVersion: 1,
          audio: { encoding: 'pcm_s16le', sampleRate: 16000, channels: 1 },
          maxRecordingMs: 300000,
          hotwords: { version: 1 }
        })
      );
    else if (request.url === '/v1/profiles')
      response.end(
        JSON.stringify({
          defaultProfileId: 'local',
          profiles: [
            {
              id: 'local',
              title: '本地低延迟',
              provider: 'openlocalasr',
              capabilities: { latencyClass: 'streaming' }
            },
            {
              id: 'cloud',
              title: '云端实时识别',
              provider: 'doubao',
              capabilities: { latencyClass: 'streaming' }
            }
          ]
        })
      );
    else {
      response.statusCode = 404;
      response.end('{}');
    }
  });
  await new Promise((resolve) => portal.listen(0, '127.0.0.1', resolve));
  const config = path.join(temporary, 'input.json');
  const packageRoot = process.env.OPENASRINPUT_TEST_PACKAGE_ROOT;
  const windowsPackage = process.env.OPENASRINPUT_TEST_WINDOWS_PACKAGE_ROOT;
  python = spawn(
    packageRoot
      ? path.join(packageRoot, 'usr/bin/openasrinput')
      : windowsPackage
        ? path.join(windowsPackage, 'python/python.exe')
        : process.env.OPENASRINPUT_TEST_PYTHON || 'python3',
    [
      ...(packageRoot ? ['settings-server'] : ['-m', 'openasrinput', 'settings']),
      '--no-open',
      '--port',
      '0',
      '--config',
      config
    ],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: packageRoot ? '' : path.join(root, 'src'),
        ...(packageRoot
          ? { OPENASRINPUT_APP_ROOT: path.join(packageRoot, 'usr/lib/openasrinput') }
          : {}),
        PYTHONDONTWRITEBYTECODE: '1'
      }
    }
  );
  python.stderr.on('data', (chunk) => process.stderr.write(chunk));
  const settings = await new Promise((resolve, reject) => {
    let text = '';
    const timer = setTimeout(() => reject(new Error('settings service did not start')), 15000);
    python.stdout.on('data', (chunk) => {
      text += chunk;
      if (text.includes('\n')) {
        clearTimeout(timer);
        resolve(JSON.parse(text.split('\n')[0]));
      }
    });
    python.on('exit', (code) => {
      clearTimeout(timer);
      reject(new Error('settings service exited: ' + code));
    });
  });
  window = new BrowserWindow({
    width: 1040,
    height: 810,
    show: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true }
  });
  const rendererErrors = [];
  window.webContents.on('console-message', (_event, details) => {
    if (details.level === 'error') rendererErrors.push(details.message);
  });
  await window.loadURL(settings.settingsUrl);
  await wait('document.getElementById("feedback").textContent === "设置已载入。"');
  assert.deepEqual(calls, []);
  assert.equal(fs.existsSync(config), false);
  assert.equal(await js('document.querySelectorAll("#settings-nav [role=tab]").length'), 7);
  assert.equal(await js('document.getElementById("theme").value'), 'material');
  assert.equal(await js('document.getElementById("scale").value'), '1');
  await screenshot('settings-appearance.png');
  await field('theme', 'nord');
  await field('color-mode', 'dark');
  await field('scale', '1.25');
  await field('width', '720');
  await field('font-size', '18');
  await field('radius', '20');
  await field('position', 'top');
  await field('transparency', '35');
  assert.equal(
    await js(
      'getComputedStyle(document.getElementById("voice-preview")).getPropertyValue("--background").trim()'
    ),
    '#2e3440'
  );
  assert.notEqual(
    await js('getComputedStyle(document.documentElement).getPropertyValue("--background").trim()'),
    '#2e3440'
  );
  assert.equal(
    await js('getComputedStyle(document.getElementById("voice-preview")).opacity'),
    '0.65'
  );
  await field('position', 'hidden');
  assert.equal(
    await js('getComputedStyle(document.getElementById("voice-preview")).visibility'),
    'hidden'
  );
  await field('position', 'top');
  await field('settings-theme', 'github');
  await field('settings-color-mode', 'dark');
  await js('document.getElementById("save").click()');
  await wait(
    'document.getElementById("feedback").dataset.tone === "success" && document.getElementById("dirty-indicator").hidden && !document.getElementById("save").disabled'
  );
  assert.equal(JSON.parse(fs.readFileSync(config)).overlay.theme, 'nord');
  assert.equal(JSON.parse(fs.readFileSync(config)).settings.theme, 'github');
  assert.equal(JSON.parse(fs.readFileSync(config)).overlay.transparency, 35);
  await js('document.getElementById("reload").click()');
  await wait(
    'document.getElementById("position").value === "top" && document.getElementById("transparency").value === "35"'
  );
  await screenshot('settings-appearance-dark.png');

  await js('document.getElementById("tab-portal").click()');
  await field('portal-url', 'http://127.0.0.1:' + portal.address().port);
  await field('portal-key', 'test-secret');
  await js('document.getElementById("tab-text-edit").click()');
  assert.equal(await js('document.getElementById("page-portal").hidden'), true);
  assert.equal(await js('document.getElementById("page-text-edit").hidden'), false);
  assert.equal(
    await js('document.getElementById("tab-text-edit").getAttribute("aria-selected")'),
    'true'
  );
  const fresh = '#model-card-new';
  const first = '#model-card-list .model-card-form:first-child';
  assert.equal(
    await js('document.querySelector("#model-card-new [name=provider]").value'),
    'deepseek'
  );
  await clickCard(fresh, 'save');
  assert.match(
    await js('document.querySelector("#model-card-new [data-role=result]").textContent'),
    /请先填写/
  );
  assert.equal(await js('document.querySelectorAll("#model-card-list form").length'), 0);
  await cardField(fresh, 'name', 'DeepSeek 兼容测试卡');
  await cardField(fresh, 'provider', 'openai-compatible');
  await cardField(fresh, 'url', 'http://127.0.0.1:' + portal.address().port + '/v1');
  await cardField(fresh, 'model', 'deepseek-flash');
  await clickCard(fresh, 'save');
  assert.match(
    await js('document.querySelector("#model-card-new [data-role=result]").textContent'),
    /API Key/
  );
  await cardField(fresh, 'apiKey', 'text-fixture-secret');
  await clickCard(fresh, 'models');
  await wait(
    'document.querySelector("#model-card-new [data-role=result]").textContent.includes("已刷新")'
  );
  await cardField(fresh, 'model-choice', 'deepseek-flash');
  await clickCard(fresh, 'save');
  await wait(
    'document.querySelectorAll("#model-card-list form").length === 1 && !document.querySelector("#model-card-list [data-action=use]").disabled'
  );
  await clickCard(first, 'use');
  await wait(
    'document.querySelector("#model-card-list [data-role=active]").textContent === "当前使用"'
  );
  await js('document.getElementById("tab-portal").click()');
  assert.equal(await js('document.getElementById("page-text-edit").hidden'), true);
  assert.equal(await js('document.querySelector("#model-card-list [name=apiKey]").value'), '');
  await js('document.getElementById("portal-test").click()');
  await wait('document.getElementById("profile-list").children.length === 3');
  assert.equal(await js('document.getElementById("profile-id")'), null);
  assert.match(
    await js('document.querySelector("#profile-list .profile-card").textContent'),
    /当前默认：本地低延迟/
  );
  assert.equal(JSON.parse(fs.readFileSync(config)).portal.apiKey, '');
  assert.deepEqual(calls, ['/v1/capabilities', '/v1/profiles']);
  await js('document.querySelectorAll("#profile-list .profile-card button")[2].click()');
  await js('document.getElementById("save").click()');
  await wait(
    'document.getElementById("portal-key").value === "" && document.getElementById("dirty-indicator").hidden && !document.getElementById("save").disabled'
  );
  await js('document.getElementById("tab-input").click()');
  for (const framework of ['ibus', 'fcitx4', 'fcitx5', 'auto']) {
    await field('input-framework', framework);
    await js('document.getElementById("save").click()');
    await wait(
      'document.getElementById("dirty-indicator").hidden && !document.getElementById("save").disabled'
    );
    assert.equal(JSON.parse(fs.readFileSync(config)).input.framework, framework);
  }
  await screenshot('settings-input-framework.png');
  const saved = JSON.parse(fs.readFileSync(config));
  assert.equal(saved.portal.apiKey, 'test-secret');
  assert.equal(saved.portal.profileId, 'cloud');
  assert.equal(saved.textEdit.apiKey, 'text-fixture-secret');
  assert.equal(await js('document.querySelector("#model-card-list [name=apiKey]").value'), '');
  if (process.platform !== 'win32') assert.equal(fs.statSync(config).mode & 0o777, 0o600);
  const publicConfig = await js(
    'fetch("/api/config",{headers:{Authorization:"Bearer "+sessionStorage.getItem("openasrinput-settings-token")}}).then(response=>response.json())'
  );
  assert.equal(publicConfig.config.portal.hasApiKey, true);
  assert.equal(publicConfig.config.portal.apiKey, undefined);
  assert.equal(publicConfig.config.textEdit.hasApiKey, true);
  assert.equal(publicConfig.config.textEdit.apiKey, undefined);
  await js('document.getElementById("tab-text-edit").click()');
  await clickCard(first, 'test');
  await wait(
    'document.querySelector("#model-card-list [data-role=result]").textContent.includes("测试通过")'
  );
  await cardField(fresh, 'name', '失败也能保存');
  await cardField(fresh, 'provider', 'openai-compatible');
  await cardField(fresh, 'url', 'http://127.0.0.1:' + portal.address().port + '/v1');
  await cardField(fresh, 'model', 'unavailable');
  await cardField(fresh, 'apiKey', 'second-fixture-secret');
  await clickCard(fresh, 'test');
  await wait(
    'document.querySelector("#model-card-new [data-role=result]").textContent.includes("HTTP 403")'
  );
  await clickCard(fresh, 'save');
  await wait('document.querySelectorAll("#model-card-list form").length === 2');
  const cardsSaved = JSON.parse(fs.readFileSync(config)).textEdit;
  assert.equal(cardsSaved.cards.length, 2);
  assert.equal(cardsSaved.cards[1].apiKey, 'second-fixture-secret');
  assert.equal(cardsSaved.activeModelCardId, cardsSaved.cards[0].id);
  assert.equal(cardsSaved.cards[0].apiKey, 'text-fixture-secret');
  assert.equal(
    await js('document.querySelectorAll("#model-card-list [data-action=test]").length'),
    2
  );
  await cardField(fresh, 'name', '未完成的新增卡');
  await cardField(first, 'name', '日常润色模型🙂');
  await clickCard(first, 'save');
  await wait(
    'document.querySelector("#model-card-list [data-role=title]").textContent === "日常润色模型🙂"'
  );
  assert.equal(
    await js('document.querySelector("#model-card-new [name=name]").value'),
    '未完成的新增卡'
  );
  assert.equal(JSON.parse(fs.readFileSync(config)).textEdit.cards.length, 2);
  await js('document.getElementById("save").click()');
  await wait(
    '!document.getElementById("save").disabled && document.getElementById("feedback").textContent.includes("设置已保存")'
  );
  assert.equal(
    await js('document.querySelector("#model-card-new [name=name]").value'),
    '未完成的新增卡'
  );
  assert.equal(JSON.parse(fs.readFileSync(config)).textEdit.cards.length, 2);
  await js('document.getElementById("reload").click()');
  await wait('document.querySelector("#model-card-new [name=name]").value === ""');
  await screenshot('settings-model-cards.png');
  await js('document.getElementById("model-card-new").scrollIntoView()');
  await screenshot('settings-model-card-new.png');
  const second = '#model-card-list .model-card-form:nth-child(2)';
  assert.match(
    await js(
      'document.querySelector("#model-card-list .model-card-form:nth-child(2) [data-role=result]").textContent'
    ),
    /文本模型请求失败（HTTP 403）/
  );
  await clickCard(second, 'use');
  await wait(
    'document.querySelector("#model-card-list .model-card-form:nth-child(2) [data-role=active]").textContent === "当前使用"'
  );
  assert.equal(JSON.parse(fs.readFileSync(config)).textEdit.apiKey, 'second-fixture-secret');
  await js('document.getElementById("model-card-disable").click()');
  await wait(
    'document.querySelectorAll("#model-card-list .selected").length === 0 && !document.querySelector("#model-card-list [name=name]").disabled'
  );
  assert.equal(JSON.parse(fs.readFileSync(config)).textEdit.activeModelCardId, '');
  await clickCard(first, 'use');
  await wait(
    'document.querySelector("#model-card-list [data-role=active]").textContent === "当前使用"'
  );
  await js('window.confirm = () => true; undefined');
  await clickCard(first, 'delete');
  await wait('document.querySelectorAll("#model-card-list form").length === 1');
  assert.equal(JSON.parse(fs.readFileSync(config)).textEdit.activeModelCardId, '');
  assert.equal(
    JSON.parse(fs.readFileSync(config)).textEdit.cards[0].apiKey,
    'second-fixture-secret'
  );
  await js('document.getElementById("tab-portal").click()');
  await screenshot('settings-portal.png');
  await js('document.getElementById("tab-text-edit").click()');
  await screenshot('settings-text-edit.png');

  await js(
    'document.getElementById("tab-hotwords").click();document.getElementById("hotwords-refresh").click()'
  );
  await wait('!document.getElementById("hotwords-form").hidden');
  assert.equal(await js('document.getElementById("hotwords-enabled").checked'), false);
  assert.match(await js('document.getElementById("hotwords-status").textContent'), /100 tokens/);
  await js('document.getElementById("hotwords-new-text").value="麒麟"');
  assert.equal(
    await js(`document.getElementById('hotwords-new-text').dispatchEvent(
    new KeyboardEvent('keydown',{key:'Enter',isComposing:true,cancelable:true}))`),
    true
  );
  assert.equal(await js('document.querySelectorAll("#hotwords-personal [data-word]").length'), 0);
  await js(
    `document.getElementById('hotwords-new-text').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))`
  );
  assert.equal(
    await js('document.querySelector("#hotwords-personal [data-word]").dataset.word'),
    '麒麟'
  );
  await js('document.getElementById("save").click()');
  assert.match(await js('document.getElementById("feedback").textContent'), /请先保存热词/);
  assert.equal(
    await js('document.querySelector("#hotwords-personal [data-word]").dataset.word'),
    '麒麟'
  );
  await js(
    'document.getElementById("hotwords-enabled").checked=true;document.getElementById("hotwords-form").requestSubmit()'
  );
  await wait('document.getElementById("feedback").textContent.includes("热词设置已保存")');
  assert.equal(vocabulary.settings.autoLearn, false);
  assert.deepEqual(vocabulary.settings.manualTerms, [{ text: '麒麟', weight: 4 }]);
  assert.match(await js('document.getElementById("hotwords-selection").textContent'), /选用 1 个/);
  assert.equal(JSON.parse(fs.readFileSync(config)).hotwords, undefined);
  await js('document.getElementById("hotwords-refresh").click()');
  await wait('document.getElementById("feedback").textContent.includes("个人热词已刷新")');
  assert.equal(
    await js('document.querySelector("#hotwords-personal [data-word]").dataset.word'),
    '麒麟'
  );
  await screenshot('settings-hotwords.png');
  await js('document.getElementById("tab-portal").click()');

  await js(
    'document.querySelector("#profile-list .profile-card button").click();document.getElementById("save").click()'
  );
  await wait(
    'document.getElementById("dirty-indicator").hidden && !document.getElementById("save").disabled'
  );
  assert.equal(JSON.parse(fs.readFileSync(config)).portal.profileId, '');
  await js('document.getElementById("reload").click()');
  await wait('document.getElementById("feedback").textContent === "已重新载入保存的设置。"');
  assert.equal(
    await js(
      'document.querySelector("#profile-list .profile-card button").getAttribute("aria-pressed")'
    ),
    'true'
  );

  await js(
    'document.getElementById("tab-appearance").click();document.getElementById("tab-appearance").dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowDown",bubbles:true}))'
  );
  assert.equal(
    await js('document.getElementById("tab-audio").getAttribute("aria-selected")'),
    'true'
  );
  await field('gain', '1.7');
  await js('document.getElementById("save").click()');
  await wait(
    'document.getElementById("dirty-indicator").hidden && !document.getElementById("save").disabled'
  );
  assert.equal(JSON.parse(fs.readFileSync(config)).audio.gain, 1.7);
  assert.equal(JSON.parse(fs.readFileSync(config)).portal.apiKey, 'test-secret');
  await js(
    'document.getElementById("tab-portal").click();document.getElementById("clear-key").click();document.getElementById("save").click()'
  );
  await wait(
    'document.getElementById("dirty-indicator").hidden && !document.getElementById("save").disabled && document.getElementById("portal-key").placeholder === "填写 Portal 接入 Key"'
  );
  assert.equal(JSON.parse(fs.readFileSync(config)).portal.apiKey, '');
  assert.deepEqual(rendererErrors, []);
  console.log(
    'PASS settings UI: navigation, theme preview, save/reload, Portal profiles, secret retention, audio gain, personal hotword query/add/save'
  );
}

run()
  .then(() => finish(0))
  .catch((error) => {
    console.error(error);
    finish(1);
  });
async function finish(code) {
  if (window && !window.isDestroyed()) window.destroy();
  if (python && python.exitCode === null) {
    python.kill('SIGINT');
    await Promise.race([new Promise((resolve) => python.once('exit', resolve)), sleep(3000)]);
    if (python.exitCode === null) python.kill('SIGKILL');
  }
  if (portal) portal.close();
  // Chromium holds its profile files until this process exits on Windows.
  if (process.platform !== 'win32') fs.rmSync(temporary, { recursive: true, force: true });
  app.exit(code);
}
