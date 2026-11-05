"""Build the product-owned installer replacement coordinator with WiX DTF."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def build(root, payload, wix_bin):
    csc = (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    )
    sdk = Path(wix_bin) / "sdk"
    source = root / "packaging/windows/Replacement.cs"
    assembly = payload / "Replacement.Actions.dll"
    config = payload / "CustomAction.config"
    config.write_text(
        '<configuration><startup useLegacyV2RuntimeActivationPolicy="true"><supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.0"/></startup></configuration>',
        encoding="utf-8",
    )
    refs = [
        "/reference:System.Windows.Forms.dll",
        "/reference:System.Core.dll",
        "/reference:System.Xml.dll",
    ]
    subprocess.run(
        [
            str(csc),
            "/nologo",
            "/codepage:65001",
            "/target:winexe",
            *refs,
            "/out:" + str(payload / "Replacement.exe"),
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        [
            str(csc),
            "/nologo",
            "/codepage:65001",
            "/target:library",
            "/define:CUSTOM_ACTION",
            *refs,
            "/reference:" + str(sdk / "Microsoft.Deployment.WindowsInstaller.dll"),
            "/out:" + str(assembly),
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        [
            str(sdk / "MakeSfxCA.exe"),
            str(payload / "Replacement.CA.dll"),
            str(sdk / "x64/sfxca.dll"),
            str(assembly),
            str(config),
            str(payload / "Replacement.exe"),
            str(sdk / "Microsoft.Deployment.WindowsInstaller.dll"),
        ],
        check=True,
    )
    assembly.unlink()
    config.unlink()
    cache = root / ".cache/windows/replacement"
    cache.mkdir(parents=True, exist_ok=True)
    files = ("Replacement.exe", "Replacement.CA.dll")
    for name in files:
        shutil.copy2(payload / name, cache / name)
    (cache / "manifest.json").write_text(
        json.dumps(
            {
                "sourceDigest": hashlib.sha256(source.read_bytes()).hexdigest(),
                "files": {
                    name: hashlib.sha256((cache / name).read_bytes()).hexdigest() for name in files
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def validate(root, directory):
    if not (directory / "manifest.json").is_file():
        raise RuntimeError(
            "Replacement tools require a native Windows build first; transfer its .cache/windows/replacement and pass --replacement-tools <directory> for Linux cross-builds"
        )
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest["sourceDigest"]
        != hashlib.sha256((root / "packaging/windows/Replacement.cs").read_bytes()).hexdigest()
    ):
        raise RuntimeError("Rebuild replacement tools: coordinator sources changed")
    for name in ("Replacement.exe", "Replacement.CA.dll"):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != manifest["files"][name]:
            raise RuntimeError("Replacement tools checksum mismatch: " + name)


def restore(root, payload, directory):
    validate(root, directory)
    for name in ("Replacement.exe", "Replacement.CA.dll"):
        shutil.copy2(directory / name, payload / name)


def author(
    element, product, sequence, kind, source, families=None, registry_prefix="Software\\OpenASR"
):
    element(product, "Property", Id="OPENASR_INSTALLER_KIND", Value=kind)
    element(product, "Binary", Id="ReplacementCA", SourceFile=source)
    element(
        product,
        "CustomAction",
        Id="ConfirmReplacement",
        BinaryKey="ReplacementCA",
        DllEntry="ConfirmReplacement",
        Return="check",
    )
    families = families or {
        "INPUT": "d3a801cf-44d0-55e4-b813-f4f15fa12b7f",
        "PORTAL": "64e55bb5-b8eb-40fa-bc40-089420d7c0a0",
        "BUNDLE": "638d1b81-3c59-49e1-9e8d-d0a68157c230",
    }
    namespace = "http://schemas.microsoft.com/wix/2006/wi"
    for family, upgrade_code in families.items():
        upgrade = next(
            (
                node
                for node in product.findall("{" + namespace + "}Upgrade")
                if node.get("Id", "").strip("{}").lower() == upgrade_code.strip("{}").lower()
            ),
            None,
        )
        if upgrade is None:
            upgrade = element(product, "Upgrade", Id=upgrade_code)
        element(
            upgrade,
            "UpgradeVersion",
            Minimum="0.0.0",
            IncludeMinimum="yes",
            OnlyDetect="yes",
            Property="REPLACE_" + family + "_PRODUCT",
        )
        property_node = element(product, "Property", Id="REPLACE_" + family + "_REG")
        suffix = {"INPUT": "Input", "PORTAL": "Portal", "BUNDLE": "InputPortal"}[family]
        element(
            property_node,
            "RegistrySearch",
            Id="Replacement" + family + "Registry",
            Root="HKCU" if family == "INPUT" else "HKLM",
            Key=registry_prefix + suffix,
            Name="InstallDir",
            Type="raw",
            Win64="yes",
        )
    prop = element(product, "Property", Id="REPLACE_PORTAL_SERVICE")
    element(
        prop,
        "RegistrySearch",
        Id="ReplacementPortalService",
        Root="HKLM",
        Key="SYSTEM\\CurrentControlSet\\Services\\" + registry_prefix.split("\\")[-1] + "Portal",
        Name="ImagePath",
        Type="raw",
        Win64="yes",
    )
    detected = {
        name: "(REPLACE_" + name + "_PRODUCT OR REPLACE_" + name + "_REG)" for name in families
    }
    conflicts = {
        "input": detected["INPUT"] + " OR " + detected["BUNDLE"],
        "portal": detected["PORTAL"]
        + " OR ("
        + detected["BUNDLE"]
        + " AND REPLACE_PORTAL_SERVICE)",
        "bundle": detected["INPUT"]
        + " OR "
        + detected["BUNDLE"]
        + " OR (&Portal=3 AND "
        + detected["PORTAL"]
        + ")",
    }[kind]
    element(
        product,
        "CustomAction",
        Id="GuardReplacement",
        Error="检测到已有软件。请完整打开安装向导，选择替换升级或停止安装；静默安装不会自动卸载旧程序。",
    )
    ui = element(product, "InstallUISequence")
    condition = "NOT REMOVE AND NOT UPGRADINGPRODUCTCODE"
    element(ui, "Custom", Action="ConfirmReplacement", Before="ExecuteAction").text = condition
    element(sequence, "Custom", Action="GuardReplacement", Before="InstallInitialize").text = (
        condition + " AND (Installed OR " + conflicts + ")"
    )
