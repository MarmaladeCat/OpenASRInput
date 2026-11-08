# Combined installation and persistent settings

**English** | [简体中文](installation.zh-CN.md)

This page describes Input 1.0.2 installation and the combined Input 1.0.2 + Portal 1.0.1 packages. Each component keeps its own product version.

## Choose your installation

- **Input + Portal:** one Windows x64 MSI, or a Linux amd64/ARM64 archive containing both DEBs and `install.sh`. These are intended for the [Input release downloads](https://github.com/MarmaladeCat/OpenASRInput/releases). On Windows leave Portal selected. On Linux extract the archive and run `./install.sh` as your desktop user; sudo installs both packages with APT. Distribution dependencies may need network access.
- **Input alone:** use the standalone package if a Portal is already available. [Portal project](https://github.com/MarmaladeCat/OpenASRPortal), [downloads](https://github.com/MarmaladeCat/OpenASRPortal/releases), and [configuration guide](https://github.com/MarmaladeCat/OpenASRPortal/blob/main/docs/user-guide.md) explain deployment. Input does not recognize speech without a working local or remote Portal.

Download the installer and its exact companion `filename.sha256`. Each checksum file contains one record for that installer only. On Linux run `sha256sum -c filename.sha256`; on Windows compare `Get-FileHash filename -Algorithm SHA256` with that record.

## First installation, upgrades, and reinstallation

The combined installer creates a separate ASR key for the installing desktop account and imports it through Input's public provisioning command. It reuses the same active installation identity on subsequent runs. The administrator password is never an Input key.

- **First installation:** once Portal is running, interactive installation opens its local `/admin/setup` page if no administrator exists. Set a password, configure an upstream, then test dictation. No administrator password is supplied by the installer.
- **Upgrade:** configuration, existing administrator identity, client keys, and hotwords are retained. Existing initialized installations do not reopen first-time setup.
- **Uninstall while retaining configuration, then reinstall:** the retained configuration is reused. An installation whose initial password setup was never completed continues to setup.

Silent Windows installation (`/qn`, or `OPENASRINPUT_NO_LAUNCH=1`) and Linux `./install.sh --no-open` leave browser opening to the user. A Linux root invocation requires `--user ACCOUNT`. With no graphical session, open Portal manually, normally at `http://127.0.0.1:10087/admin`; the configured port is retained. Linux installation does not restart the desktop/input framework. Start and select the engine as described in the [user guide](user-guide.md).

## Persistent directories

| Platform | Input | Portal | Installer handoff |
| --- | --- | --- | --- |
| Windows | `%ProgramData%\OpenASR\Input\<SID>\input.json` | `%ProgramData%\OpenASR\Portal\service.json` and `data\` | `%ProgramData%\OpenASR\Installer\provisioning\<SID>\` |
| Linux | `/var/lib/openasr/input/<uid>/input.json` | `/var/lib/openasr/portal/service.env` and `data/` | `/var/lib/openasr/installer/<uid>/` |

SID/UID identifies the OS account, independent of its display name. Each user's Input files are private; Portal owns its service data. The common parent directory does not share keys or databases between products. Windows installation requests elevation to prepare the common data root.

Old default Input configurations in `%APPDATA%\OpenASRInput` or the XDG configuration directory are copied once, including card metadata. Running-session markers are not migrated. Portal migrates old default service configuration and data while the service is stopped. Legacy copies remain for recovery; verify the new installation before removing backups. Explicit `OPENASRINPUT_CONFIG` instances stay isolated, and Portal's custom data paths are retained.

Source-only runs without an installed data root retain APPDATA/XDG behavior. Connection and About always shows the actual Input configuration path. Back up the entire actual configuration directory; for Portal include both `portal.db` and `asr-key-vault.key`. Windows uninstall offers retention or explicit deletion; Linux `apt remove` retains data.

Windows maintenance and uninstall use the registered application directory, including custom installation paths. The choice to retain or delete configuration is separate from the application location.

## Chinese and English

Use **中文 / English** at the upper right of Input settings and Portal administration, including Portal's first-time setup page. The initial choice follows the browser/system language. Each product remembers its own selection in that browser; switching updates the page without reloading or losing unsaved fields. Titles, hotwords, credentials, recognized text, and calibration passages are data and retain their original content.
