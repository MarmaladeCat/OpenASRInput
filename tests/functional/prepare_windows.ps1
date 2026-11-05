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
    & "$env:DOTNET_ROOT/dotnet.exe" publish src/native/windows/OpenASRInputBridge.csproj -c Release -r win-x64 --self-contained false -o "$tools/bridge"
    if ($LASTEXITCODE -ne 0) { throw 'Bridge publish failed' }
    & "$env:DOTNET_ROOT/dotnet.exe" publish tests/windows_editor/WindowsTestEditor.csproj -c Release -r win-x64 --self-contained false -o "$tools/editor"
    if ($LASTEXITCODE -ne 0) { throw 'Test editor publish failed' }
} finally {
    Pop-Location
}
