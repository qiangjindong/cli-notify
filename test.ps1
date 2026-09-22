$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\windows\installation.ps1"

$helper = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CliNotify\app\CliNotify.exe'
if (-not (Test-Path -LiteralPath $helper)) { throw 'Not installed. Run .\install.ps1 first.' }
Invoke-Helper $helper @('--test')
Write-Host 'Test notification sent. Clicking it should return to this terminal.'
