param([string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }))
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\windows\installation.ps1"

$CodexHome = [IO.Path]::GetFullPath($CodexHome)
Get-Command codex.exe -ErrorAction Stop | Out-Null
Get-Command wt.exe -ErrorAction Stop | Out-Null
if (-not ((& dotnet --list-sdks) -match '^9\.')) { throw 'Windows .NET 9 SDK is required.' }
$settingsPath = Join-Path $PSScriptRoot 'codex-win-notify.json'
$settings = Get-Content -Raw -LiteralPath $settingsPath | ConvertFrom-Json
$notificationProperty = $settings.PSObject.Properties['notification']
if ($null -eq $notificationProperty -or $null -eq $settings.notification -or
    $null -eq $settings.notification.PSObject.Properties['icon']) {
    throw 'codex-win-notify.json must contain notification.icon.'
}
$icon = $settings.notification.icon
if ($null -ne $icon) {
    if (-not ($icon -is [string]) -or [string]::IsNullOrWhiteSpace($icon)) { throw 'notification.icon must be a PNG path or null.' }
    if (-not [IO.Path]::IsPathRooted($icon)) { $icon = Join-Path $PSScriptRoot $icon }
    $icon = [IO.Path]::GetFullPath($icon)
    if ([IO.Path]::GetExtension($icon) -ine '.png') { throw 'notification.icon currently supports PNG files only.' }
    if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) { throw "Notification icon not found: $icon" }
}
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
    $iconBuild = Join-Path $root 'build-windows-icon'
    $generatedIcon = Join-Path $iconBuild 'app.ico'
    $publishArgs = @('publish', "$PSScriptRoot\windows\CodexWinNotify.csproj", '-c', 'Release', '-r', 'win-x64', '--self-contained', 'false', '-o', $stage, '--nologo')
    if ($null -eq $icon) { Remove-Item -LiteralPath $generatedIcon -Force -ErrorAction SilentlyContinue }
    else {
        & "$PSScriptRoot\windows\make-icon.ps1" -InputPng $icon -OutputIco $generatedIcon
        $publishArgs += "-p:ApplicationIcon=$generatedIcon"
    }
    & dotnet @publishArgs
    if ($LASTEXITCODE -ne 0) { throw 'Publish failed; configuration was not changed.' }
    Invoke-Helper (Join-Path $stage 'CodexWinNotify.exe') @('--configure', 'check', $CodexHome)
    $app = Join-Path $root 'app'
    $helper = Join-Path $app 'CodexWinNotify.exe'
    Stop-InstalledHelper $helper
    New-Item -ItemType Directory -Force -Path $app, $clients | Out-Null
    Copy-Item -Path "$stage\*" -Destination $app -Recurse -Force
    Get-ChildItem -LiteralPath $root -Filter 'notification-icon-*.png' | Remove-Item -Force
    Remove-Item -LiteralPath (Join-Path $root 'notification-icon.png') -Force -ErrorAction SilentlyContinue
    # Keep a lease even if configuring fails, so another client cannot remove
    # files needed for a repair/retry of this installation.
    @{ home = $CodexHome; helper = $helper } | ConvertTo-Json | Set-Content -LiteralPath $manifest -Encoding UTF8
    Invoke-Helper $helper @('--configure', 'install', $CodexHome)
    Write-Host 'Installed. Close Codex and run codex again. Native desktop acceptance is documented in docs/technical.md.'
} finally { $lock.Dispose() }
