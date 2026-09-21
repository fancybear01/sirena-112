param(
    [ValidateSet('start', 'stop', 'smoke', 'status')]
    [string]$Action = 'start'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$composeFile = Join-Path $repositoryRoot 'compose.card.yaml'
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$dockerExe = if ($dockerCommand) {
    $dockerCommand.Source
} else {
    $localDocker = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
    $systemDocker = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
    if (Test-Path -LiteralPath $localDocker) { $localDocker }
    elseif (Test-Path -LiteralPath $systemDocker) { $systemDocker }
    else { throw 'Docker CLI не найден. Установите Docker Desktop или добавьте docker.exe в PATH.' }
}

function Invoke-Compose {
    param([string[]]$Arguments)
    & $dockerExe compose -f $composeFile @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose завершился с кодом $LASTEXITCODE. Проверьте вывод выше."
    }
}

try {
    & $dockerExe info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Engine не запущен. Откройте Docker Desktop и дождитесь состояния Engine running.'
    }

    switch ($Action) {
        'start' {
            $existingWeb = & $dockerExe compose -f $composeFile ps --status running -q web
            if (-not $existingWeb) {
                foreach ($port in @(5173, 8080, 8090)) {
                    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
                        throw "Порт $port уже занят. Освободите его и повторите запуск."
                    }
                }
            }
            Invoke-Compose -Arguments @('up', '--build', '--detach', '--wait', 'ai', 'core', 'web')
            Invoke-Compose -Arguments @('run', '--no-deps', '--rm', 'smoke')
            Write-Host 'Карточное демо готово: http://localhost:5173/teacher и http://localhost:5173/student'
            Write-Host 'Остановка только этого демо: .\scripts\demo-card.ps1 stop'
        }
        'smoke' {
            Invoke-Compose -Arguments @('run', '--no-deps', '--rm', 'smoke')
        }
        'status' {
            Invoke-Compose -Arguments @('ps')
        }
        'stop' {
            Invoke-Compose -Arguments @('down')
            Write-Host 'Остановлены только контейнеры проекта sirena-card; тома и голосовой стек не удалены.'
        }
    }
} catch {
    [Console]::Error.WriteLine("Не удалось выполнить '$Action': $($_.Exception.Message)")
    [Console]::Error.WriteLine('Проверка состояния: .\scripts\demo-card.ps1 status')
    exit 1
}
