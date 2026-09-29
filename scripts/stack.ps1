param(
    [ValidateSet('init', 'doctor', 'start', 'stop', 'restart', 'status', 'smoke', 'logs', 'update')]
    [string]$Action = 'status',
    [string]$BundlePath = '',
    [ValidateSet('all', 'core', 'ai', 'media', 'postgres', 'asterisk', 'web', 'monitor')]
    [string]$Service = 'all'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$composeFile = Join-Path $repositoryRoot 'compose.yaml'
$offlineComposeFile = Join-Path $repositoryRoot 'compose.offline.yaml'
$envFile = Join-Path $repositoryRoot '.env'
$exampleEnvFile = Join-Path $repositoryRoot '.env.example'

function Get-DockerExecutable {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw 'Docker CLI не найден. Установите Docker Desktop и Docker Compose v2.'
}

$dockerExe = Get-DockerExecutable

function Invoke-Docker {
    param([string[]]$Arguments, [switch]$Capture)
    if ($Capture) {
        $output = & $dockerExe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "docker завершился с кодом $LASTEXITCODE" }
        return $output
    }
    & $dockerExe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker завершился с кодом $LASTEXITCODE" }
}

function Get-ComposeArguments {
    @('compose', '--env-file', $envFile, '-f', $composeFile, '-f', $offlineComposeFile)
}

function Invoke-Compose {
    param([string[]]$Arguments, [switch]$Capture)
    Invoke-Docker -Arguments ((Get-ComposeArguments) + $Arguments) -Capture:$Capture
}

function Test-AdminHelper {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8100/health' -TimeoutSec 1
        return $health.status -eq 'UP'
    } catch {
        return $false
    }
}

function Start-AdminHelper {
    if (Test-AdminHelper) { return }
    $helper = Join-Path $repositoryRoot 'scripts\admin_helper.py'
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    $arguments = @('-3', $helper)
    if (-not $launcher) {
        $launcher = Get-Command python -ErrorAction SilentlyContinue
        $arguments = @($helper)
    }
    if (-not $launcher) {
        throw 'Python 3 не найден. Он нужен локальному backend/helper админки.'
    }
    Start-Process -FilePath $launcher.Source -ArgumentList $arguments -WorkingDirectory $repositoryRoot -WindowStyle Hidden | Out-Null
    foreach ($attempt in 1..20) {
        Start-Sleep -Milliseconds 250
        if (Test-AdminHelper) { return }
    }
    throw 'Локальный backend/helper админки не запустился на 127.0.0.1:8100.'
}

function New-RandomSecret {
    param([int]$Bytes = 24)
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return -join ($buffer | ForEach-Object { $_.ToString('x2') })
}

function Initialize-Environment {
    if (Test-Path -LiteralPath $envFile) {
        Write-Host '.env уже существует; существующие секреты не изменены.'
        return
    }
    $content = Get-Content -LiteralPath $exampleEnvFile -Raw
    $replacements = @{
        GENERATE_POSTGRES_PASSWORD = New-RandomSecret 24
        GENERATE_ADMIN_PASSWORD = New-RandomSecret 18
        GENERATE_CORE_MEDIA_TOKEN = New-RandomSecret 32
        GENERATE_AI_SERVICE_TOKEN = New-RandomSecret 32
        GENERATE_SIP_1001_PASSWORD = New-RandomSecret 18
        GENERATE_SIP_1002_PASSWORD = New-RandomSecret 18
        GENERATE_ARI_PASSWORD = New-RandomSecret 24
    }
    foreach ($entry in $replacements.GetEnumerator()) {
        $content = $content.Replace($entry.Key, $entry.Value)
    }
    [System.IO.File]::WriteAllText($envFile, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Host 'Создан .env с локальными случайными секретами. Файл исключён из Git.'
}

function Read-DotEnv {
    if (-not (Test-Path -LiteralPath $envFile)) {
        throw 'Файл .env отсутствует. Выполните: .\scripts\stack.ps1 init'
    }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $key, $value = $line -split '=', 2
        $values[$key.Trim()] = $value.Trim()
    }
    return $values
}

function Assert-Secret {
    param([hashtable]$Values, [string]$Name, [int]$MinimumLength)
    $value = $Values[$Name]
    if (-not $value -or $value.Length -lt $MinimumLength -or
        $value -match '^(GENERATE_|change-me|sirena112-local)') {
        throw "$Name не задан безопасным значением. Повторно создайте .env или исправьте его вручную."
    }
}

function Assert-DockerReady {
    & $dockerExe info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Engine недоступен. Запустите Docker Desktop и дождитесь Engine running.'
    }
}

function Assert-Models {
    $modelRoot = Join-Path $repositoryRoot 'models'
    $required = @(
        (Join-Path $modelRoot 'vosk-model-small-ru-0.22\am\final.mdl'),
        (Join-Path $modelRoot 'ru_RU-dmitri-medium.onnx'),
        (Join-Path $modelRoot 'ru_RU-dmitri-medium.onnx.json')
    )
    foreach ($path in $required) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Отсутствует модель: $path. Выполните scripts\prepare-offline.ps1."
        }
    }
    $expected = @{
        'vosk-model-small-ru-0.22.zip' = '961D5FF98A17F4AA6DE69864D0AA71FA5BAC682301D2B5D17A3F24C5C99A46D4'
        'ru_RU-dmitri-medium.onnx' = 'F073356EBC4BD0F80C5AF58DF2953A5988BD5BDAB1EB38635CE960B071FBEFCB'
        'ru_RU-dmitri-medium.onnx.json' = '667EF3117BC642C2892DFF7690D8BDC8CA4228AEAA783B2DC1416DF632855E0D'
    }
    foreach ($entry in $expected.GetEnumerator()) {
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $modelRoot $entry.Key)).Hash
        if ($actual -ne $entry.Value) { throw "Контрольная сумма $($entry.Key) не совпала." }
    }
}

