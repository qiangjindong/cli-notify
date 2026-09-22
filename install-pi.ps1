# Install only the shared notification helper and its Pi lease, not Codex hooks.
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\install.ps1" -PiOnly
