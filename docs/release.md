# OpenASRInput 1.0.0 release notes

**English** | [简体中文](release.zh-CN.md)

Product and package versions are 1.0.0; public recognition protocol remains v1. Documentation is English-first with linked Chinese counterparts.

## Capabilities

- Unified Portal recognition with preedit, stable finals, normal finalization, and cancellation.
- Native Linux IBus/Fcitx5/Fcitx4 bridges and an independent Windows bridge.
- Web settings for appearance, input frameworks, microphones, Portal connections, personal hotwords, and text-command editing.
- Target/round isolation, recognition ledgers, and commit ACKs prevent duplicate or wrong-target commits.

## Downloads and reading

Choose Linux `*_linux_amd64_local-auto.deb` or `*_linux_arm64_local-auto.deb` for your CPU, or Windows `*_windows_amd64_native.msi`. Packages include private Python; Linux still needs the desktop's input framework.

`OpenASRInput_1.0.0_docs.zip` contains complete bilingual authored documentation. Extract and start with README.md or docs/user-guide.md. manifest.json records source/platform; SHA256SUMS checks integrity. Build manifests are not platform certification.

## Compatibility and upgrades

Fcitx4 is X11-only. Accept Wayland separately by desktop/framework. Native capabilities differ across applications. Demo never commits to real applications. Before upgrading, exit Input, back up local configuration, and retain the Portal key. Active old sessions cannot resume.

Windows settings still contain an old Alt+Z hint; the actual native shortcut is Alt+X, as documented in the guide.

List unverified systems, native targets, installation/upgrades, and real recording in delivery acceptance. Future release notes describe user-visible changes and compatibility by version, not daily development logs.
