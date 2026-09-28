Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$bundleRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$manifest = Join-Path $bundleRoot 'SHA256SUMS'
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    throw "Не найден $manifest"
}

foreach ($line in Get-Content -LiteralPath $manifest) {
    if ($line -notmatch '^([0-9a-fA-F]{64})\s+(.+)$') {
        throw "Некорректная строка SHA256SUMS: $line"
    }
    $expected = $Matches[1].ToLowerInvariant()
    $relative = $Matches[2].Replace('/', [System.IO.Path]::DirectorySeparatorChar)
    $path = [System.IO.Path]::GetFullPath((Join-Path $bundleRoot $relative))
    if (-not $path.StartsWith($bundleRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Путь выходит за пределы пакета: $relative"
    }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Отсутствует файл из манифеста: $relative"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "SHA-256 не совпала: $relative"
    }
}

Write-Host 'PASS: все файлы offline-bundle соответствуют SHA256SUMS.'
