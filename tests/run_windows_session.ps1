param(
    [Parameter(Mandatory = $true)][string]$PortalCheckout,
    [Parameter(Mandatory = $true)][string]$EditorDirectory,
    [Parameter(Mandatory = $true)][string]$Helper,
    [switch]$Microphone,
    [switch]$SessionOnly
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$portal = (Resolve-Path $PortalCheckout).Path
$editor = (Resolve-Path $EditorDirectory).Path
if ((Split-Path $editor -Leaf) -eq 'test-results' -or -not ($editor -split '[\\/]' -contains 'test-results')) {
    throw 'Use a disposable editor sandbox inside test-results.'
}
$identity = Get-Content (Join-Path $editor 'editor-identity.json') -Raw | ConvertFrom-Json
if ($identity.title -ne 'OpenASRInput Windows Test Editor') { throw 'Not a disposable test editor.' }
$report = Join-Path $root ('test-results/session-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $report | Out-Null
$names = @('PYTHONPATH', 'OPENASRINPUT_TEST_EDITOR_DIR', 'OPENASRINPUT_TEST_TARGET_PROCESS_ID',
    'OPENASRINPUT_WINDOWS_HELPER', 'OPENASRINPUT_TEST_MICROPHONE', 'OPENASRINPUT_TEST_PORTAL_URL')
$previous = @{}
foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$fixture = $null
try {
    $env:OPENASRINPUT_TEST_EDITOR_DIR = $editor
    $env:OPENASRINPUT_TEST_TARGET_PROCESS_ID = [string]$identity.processId
    $env:OPENASRINPUT_WINDOWS_HELPER = (Resolve-Path $Helper).Path
    if (-not (New-Object -ComObject WScript.Shell).AppActivate([int]$identity.processId)) {
        throw 'Cannot activate the disposable editor.'
    }
    $env:PYTHONPATH = Join-Path $root 'src'
    if (-not $SessionOnly) {
        & "$root/.venv/Scripts/python.exe" -m unittest discover -s "$root/tests" -p test_windows_live.py -v
        if ($LASTEXITCODE -ne 0) { throw 'Native editor regression failed.' }
    }
    if ($Microphone) {
        $env:PYTHONPATH = Join-Path $portal 'src'
        $fixture = Start-Process -FilePath "$portal/.venv/Scripts/python.exe" -ArgumentList '-u tests/serve_windows_session.py' -WorkingDirectory $portal -WindowStyle Hidden -PassThru -RedirectStandardOutput "$report/server.json" -RedirectStandardError "$report/server.err"
        $deadline = (Get-Date).AddSeconds(15)
        do {
            Start-Sleep -Milliseconds 100
            $ready = Get-Content "$report/server.json" -Raw
        } while (-not $ready -and (Get-Date) -lt $deadline -and -not $fixture.HasExited)
        if (-not $ready) { throw "Fixture failed; see $report/server.err" }
        $env:OPENASRINPUT_TEST_PORTAL_URL = ($ready | ConvertFrom-Json).url
        $env:OPENASRINPUT_TEST_MICROPHONE = '1'
        $env:PYTHONPATH = Join-Path $root 'src'
        (New-Object -ComObject WScript.Shell).AppActivate([int]$identity.processId) | Out-Null
        Start-Sleep -Milliseconds 500
        & "$root/.venv/Scripts/python.exe" -m unittest discover -s "$root/tests" -p test_windows_session.py -v
        if ($LASTEXITCODE -ne 0) { throw 'Microphone/session regression failed.' }
    }
}
finally {
    # Windows venv launchers own a Python child; reap this fixture tree only.
    if ($fixture -and -not $fixture.HasExited) { taskkill /PID $fixture.Id /T /F | Out-Null }
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
    Write-Output "Session fixture report: $report"
}
