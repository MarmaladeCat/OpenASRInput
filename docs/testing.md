# OpenASRInput testing requirements

**English** | [简体中文](testing.zh-CN.md)

These are the product's development/release acceptance requirements; see the [executable scenarios](../tests/functional/manifest.json).
Tests must run from this repository alone, without parent/other-product sources or interpreters.

## Run inside this repository

Use Python 3.10+. Page/panel tests use Node/Electron tooling (Node.js 22.13+). Linux UI runs under Xvfb, Windows on an isolated interactive desktop. Native tests require the relevant OS/input framework.

```bash
python scripts/test.py list --suite core
python scripts/test.py setup --suite unit
python scripts/test.py run --suite unit --allow-skips
python scripts/test.py setup --suite core
python scripts/test.py run --suite core
python scripts/test.py setup --suite ui
python scripts/test.py run --suite ui
```

`setup` creates this product's Python test environment in `.cache/functional/`; desktop dependencies belong in its node_modules/, browser tools in `.cache/test-lab/ui/`.
The application still uses its own runtime. Each run creates new reports/logs under test-results/functional/.
`--case <ID>` selects a case, not whole-product acceptance.

### Windows editor compatibility

`windows-native` includes actual TextBox/RichTextBox/WebView2 journeys, injected Shift+Space start requests with a text caret, the same controls in a `POWERPNT`-named disposable fixture (`native-office-controls`), and headless target/native-range rules (`native-target-rules`). The named fixture catches process-wide misrouting; it is not Microsoft Office. Headless rules cover optional-provider failures, missing geometry, native Office selection fallback, explicit read-only rejection, focus changes, Unicode range replacement, and ambiguous setters.

For package-native acceptance, run `tests/functional/check_windows_editor.py --bridge '<candidate>/native/OpenASRInputBridge.exe'` with the product test Python and `PYTHONPATH=src;tests`; repeat with `--office-host`. The environment report records the actual bridge assembly hash.

The disposable editor also hosts a real WPF text box whose optional Value getter can fail before or after insertion while TextPattern still works. Verify selected-position Unicode insertion, idempotent replay, panel-only preview and zero writes when all confirmation channels are unavailable, and read-only/recovery transitions across WinForms, WPF, and Chromium. Headless rules independently fault value/text/selection/count capabilities and trigger focus changes inside provider calls; they execute the actual evidence and continuation code. Missing capability is not permission to ignore explicit protection or to replay an uncertain write.

Windows installer acceptance must also use isolated, nondefault program and configuration directories. Exercise native uninstall with configuration retained, reinstallation, and explicit configuration deletion; verify both the custom application payload and requested data are removed. Package checks require current-user installation-directory discovery before directory costing, so maintenance does not silently fall back to the default path.

Extracted-runtime checks must set a disposable `OPENASR_DATA_ROOT` as well as the configuration file; an installed shared root can otherwise redirect runtime state outside APPDATA. Chromium read-only fixture commands acknowledge UIA publication (or the resulting focus loss), independently of bridge validity. A DOM mutation acknowledgement alone does not establish accessibility readiness.

For real Office, explicitly run on an isolated interactive desktop with Microsoft PowerPoint installed:

```powershell
python scripts/test.py setup --suite windows-office
python scripts/test.py run --suite windows-office --execution-host virtual-machine
# To check an extracted current candidate instead of the source-built bridge:
python tests/functional/check_windows_powerpoint.py --bridge '<candidate>/native/OpenASRInputBridge.exe'
```

The test creates its own disposable presentation under test-results/ and covers text boxes, empty title placeholders, table cells, normal/page notes, Unicode/paragraphs, selection-only replacement, preview revision/cancellation, long finals, and cross-shape/cell focus isolation. Missing PowerPoint is blocked with a nonzero exit, never a skip/pass. Keep `native-powerpoint-result.json`, the runner log, and the sandbox captures; record the exact Office version and bridge hashes. Permanent Office editions and Microsoft 365 require separate runs. Check physical Shift+Space with a blinking caret and real microphone separately from bridge-protocol tests.

## Required behavior

| Layer                            | Coverage                                                                                                                                                              |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| unit / core                      | Recording rounds, connection cards/key isolation, preview/revision/final, focus loss/cancel, configuration reload, no duplicate shortcuts or swallowed ordinary input |
| UI                               | Settings, Portal cards, microphone calibration; synthetic audio/upstream fixtures                                                                                     |
| Native / installation / services | Linux Fcitx4/X11, Fcitx5/IBus with X11/Wayland; Windows UI Automation editors; use bridges from the current candidate                                                 |
| Performance                      | Start-to-ready, first partial, end-to-stable-commit, lost/duplicate events, long-recording memory                                                                     |

Package check example, after building the matching target:

```bash
python tests/test_portable_deb.py .cache/build/artifacts/linux/amd64/auto/openasrinput_1.0.2_amd64.deb
```

## Result rules

- Failures return nonzero. Missing environments/dependencies/devices are blocked, not passed.
- unittest skips appear as incomplete and normally return nonzero. `--allow-skips` permits daily success exits but remains incomplete, never platform release acceptance.
- Simulated upstreams/synthetic audio establish business/protocol checks only, not real recognition, microphones, or native hardware input.
- Accept every OS, CPU, desktop/input framework, and installation form independently. Never copy another platform's pass.
- Reconfirm source/candidate consistency after source, locks, or resources change. Old reports cannot stand in for current candidates.
- Use temporary HOME, ports, configuration, databases, and fictional keys; never production data or desktop/input-method restarts.

## Performance regressions

Fix machine/OS/interpreter/dependencies, inputs/resource hashes, CPU threads, and service configuration.
Warm up, then interleave at least five baseline and five candidate runs. Retain all samples, median, p95, error rate, and peak memory.
Functionality and accuracy must both hold. A median regression above 10% or p95 above 15% blocks a no-regression claim pending investigation; noisy/insufficient samples are unconfirmed.
Whole-core-suite duration measures regression runtime, not user-operation latency or real ASR RTF.
Store baselines, measurements, and samples in test-results/, not old release status in source.

## Test environment ownership

Dockerfiles, Compose templates, scripts, and locks are reproducible source and may be committed.
Container exports/layers, VM disks, ISOs, snapshots, secrets, recordings, and reports go to `.cache/` or test-results/, never Git.
Clean up only this run's processes/containers/volumes; isolate instances and production data in shared VMs.

## User-guide image provenance

`docs/images/linux-settings.png`: version 1.0 source settings service, Linux amd64/Chrome, without an input daemon. `windows-settings.png`: private Python settings service extracted from the 1.0.0 MSI, Windows 11 amd64/Edge. Both use temporary input.json and browser profiles, directly capture Input and Shortcuts, and do not alter interface pixels. These are capture-source versions, not claims of new-version acceptance.

The demonstration verifies configuration pages/platform layout only, without starting the user's input method, real microphone capture, or native commits. Windows retains the old Alt+Z hint; the guide explains actual Alt+X. Recapture with fresh temporary directories/loopback ports and check for paths/keys before publishing. Keep scripts/logs in test-results/.
