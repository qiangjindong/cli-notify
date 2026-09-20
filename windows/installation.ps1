function Enter-InstallLock([string]$Root) {
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    # File sharing flags also serialize WSL installers through the Windows helper.
    return [IO.File]::Open((Join-Path $Root 'install.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
}
function Invoke-Helper([string]$Executable, [string[]]$Arguments) {
    # Start-Process waits for WinExe; & does not reliably wait in Windows PowerShell.
    $quoted = ($Arguments | ForEach-Object {
        $value = [regex]::Replace($_, '(\\*)"', '$1$1\"')
        '"' + [regex]::Replace($value, '(\\+)$', '$1$1') + '"'
    }) -join ' '
    $process = Start-Process -FilePath $Executable -ArgumentList $quoted -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Helper failed ($($process.ExitCode)); see $env:LOCALAPPDATA\CodexWinNotify\helper.log" }
}
function Stop-InstalledHelper([string]$Helper) {
    Get-Process CodexWinNotify -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $Helper } | Stop-Process -Force
}
function Remove-InstallData([string]$Root) {
    $expected = [IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CodexWinNotify'))
    if ([IO.Path]::GetFullPath($Root) -ne $expected) { throw 'Unexpected installation directory.' }
    # Keep the open lock file in place until the caller releases its handle.
    Get-ChildItem -LiteralPath $Root -Force | Where-Object { $_.Name -ne 'install.lock' } | ForEach-Object {
        $resolved = [IO.Path]::GetFullPath($_.FullName)
        if (-not $resolved.StartsWith($expected + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected cleanup path.' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
