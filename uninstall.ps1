param([string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }))
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\windows\installation.ps1"
. "$PSScriptRoot\windows\plugin.ps1"
$CodexHome = [IO.Path]::GetFullPath($CodexHome)
$root = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CodexWinNotify'
$lock = Enter-InstallLock $root
try {
    $manifest = Join-Path $root 'clients\windows.json'
    if (-not (Test-Path -LiteralPath $manifest)) { Write-Host 'No Windows client installed.'; return }
    $client = Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json
    if ($client.home -ne $CodexHome) { throw 'CODEX_HOME does not match the installed Windows client.' }
    $helper = Join-Path $root 'app\CodexWinNotify.exe'
    if ($client.PSObject.Properties['plugin_id']) { Remove-PersonalPlugin $client $CodexHome }
    Invoke-Helper $helper @('--configure', 'uninstall', $CodexHome)
    Remove-Item -LiteralPath $manifest
    if (Get-ChildItem -LiteralPath (Join-Path $root 'clients') -Filter '*.json') {
        Write-Host 'Windows hooks removed. Shared helper retained for other clients.'
        return
    }
    # Old WSL installs have no lease. Preserve a pre-existing build directory
    # until WSL has been upgraded to the client-aware installer.
    if (Test-Path -LiteralPath (Join-Path $root 'build')) {
        Write-Host 'Windows hooks removed. Possible legacy WSL installation retained; update/uninstall it from WSL.'
        return
    }
    Stop-InstalledHelper $helper
    Invoke-Helper $helper @('--uninstall')
    Remove-InstallData $root
    Write-Host 'Uninstalled. Existing Codex configuration and source files retained.'
} finally { $lock.Dispose() }
