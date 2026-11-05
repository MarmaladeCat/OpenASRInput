[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$DataDir, [switch]$AllUsers)
$ErrorActionPreference='Stop'
$DataDir=[IO.Path]::GetFullPath($DataDir).TrimEnd('\')
function Remove-OwnedDirectory([string]$Path) {
    $full=[IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ([IO.Path]::GetFileName($full) -notmatch '^OpenASRInput(?:-MsiTest-[a-f0-9]+)?$') { throw 'Refusing unrecognized Input data directory.' }
    if (-not (Test-Path -LiteralPath $full)) { return }
    $item=Get-Item -LiteralPath $full -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        (Get-ChildItem -LiteralPath $full -Recurse -Force -Attributes ReparsePoint)) {throw 'Refusing Input data deletion through reparse points.'}
    Remove-Item -LiteralPath $full -Recurse -Force
}
$targets=@($DataDir)
if ($AllUsers -and [IO.Path]::GetFileName($DataDir) -notlike 'OpenASRInput-MsiTest-*') {
    $targets += @(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\*' |
        Where-Object {$_.ProfileImagePath} | ForEach-Object {Join-Path ([Environment]::ExpandEnvironmentVariables($_.ProfileImagePath)) 'AppData\Roaming\OpenASRInput'})
}
foreach($target in ($targets | Select-Object -Unique)) {Remove-OwnedDirectory $target}
