# OpenASRInput functional tests

**English** | [简体中文](README.zh-CN.md)

[manifest.json](manifest.json) defines scenarios and expected results; [requirements.txt](requirements.txt) pins protocol/settings dependencies, without microphone or large-model runtimes.

- `settings-service`: real HTTP service, authentication, configuration save/read, occupied-port rejection.
- `connection-preflight`: real CLI preflight, key isolation under endpoint overrides, per-round snapshots.
- `legacy-windows-encoding` (Windows): disable Python UTF-8 mode; verify Chinese model-card saving, migration, and caching under the native code page.
- `settings-workflow`: complete real-page settings/model-card workflow.
- `portal-cards`: per-card testing, key isolation, switching, saving, reloading, deletion.
- `microphone-calibration`: real page calibration, retest, independent validation, cancellation, saving; synthetic PCM/simulated ASR.
- `native-editor` (Windows): actual helper/UI Automation with dedicated TextBox/RichTextBox/WebView2 editors; commits, revisions, cancellation, selection replacement, focus guards. Missing environments/skips are not passes.

From this repository root, Python 3.10+:

```bash
python scripts/test.py setup --suite core
python scripts/test.py run --suite core
python scripts/test.py setup --suite ui
python scripts/test.py run --suite ui
# On an isolated interactive Windows desktop
python scripts/test.py setup --suite windows-native
python scripts/test.py run --suite windows-native --execution-host virtual-machine
```

The runner prepares product test environments, UI tools, and `src`/`tests` search paths. UI uses Electron 44.4.5 and points `OPENASRINPUT_TEST_PYTHON` to this product's venv. Direct manifest debugging requires the same environment. On physical Windows set execution-host to physical.
Native setup invokes `prepare_windows.ps1`; run invokes `check_windows_editor.py`. The pinned .NET SDK is SHA-512-verified and stored in `.cache/functional/windows/`.
The runner waits for WebView2 and verifies window process identity. If Windows denies background activation, it clicks only coordinates confirmed by hit-testing to belong to the dedicated editor, then rechecks the foreground process. Before exit it saves `test-results/native-editor-desktop.png`.
Per-Monitor V2 DPI awareness keeps window/click hit-test coordinates consistent at high DPI. `native-editor-environment.json` records .NET/WebView2, DPI, and display regions; `native-editor-result.json` records counts, failures, and skips. VM workers return this evidence too.

For extra real-microphone checks on physical hardware, run explicitly (outside default `windows-native`):

```powershell
$env:PYTHONPATH = 'src;tests'
& .cache/functional/win32-amd64/venv/Scripts/python.exe tests/functional/check_windows_editor.py `
  --microphone --portal-checkout '<Portal-checkout>' --portal-python '<Portal-test-python.exe>'
```

This runs only three `test_windows_session` scenarios, creating its own local Portal/simulated upstream and dedicated editor, then cleaning both process trees. Reports are `test-results/native-microphone-*`. It verifies real audio buffering, stop, dictation/command commits, not cloud accuracy or physical key presses.

Environments/downloads/builds belong in `.cache/`; test configuration, editors, and captures in test-results/. Neither enters Git. Settings/UI scenarios never switch the host input method. ARM64 core does not establish Fcitx/deb installation acceptance. Accept real recording, Office, and installation/upgrades separately under [testing](../../docs/testing.md); see [development](../../docs/development.md) for builds.
