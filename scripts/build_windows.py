"""Build a per-user Windows 11 x64 MSI on Windows or a Linux Docker host."""

import argparse
import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
windows_replacement = runpy.run_path(str(ROOT / "scripts/windows_replacement.py"))
wheel_cache = runpy.run_path(str(ROOT / "scripts/wheel_cache.py"))
CACHE = ROOT / ".cache/windows"
BUILD = ROOT / ".cache/build/windows"
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(
    1
)
UPGRADE = uuid.UUID("d3a801cf-44d0-55e4-b813-f4f15fa12b7f")
IMAGE = "openasrinput-build:windows"


def download(url, path, sha512=None):
    if path.exists() and (
        not sha512 or hashlib.sha512(path.read_bytes()).hexdigest().lower() == sha512.lower()
    ):
        return
    print("Downloading " + url, flush=True)
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=90) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if sha512 and hashlib.sha512(temporary.read_bytes()).hexdigest().lower() != sha512.lower():
            raise RuntimeError("SDK checksum mismatch")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_sdk():
    record = CACHE / "dotnet-sdk.json"
    if record.exists():
        sdk = json.loads(record.read_text())
    else:
        with urllib.request.urlopen(
            "https://builds.dotnet.microsoft.com/dotnet/release-metadata/8.0/releases.json",
            timeout=30,
        ) as response:
            releases = json.load(response)
        version = releases["latest-sdk"]
        sdk = next(
            file
            for release in releases["releases"]
            for item in (release.get("sdks") or [release.get("sdk", {})])
            if item.get("version") == version
            for file in item["files"]
            if file["rid"] == "linux-x64"
        )
        record.write_text(json.dumps(sdk, indent=2) + "\n")
    download(sdk["url"], CACHE / "dotnet-sdk.tar.gz", sdk["hash"])


def docker(arguments, mounts=(), environment=None, capture=False):
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-e",
        "HOME=/tmp",
        "-e",
        "DOTNET_CLI_HOME=/tmp/dotnet-home",
        "-e",
        "NUGET_PACKAGES=/cache/nuget",
        "-v",
        f"{ROOT}:/source:ro",
        "-v",
        f"{BUILD}:/build",
        "-v",
        f"{CACHE}:/cache",
    ]
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        command += ["-e", variable]
    command += ["-e", "NO_PROXY=127.0.0.1,localhost"]
    for source, target in mounts:
        command += ["-v", f"{source}:{target}"]
    if capture:
        return subprocess.check_output([*command, IMAGE, *arguments], text=True, env=environment)
    subprocess.run([*command, IMAGE, *arguments], check=True, env=environment)


def cross_source(source):
    """Keep unsupported WiX actions as placeholders until their MSI rows are restored."""
    document = ET.parse(source)
    for action in document.findall(".//{http://schemas.microsoft.com/wix/2006/wi}CustomAction"):
        if "Error" in action.attrib or "Directory" in action.attrib:
            identifier = action.attrib["Id"]
            action.attrib.clear()
            action.attrib.update(Id=identifier, Property="CROSSBUILD_PLACEHOLDER", Value="unused")
    target = source.with_name("input-wixl.wxs")
    document.write(target, encoding="utf-8", xml_declaration=True)
    return target


