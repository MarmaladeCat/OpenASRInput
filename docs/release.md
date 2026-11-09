# OpenASRInput 1.1.1 release notes

**English** | [简体中文](release.zh-CN.md)

Product and package versions are 1.1.1; public recognition protocol remains v1. Documentation is English-first with linked Chinese counterparts.

## Capabilities

- Unified Portal recognition with preedit, stable finals, normal finalization, and cancellation.
- Native Linux IBus/Fcitx5/Fcitx4 bridges and an independent Windows bridge.
- Web settings for appearance, input frameworks, microphones, Portal connections, personal hotwords, and text-command editing.
- Target/round isolation, recognition ledgers, and commit ACKs prevent duplicate or wrong-target commits.

## Downloads and reading

Input requires [OpenASRPortal](https://github.com/MarmaladeCat/OpenASRPortal), locally or remotely. [Download Portal](https://github.com/MarmaladeCat/OpenASRPortal/releases) and follow its [configuration guide](https://github.com/MarmaladeCat/OpenASRPortal/blob/main/docs/user-guide.md). The Input release page is the intended home of combined Input + Portal installers.

Standalone packages use `OpenASRInput_1.1.1_linux_amd64.deb`, `OpenASRInput_1.1.1_linux_arm64.deb`, or `OpenASRInput_1.1.1_windows_amd64.msi`. Combined packages append the included Portal version: `OpenASRInput_1.1.1_windows_amd64_OpenASRPortal_1.1.1.msi`, or `OpenASRInput_1.1.1_linux_<architecture>_OpenASRPortal_1.1.1.deb`. The Linux combined DEB owns both applications as `openasrinput-portal`; APT handles installation, replacement and removal. Packages include private Python; Linux still needs the desktop's input framework.

GitHub Release attachments contain only packages and an exact `filename.sha256` companion for each, with one checksum record. Read the [user guide](user-guide.md) and [installation guide](installation.md) online. Local source builds retain documentation archives, manifest.json, and SHA256SUMS for the complete collected directory. Build manifests are not platform certification.

## Changes in 1.1.1

Settings use an English/Chinese language dropdown and retain in-progress form values when switching. Portal's combined management UI adds inline upstream editing, panel-local connection results, and proxy availability/latency testing.

Combined installers include Input 1.1.1 and independently versioned Portal 1.1.1 with genuine Bailian/Soniox streaming, Boson AI Higgs STT and per-upstream HTTP/HTTPS proxy selection. Select the Boson profile in Portal to receive finalized text after speech segments; that provider does not emit word-by-word previews. The Input protocol remains v1.

Windows x64 and Linux amd64/ARM64 combined installers, fixed per-user configuration beneath the OpenASR root, legacy migration, setup-on-demand after installation, and upper-right Chinese/English page switching are described in [installation.md](installation.md).

Windows target detection tolerates missing optional UIA value/position capabilities and supports native PowerPoint text-selection fallback. Office writes bind to the focused document pane; ordinary controls in that process keep their own insertion backend. Missing UIA text ranges use panel-only preview with confirmed native range insertion. Real Office compatibility remains subject to the version-specific [acceptance procedure](testing.md).

Windows custom-editor insertion checks optional value, text, and caret capabilities independently, including provider failures after a write. Focus is rechecked after provider queries. If no reliable confirmation baseline is available, the character backend reports failure before sending text; ambiguous writes are not repeated.

Standalone Windows installation remembers a custom application directory during maintenance and removal. Uninstalling with configuration deletion resolves the registered installation location instead of reverting to the default application path.

## Compatibility and upgrades

Fcitx4 is X11-only. Accept Wayland separately by desktop/framework. Native capabilities differ across applications. Demo never commits to real applications. Before upgrading, exit Input, back up local configuration, and retain the Portal key. Active old sessions cannot resume.

Windows settings still contain an old Alt+Z hint; the actual native shortcut is Alt+X, as documented in the guide.

List unverified systems, native targets, installation/upgrades, and real recording in delivery acceptance. Future release notes describe user-visible changes and compatibility by version, not daily development logs.
