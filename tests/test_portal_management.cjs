const { app, BrowserWindow } = require('electron');
const fs = require('node:fs'),
  path = require('node:path'),
  assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const root = path.resolve(__dirname, '..'),
  tmp = fs.mkdtempSync(path.join(root, 'test-results', 'key-ui-'));
app.setPath('userData', tmp);
app.disableHardwareAcceleration();
if (process.platform === 'linux') app.commandLine.appendSwitch('ozone-platform', 'x11');
let win, child;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const js = (code) => win.webContents.executeJavaScript(code);
async function wait(code) {
  for (let i = 0; i < 200; i++) {
    if (await js(code)) return;
    await sleep(25);
  }
  throw Error('UI timeout: ' + code);
}
async function run() {
  await app.whenReady();
  const portal = process.env.OPENASRINPUT_TEST_PORTAL_CHECKOUT;
  child = spawn(
    process.env.OPENASRPORTAL_TEST_PYTHON || process.env.OPENASRINPUT_TEST_PYTHON,
    ['tests/serve_management_ui.py'],
    {
      cwd: portal,
      env: { ...process.env, PYTHONPATH: path.join(portal, 'src'), PYTHONDONTWRITEBYTECODE: '1' }
    }
  );
  child.stderr.on('data', (b) => process.stderr.write(b));
  const ready = await new Promise((resolve, reject) => {
    let text = '';
    child.stdout.on('data', (b) => {
      text += b;
      if (text.includes('\n')) resolve(JSON.parse(text.split('\n')[0]));
    });
    child.on('exit', () => reject(Error('fixture exited')));
  });
  win = new BrowserWindow({
    width: 1080,
    height: 820,
    webPreferences: { nodeIntegration: false, contextIsolation: true }
  });
  const rendererErrors = [];
  win.webContents.on('console-message', (_event, details) => {
    if (details.level === 'error') rendererErrors.push(details.message);
  });
  await win.loadURL(ready.url + '/admin');
  await js(
    'document.getElementById("admin-key").value="test-admin-password";document.getElementById("connect").click()'
  );
  await wait('!document.getElementById("workspace").hidden');
  assert.equal(await js('document.querySelectorAll("#admin-nav [role=tab]").length'), 6);
  await js('document.getElementById("tab-downstream").click()');
  await js(
    'document.getElementById("key-title").value="测试输入法";document.getElementById("key-form").requestSubmit()'
  );
  await wait('!document.getElementById("new-key").hidden');
  const key = await js('document.getElementById("new-key-value").value');
  assert.ok(key.startsWith('asr_'));
  const result = await js(
    `Promise.all([fetch('/v1/capabilities',{headers:{Authorization:'Bearer '+${JSON.stringify(key)}}}).then(r=>r.status),fetch('/v1/admin/contract',{headers:{Authorization:'Bearer '+${JSON.stringify(key)}}}).then(r=>r.status),fetch('/v1/profiles',{headers:{Authorization:'Bearer test-admin'}}).then(r=>r.status)])`
  );
  assert.deepEqual(result, [200, 401, 401]);
  await js('document.getElementById("key-dismiss").click()');
  assert.equal(await js('document.getElementById("new-key-value").value'), '');
  await js(
    'Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async value=>{window.copiedKey=value}}})'
  );
  await js(
    '[...document.querySelectorAll("#keys article")].find(card=>card.querySelector("h3").textContent==="测试输入法").querySelector(".key-view").click()'
  );
  await wait(
    '[...document.querySelectorAll("#keys article")].find(card=>card.querySelector("h3").textContent==="测试输入法").querySelector(".key-value").value.startsWith("asr_")'
  );
  assert.equal(
    await js(
      '[...document.querySelectorAll("#keys article")].find(card=>card.querySelector("h3").textContent==="测试输入法").querySelector(".key-value").value'
    ),
    key
  );
  await js(
    '[...document.querySelectorAll("#keys article")].find(card=>card.querySelector("h3").textContent==="测试输入法").querySelector(".key-copy").click()'
  );
  await wait('window.copiedKey?.startsWith("asr_")');
  assert.equal(await js('window.copiedKey'), key);
  await js('document.getElementById("tab-upstream").click()');
  assert.equal(
    await js(
      '[...document.querySelectorAll("#keys article")].find(card=>card.querySelector("h3").textContent==="测试输入法").querySelector(".key-value").value'
    ),
    ''
  );
  await js('document.getElementById("tab-downstream").click()');
  await js(
    'document.getElementById("key-title").value="测试Drafts";document.getElementById("key-form").requestSubmit()'
  );
  await wait('!document.getElementById("new-key").hidden');
  const secondKey = await js('document.getElementById("new-key-value").value');
  assert.notEqual(secondKey, key);
  await js('document.getElementById("key-dismiss").click()');
  await sleep(100);
  fs.writeFileSync(
    path.join(root, 'test-results', 'portal-asr-keys.png'),
    (await win.webContents.capturePage()).toPNG()
  );
  await js(
    '[...document.querySelectorAll("#keys article")].find(card=>card.querySelector("h3").textContent==="测试输入法").querySelector(".danger").click()'
  );
  await wait(
    '[...document.querySelectorAll("#keys article")].find(card=>card.querySelector("h3").textContent==="测试输入法").querySelector(".danger").disabled'
  );
  assert.equal(
    await js(
      `fetch('/v1/profiles',{headers:{Authorization:'Bearer '+${JSON.stringify(key)}}}).then(r=>r.status)`
    ),
    401
  );
  await js(
    'document.getElementById("tab-upstream").click();document.getElementById("new").click()'
  );
  await js(
    'document.getElementById("profile-id").value="local";document.getElementById("profile-title").value="演示本地上游";document.querySelector("#fields input[name=apiKey]").value="fake-upstream";document.getElementById("form").requestSubmit()'
  );
  await wait('document.querySelectorAll("#profiles article").length===1');
  await js('document.getElementById("new").click()');
  await js(
    'document.getElementById("profile-id").value="next";document.getElementById("profile-title").value="备用上游";document.querySelector("#fields input[name=apiKey]").value="fake-upstream";document.getElementById("form").requestSubmit()'
  );
  await wait('document.querySelectorAll("#profiles article").length===2');
  await js(
    `(() => {const card=document.querySelector('#profiles article[data-id="local"]');card.querySelector('input[name=remainingMinutes]').value='0.0025';card.querySelector('.quota-form').requestSubmit();})()`
  );
  await wait(
    'document.querySelector(\'#profiles article[data-id="local"] .quota-balance\').textContent.includes("0.15 秒")'
  );
  await js('document.getElementById("tab-downstream").click()');
  await js(
    `(() => {const card=[...document.querySelectorAll('#keys article')].find(item=>item.querySelector('h3').textContent==='测试Drafts');card.querySelector('input[name=remainingMinutes]').value='1';card.querySelector('.quota-form').requestSubmit();})()`
  );
  await wait(
    '[...document.querySelectorAll("#keys article")].find(item=>item.querySelector("h3").textContent==="测试Drafts").querySelector(".quota-balance").textContent.includes("1 分")'
  );
  const finished = await js(`(async () => {
    const descriptor=await fetch('/v1/sessions',{method:'POST',headers:{Authorization:'Bearer '+${JSON.stringify(secondKey)},'Content-Type':'application/json'},body:'{}'}).then(response=>response.json());
    return await new Promise((resolve,reject)=>{
      const socket=new WebSocket(location.origin.replace('http','ws')+descriptor.streamPath+'?ticket='+descriptor.ticket);
      const timeout=setTimeout(()=>{socket.close();reject(new Error('quota stream timed out'));},5000);
      socket.onmessage=({data})=>{const event=JSON.parse(data);if(event.type==='session.ready')socket.send(new Uint8Array(6400));if(event.type==='session.finished'){clearTimeout(timeout);socket.close();resolve(event);}if(event.type==='session.error'){clearTimeout(timeout);socket.close();reject(new Error(event.message));}};
    });
  })()`);
  assert.equal(finished.reason, 'quota_exhausted');
  await js('document.getElementById("refresh").click()');
  await wait('document.querySelector(\'#profiles article[data-id="next"] .default\') !== null');
  assert.match(
    await js('document.querySelector(\'#profiles article[data-id="local"] h3\').textContent'),
    /停用/
  );
  await js('document.getElementById("tab-usage").click()');
  await wait('document.querySelectorAll("#usage-keys tbody tr").length===1');
  assert.match(await js('document.getElementById("usage-keys").textContent'), /测试Drafts/);
  assert.match(await js('document.getElementById("usage-timeline").textContent'), /0.15 秒/);
  assert.match(await js('document.getElementById("usage-timeline").textContent'), /未上报/);
  fs.writeFileSync(
    path.join(root, 'test-results', 'portal-usage.png'),
    (await win.webContents.capturePage()).toPNG()
  );
  await js('document.getElementById("tab-upstream").click()');
  await js(
    `(() => {const card=document.querySelector('#profiles article[data-id="local"]');card.querySelector('input[name=remainingMinutes]').value='1';card.querySelector('.quota-form').requestSubmit();})()`
  );
  await wait(
    'document.querySelector(\'#profiles article[data-id="local"] h3\').textContent.includes("启用")'
  );
  await js(
    '[...document.querySelectorAll(\'#profiles article[data-id="next"] button\')].find(button=>button.textContent==="上移").click()'
  );
  await wait('document.querySelector("#profiles article").dataset.id === "next"');
  await js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  await sleep(100);
  fs.writeFileSync(
    path.join(root, 'test-results', 'portal-upstream.png'),
    (await win.webContents.capturePage()).toPNG()
  );
  await js('document.getElementById("tab-overview").click()');
  await sleep(100);
  assert.equal(await js('document.getElementById("profile-count").textContent'), '2');
  fs.writeFileSync(
    path.join(root, 'test-results', 'portal-overview.png'),
    (await win.webContents.capturePage()).toPNG()
  );
  console.log(
    'PASS Portal admin UI: keys, permissions, time statistics, remaining quotas, quota finalization, automatic fallback, upstream ordering'
  );
  assert.deepEqual(rendererErrors, []);
}
run()
  .then(() => finish(0))
  .catch((e) => {
    console.error(e);
    finish(1);
  });
async function finish(code) {
  if (win) win.destroy();
  if (child) {
    child.kill('SIGINT');
    await sleep(200);
  }
  if (process.platform !== 'win32') fs.rmSync(tmp, { recursive: true, force: true });
  app.exit(code);
}