def normalize_cross_msi(package, stage, source):
    """Make older wixl honor the WiX-authored upgrade and per-user lifecycle tables."""
    tables = {}
    for name in ("Upgrade", "Property", "CustomAction", "InstallExecuteSequence", "RemoveFile"):
        text = docker(
            ["msiinfo", "export", "/out/" + package.name, name],
            [(package.parent, "/out")],
            capture=True,
        )
        lines = text.splitlines()
        tables[name] = (lines[:3], [line.split("\t") for line in lines[3:] if line])
    for row in tables["Upgrade"][1]:
        if row[6] == "OLDVERSION":
            row[4] = "768"  # inclusive lower and upper bounds, not OnlyDetect
    ns = {"w": "http://schemas.microsoft.com/wix/2006/wi"}
    document = ET.parse(source)
    secure = {
        entry.attrib["Id"]
        for entry in document.findall(".//w:Property", ns)
        if entry.attrib.get("Secure") == "yes"
    }
    secure.update(entry.attrib["Property"] for entry in document.findall(".//w:UpgradeVersion", ns))
    for row in tables["Property"][1]:
        if row[0] == "SecureCustomProperties":
            row[1] = ";".join(sorted(secure))
            break
    else:
        tables["Property"][1].append(["SecureCustomProperties", ";".join(sorted(secure))])
    actions = tables["CustomAction"][1]
    authored = {
        entry.attrib["Id"]: entry.attrib for entry in document.findall(".//w:CustomAction", ns)
    }
    for row in actions:
        action = authored.get(row[0], {})
        if "Error" in action:
            row[1:4] = ["19", "", action["Error"]]
        elif "Directory" in action:
            kind = 34
            kind |= {"immediate": 0, "deferred": 1024, "rollback": 1280, "commit": 1536}[
                action.get("Execute", "immediate")
            ]
            kind |= 2048 if action.get("Impersonate") == "no" else 0
            kind |= {"check": 0, "ignore": 64, "asyncWait": 128, "asyncNoWait": 192}[
                action.get("Return", "check")
            ]
            row[1:4] = [str(kind), action["Directory"], action["ExeCommand"]]
    actions[:] = [row for row in actions if row[0] not in ("StopInput", "SetInstallLocation")]
    actions.extend(
        [
            ["StopInput", "2", "StopLauncher", '--shutdown "[INSTALLDIR]."', ""],
            ["SetInstallLocation", "51", "ARPINSTALLLOCATION", "[INSTALLDIR]", ""],
        ]
    )
    for row in tables["InstallExecuteSequence"][1]:
        if row[0] == "SetInstallLocation":
            row[2] = "1001"
        elif row[0] == "StopInput":
            row[2] = "1399"
    removals = {
        entry.attrib["Id"]: entry.attrib.get("Directory", "InputMenu")
        for entry in document.findall(".//w:RemoveFolder", ns)
    }
    for row in tables["RemoveFile"][1]:
        if row[0] in removals:
            row[3] = removals[row[0]]
    imports = []
    for name, (header, rows) in tables.items():
        filename = stage / (name + ".idt")
        filename.write_text(
            "\r\n".join([*header, *("\t".join(row) for row in rows)]) + "\r\n", encoding="utf-8"
        )
        imports += ["-i", "/stage/" + filename.name]
    docker(
        ["msibuild", "/out/" + package.name, *imports],
        [(package.parent, "/out"), (stage, "/stage")],
    )


def python_runtime(payload, version):
    if not version:
        with urllib.request.urlopen("https://www.python.org/ftp/python/", timeout=30) as response:
            versions = set(re.findall(r'href="(3\.13\.\d+)/"', response.read().decode()))
        for candidate in sorted(
            versions, key=lambda v: tuple(map(int, v.split("."))), reverse=True
        ):
            url = (
                f"https://www.python.org/ftp/python/{candidate}/python-{candidate}-embed-amd64.zip"
            )
            try:
                download(url, CACHE / f"python-{candidate}-embed-amd64.zip")
                version = candidate
                break
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
        if not version:
            raise RuntimeError("No supported Python 3.13 embedded runtime found")
    archive = CACHE / f"python-{version}-embed-amd64.zip"
    download(f"https://www.python.org/ftp/python/{version}/{archive.name}", archive)
    python = payload / "python"
    with zipfile.ZipFile(archive) as source:
        source.extractall(python)
    tag = "".join(version.split(".")[:2])
    (python / f"python{tag}._pth").write_text(
        f"python{tag}.zip\n.\nLib/site-packages\n../app\nimport site\n"
    )
    wheels = wheel_cache["wheelhouse"](
        CACHE / "wheels", ["aiohttp>=3.12,<4"], ".".join(version.split(".")[:2])
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(wheels),
            "--target",
            str(python / "Lib/site-packages"),
            "--platform",
            "win_amd64",
            "--python-version",
            ".".join(version.split(".")[:2]),
            "--only-binary=:all:",
            "--no-compile",
            "--ignore-installed",
            "--no-warn-conflicts",
            *map(str, sorted(wheels.glob("*.whl"))),
        ],
        check=True,
    )
    return {"version": version, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}


