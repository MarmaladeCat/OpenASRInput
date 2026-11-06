<# Product-owned configuration provisioning; called by standalone and combined MSI. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$DataDir,
      [Parameter(Mandatory=$true)][string]$UserSid,
      [string]$LegacyDataDir,
      [string]$PreviousInstallation)
$ErrorActionPreference = 'Stop'
$identity = New-Object Security.Principal.SecurityIdentifier($UserSid)
$DataDir = [IO.Path]::GetFullPath($DataDir)
foreach ($path in @($DataDir, $LegacyDataDir)) {
    if ($path -and (Test-Path -LiteralPath $path)) {
        $item = Get-Item -LiteralPath $path
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            (Get-ChildItem -LiteralPath $path -Recurse -Force -Attributes ReparsePoint)) {
            throw 'Input configuration cannot contain reparse points.'
        }
    }
}
$root = Join-Path $env:ProgramData 'OpenASR'
$users = Join-Path $root 'Input'
foreach ($path in @($root, $users)) {
    if ((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Input configuration parent cannot be a reparse point.'
    }
}
foreach ($path in @($root, $users)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetSecurityDescriptorSddlForm('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;0x1200a9;;;BU)')
    if ($path -eq $users) {
        # Other users can create their SID directory; only its creator owns it.
        $acl.SetSecurityDescriptorSddlForm('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;0x1200ad;;;BU)(A;OICIIO;FA;;;CO)')
    }
    Set-Acl -LiteralPath $path -AclObject $acl
}
$retained = Test-Path -LiteralPath (Join-Path $DataDir 'input.json')
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetSecurityDescriptorSddlForm('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;' + $identity.Value + ')')
Set-Acl -LiteralPath $DataDir -AclObject $acl
if (-not $retained -and $LegacyDataDir -and (Test-Path -LiteralPath (Join-Path $LegacyDataDir 'input.json'))) {
    Get-ChildItem -LiteralPath $LegacyDataDir -Filter 'input*.json' -File |
        Where-Object { $_.Name -notlike '*.runtime.json' -and $_.Name -ne 'input.json' } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $DataDir $_.Name) -Force }
    Copy-Item -LiteralPath (Join-Path $LegacyDataDir 'input.json') -Destination (Join-Path $DataDir 'input.json.migrating') -Force
    Move-Item -LiteralPath (Join-Path $DataDir 'input.json.migrating') -Destination (Join-Path $DataDir 'input.json') -Force
    $retained = $true
}
$operation = if ($PreviousInstallation) { 'upgrade' } elseif ($retained) { 'reinstall' } else { 'first-install' }
@{ schemaVersion = 1; operation = $operation } | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $DataDir 'installation.json') -Encoding UTF8
& icacls.exe "$DataDir\*" /reset /T /Q | Out-Null
if ($LASTEXITCODE) { throw 'Could not protect Input configuration.' }
