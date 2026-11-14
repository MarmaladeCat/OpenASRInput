# Combined installation and persistent settings

**English** | [简体中文](installation.zh-CN.md)

This page describes Input 1.2.0 installation and the combined Input 1.2.0 + Portal 1.2.0 packages. Each component keeps its own product version.

## Choose your installation

- **Input + Portal:** one Windows x64 MSI, or one Linux amd64/ARM64 DEB containing both applications and private runtimes. These are intended for the [Input release downloads](https://github.com/MarmaladeCat/OpenASRInput/releases). On Windows leave Portal selected. On Linux open the DEB with a package manager, or run `sudo apt install ./OpenASRInput_1.2.0_linux_amd64_OpenASRPortal_1.2.0.deb` (use `arm64` for ARM64). Distribution dependencies may need network access.
- **Input alone:** use the standalone package if a Portal is already available. [Portal project](https://github.com/MarmaladeCat/OpenASRPortal), [downloads](https://github.com/MarmaladeCat/OpenASRPortal/releases), and [configuration guide](https://github.com/MarmaladeCat/OpenASRPortal/blob/main/docs/user-guide.md) explain deployment. Input does not recognize speech without a working local or remote Portal.

Download the installer and its exact companion `filename.sha256`. Each checksum file contains one record for that installer only. On Linux run `sha256sum -c filename.sha256`; on Windows compare `Get-FileHash filename -Algorithm SHA256` with that record.

## First installation, upgrades, and reinstallation

The combined installer creates a separate ASR key for the installing desktop account and imports it through Input's public provisioning command. It reuses the same active installation identity on subsequent runs. The administrator password is never an Input key.

- **First installation:** once Portal is running, Windows interactive installation or the Linux setup launcher opens its local `/admin/setup` page if no administrator exists. Set a password, configure an upstream, then test dictation. No administrator password is supplied by the installer.
- **Upgrade:** configuration, existing administrator identity, client keys, and hotwords are retained. Existing initialized installations do not reopen first-time setup.
- **Uninstall while retaining configuration, then reinstall:** the retained configuration is reused. An installation whose initial password setup was never completed continues to setup.

Silent Windows installation (`/qn`, or `OPENASRINPUT_NO_LAUNCH=1`) leaves browser opening to the user. Linux package installation does not open a browser: sudo installation connects the invoking account; after graphical/root installation, open **OpenASR Input + Portal Setup** from the application menu, or run `sudo openasrinput-portal-setup --user ACCOUNT --no-open`. On a headless system, open Portal manually, normally at `http://127.0.0.1:10087/admin`; the configured port is retained. Linux installation does not restart the desktop/input framework. Start and select the engine as described in the [user guide](user-guide.md).

APT owns both applications under `openasrinput-portal`. Installing it replaces the standalone `openasrinput` and `openasrportal` packages, including installations from the old archive, while retaining data. Use `sudo apt remove openasrinput-portal` to remove both applications; `purge` also retains product data. To return to standalone installation, install both standalone DEBs together with APT, replacing the combined package.

## Persistent directories

| Platform | Input | Portal | Installer handoff |
| --- | --- | --- | --- |
| Windows | `%ProgramData%\OpenASR\input\<SID>\input.json` | `%ProgramData%\OpenASR\portal\service.json` and `data\` | `%ProgramData%\OpenASR\installer\provisioning\<SID>\` |
| Linux | `/var/lib/OpenASR/input/<uid>/input.json` | `/var/lib/OpenASR/portal/service.env` and `data/` | `/var/lib/OpenASR/installer/<uid>/` |

SID/UID identifies the OS account, independent of its display name. Each user's Input files are private; Portal owns its service data. The common parent directory does not share keys or databases between products. Windows installation requests elevation to prepare the common data root.

Old default Input configurations in `%APPDATA%\OpenASRInput` or the XDG configuration directory are copied once, including card metadata. Running-session markers are not migrated. Portal migrates old default service configuration and data while the service is stopped. Legacy copies remain for recovery; verify the new installation before removing backups. Explicit `OPENASRINPUT_CONFIG` instances stay isolated, and Portal's custom data paths are retained.

Source, standalone and combined launches use these same defaults. Install once to prepare permissions; for isolated development set `OPENASRINPUT_CONFIG`, or `OPENASR_DATA_ROOT` for the product namespace. Linux also copies old `/var/lib/openasr/input/<uid>` configuration once; package activation state moves beside `input.json` under `package/`. OS-required service files and transient `/run/user` sockets remain at their OS integration paths. Connection and About shows the actual path. Back up the whole directory; Portal backups include `portal.db` and `asr-key-vault.key`.

Windows maintenance and uninstall use the registered application directory, including custom installation paths. The choice to retain or delete configuration is separate from the application location.

### Retiring old Input directories

After checking the actual configuration path in **Connection and About**, verifying your cards/settings in 1.2.0, and stopping old Input instances, these old defaults can be removed: Windows `%APPDATA%\OpenASRInput`; Linux `${XDG_CONFIG_HOME:-$HOME/.config}/openasrinput` and `/var/lib/openasr/input/<uid>`. They remain usable if explicitly selected by `OPENASRINPUT_CONFIG` or a registered custom installation path, so a legacy-looking name alone does not establish that a directory is unused.

For a genuinely fresh installation, archive any settings you need elsewhere, then remove the identified old defaults before the first new launch; otherwise one-time migration may restore them. Keep `/var/lib/OpenASR/input/<uid>` or `%ProgramData%\OpenASR\input\<SID>` for the current installation. Linux paths are case-sensitive. Package-managed files under `/usr`, `/etc`, and transient sockets under `/run/user` are integration files, not obsolete configuration backups.

## Optional Wanxiang package

The workspace can compose a full package with Wanxiang Pure 18.1.9 and its required LTS grammar, keeping the lightweight installers. Linux uses `..._Wanxiang.deb` with APT frontend dependencies; Windows uses `..._Wanxiang.zip` with `Install.cmd`, the combined MSI and official Weasel 0.17.4. Pure provides Lua-free full Pinyin. Existing Rime user directories are preserved. See the [full-package guide](https://github.com/MarmaladeCat/OpenASRSoftwares/blob/main/packaging/rime/README.md) for setup, builds and licenses.

Managed Rime data also stays under OpenASR: Windows `Rime\<SID>` and `Rime\Resources`; Linux `rime/<uid>/<framework>` and `rime/resources`. Standard Linux Rime directories are links. Pinyin remains local; speech requires a configured Portal upstream.

## Complete cleanup

Windows default uninstall retains settings. Clear **Keep configuration** in the product uninstaller to delete managed settings, keys, databases, caches and identified legacy defaults. The full kit has a separate Installed Apps entry with a default-off **Delete managed settings…** checkbox, covering its Rime data and the Weasel it installed too. Independent Rime and explicit external/source-run paths require separate cleanup.

Linux: stop Input, then `sudo apt remove openasrinput-portal` (or the standalone packages). Both remove and purge retain user data. Erase only your Input data with `sudo rm -rf -- "/var/lib/OpenASR/input/$(id -u)"`. The entire `/var/lib/OpenASR` also contains Notes, Drafts, LocalASR, Rime and installer data: deleting it erases every product's keys, databases and models for all accounts.

Before deleting managed Rime data, inspect its standard directory links and unlink only pointers into your `/var/lib/OpenASR/rime/<uid>/`. Legacy copies can remain under `/var/lib/openasr`, XDG Input directories, `/etc/openasrportal` and `/var/lib/openasrportal`; inspect them separately. Explicit custom paths and old Docker volumes remain separate.

## Chinese and English

Use the **中文 / English** dropdown at the upper right of Input settings and Portal administration, including Portal's first-time setup page. The initial choice follows the browser/system language. Each product remembers its own selection in that browser; switching updates the page without reloading or losing unsaved fields. Titles, hotwords, credentials, recognized text, and calibration passages are data and retain their original content.