def wix(payload, filename):
    namespace = "http://schemas.microsoft.com/wix/2006/wi"
    ET.register_namespace("", namespace)

    def element(parent, tag, **attributes):
        return ET.SubElement(parent, "{" + namespace + "}" + tag, attributes)

    document = ET.Element("{" + namespace + "}Wix")
    product = element(
        document,
        "Product",
        Id=str(uuid.uuid4()),
        Name="OpenASRInput",
        Language="1033",
        Codepage="936",
        Version=VERSION,
        Manufacturer="OpenASRInput",
        UpgradeCode=str(UPGRADE),
    )
    element(
        product,
        "Package",
        InstallerVersion="500",
        Compressed="yes",
        InstallPrivileges="elevated",
    )
    element(product, "Property", Id="ARPNOMODIFY", Value="1")
    element(product, "Property", Id="ARPNOREPAIR", Value="1")
    # The visible Apps entry must use our data-choice/stop coordinator, not /x.
    element(product, "Property", Id="ARPSYSTEMCOMPONENT", Value="1")
    element(product, "Property", Id="OPENASRINPUT_NO_LAUNCH", Secure="yes")
    element(product, "Property", Id="OPENASR_PREVIOUS_INSTALLATION", Secure="yes")
    element(product, "Property", Id="REMOVEUSERDATA", Value="0", Secure="yes")
    element(product, "Property", Id="INPUTDATADIR", Secure="yes")
    previous_install = element(product, "Property", Id="INSTALLDIR", Secure="yes")
    element(
        previous_install,
        "RegistrySearch",
        Id="PreviousInputInstallDir",
        Root="HKCU",
        Key="Software\\OpenASRInput",
        Name="InstallDir",
        Type="raw",
        Win64="yes",
    )
    state = element(product, "Property", Id="LEGACYINPUTDATADIR", Secure="yes")
    element(
        state,
        "RegistrySearch",
        Id="PreviousInputData",
        Root="HKCU",
        Key="Software\\OpenASRInput",
        Name="StateDir",
        Type="raw",
        Win64="yes",
    )
    element(
        product,
        "CustomAction",
        Id="DefaultInputData",
        Property="INPUTDATADIR",
        Value="[CommonAppDataFolder]OpenASR\\Input\\[UserSID]",
    )
    (payload / "uninstall.ini").write_text(
        "OpenASRInput\n{" + product.attrib["Id"] + "}\n", encoding="utf-8"
    )
    branded = (payload / "app/openasrinput/presentation/branding/logo.ico").is_file()
    if branded:
        element(
            product,
            "Icon",
            Id="ProductLogo",
            SourceFile="payload/app/openasrinput/presentation/branding/logo.ico",
        )
        element(product, "Property", Id="ARPPRODUCTICON", Value="ProductLogo")
    element(
        product, "Condition", Message="OpenASRInput supports current-user installation only."
    ).text = "NOT ALLUSERS"
    element(product, "Media", Id="1", Cabinet="input.cab", EmbedCab="yes")
    upgrade = element(product, "Upgrade", Id=str(UPGRADE))
    element(
        upgrade,
        "UpgradeVersion",
        Minimum="0.0.0",
        IncludeMinimum="yes",
        Maximum=VERSION,
        IncludeMaximum="yes",
        Property="OLDVERSION",
    )
    element(
        upgrade,
        "UpgradeVersion",
        Minimum=VERSION,
        IncludeMinimum="no",
        OnlyDetect="yes",
        Property="NEWERVERSION",
    )
    element(
        product, "Condition", Message="A newer OpenASRInput version is already installed."
    ).text = "Installed OR NOT NEWERVERSION"
    sequence = element(product, "InstallExecuteSequence")
    windows_replacement["author"](element, product, sequence, "input", "payload/Replacement.CA.dll")
    element(
        product,
        "CustomAction",
        Id="RestoreInputData",
        Property="INPUTDATADIR",
        Value="[LEGACYINPUTDATADIR]",
    )
    element(
        sequence, "Custom", Action="RestoreInputData", After="CostFinalize"
    ).text = "NOT INPUTDATADIR AND LEGACYINPUTDATADIR AND REMOVE"
    element(
        sequence, "Custom", Action="DefaultInputData", After="RestoreInputData"
    ).text = "NOT INPUTDATADIR"
    element(
        product,
        "CustomAction",
        Id="DefaultLegacyInputData",
        Property="LEGACYINPUTDATADIR",
        Value="[AppDataFolder]OpenASRInput",
    )
    element(
        sequence, "Custom", Action="DefaultLegacyInputData", After="DefaultInputData"
    ).text = "NOT LEGACYINPUTDATADIR"
    element(
        product,
        "CustomAction",
        Id="SetInstallLocation",
        Property="ARPINSTALLLOCATION",
        Value="[INSTALLDIR]",
    )
    element(
        sequence, "Custom", Action="SetInstallLocation", After="CostFinalize"
    ).text = "NOT REMOVE"
    element(sequence, "RemoveExistingProducts", Sequence="1501").text = "OLDVERSION"
    target = element(product, "Directory", Id="TARGETDIR", Name="SourceDir")
    element(target, "Directory", Id="System64Folder")
    element(target, "Directory", Id="CommonAppDataFolder")
    local = element(target, "Directory", Id="LocalAppDataFolder")
    programs = element(local, "Directory", Id="AppPrograms", Name="Programs")
    install = element(programs, "Directory", Id="INSTALLDIR", Name="OpenASRInput")
    menu = element(
        element(target, "Directory", Id="ProgramMenuFolder"),
        "Directory",
        Id="InputMenu",
        Name="OpenASRInput",
    )
    element(target, "Directory", Id="DesktopFolder")
    feature = element(product, "Feature", Id="Complete", Title="OpenASRInput", Level="1")
    directories = {Path("."): install}
    launcher_id = ""
    for source in sorted(payload.rglob("*")):
        relative = source.relative_to(payload)
        ident = hashlib.sha1(relative.as_posix().encode()).hexdigest()[:24]
        if source.is_dir():
            directories[relative] = element(
                directories[relative.parent], "Directory", Id="D" + ident, Name=source.name
            )
            continue
        component_id, file_id = "C" + ident, "F" + ident
        component = element(
            directories[relative.parent],
            "Component",
            Id=component_id,
            Guid=str(uuid.uuid5(UPGRADE, relative.as_posix())),
            Win64="yes",
        )
        element(
            component,
            "File",
            Id=file_id,
            Name=source.name,
            Source="payload/" + relative.as_posix(),
        )
        element(
            component,
            "RegistryValue",
            Root="HKCU",
            Key="Software\\OpenASRInput\\Components",
            Name=component_id,
            Type="integer",
            Value="1",
            KeyPath="yes",
        )
        element(feature, "ComponentRef", Id=component_id)
        if relative.as_posix() == "OpenASRInput.exe":
            launcher_id = file_id
    shortcuts = element(
        menu, "Component", Id="Shortcuts", Guid=str(uuid.uuid5(UPGRADE, "shortcuts")), Win64="yes"
    )
    element(
        shortcuts,
        "Shortcut",
        Id="StartInput",
        Name="OpenASRInput",
        Target="[INSTALLDIR]OpenASRInput.exe",
        WorkingDirectory="INSTALLDIR",
    )
    element(
        shortcuts,
        "Shortcut",
        Id="Settings",
        Name="OpenASRInput Settings",
        Arguments="--settings",
        Target="[INSTALLDIR]OpenASRInput.exe",
        WorkingDirectory="INSTALLDIR",
    )
    element(
        shortcuts,
        "Shortcut",
        Id="DesktopInput",
        Directory="DesktopFolder",
        Name="OpenASRInput",
        Target="[INSTALLDIR]OpenASRInput.exe",
        WorkingDirectory="INSTALLDIR",
    )
    element(
        shortcuts,
        "RegistryValue",
        Root="HKCU",
        Key="Software\\OpenASRInput",
        Name="InstallDir",
        Type="string",
        Value="[INSTALLDIR]",
        KeyPath="yes",
    )
    element(
        shortcuts,
        "RegistryValue",
        Root="HKCU",
        Key="Software\\OpenASRInput",
        Name="StateDir",
        Type="string",
        Value="[INPUTDATADIR]",
    )
    element(
        shortcuts,
        "Shortcut",
        Id="UninstallInput",
        Name="Uninstall OpenASRInput",
        Target="[INSTALLDIR]Uninstall.exe",
        WorkingDirectory="INSTALLDIR",
    )
    for name, value, kind in (
        ("DisplayName", "OpenASRInput", "string"),
        ("DisplayVersion", VERSION, "string"),
        ("Publisher", "OpenASRInput", "string"),
        ("InstallLocation", "[INSTALLDIR]", "string"),
        ("DisplayIcon", "[INSTALLDIR]OpenASRInput.exe", "string"),
        ("UninstallString", '"[INSTALLDIR]Uninstall.exe"', "string"),
        ("QuietUninstallString", '"[INSTALLDIR]Uninstall.exe" --quiet', "string"),
        ("NoModify", "1", "integer"),
        ("NoRepair", "1", "integer"),
    ):
        element(
            shortcuts,
            "RegistryValue",
            Root="HKCU",
            Key="Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\OpenASRInput",
            Name=name,
            Type=kind,
            Value=value,
        )
    element(
        shortcuts,
        "RegistryValue",
        Root="HKCU",
        Key="Software\\Microsoft\\Windows\\CurrentVersion\\Run",
        Name="OpenASRInput",
        Type="string",
        Value='"[INSTALLDIR]OpenASRInput.exe" --background',
    )
    element(shortcuts, "RemoveFolder", Id="RemoveMenu", On="uninstall")
    element(
        shortcuts, "RemoveFolder", Id="RemoveAppPrograms", Directory="AppPrograms", On="uninstall"
    )
    for path, directory in directories.items():
        ident = hashlib.sha1(path.as_posix().encode()).hexdigest()[:24]
        element(
            shortcuts,
            "RemoveFolder",
            Id="Remove" + ident,
            Directory=directory.attrib["Id"],
            On="uninstall",
        )
    element(feature, "ComponentRef", Id="Shortcuts")
    if branded:
        for shortcut in shortcuts.findall("{" + namespace + "}Shortcut"):
            shortcut.set("Icon", "ProductLogo")
            shortcut.set("IconIndex", "0")
    # Embed the small native launcher so removal still works if installed
    # launcher/runtime files are missing. It only stops this install's bridge
    # and its private pythonw parent, before Windows Installer checks file locks.
    element(product, "Binary", Id="StopLauncher", SourceFile="payload/OpenASRInput.exe")
    element(
        product,
        "CustomAction",
        Id="StopInput",
        BinaryKey="StopLauncher",
        ExeCommand='--shutdown "[INSTALLDIR]."',
        Return="check",
        Impersonate="yes",
    )
    element(
        sequence, "Custom", Action="StopInput", Before="InstallValidate"
    ).text = 'Installed AND (REMOVE~="ALL" OR REINSTALL OR UPGRADINGPRODUCTCODE)'
    prepare = (
        '"[System64Folder]WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass '
        '-File "[INSTALLDIR]prepare_data.ps1" -DataDir "[INPUTDATADIR]" -UserSid "[UserSID]" '
        '-LegacyDataDir "[LEGACYINPUTDATADIR]" -PreviousInstallation "[Installed][OLDVERSION][OPENASR_PREVIOUS_INSTALLATION]"'
    )
    element(
        product,
        "CustomAction",
        Id="SetPrepareInputState",
        Property="PrepareInputState",
        Value=prepare,
    )
    element(
        product,
        "CustomAction",
        Id="PrepareInputState",
        BinaryKey="WixCA",
        DllEntry="WixQuietExec",
        Execute="deferred",
        Return="check",
        Impersonate="no",
    )
    element(
        sequence, "Custom", Action="SetPrepareInputState", After="InstallFiles"
    ).text = "NOT REMOVE"
    element(
        sequence, "Custom", Action="PrepareInputState", After="SetPrepareInputState"
    ).text = "NOT REMOVE"
    element(
        product,
        "CustomAction",
        Id="Launch",
        FileKey=launcher_id,
        ExeCommand="--settings",
        Return="asyncNoWait",
        Impersonate="yes",
    )
    element(
        sequence, "Custom", Action="Launch", After="InstallFinalize"
    ).text = "NOT Installed AND NOT REMOVE AND UILevel >= 5 AND NOT OPENASRINPUT_NO_LAUNCH"
    command = (
        '"[System64Folder]WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass '
        '-File "[INSTALLDIR]remove_data.ps1" -DataDir "[INPUTDATADIR]"'
    )
    element(
        product, "CustomAction", Id="SetRemoveInputData", Property="RemoveInputData", Value=command
    )
    element(
        product,
        "CustomAction",
        Id="RemoveInputData",
        Directory="System64Folder",
        ExeCommand=command,
        Execute="deferred",
        Return="check",
        Impersonate="yes",
    )
    condition = 'REMOVE~="ALL" AND NOT UPGRADINGPRODUCTCODE AND REMOVEUSERDATA="1"'
    element(sequence, "Custom", Action="SetRemoveInputData", After="StopServices").text = condition
    element(
        sequence, "Custom", Action="RemoveInputData", After="SetRemoveInputData"
    ).text = condition
    ET.ElementTree(document).write(filename, encoding="utf-8", xml_declaration=True)


