# OpenASRInput 1.0.2 release notes

**English** | [简体中文](release.zh-CN.md)

Product and package versions are 1.0.2; public recognition protocol remains v1. Documentation is English-first with linked Chinese counterparts.

## Capabilities

- Unified Portal recognition with preedit, stable finals, normal finalization, and cancellation.
- Native Linux IBus/Fcitx5/Fcitx4 bridges and an independent Windows bridge.
- Web settings for appearance, input frameworks, microphones, Portal connections, personal hotwords, and text-command editing.
- Target/round isolation, recognition ledgers, and commit ACKs prevent duplicate or wrong-target commits.

## Downloads and reading

Input requires [OpenASRPortal](https://github.com/MarmaladeCat/OpenASRPortal), locally or remotely. [Download Portal](https://github.com/MarmaladeCat/OpenASRPortal/releases) and follow its [configuration guide](https://github.com/MarmaladeCat/OpenASRPortal/blob/main/docs/user-guide.md). The Input release page is the intended home of combined Input + Portal installers.

Choose Linux `*_linux_amd64_local-auto.deb` or `*_linux_arm64_local-auto.deb` for your CPU, or Windows `*_windows_amd64_native.msi`. Packages include private Python; Linux still needs the desktop's input framework.

Each installer has an exact `filename.sha256` companion containing one checksum record. Local source builds also retain manifest.json and SHA256SUMS for the complete collected directory. Documentation archives contain the original bilingual pages and images. Build manifests are not platform certification.

## Current-source changes awaiting review

Windows x64 and Linux amd64/ARM64 combined installers, fixed per-user configuration beneath the OpenASR root, legacy migration, setup-on-demand after installation, and upper-right Chinese/English page switching are described in [installation.md](installation.md). The 1.0.2 candidates are available for maintainer review and manual testing before publication.

Windows target detection tolerates missing optional UIA value/position capabilities and supports native PowerPoint text-selection fallback. Office writes bind to the focused document pane; ordinary controls in that process keep their own insertion backend. Missing UIA text ranges use panel-only preview with confirmed native range insertion. Real Office compatibility remains subject to the version-specific [acceptance procedure](testing.md).

Windows custom-editor insertion checks optional value, text, and caret capabilities independently, including provider failures after a write. Focus is rechecked after provider queries. If no reliable confirmation baseline is available, the character backend reports failure before sending text; ambiguous writes are not repeated.

## Compatibility and upgrades

Fcitx4 is X11-only. Accept Wayland separately by desktop/framework. Native capabilities differ across applications. Demo never commits to real applications. Before upgrading, exit Input, back up local configuration, and retain the Portal key. Active old sessions cannot resume.

Windows settings still contain an old Alt+Z hint; the actual native shortcut is Alt+X, as documented in the guide.

List unverified systems, native targets, installation/upgrades, and real recording in delivery acceptance. Future release notes describe user-visible changes and compatibility by version, not daily development logs.
