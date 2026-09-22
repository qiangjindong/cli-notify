function Get-HelperSourceDigest([string]$Path) {
    # Git checkouts may use CRLF on Windows and LF in WSL.
    $text = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($Path)).Replace("`r`n", "`n")
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Get-HelperSourceHashes([string]$Source, [AllowNull()][string]$Icon) {
    $hashes = @{}
    $files = @(Get-ChildItem -LiteralPath (Join-Path $Source 'windows') -Filter '*.cs')
    $files += Get-Item -LiteralPath (Join-Path $Source 'windows/CliNotify.csproj')
    foreach ($file in $files) { $hashes[$file.Name] = Get-HelperSourceDigest $file.FullName }
    if ($Icon) {
        $hashes['notification.icon'] = (Get-FileHash -LiteralPath $Icon -Algorithm SHA256).Hash.ToLowerInvariant()
        $hashes['make-icon.ps1'] = Get-HelperSourceDigest (Join-Path $Source 'windows/make-icon.ps1')
    }
    return $hashes
}
function Get-HelperAppHashes([string]$Root) {
    $app = Join-Path $Root 'app'
    foreach ($name in @('CliNotify.exe', 'CliNotify.dll', 'CliNotify.deps.json', 'CliNotify.runtimeconfig.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $app $name) -PathType Leaf)) { throw 'Incomplete helper installation' }
    }
    $hashes = @{}
    foreach ($file in (Get-ChildItem -LiteralPath $app -Recurse -File)) {
        $name = $file.FullName.Substring($app.Length + 1).Replace('\', '/')
        $hashes[$name] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $hashes
}
function Test-HelperHashes($Saved, [hashtable]$Expected) {
    if ($null -eq $Saved -or @($Saved.PSObject.Properties).Count -ne $Expected.Count) { return $false }
    foreach ($name in $Expected.Keys) {
        if ($null -eq $Saved.PSObject.Properties[$name] -or $Saved.PSObject.Properties[$name].Value -cne $Expected[$name]) { return $false }
    }
    return $true
}
function Test-CompatibleHelper([string]$Root, [string]$Source, [AllowNull()][string]$Icon) {
    try {
        $receipt = Get-Content -Raw -LiteralPath (Join-Path $Root 'helper-install.json') -ErrorAction Stop | ConvertFrom-Json
        return ($receipt.schema -eq 1 -and
            (Test-HelperHashes $receipt.source (Get-HelperSourceHashes $Source $Icon)) -and
            (Test-HelperHashes $receipt.files (Get-HelperAppHashes $Root)))
    } catch { return $false }
}
function Write-HelperReceipt([string]$Root, [string]$Source, [AllowNull()][string]$Icon) {
    $temporary = Join-Path $Root 'helper-install.json.tmp'
    @{ schema = 1; source = (Get-HelperSourceHashes $Source $Icon); files = (Get-HelperAppHashes $Root) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination (Join-Path $Root 'helper-install.json') -Force
}
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
    if ($process.ExitCode -ne 0) { throw "Helper failed ($($process.ExitCode)); see $env:LOCALAPPDATA\CliNotify\helper.log" }
}
function Stop-InstalledHelper([string]$Helper) {
    Get-Process CliNotify -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $Helper } | Stop-Process -Force
}
function Remove-InstallData([string]$Root) {
    $expected = [IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CliNotify'))
    if ([IO.Path]::GetFullPath($Root) -ne $expected) { throw 'Unexpected installation directory.' }
    # Keep the open lock file in place until the caller releases its handle.
    Get-ChildItem -LiteralPath $Root -Force | Where-Object { $_.Name -ne 'install.lock' } | ForEach-Object {
        $resolved = [IO.Path]::GetFullPath($_.FullName)
        if (-not $resolved.StartsWith($expected + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected cleanup path.' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