def native_windows_tools(args):
    dotnet = args.dotnet or shutil.which("dotnet")
    wix_bin = args.wix_bin or (Path(os.environ["WIX"]) / "bin" if os.environ.get("WIX") else None)
    candle = str(wix_bin / "candle.exe") if wix_bin else shutil.which("candle")
    light = str(wix_bin / "light.exe") if wix_bin else shutil.which("light")
    if not all(value and Path(value).is_file() for value in (dotnet, candle, light)):
        raise RuntimeError(
            "Windows build requires .NET 8 SDK and WiX 3.14.1; use --dotnet and --wix-bin"
        )
    if os.environ.get("LLVM_MINGW_ROOT"):
        tools = Path(os.environ["LLVM_MINGW_ROOT"]) / "bin"
        compiler = tools / "x86_64-w64-mingw32-clang.exe"
        resource = tools / "x86_64-w64-mingw32-windres.exe"
        if not compiler.is_file() or not resource.is_file():
            raise RuntimeError("LLVM_MINGW_ROOT must contain native Windows clang and windres")
        environment = os.environ.copy()
        environment["PATH"] = str(tools) + os.pathsep + environment["PATH"]
        return str(dotnet), candle, light, compiler, environment
    program_files = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    vswhere = program_files / "Microsoft Visual Studio/Installer/vswhere.exe"
    studio = Path(
        subprocess.check_output(
            [
                str(vswhere),
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ],
            text=True,
        ).strip()
    )
    toolsets = sorted((studio / "VC/Tools/MSVC").glob("*"))
    sdk = program_files / "Windows Kits/10"
    versions = sorted(
        path.name for path in (sdk / "Include").glob("*") if (path / "um/windows.h").is_file()
    )
    if not toolsets or not versions:
        raise RuntimeError(
            "Windows build requires Visual Studio C++ Build Tools and Windows 10/11 SDK"
        )
    compiler = toolsets[-1]
    version = versions[-1]
    environment = os.environ.copy()
    environment["PATH"] = str(compiler / "bin/Hostx64/x64") + os.pathsep + environment["PATH"]
    environment["INCLUDE"] = os.pathsep.join(
        map(
            str,
            [
                compiler / "include",
                *[sdk / "Include" / version / part for part in ("ucrt", "shared", "um")],
            ],
        )
    )
    environment["LIB"] = os.pathsep.join(
        map(
            str,
            [
                compiler / "lib/x64",
                *[sdk / "Lib" / version / part / "x64" for part in ("ucrt", "um")],
            ],
        )
    )
    return str(dotnet), candle, light, compiler / "bin/Hostx64/x64/cl.exe", environment


