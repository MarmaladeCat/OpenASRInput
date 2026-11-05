const { app, BrowserWindow } = require('electron');
const fs = require('node:fs'),
  path = require('node:path'),
  http = require('node:http'),
  assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const { once } = require('node:events');
const root = path.resolve(__dirname, '..');
const temp = fs.mkdtempSync(path.join(root, 'test-results', 'portal-cards-ui-'));
app.setPath('userData', path.join(temp, 'browser'));
app.disableHardwareAcceleration();
if (process.platform === 'linux') app.commandLine.appendSwitch('ozone-platform', 'x11');
app.on('window-all-closed', () => {});
let server, python, win;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const js = (code) => win.webContents.executeJavaScript(code);
async function wait(code) {
  for (let n = 0; n < 250; n++) {
    if (await js(code)) return;
    await sleep(30);
  }
  throw new Error(
    'UI timeout: ' +
      code +
      '\n' +
      (await js('document.querySelector("#portal-card-list")?.textContent'))
  );
}
async function input(selector, fields) {
  await js(
    `(()=>{const form=document.querySelector(${JSON.stringify(selector)});for(const [name,value] of Object.entries(${JSON.stringify(fields)})){const f=form.elements.namedItem(name);f.value=value;f.dispatchEvent(new Event('input',{bubbles:true}));}})()`
  );
}
async function click(selector) {
  await js(`document.querySelector(${JSON.stringify(selector)}).click()`);
}
async function run() {
  await app.whenReady();
  server = http.createServer((request, response) => {
    response.setHeader('Content-Type', 'application/json');
    if (!['Bearer key-a', 'Bearer key-b'].includes(request.headers.authorization)) {
      response.statusCode = 401;
      response.end(JSON.stringify({ error: { code: 'AUTH_FAILED', message: 'invalid test key' } }));
      return;
    }
    setTimeout(
      () =>
        response.end(
          JSON.stringify(
            request.url === '/v1/capabilities'
              ? {
                  protocolVersion: 1,
                  maxRecordingMs: 300000,
                  audio: { encoding: 'pcm_s16le', sampleRate: 16000, channels: 1 }
                }
              : {
                  defaultProfileId: 'local',
                  profiles: [{ id: 'local', title: '测试上游', provider: 'openlocalasr' }]
                }
          )
        ),
      20
    );
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const config = path.join(temp, 'input.json');
  const packageRoot = process.env.OPENASRINPUT_TEST_PACKAGE_ROOT;
  python = spawn(
    packageRoot
      ? path.join(packageRoot, 'usr/bin/openasrinput')
      : process.env.OPENASRINPUT_TEST_PYTHON || 'python3',
    [
      ...(packageRoot ? ['settings-server'] : ['-B', '-m', 'openasrinput', 'settings']),
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
  python.stderr.pipe(process.stderr);
  const ready = await new Promise((resolve, reject) => {
    let out = '';
    python.stdout.on('data', (data) => {
      out += data;
      if (out.includes('\n')) resolve(JSON.parse(out.split('\n')[0]));
    });
    python.on('exit', (code) => reject(new Error('Settings exited ' + code)));
  });
  win = new BrowserWindow({
    show: false,
    width: 1100,
    height: 900,
    webPreferences: { nodeIntegration: false, contextIsolation: true }
  });
  win.webContents.on('will-prevent-unload', (event) => event.preventDefault());
  await win.loadURL(ready.settingsUrl);
  await wait('!!document.querySelector("#portal-card-new form")');
  await js(
    "document.getElementById('width').value='720'; document.getElementById('width').dispatchEvent(new Event('input',{bubbles:true}));"
  );
  await click('#save');
  await wait('document.getElementById("feedback").textContent.includes("设置已保存")');
  assert.equal(
    JSON.parse(fs.readFileSync(config)).portal.cards.length,
    0,
    'Appearance-only save must not create an empty legacy Portal card'
  );
  await click('#tab-portal');
  await input('#portal-card-new form', { name: '本机网关 A', url: origin, apiKey: 'key-a' });
  await click('#portal-card-new [data-action=test]');
  await wait(
    'document.querySelector("#portal-card-new [data-role=result]").textContent.includes("连接通过")'
  );
  await click('#portal-card-new [data-action=save]');
  await wait('document.querySelectorAll("#portal-card-list form").length===1');
  assert.equal(await js('document.querySelector("#portal-card-new input[name=apiKey]").value'), '');
  await input('#portal-card-new form', { name: '备用网关 B', url: origin, apiKey: 'key-b' });
  await click('#portal-card-new [data-action=test]');
  await wait(
    'document.querySelector("#portal-card-new [data-role=result]").textContent.includes("连接通过")'
  );
  await click('#portal-card-new [data-action=save]');
  await wait('document.querySelectorAll("#portal-card-list form").length===2');
  await click('#portal-card-list form:nth-child(2) [data-action=use]');
  await wait(
    'document.querySelector("#portal-card-list form:nth-child(2)").classList.contains("selected")'
  );
  const saved = JSON.parse(fs.readFileSync(config));
  assert.equal(saved.portal.apiKey, 'key-b');
  assert.equal(saved.portal.cards[0].apiKey, 'key-a');
  await input('#portal-card-list form:nth-child(1)', { apiKey: 'wrong-key' });
  await click('#portal-card-list form:nth-child(1) [data-action=test]');
  await wait(
    'document.querySelector("#portal-card-list form [data-role=result]").textContent.includes("连接失败")'
  );
  assert.equal(JSON.parse(fs.readFileSync(config)).portal.apiKey, 'key-b');
  const reloaded = new Promise((resolve) => win.webContents.once('did-finish-load', resolve));
  win.reload();
  await reloaded;
  await wait('document.querySelectorAll("#portal-card-list form").length===2');
  await click('#tab-portal');
  await click('#portal-card-list form:first-child [data-action=test]');
  await wait(
    'document.querySelector("#portal-card-list form [data-role=result]").textContent.includes("连接通过")'
  );
  assert.match(
    await js('document.querySelector("#portal-card-list form [data-role=result]").textContent'),
    /\d+ ms/
  );
  await js('void(window.confirm=()=>true)');
  await click('#portal-card-list form:nth-child(2) [data-action=delete]');
  await wait('document.querySelectorAll("#portal-card-list form").length===1');
  assert.equal(JSON.parse(fs.readFileSync(config)).portal.activePortalCardId, '');
  await click('#portal-card-list form [data-action=use]');
  await wait('document.querySelector("#portal-card-list form").classList.contains("selected")');
  fs.writeFileSync(
    path.join(root, 'test-results', 'portal-cards.png'),
    (await win.webContents.capturePage()).toPNG()
  );
  console.log(
    'PASS Portal cards: multiple connections, independent keys, per-card status/latency, active selection, failure isolation, reload and deletion'
  );
}
run()
  .then(() => finish(0))
  .catch((error) => {
    console.error(error);
    finish(1);
  });
async function finish(code) {
  if (win && !win.isDestroyed()) win.destroy();
  if (python && python.exitCode === null && python.signalCode === null) {
    const exited = once(python, 'exit');
    if (process.platform === 'win32')
      spawnSync('taskkill', ['/PID', String(python.pid), '/T', '/F']);
    else python.kill('SIGINT');
    await Promise.race([exited, sleep(3000)]);
    if (python.exitCode === null && python.signalCode === null) {
      python.kill('SIGKILL');
      await exited;
    }
  }
  if (server) server.close();
  app.exit(code);
}
