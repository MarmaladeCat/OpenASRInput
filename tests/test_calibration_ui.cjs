// Real settings UI and Python calibration state machine; synthetic audio/cloud only.
const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const root = path.resolve(__dirname, '..');
fs.mkdirSync(path.join(root, 'test-results'), { recursive: true });
const temporary = fs.mkdtempSync(path.join(root, 'test-results', 'calibration-ui-'));
app.setPath('userData', path.join(temporary, 'browser'));
app.disableHardwareAcceleration();
if (process.platform === 'linux') app.commandLine.appendSwitch('ozone-platform', 'x11');
let window, python;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const js = (value) => window.webContents.executeJavaScript(value);
async function wait(expression) {
  for (let i = 0; i < 300; i++) {
    if (await js(expression)) return;
    await sleep(30);
  }
  throw new Error(
    'Timeout: ' +
      expression +
      ' / ' +
      (await js('document.getElementById("calibration-status").textContent'))
  );
}
const click = (id) => js(`document.getElementById(${JSON.stringify(id)}).click()`);
const state = (value) =>
  `document.getElementById('calibration-status').dataset.state === '${value}'`;

async function run() {
  await app.whenReady();
  const windowsPackage = process.env.OPENASRINPUT_TEST_WINDOWS_PACKAGE_ROOT;
  const fixture = path.join(root, 'tests/calibration_ui_server.py');
  python = spawn(
    windowsPackage
      ? path.join(windowsPackage, 'python/python.exe')
      : process.env.OPENASRINPUT_TEST_PYTHON || 'python3',
    [
      ...(windowsPackage
        ? [
            '-c',
            `import runpy,sys; sys.dont_write_bytecode=True; sys.path.insert(0,${JSON.stringify(path.join(root, 'tests'))}); runpy.run_path(${JSON.stringify(fixture)},run_name='__main__')`
          ]
        : [fixture]),
      '--directory',
      temporary
    ],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: windowsPackage ? '' : path.join(root, 'src'),
        PYTHONDONTWRITEBYTECODE: '1'
      },
      stdio: ['ignore', 'pipe', 'pipe']
    }
  );
  python.stderr.on('data', (data) => process.stderr.write(data));
  const ready = path.join(temporary, 'ready.json');
  for (let i = 0; !fs.existsSync(ready); i++) {
    if (i > 200 || python.exitCode !== null) throw new Error('Fixture did not start');
    await sleep(25);
  }
  window = new BrowserWindow({
    width: 1200,
    height: 1000,
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false }
  });
  await window.loadURL(JSON.parse(fs.readFileSync(ready)).url);
  await wait("document.getElementById('calibration-passage').textContent.length > 20");
  await click('tab-audio');
  assert.equal(await js("document.getElementById('device').value"), '');
  assert.equal(await js("document.getElementById('gain').closest('details').open"), false);
  await click('calibration-start');
  await wait(state('noise'));
  assert.equal(await js("document.getElementById('calibration-passage').hidden"), true);
  await wait(state('recording') + " && !document.getElementById('calibration-stop').disabled");
  assert.equal(await js("document.getElementById('save').disabled"), true);
  await click('calibration-stop');
  await wait(state('await-validation'));
  assert.match(await js("document.getElementById('calibration-passage').textContent"), /周末/);
  await click('calibration-validate');
  await wait(
    state('validation-recording') + " && !document.getElementById('calibration-stop').disabled"
  );
  await click('calibration-stop');
  await wait(state('complete'));
  assert.equal(await js("document.getElementById('calibration-apply').hidden"), false);
  assert.match(await js("document.getElementById('calibration-results').textContent"), /独立验证/);
  await js("document.getElementById('calibration-heading').scrollIntoView()");
  await js(
    'document.fonts.ready.then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))'
  );
  await sleep(100);
  fs.writeFileSync(
    path.join(root, 'test-results/calibration-verified.png'),
    (await window.webContents.capturePage()).toPNG()
  );
  await click('calibration-apply');
  await wait(state('saved'));
  let config = JSON.parse(fs.readFileSync(path.join(temporary, 'input.json')));
  assert.equal(config.audio.calibrations.length, 1);
  assert.equal(config.audio.calibrations[0].gain, 3);
  assert.equal(config.audio.gain, 1);
  assert.equal(config.audio.deviceId, null);
  assert.equal(config.audio.calibrations[0].deviceId, 'synthetic-mic');
  await click('calibration-reset');
  await wait(state('idle'));
  config = JSON.parse(fs.readFileSync(path.join(temporary, 'input.json')));
  assert.equal(config.audio.calibrations.length, 0);
  await click('calibration-start');
  await wait(state('noise') + ' || ' + state('recording'));
  await click('calibration-cancel');
  await wait(state('cancelled'));
  assert.equal(await js("document.getElementById('save').disabled"), false);
  console.log(
    'PASS default microphone UI: automatic gain without manual tuning, quiet-stage prompt, compare, validate, apply, restore, cancel'
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
    const exited = new Promise((resolve) => python.once('exit', resolve));
    python.kill();
    await exited;
  }
  // Chromium keeps cache handles until Electron exits on Windows. Preserve the
  // isolated test-results sandbox, as the other settings UI regressions do.
  if (process.platform !== 'win32') fs.rmSync(temporary, { recursive: true, force: true });
  app.exit(code);
}