def build_native_windows(dotnet):
    subprocess.run(
        [
            dotnet,
            "run",
            "--project",
            str(ROOT / "tests/windows/NativeRules.csproj"),
            "-c",
            "Release",
        ],
        check=True,
    )
    subprocess.run(
        [
            dotnet,
            "build",
            str(ROOT / "src/native/windows/OpenASRInputBridge.csproj"),
            "--no-incremental",
            "-c",
            "Release",
            "-r",
            "win-x64",
            "--self-contained",
            "true",
            "-p:DebugType=None",
            "-p:DebugSymbols=false",
        ],
        check=True,
    )
    # Source synchronization/VM clock changes must not package an old bridge
    # with a new source receipt. Publish only the explicitly rebuilt assembly.
    if (BUILD / "native").exists():
        shutil.rmtree(BUILD / "native")
    subprocess.run(
        [
            dotnet,
            "publish",
            "--no-build",
            str(ROOT / "src/native/windows/OpenASRInputBridge.csproj"),
            "-c",
            "Release",
            "-r",
            "win-x64",
            "--self-contained",
            "true",
            "-p:DebugType=None",
            "-p:DebugSymbols=false",
            "-o",
            str(BUILD / "native"),
        ],
        check=True,
    )


def launcher_resources(payload, stage, windows_tools):
    icon = payload / "app/openasrinput/presentation/branding/logo.ico"
    if not icon.is_file():
        return []
    resource = stage / "logo.rc"
    if windows_tools:
        resource.write_text('1 ICON "' + icon.as_posix() + '"\n', encoding="utf-8")
        compiler = windows_tools[3]
        if compiler.name == "x86_64-w64-mingw32-clang.exe":
            result = stage / "logo.o"
            subprocess.run(
                [
                    str(compiler.with_name("x86_64-w64-mingw32-windres.exe")),
                    str(resource),
                    "-O",
                    "coff",
                    "-o",
                    str(result),
                ],
                env=windows_tools[4],
                check=True,
            )
            return [str(result)]
        sdk = (
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
            / "Windows Kits/10/bin"
        )
        compilers = sorted(sdk.glob("*/x64/rc.exe"))
        if not compilers:
            raise RuntimeError("Windows SDK resource compiler is required for logo.ico")
        result = stage / "logo.res"
        subprocess.run(
            [str(compilers[-1]), "/nologo", "/fo", str(result), str(resource)], check=True
        )
        return [str(result)]
    resource.write_text('1 ICON "/payload/app/openasrinput/presentation/branding/logo.ico"\n')
    docker(
        ["x86_64-w64-mingw32-windres", "/stage/logo.rc", "-O", "coff", "-o", "/stage/logo.o"],
        [(payload, "/payload"), (stage, "/stage")],
    )
    return ["/stage/logo.o"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-image-build", action="store_true")
    parser.add_argument("--python-version")
    parser.add_argument("--dotnet", help="Windows .NET 8 SDK executable")
    parser.add_argument("--wix-bin", type=Path, help="Windows WiX 3.14.1 binaries directory")
    parser.add_argument(
        "--replacement-tools",
        type=Path,
        help="Matching native Windows replacement-tool cache for Linux cross-builds",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".cache/build/artifacts/windows/amd64/native"
    )
    args = parser.parse_args()
    if os.name != "nt":
        windows_replacement["validate"](ROOT, args.replacement_tools or CACHE / "replacement")
    CACHE.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    windows_tools = native_windows_tools(args) if os.name == "nt" else None
    if not windows_tools and not args.skip_image_build:
        prepare_sdk()
        command = [
            "docker",
            "build",
            "--network=host",
            "-f",
            "packaging/docker/Dockerfile.windows-build",
            "-t",
            IMAGE,
        ]
        for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            command += ["--build-arg", variable]
        subprocess.run([*command, "."], cwd=ROOT, check=True)
    if windows_tools:
        build_native_windows(windows_tools[0])
    else:
        build_docker_native()
    with tempfile.TemporaryDirectory(prefix="msi-", dir=BUILD) as temporary:
        stage = Path(temporary)
        payload = stage / "payload"
        shutil.copytree(
            BUILD / "native", payload / "native", ignore=shutil.ignore_patterns("*.pdb")
        )
        shutil.copytree(
            ROOT / "src/openasrinput",
            payload / "app/openasrinput",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copy2(ROOT / "packaging/windows/launch.py", payload / "app/launch.py")
        shutil.copy2(ROOT / "LICENSE", payload / "LICENSE.txt")
        shutil.copy2(ROOT / "packaging/windows/remove_data.ps1", payload / "remove_data.ps1")
        shutil.copy2(ROOT / "packaging/windows/prepare_data.ps1", payload / "prepare_data.ps1")
        csc = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        )
        if windows_tools:
            windows_replacement["build"](ROOT, payload, Path(windows_tools[1]).parent)
            subprocess.run(
                [
                    str(csc),
                    "/nologo",
                    "/target:winexe",
                    "/codepage:65001",
                    "/reference:System.Windows.Forms.dll",
                    "/reference:System.Core.dll",
                    "/reference:System.ServiceProcess.dll",
                    "/out:" + str(payload / "Uninstall.exe"),
                    str(ROOT / "packaging/windows/Uninstall.cs"),
                ],
                check=True,
            )
        else:
            windows_replacement["restore"](
                ROOT, payload, args.replacement_tools or CACHE / "replacement"
            )
            docker(
                [
                    "mcs",
                    "-target:winexe",
                    "-r:System.Windows.Forms",
                    "-r:System.Core",
                    "-r:System.ServiceProcess",
                    "-out:/payload/Uninstall.exe",
                    "/source/packaging/windows/Uninstall.cs",
                ],
                [(payload, "/payload")],
            )
        runtime = python_runtime(payload, args.python_version)
        source = stage / "input.wxs"
        package = output / f"OpenASRInput_{VERSION}_win-x64.msi"
        resources = launcher_resources(payload, stage, windows_tools)
        if windows_tools:
            _, candle, light, compiler, environment = windows_tools
            command = (
                [
                    str(compiler),
                    "-O2",
                    "-std=c11",
                    "-municode",
                    "-mwindows",
                    "-static",
                    str(ROOT / "packaging/windows/launcher.c"),
                    *resources,
                    "-luser32",
                    "-lshell32",
                    "-o",
                    str(payload / "OpenASRInput.exe"),
                ]
                if compiler.name == "x86_64-w64-mingw32-clang.exe"
                else [
                    str(compiler),
                    "/nologo",
                    "/O2",
                    "/MT",
                    "/utf-8",
                    "/std:c11",
                    str(ROOT / "packaging/windows/launcher.c"),
                    *resources,
                    "/Fe:" + str(payload / "OpenASRInput.exe"),
                    "/Fo:" + str(stage / "launcher.obj"),
                    "/link",
                    "/SUBSYSTEM:WINDOWS",
                    "/MACHINE:X64",
                    "user32.lib",
                    "shell32.lib",
                ]
            )
            subprocess.run(
                command,
                cwd=stage,
                env=environment,
                check=True,
            )
            wix(payload, source)
            subprocess.run(
                [
                    candle,
                    "-nologo",
                    "-arch",
                    "x64",
                    "-ext",
                    str(Path(candle).parent / "WixUtilExtension.dll"),
                    "-out",
                    str(stage / "input.wixobj"),
                    str(source),
                ],
                cwd=stage,
                check=True,
            )
            subprocess.run(
                # ICE91 describes per-machine behavior, explicitly rejected by
                # our launch condition. ICE61 warns about intentionally replacing
                # same-version rebuilds; keep all other MSI validation enabled.
                [
                    light,
                    "-nologo",
                    "-sice:ICE91",
                    "-sice:ICE61",
                    "-ext",
                    str(Path(candle).parent / "WixUtilExtension.dll"),
                    "-out",
                    str(package),
                    str(stage / "input.wixobj"),
                ],
                cwd=stage,
                check=True,
            )
        else:
            docker(
                [
                    "x86_64-w64-mingw32-gcc",
                    "-O2",
                    "-municode",
                    "-mwindows",
                    "-static",
                    "/source/packaging/windows/launcher.c",
                    *resources,
                    "-lshell32",
                    "-o",
                    "/payload/OpenASRInput.exe",
                ],
                [(payload, "/payload"), (stage, "/stage")],
            )
            wix(payload, source)
            compatible = cross_source(source)
            docker(
                [
                    "wixl",
                    "-a",
                    "x64",
                    "-I",
                    "/stage",
                    "-o",
                    "/out/" + package.name,
                    "/stage/" + compatible.name,
                ],
                [(payload, "/payload"), (stage, "/stage"), (output, "/out")],
            )
            normalize_cross_msi(package, stage, source)
        record = {
            "platform": "win-x64",
            "version": VERSION,
            "python": runtime,
            "file": package.name,
            "bytes": package.stat().st_size,
            "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        }
        symbols = package.with_suffix(".wixpdb")
        if symbols.exists():
            symbols.replace(BUILD / symbols.name)
        (output / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
        print(package)


def build_docker_native():
    docker(
        [
            "dotnet",
            "build",
            "/source/tests/windows/NativeRules.csproj",
            "-c",
            "Release",
            "-p:BaseIntermediateOutputPath=/build/rules-obj/",
            "-p:OutputPath=/build/rules-bin/",
            "-p:CopyRetryCount=0",
        ]
    )
    docker(["dotnet", "/build/rules-bin/NativeRules.dll"])
    docker(
        [
            "dotnet",
            "publish",
            "/source/src/native/windows/OpenASRInputBridge.csproj",
            "-c",
            "Release",
            "-r",
            "win-x64",
            "--self-contained",
            "true",
            "-p:BaseIntermediateOutputPath=/build/obj/",
            "-p:OutputPath=/build/bin/",
            "-p:CopyRetryCount=0",
            "-p:DebugType=None",
            "-p:DebugSymbols=false",
            "-o",
            "/build/native",
        ]
    )


if __name__ == "__main__":
    main()
