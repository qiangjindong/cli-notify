function Write-JsonAtomic([string]$Path, $Value) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Path.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText($temporary, (($Value | ConvertTo-Json -Depth 20) + "`n"), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
}

function Prepare-PersonalPlugin([string]$SourceRoot, [string]$UserHome = $HOME) {
    $name = 'codex-win-notify'
    $marketplace = Join-Path $UserHome '.agents\plugins\marketplace.json'
    $pluginSource = Join-Path $UserHome "plugins\$name"
    if (Test-Path -LiteralPath $marketplace) {
        if ((Get-Item -LiteralPath $marketplace).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing to replace a symlinked personal marketplace.' }
        $document = Get-Content -Raw -LiteralPath $marketplace | ConvertFrom-Json
    } else {
        $document = [pscustomobject]@{ name='personal'; interface=[pscustomobject]@{ displayName='Personal' }; plugins=@() }
    }
    if (-not ($document.name -is [string]) -or $document.name -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid personal marketplace name.' }
    $entries = @($document.plugins)
    $found = @($entries | Where-Object { $_.name -eq $name })
    if ($found.Count -gt 1) { throw 'Duplicate codex-win-notify marketplace entries.' }
    if ($found.Count -eq 1 -and ($found[0].source.source -ne 'local' -or $found[0].source.path -ne "./plugins/$name")) {
        throw 'A different codex-win-notify plugin already exists in the personal marketplace.'
    }
    if (Test-Path -LiteralPath $pluginSource) {
        if ((Get-Item -LiteralPath $pluginSource).Attributes -band [IO.FileAttributes]::ReparsePoint -or
            -not (Test-Path -LiteralPath (Join-Path $pluginSource '.codex-win-notify-owned'))) {
            throw 'Personal plugin source path is not owned by codex-win-notify.'
        }
        Remove-Item -LiteralPath $pluginSource -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $pluginSource '.codex-plugin'), (Join-Path $pluginSource 'hooks') | Out-Null
    $manifest = Get-Content -Raw -LiteralPath (Join-Path $SourceRoot '.codex-plugin\plugin.json') | ConvertFrom-Json
    $manifest.version = ($manifest.version -split '\+',2)[0] + '+codex.local-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmssfff')
    Write-JsonAtomic (Join-Path $pluginSource '.codex-plugin\plugin.json') $manifest
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'hooks\hooks.json') -Destination (Join-Path $pluginSource 'hooks\hooks.json')
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'bridge.py') -Destination (Join-Path $pluginSource 'bridge.py')
    [IO.File]::WriteAllText((Join-Path $pluginSource '.codex-win-notify-owned'), "managed by codex-win-notify`n", [Text.UTF8Encoding]::new($false))
    $entry = [pscustomobject]@{ name=$name; source=[pscustomobject]@{ source='local'; path="./plugins/$name" };
        policy=[pscustomobject]@{ installation='AVAILABLE'; authentication='ON_INSTALL' }; category='Productivity' }
    if ($found.Count -eq 1) {
        for ($index = 0; $index -lt $entries.Count; $index++) {
            if ($entries[$index].name -eq $name) { $entries[$index] = $entry; break }
        }
    } else { $entries += $entry }
    $document.plugins = @($entries)
    Write-JsonAtomic $marketplace $document
    return [pscustomobject]@{ marketplace=$marketplace; marketplace_name=$document.name; plugin_source=$pluginSource }
}

function Invoke-CodexPluginAdd([string]$CodexHome, [string]$MarketplaceName) {
    $codex = (Get-Command codex.exe -ErrorAction Stop).Source
    $previous = $env:CODEX_HOME
    try {
        $env:CODEX_HOME = $CodexHome
        $output = & $codex plugin add "codex-win-notify@$MarketplaceName" --json
        if ($LASTEXITCODE -ne 0) { throw 'Codex plugin installation failed.' }
        return (($output -join "`n") | ConvertFrom-Json)
    } finally { $env:CODEX_HOME = $previous }
}

function Remove-PersonalPlugin($Client, [string]$CodexHome, [string]$UserHome = $HOME) {
    if (-not ($Client.plugin_id -is [string]) -or -not $Client.plugin_id.StartsWith('codex-win-notify@')) {
        throw 'Unexpected plugin id.'
    }
    $marketplace = [IO.Path]::GetFullPath($Client.marketplace)
    $pluginSource = [IO.Path]::GetFullPath($Client.plugin_source)
    if ($marketplace -ne [IO.Path]::GetFullPath((Join-Path $UserHome '.agents\plugins\marketplace.json')) -or
        $pluginSource -ne [IO.Path]::GetFullPath((Join-Path $UserHome 'plugins\codex-win-notify'))) { throw 'Unexpected plugin installation paths.' }
    if (-not (Test-Path -LiteralPath (Join-Path $pluginSource '.codex-win-notify-owned'))) {
        throw 'Personal plugin installation is not owned by codex-win-notify.'
    }
    $document = Get-Content -Raw -LiteralPath $marketplace | ConvertFrom-Json
    $owned = @($document.plugins | Where-Object {
        $_.name -eq 'codex-win-notify' -and $_.source.source -eq 'local' -and $_.source.path -eq './plugins/codex-win-notify'
    })
    if ($owned.Count -ne 1) { throw 'Personal plugin marketplace entry is not owned by codex-win-notify.' }
    $codex = (Get-Command codex.exe -ErrorAction Stop).Source
    $previous = $env:CODEX_HOME
    try {
        $env:CODEX_HOME = $CodexHome
        & $codex plugin remove $Client.plugin_id
        if ($LASTEXITCODE -ne 0) { throw 'Codex plugin removal failed.' }
    } finally { $env:CODEX_HOME = $previous }
    $document.plugins = @($document.plugins | Where-Object {
        -not ($_.name -eq 'codex-win-notify' -and $_.source.source -eq 'local' -and $_.source.path -eq './plugins/codex-win-notify')
    })
    Write-JsonAtomic $marketplace $document
    Remove-Item -LiteralPath $pluginSource -Recurse -Force
}
