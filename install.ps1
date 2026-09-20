param([string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }))
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\windows\installation.ps1"

$CodexHome = [IO.Path]::GetFullPath($CodexHome)
Get-Command codex.exe -ErrorAction Stop | Out-Null
Get-Command wt.exe -ErrorAction Stop | Out-Null
if (-not ((& dotnet --list-sdks) -match '^9\.')) { throw 'Windows .NET 9 SDK is required.' }
$root = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CodexWinNotify'
$lock = Enter-InstallLock $root
try {
    $clients = Join-Path $root 'clients'
    $manifest = Join-Path $clients 'windows.json'
    if (Test-Path -LiteralPath $manifest) {
        $previous = Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json
        if ($previous.home -ne $CodexHome) { throw 'Uninstall the existing Windows client before changing CODEX_HOME.' }
    }
    $stage = Join-Path $root 'build-windows'
    & dotnet publish "$PSScriptRoot\windows\CodexWinNotify.csproj" -c Release -r win-x64 --self-contained false -o $stage --nologo
    if ($LASTEXITCODE -ne 0) { throw 'Publish failed; configuration was not changed.' }
    Invoke-Helper (Join-Path $stage 'CodexWinNotify.exe') @('--configure', 'check', $CodexHome)
    $app = Join-Path $root 'app'
    $helper = Join-Path $app 'CodexWinNotify.exe'
    Stop-InstalledHelper $helper
    New-Item -ItemType Directory -Force -Path $app, $clients | Out-Null
    Copy-Item -Path "$stage\*" -Destination $app -Recurse -Force
    # Keep a lease even if configuring fails, so another client cannot remove
    # files needed for a repair/retry of this installation.
    @{ home = $CodexHome; helper = $helper } | ConvertTo-Json | Set-Content -LiteralPath $manifest -Encoding UTF8
    Invoke-Helper $helper @('--configure', 'install', $CodexHome)
    Write-Host 'Installed. Close Codex and run codex again. Native desktop acceptance is documented in docs/technical.md.'
} finally { $lock.Dispose() }