function Assert-Images {
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
    foreach ($image in $images) {
        & $dockerExe image inspect $image *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Docker-образ $image отсутствует. Загрузите offline-bundle\images.tar или выполните prepare-offline.ps1."
        }
    }
}

function Assert-PortsAvailable {
    $running = @(Invoke-Compose -Arguments @('ps', '--status', 'running', '-q') -Capture)
    if ($running.Count -gt 0) { return }
    $values = Read-DotEnv
    $ports = @(
        [int]$values['POSTGRES_PORT'], [int]$values['WEB_PORT'], [int]$values['CORE_PORT'],
        [int]$values['AI_PORT'], [int]$values['MEDIA_PORT'], [int]$values['ASTERISK_HTTP_PORT'],
        [int]$values['ASTERISK_SIP_PORT'], [int]$values['MONITOR_PORT']
    )
    foreach ($port in $ports) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw "TCP-порт $port уже занят. Освободите его или измените соответствующую переменную в .env."
        }
    }
}

function Invoke-Doctor {
    Assert-DockerReady
    $values = Read-DotEnv
    Assert-Secret $values 'POSTGRES_PASSWORD' 16
    Assert-Secret $values 'CORE_MEDIA_SERVICE_TOKEN' 32
    Assert-Secret $values 'AI_SERVICE_TOKEN' 32
    Assert-Secret $values 'ASTERISK_ARI_PASSWORD' 16
    Assert-Secret $values 'ASTERISK_SIP_1001_PASSWORD' 12
    Assert-Secret $values 'ASTERISK_SIP_1002_PASSWORD' 12
    if ($values['SIRENA_BIND_ADDRESS'] -ne '127.0.0.1') {
        throw 'Автономный профиль разрешает только SIRENA_BIND_ADDRESS=127.0.0.1. Для LAN нужен отдельный TLS/auth профиль и новая сборка.'
    }
    Assert-Models
    Assert-Images
    Invoke-Compose -Arguments @('config', '--quiet')
    Assert-PortsAvailable
    Write-Host 'PASS: Docker, Compose, секреты, модели, образы, конфигурация и порты готовы.'
}

try {
    Push-Location $repositoryRoot
    switch ($Action) {
        'init' { Initialize-Environment }
        'doctor' { Invoke-Doctor }
        'start' {
            Start-AdminHelper
            Invoke-Doctor
            $arguments = @('up', '--detach', '--wait', '--wait-timeout', '300', '--no-build', '--pull', 'never')
            if ($Service -ne 'all') { $arguments += @('--no-deps', $Service) }
            Invoke-Compose -Arguments $arguments
            Write-Host 'Стенд готов: Web http://localhost:5173, мониторинг http://localhost:8099/status, admin helper http://localhost:8100'
        }
        'stop' {
            if ($Service -eq 'all') {
                Invoke-Compose -Arguments @('down')
                Write-Host 'Контейнеры остановлены; том PostgreSQL сохранён. Admin helper оставлен для повторного запуска.'
            } else {
                Invoke-Compose -Arguments @('stop', $Service)
            }
        }
        'restart' {
            Start-AdminHelper
            $targets = if ($Service -eq 'all') { @() } else { @($Service) }
            Invoke-Compose -Arguments (@('restart') + $targets)
            $arguments = @('up', '--detach', '--wait', '--wait-timeout', '300', '--no-build', '--pull', 'never')
            if ($Service -ne 'all') { $arguments += @('--no-deps', $Service) }
            Invoke-Compose -Arguments $arguments
        }
        'status' {
            Invoke-Compose -Arguments @('ps')
            try {
                Invoke-RestMethod -Uri 'http://127.0.0.1:8099/status' -TimeoutSec 5 | ConvertTo-Json -Depth 5
            } catch {
                Write-Warning 'Мониторинг пока недоступен. Запустите doctor или logs для диагностики.'
            }
        }
        'smoke' {
            Invoke-Compose -Arguments @('--profile', 'smoke', 'run', '--no-deps', '--rm', 'card-smoke')
            Invoke-Compose -Arguments @('--profile', 'smoke', 'run', '--no-deps', '--rm', 'voice-smoke')
        }
        'logs' { Invoke-Compose -Arguments @('logs', '--no-color', '--tail', '200') }
        'update' {
            if ($Service -ne 'all') { throw 'Пакетное обновление выполняется только для всего комплекса.' }
            Start-AdminHelper
            if (-not $BundlePath) { $BundlePath = Join-Path $repositoryRoot 'offline-bundle\images.tar' }
            $resolvedBundle = (Resolve-Path -LiteralPath $BundlePath).Path
            Invoke-Docker -Arguments @('load', '--input', $resolvedBundle)
            Invoke-Doctor
            Invoke-Compose -Arguments @('up', '--detach', '--wait', '--wait-timeout', '300', '--no-build', '--pull', 'never', '--force-recreate')
            Write-Host 'Образы обновлены; данные PostgreSQL сохранены.'
        }
    }
} catch {
    [Console]::Error.WriteLine("Не удалось выполнить '$Action': $($_.Exception.Message)")
    [Console]::Error.WriteLine('Диагностика: .\scripts\stack.ps1 doctor или .\scripts\stack.ps1 logs')
    exit 1
} finally {
    Pop-Location
}
