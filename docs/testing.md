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

## Required behavior

| Layer                            | Coverage                                                                                                                                                              |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| unit / core                      | Recording rounds, connection cards/key isolation, preview/revision/final, focus loss/cancel, configuration reload, no duplicate shortcuts or swallowed ordinary input |
| UI                               | Settings, Portal cards, microphone calibration; synthetic audio/upstream fixtures                                                                                     |
| Native / installation / services | Linux Fcitx4/X11, Fcitx5/IBus with X11/Wayland; Windows UI Automation editors; use bridges from the current candidate                                                 |
| Performance                      | Start-to-ready, first partial, end-to-stable-commit, lost/duplicate events, long-recording memory                                                                     |

Package check example, after building the matching target:

```bash
python tests/test_portable_deb.py .cache/build/artifacts/linux/amd64/auto/openasrinput_1.0.0_amd64.deb
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
