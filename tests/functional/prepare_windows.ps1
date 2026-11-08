$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$tools = Join-Path $root '.cache/functional/windows'
$env:DOTNET_ROOT = Join-Path $tools 'dotnet'
$env:DOTNET_CLI_HOME = Join-Path $tools 'home'
$env:NUGET_PACKAGES = Join-Path $tools 'nuget'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
New-Item -ItemType Directory -Force $env:DOTNET_ROOT | Out-Null
if (-not (Test-Path "$env:DOTNET_ROOT/dotnet.exe")) {
    $download = Join-Path $tools 'dotnet.zip'
    $options = @{ Uri = 'https://builds.dotnet.microsoft.com/dotnet/Sdk/8.0.413/dotnet-sdk-8.0.413-win-x64.zip'; OutFile = $download; UseBasicParsing = $true }
    if ($env:HTTPS_PROXY) { $options.Proxy = $env:HTTPS_PROXY }
    if (-not (Test-Path $download)) { Invoke-WebRequest @options }
    if ((Get-FileHash $download -Algorithm SHA512).Hash -ne 'a2fac0881d963c05b9844e5133d71b3008a58b2ca251befbc617dd1666ff74d9496327f87037319f49f49e89c113038020027f158bfc71105d4300e1bf446b35') {
        throw 'Invalid .NET SDK checksum'
    }
    Expand-Archive $download $env:DOTNET_ROOT -Force
    Remove-Item $download
}
Push-Location $root
try {
    # A VM clock can move backwards. Never accept a cached assembly just because
    # its timestamp is newer than the freshly synchronized source snapshot.
    foreach ($item in @(
        @('src/native/windows/OpenASRInputBridge.csproj', 'bridge'),
        @('tests/windows_editor/WindowsTestEditor.csproj', 'editor')
    )) {
        & "$env:DOTNET_ROOT/dotnet.exe" build $item[0] --no-incremental -c Release -r win-x64 --self-contained false
        if ($LASTEXITCODE -ne 0) { throw "Current-source build failed: $($item[0])" }
        $output = Join-Path $tools $item[1]
        # Publish also uses PreserveNewest: a rebuilt assembly with an older
        # VM timestamp must not leave yesterday's published DLL in this folder.
        if (Test-Path $output) { Remove-Item $output -Recurse -Force }
        & "$env:DOTNET_ROOT/dotnet.exe" publish $item[0] --no-build -c Release -r win-x64 --self-contained false -o $output
        if ($LASTEXITCODE -ne 0) { throw "Publish failed: $($item[0])" }
    }
} finally {
    Pop-Location
}
