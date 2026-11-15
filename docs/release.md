# OpenASRInput 1.2.0 release notes

**English** | [简体中文](release.zh-CN.md)

Product and package versions are 1.2.0; public recognition protocol remains v1. Documentation is English-first with linked Chinese counterparts.

## Capabilities

- Unified Portal recognition with preedit, stable finals, normal finalization, and cancellation.
- Native Linux IBus/Fcitx5/Fcitx4 bridges and an independent Windows bridge.
- Web settings for appearance, input frameworks, microphones, Portal connections, personal hotwords, and text-command editing.
- Target/round isolation, recognition ledgers, and commit ACKs prevent duplicate or wrong-target commits.

## Downloads and reading

Input requires [OpenASRPortal](https://github.com/MarmaladeCat/OpenASRPortal), locally or remotely. [Download Portal](https://github.com/MarmaladeCat/OpenASRPortal/releases) and follow its [configuration guide](https://github.com/MarmaladeCat/OpenASRPortal/blob/main/docs/user-guide.md). The Input release page is the intended home of combined Input + Portal installers.

Standalone packages use `OpenASRInput_1.2.0_linux_amd64.deb`, `OpenASRInput_1.2.0_linux_arm64.deb`, or `OpenASRInput_1.2.0_windows_amd64.msi`. Combined packages append the included Portal version: `OpenASRInput_1.2.0_windows_amd64_OpenASRPortal_1.2.0.msi`, or `OpenASRInput_1.2.0_linux_<architecture>_OpenASRPortal_1.2.0.deb`. The Linux combined DEB owns both applications as `openasrinput-portal`; APT handles installation, replacement and removal. Packages include private Python; Linux still needs the desktop's input framework.

GitHub Release attachments contain only packages and an exact `filename.sha256` companion for each, with one checksum record. Read the [user guide](user-guide.md) and [installation guide](installation.md) online. Local source builds retain documentation archives, manifest.json, and SHA256SUMS for the complete collected directory. Build manifests are not platform certification.

## Changes in 1.2.0

Ready waiting now covers Portal's queue/initialization budget, with bounded 60-second prebuffering. All launch modes use the same identity-scoped OpenASR data root; package activation state lives beside configuration.

The round limit is the smaller of 295 seconds and the negotiated profile limit, including capture before Portal is ready and stop-time tails. Creation/ready snapshots are checked; oversized prebuffer is rejected before upload. Finalization updates an already-pending receive deadline. Settings show the actual preview timing and active recording limit; ordered public finals remain one-time native commits.

Local settings pages have independent, server-enforced lifetimes: 20 minutes by default, configurable in Appearance, with 0 for no expiry. Reloads do not renew a session. At expiry the page closes where the browser permits, otherwise displays an inactive expiry screen. Reopening settings creates a new session without stopping dictation.

Settings use an English/Chinese language dropdown and retain in-progress form values when switching. Portal's combined management UI adds inline upstream editing, panel-local connection results, and proxy availability/latency testing.

Combined installers include Input 1.2.0 and independently versioned Portal 1.2.0 with genuine Bailian/Soniox streaming, Boson AI Higgs STT and per-upstream HTTP/HTTPS proxy selection. Boson uploads the complete round and returns text after recording stops, without local silence segmentation or word-by-word previews. The Input protocol remains v1.

Windows x64 and Linux amd64/ARM64 combined installers, fixed per-user configuration beneath the OpenASR root, legacy migration, setup-on-demand after installation, and upper-right Chinese/English page switching are described in [installation.md](installation.md).

Windows target detection tolerates missing optional UIA value/position capabilities and supports native PowerPoint text-selection fallback. Office writes bind to the focused document pane; ordinary controls in that process keep their own insertion backend. Missing UIA text ranges use panel-only preview with confirmed native range insertion. Real Office compatibility remains subject to the version-specific [acceptance procedure](testing.md).

PowerPoint document windows using either `mdiClass` or `paneClassDC` route through the Office selection API, preserving paragraph breaks and surrounding text. Native fallback checks slide/shape ownership independently of COM proxy equality and uses an available selection provider to preserve caret identity. The Windows preview window retains its calculated caret-relative position on its first display. Hotkey diagnostics distinguish registration/hook errors from synthetic-key delivery limitations.

Windows custom-editor insertion checks optional value, text, and caret capabilities independently, including provider failures after a write. Focus is rechecked after provider queries. If no reliable confirmation baseline is available, the character backend reports failure before sending text; ambiguous writes are not repeated.

Standalone Windows installation remembers a custom application directory during maintenance and removal. Uninstalling with configuration deletion resolves the registered installation location instead of reverting to the default application path.

## Compatibility and upgrades

Fcitx4 is X11-only. Accept Wayland separately by desktop/framework. Native capabilities differ across applications. Demo never commits to real applications. Before upgrading, exit Input, back up local configuration, and retain the Portal key. Active old sessions cannot resume.

Linux Alt+Z / Windows Alt+X falls back to ordinary dictation when selection reading is unavailable or empty; optional UIA failures no longer block a valid editable target. Settings show both platform shortcuts. Ordinary dictation removes padding spaces after Chinese `。！？` without changing English word spacing or newlines. See [optional Wanxiang packages and data cleanup](installation.md).

List unverified systems, native targets, installation/upgrades, and real recording in delivery acceptance. Future release notes describe user-visible changes and compatibility by version, not daily development logs.
