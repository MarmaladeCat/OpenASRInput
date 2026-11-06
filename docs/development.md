# OpenASRInput development and releases

**English** | [简体中文](development.zh-CN.md)

For source maintainers. Users should read the [user guide](user-guide.md); acceptance follows [testing requirements](testing.md). This repository owns its environment and never borrows Portal/workspace dependencies.

## Source environment

Current-source installation and language behavior is in [installation.md](installation.md). `python scripts/release.py --source-digest` exposes the source fingerprint for an external bundle composer; it never imports another product. The public `openasrinput provision --handoff FILE` command consumes a recipient-private Portal handoff. Browser messages live in the product-owned `presentation/web/*messages.mjs` catalogs; user-content nodes are explicitly excluded from translation. UI tests switch both languages without resetting forms.

Use Python 3.10+ and create a repository-local virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[portal]'
bash scripts/start.sh demo
bash scripts/start.sh settings
```

On Windows use `py -3.12 -m venv .venv`, then `.venv\Scripts\python.exe -m pip install -e ".[portal]"` and `.venv\Scripts\python.exe -m openasrinput settings`. Point `OPENASRINPUT_CONFIG` at a file in an ignored directory. Demo tests in-memory preedit, not native text delivery.

Linux native builds need the relevant input-method development libraries; Windows needs .NET/C++ tools. Node/Electron serve only page/panel regression tests, not the Python runtime. See [architecture](architecture.md) for source responsibilities.

## Changes and checks

```bash
python scripts/test.py setup --suite unit
python scripts/test.py run --suite unit --allow-skips
node tests/test_wayland_panel.mjs
node tests/test_gnome_lifecycle.mjs
```

Select additional core, UI, native, or package scenarios for the change. Conditional skips remain incomplete. Use this pyproject.toml's Ruff configuration and existing frontend formatting. Never restart the user's desktop/input method for tests.

## Pinned builds

```bash
python scripts/build.py --platform linux --arch amd64
python scripts/build.py --platform linux --arch arm64
# Run in isolated Windows
python scripts/build.py --platform windows --arch amd64 --wix-bin <WiX-directory>
```

Linux uses Ubuntu 22.04 baseline containers and PyInstaller 6.16.0. Windows uses Python 3.12.10, .NET SDK 8.0.408, WiX 3.14.1, and LLVM-MinGW 20261104 UCRT x86_64 or installed Visual Studio C++/Windows SDK. `LLVM_MINGW_ROOT` points to the verified extraction. The LLVM-MinGW ZIP SHA256 is `552191b5754c49a5a20723276a6fc56541ea1922c4c50b7b669022333fc1b40f`.

`build.py` is public; `build_portable_deb.py` assembles the pinned Linux environment, `build_deb.py/build_runtime.py` assemble packages/private Python, `build_windows.py` builds Windows bridge/MSI, and `windows_replacement.py` handles replacement/uninstall. `build-native.sh` supports standalone native development; `package_gnome.py` manages extension packages.

`container_matrix.py` and `desktop_matrix.py/desktop_targets.py` run OS/desktop matrices. `check_gnome_panel.py/check_settings.py/check_electron.py` are isolated graphical checks; `check_git_payload.py` checks standalone source payloads.

## Releases and documentation

For a docs-only preview, create `test-results/`, then run `python scripts/release.py --docs test-results/product-docs.zip`. All authored Markdown, images, and linked attachments retain their original bytes and relative paths. Flat releases include `release.md` / `release.zh-CN.md` beside identical README copies to keep language links valid.

VERSION and tool metadata are **1.0.1**. Candidates go to `.cache/build/artifacts/<os>/<arch>/<variant>/`; `scripts/release.py` publishes successful candidates to `release/1.0.1/`, never dist/. The version directory contains flat packages, complete docs ZIP, bilingual READMEs, manifest, and SHA256SUMS.

The publisher checks version, architecture, unique candidates, and hashes. Other platforms merge only with matching source provenance. Old receipts cannot establish new candidates after source/docs changes; rebuild relevant targets. Record builds and platform acceptance separately.

Maintain both languages for the six document categories. Write user-visible changes in [release notes](release.md), not test diaries. Archives preserve images and relative paths; release READMEs copy release notes verbatim. Scripts must not synthesize product prose. Selected screenshots disclose platform, capture version, demonstration, and simulation limits.

Git owns source, dependencies, templates, recipes, tests, and authored docs. Ignore real configuration, credentials, databases, recordings, raw test captures, caches, and installers. Push this product before workspace gitlinks; maintainers authorize commits/uploads.
