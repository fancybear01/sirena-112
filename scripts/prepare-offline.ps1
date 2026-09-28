param(
    [string]$OutputDirectory = 'offline-bundle'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$outputRoot = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory
} else {
    Join-Path $repositoryRoot $OutputDirectory
}
$modelRoot = Join-Path $repositoryRoot 'models'
$modelManifest = Join-Path $repositoryRoot 'infra\offline\models.env'
$envFile = Join-Path $repositoryRoot '.env'
$composeFile = Join-Path $repositoryRoot 'compose.yaml'

function Read-KeyValues {
    param([string]$Path)
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $key, $value = $line -split '=', 2
        $values[$key.Trim()] = $value.Trim()
    }
    return $values
}

function Get-Hash {
    param([string]$Path)
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-Artifact {
    param([string]$Url, [string]$Path, [string]$ExpectedHash, [switch]$IPv4)
    if ((Test-Path -LiteralPath $Path) -and (Get-Hash $Path) -eq $ExpectedHash) { return }
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curl) { throw 'curl.exe не найден; он входит в Windows 10/11.' }
    $arguments = @('-fL', '--retry', '3', '--output', $Path, $Url)
    if ($IPv4) { $arguments = @('-4') + $arguments }
    & $curl.Source @arguments
    if ($LASTEXITCODE -ne 0) { throw "Не удалось скачать $Url" }
    $actual = Get-Hash $Path
    if ($actual -ne $ExpectedHash) {
        throw "SHA-256 для $Path не совпала: ожидалась $ExpectedHash, получена $actual"
    }
}

try {
    Push-Location $repositoryRoot
    if (-not (Test-Path -LiteralPath $envFile)) {
        & (Join-Path $PSScriptRoot 'stack.ps1') init
    }

    New-Item -ItemType Directory -Force -Path $modelRoot | Out-Null
    $models = Read-KeyValues $modelManifest
    $voskArchive = Join-Path $modelRoot $models['VOSK_ARCHIVE']
    Get-Artifact $models['VOSK_URL'] $voskArchive $models['VOSK_SHA256'] -IPv4
    $voskDirectory = Join-Path $modelRoot $models['VOSK_DIRECTORY']
    if (-not (Test-Path -LiteralPath (Join-Path $voskDirectory 'am\final.mdl'))) {
        Expand-Archive -LiteralPath $voskArchive -DestinationPath $modelRoot -Force
    }
    Get-Artifact $models['PIPER_MODEL_URL'] (Join-Path $modelRoot $models['PIPER_MODEL']) $models['PIPER_MODEL_SHA256']
    Get-Artifact $models['PIPER_CONFIG_URL'] (Join-Path $modelRoot $models['PIPER_CONFIG']) $models['PIPER_CONFIG_SHA256']

    docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Engine не запущен.' }
    docker pull 'postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea'
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось получить закреплённый PostgreSQL-образ.' }
    docker tag 'postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea' 'postgres:16-alpine'
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось присвоить локальный тег PostgreSQL-образу.' }
    docker compose --env-file $envFile -f $composeFile --profile smoke build --pull
    if ($LASTEXITCODE -ne 0) { throw 'Сборка образов завершилась ошибкой.' }
    & (Join-Path $PSScriptRoot 'stack.ps1') doctor

    New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
    Remove-Item -LiteralPath (Join-Path $outputRoot '.env') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $outputRoot 'SHA256SUMS') -Force -ErrorAction SilentlyContinue
    $images = @(
        'postgres:16-alpine',
        'sirena-112-ai:2026.09.28',
        'sirena-112-asterisk:2026.09.28',
        'sirena-112-media:2026.09.28',
        'sirena-112-core:2026.09.28',
        'sirena-112-web:2026.09.28',
        'sirena-112-monitor:2026.09.28',
        'sirena-112-smoke:2026.09.28'
    )
    $imagesTar = Join-Path $outputRoot 'images.tar'
    docker save --output $imagesTar @images
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось сохранить Docker-образы.' }

    foreach ($directory in @('scripts', 'docs', 'infra\offline', 'models')) {
        $destination = Join-Path $outputRoot $directory
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
    }
    Copy-Item -LiteralPath $composeFile -Destination (Join-Path $outputRoot 'compose.yaml') -Force
    Copy-Item -LiteralPath (Join-Path $repositoryRoot 'compose.offline.yaml') -Destination $outputRoot -Force
    Copy-Item -LiteralPath (Join-Path $repositoryRoot '.env.example') -Destination $outputRoot -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'stack.ps1') -Destination (Join-Path $outputRoot 'scripts') -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'stack.sh') -Destination (Join-Path $outputRoot 'scripts') -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'verify-bundle.ps1') -Destination (Join-Path $outputRoot 'scripts') -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'verify-bundle.sh') -Destination (Join-Path $outputRoot 'scripts') -Force
    Copy-Item -LiteralPath (Join-Path $repositoryRoot 'docs\offline-full-stack.md') -Destination (Join-Path $outputRoot 'docs') -Force
    Copy-Item -LiteralPath $modelManifest -Destination (Join-Path $outputRoot 'infra\offline') -Force
    Copy-Item -Path (Join-Path $modelRoot '*') -Destination (Join-Path $outputRoot 'models') -Recurse -Force

    [System.IO.File]::WriteAllText((Join-Path $outputRoot 'VERSION'), "2026.09.28`n", [System.Text.UTF8Encoding]::new($false))
    $manifestLines = Get-ChildItem -LiteralPath $outputRoot -File -Recurse |
        Where-Object { $_.Name -notin @('SHA256SUMS', '.env') } |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($outputRoot.TrimEnd('\').Length + 1).Replace('\', '/')
            "$(Get-Hash $_.FullName)  $relative"
        }
    [System.IO.File]::WriteAllLines((Join-Path $outputRoot 'SHA256SUMS'), $manifestLines, [System.Text.UTF8Encoding]::new($false))
    Write-Host "PASS: офлайн-пакет подготовлен в $outputRoot"
    Write-Host 'Секретный .env намеренно не включён. На целевой машине выполните scripts\stack.ps1 init.'
} catch {
    [Console]::Error.WriteLine("Не удалось подготовить офлайн-пакет: $($_.Exception.Message)")
    exit 1
} finally {
    Pop-Location
}
