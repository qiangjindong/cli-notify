param(
    [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }),
    [switch]$PiOnly
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\windows\installation.ps1"

if (-not $PiOnly) {
    $CodexHome = [IO.Path]::GetFullPath($CodexHome)
    Get-Command codex.exe -ErrorAction Stop | Out-Null
}
Get-Command wt.exe -ErrorAction Stop | Out-Null
$settingsPath = Join-Path $PSScriptRoot 'cli-notify.json'
$settings = Get-Content -Raw -LiteralPath $settingsPath | ConvertFrom-Json
$notificationProperty = $settings.PSObject.Properties['notification']
if ($null -eq $notificationProperty -or $null -eq $settings.notification -or
    $null -eq $settings.notification.PSObject.Properties['icon']) {
    throw 'cli-notify.json must contain notification.icon.'
}
$icon = $settings.notification.icon
if ($null -ne $icon) {
    if (-not ($icon -is [string]) -or [string]::IsNullOrWhiteSpace($icon)) { throw 'notification.icon must be a PNG path or null.' }
    if (-not [IO.Path]::IsPathRooted($icon)) { $icon = Join-Path $PSScriptRoot $icon }
    $icon = [IO.Path]::GetFullPath($icon)
    if ([IO.Path]::GetExtension($icon) -ine '.png') { throw 'notification.icon currently supports PNG files only.' }
    if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) { throw "Notification icon not found: $icon" }
}
$root = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CliNotify'
$lock = Enter-InstallLock $root
try {
    $clients = Join-Path $root 'clients'
    $manifest = Join-Path $clients $(if ($PiOnly) { 'pi-windows.json' } else { 'windows.json' })
    if (-not $PiOnly -and (Test-Path -LiteralPath $manifest)) {
        $previous = Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json
        if ($previous.home -ne $CodexHome) { throw 'Uninstall the existing Windows client before changing CODEX_HOME.' }
    }
    $app = Join-Path $root 'app'
    $helper = Join-Path $app 'CliNotify.exe'
    if (Test-CompatibleHelper $root $PSScriptRoot $icon) {
        Write-Host 'Compatible notification helper already installed; skipping build and update.'
        if (-not $PiOnly) { Invoke-Helper $helper @('--configure', 'check', $CodexHome) }
    } else {
        if (-not ((& dotnet --list-sdks) -match '^9\.')) { throw 'Windows .NET 9 SDK is required.' }
        Remove-Item -LiteralPath (Join-Path $root 'helper-install.json') -Force -ErrorAction SilentlyContinue
        $stage = Join-Path $root 'build-windows'
        $iconBuild = Join-Path $root 'build-windows-icon'
        $generatedIcon = Join-Path $iconBuild 'app.ico'
        $publishArgs = @('publish', "$PSScriptRoot\windows\CliNotify.csproj", '-c', 'Release', '-r', 'win-x64', '--self-contained', 'false', '-o', $stage, '--nologo')
        if ($null -eq $icon) { Remove-Item -LiteralPath $generatedIcon -Force -ErrorAction SilentlyContinue }
        else {
            & "$PSScriptRoot\windows\make-icon.ps1" -InputPng $icon -OutputIco $generatedIcon
            $publishArgs += "-p:ApplicationIcon=$generatedIcon"
        }
        & dotnet @publishArgs
        if ($LASTEXITCODE -ne 0) { throw 'Publish failed; configuration was not changed.' }
        if (-not $PiOnly) { Invoke-Helper (Join-Path $stage 'CliNotify.exe') @('--configure', 'check', $CodexHome) }
        Stop-InstalledHelper $helper
        New-Item -ItemType Directory -Force -Path $app, $clients | Out-Null
        Copy-Item -Path "$stage\*" -Destination $app -Recurse -Force
        Get-ChildItem -LiteralPath $root -Filter 'notification-icon-*.png' | Remove-Item -Force
        Remove-Item -LiteralPath (Join-Path $root 'notification-icon.png') -Force -ErrorAction SilentlyContinue
        Write-HelperReceipt $root $PSScriptRoot $icon
    }
    New-Item -ItemType Directory -Force -Path $clients | Out-Null
    # Keep a lease even if configuring fails, so another client cannot remove
    # files needed for a repair/retry of this installation.
    if ($PiOnly) {
        @{ source = $PSScriptRoot; helper = $helper } | ConvertTo-Json | Set-Content -LiteralPath $manifest -Encoding UTF8
        Write-Host 'Pi helper installed (no Codex configuration changed). Next: pi install . ; then restart Pi.'
    } else {
        @{ home = $CodexHome; helper = $helper } | ConvertTo-Json | Set-Content -LiteralPath $manifest -Encoding UTF8
        Invoke-Helper $helper @('--configure', 'install', $CodexHome)
        Write-Host 'Installed. Close Codex and run codex again. Native desktop acceptance is documented in docs/technical.md.'
    }
} finally { $lock.Dispose() }
