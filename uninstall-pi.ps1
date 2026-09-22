# Remove the extension with `pi remove <package path>` and restart Pi first.
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\windows\installation.ps1"
$root = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CliNotify'
$lock = Enter-InstallLock $root
try {
    $manifest = Join-Path $root 'clients\pi-windows.json'
    if (-not (Test-Path -LiteralPath $manifest)) { Write-Host 'No Pi helper client installed.'; return }
    Remove-Item -LiteralPath $manifest
    if ((Get-ChildItem -LiteralPath (Join-Path $root 'clients') -Filter '*.json') -or
        (Test-Path -LiteralPath (Join-Path $root 'build'))) {
        Write-Host 'Pi lease removed. Shared helper retained for Codex/WSL clients.'
        return
    }
    $helper = Join-Path $root 'app\CliNotify.exe'
    Stop-InstalledHelper $helper
    Invoke-Helper $helper @('--uninstall')
    Remove-InstallData $root
    Write-Host 'Pi helper uninstalled. Source files retained.'
} finally { $lock.Dispose() }
