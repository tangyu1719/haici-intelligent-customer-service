# HaiCi service helpers (Windows PowerShell)
$ErrorActionPreference = 'Stop'

$script:ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:BackendDir = Join-Path $ProjectRoot 'backend'
$script:FrontendDir = Join-Path $ProjectRoot 'frontend'
$script:RunDir = Join-Path $ProjectRoot '.run'
$script:LogDir = Join-Path $RunDir 'logs'

$script:BackendPort = 8012
$script:FrontendPort = 5173
$script:ChromaPort = 8001
$script:MysqlPort = 3307

function Ensure-RunDirs {
    foreach ($d in @($RunDir, $LogDir)) {
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    }
}

function Get-PythonExe {
    $venvPy = Join-Path $BackendDir '.venv\Scripts\python.exe'
    if (Test-Path $venvPy) { return $venvPy }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return 'py' }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return 'python' }
    throw 'Python not found. Install Python 3.10+ or create backend/.venv'
}

function Get-PythonArgs {
    param([string]$Exe)
    if ($Exe -eq 'py') { return @('-3') }
    return @()
}

function Get-NpmCmd {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npm) { return $npm.Source }
    $npm2 = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm2) { return $npm2.Source }
    throw 'npm not found. Install Node.js 18+'
}

function Get-PortPid {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($conn) { return [int]$conn.OwningProcess }
    return $null
}

function Stop-PortProcess {
    param(
        [int]$Port,
        [string]$Label = "port $Port"
    )
    $procId = Get-PortPid -Port $Port
    if (-not $procId) {
        Write-Host "STOP  $Label not listening" -ForegroundColor DarkGray
        return
    }
    try {
        $proc = Get-Process -Id $procId -ErrorAction Stop
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "STOP  $Label (PID $procId $($proc.ProcessName))" -ForegroundColor Yellow
    } catch {
        Write-Host "STOP  $Label PID $procId failed: $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Stop-ByPidFile {
    param([string]$Name)
    $file = Join-Path $RunDir "$Name.pid"
    if (-not (Test-Path $file)) { return }
    $stored = (Get-Content $file -Raw).Trim()
    if ($stored -match '^\d+$') {
        $procId = [int]$stored
        if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Write-Host "STOP  $Name from pid file ($procId)" -ForegroundColor Yellow
        }
    }
    Remove-Item $file -Force -ErrorAction SilentlyContinue
}

function Save-PidFile {
    param(
        [string]$Name,
        [int]$ProcessId
    )
    Ensure-RunDirs
    Set-Content -Path (Join-Path $RunDir "$Name.pid") -Value $ProcessId -Encoding ascii
}

function Wait-PortListen {
    param(
        [int]$Port,
        [int]$TimeoutSec = 60,
        [string]$Label = ''
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Get-PortPid -Port $Port) {
            if ($Label) { Write-Host "OK    $Label listening on $Port" -ForegroundColor Green }
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    if ($Label) { Write-Host "FAIL  $Label port $Port timeout" -ForegroundColor Red }
    return $false
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSec = 90,
        [string]$Label = ''
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) {
                if ($Label) { Write-Host "OK    $Label $Url" -ForegroundColor Green }
                return $true
            }
        } catch { }
        Start-Sleep -Milliseconds 800
    }
    if ($Label) { Write-Host "FAIL  $Label $Url timeout" -ForegroundColor Red }
    return $false
}

function Test-DockerAvailable {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) { return $false }
    try {
        docker info *> $null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Start-DockerMiddleware {
    if (-not (Test-DockerAvailable)) {
        Write-Host 'WARN  Docker unavailable; ensure MySQL:3307 and Chroma:8001 are up' -ForegroundColor Yellow
        return $false
    }
    Push-Location $ProjectRoot
    try {
        Write-Host 'START Docker middleware (MySQL + Chroma)...' -ForegroundColor Cyan
        docker compose up -d
        if ($LASTEXITCODE -ne 0) { throw "docker compose up failed (exit $LASTEXITCODE)" }
        $okMysql = Wait-PortListen -Port $MysqlPort -TimeoutSec 90 -Label 'MySQL'
        $okChroma = Wait-PortListen -Port $ChromaPort -TimeoutSec 90 -Label 'Chroma'
        return ($okMysql -and $okChroma)
    } finally {
        Pop-Location
    }
}

function Stop-DockerMiddleware {
    if (-not (Test-DockerAvailable)) {
        Write-Host 'SKIP  Docker unavailable' -ForegroundColor DarkGray
        return
    }
    Push-Location $ProjectRoot
    try {
        Write-Host 'STOP  Docker middleware...' -ForegroundColor Cyan
        docker compose stop
    } finally {
        Pop-Location
    }
}

function Start-Backend {
    Ensure-RunDirs
    Stop-ByPidFile -Name 'backend'
    Stop-PortProcess -Port $BackendPort -Label 'backend API'

    $py = Get-PythonExe
    $pyArgs = Get-PythonArgs -Exe $py
    $outLog = Join-Path $LogDir 'backend.out.log'
    $errLog = Join-Path $LogDir 'backend.err.log'

    $uvicornArgs = $pyArgs + @(
        '-m', 'uvicorn', 'app.main:app',
        '--host', '127.0.0.1',
        '--port', "$BackendPort"
    )

    Write-Host "START backend http://127.0.0.1:$BackendPort ..." -ForegroundColor Cyan
    $proc = Start-Process -FilePath $py `
        -ArgumentList $uvicornArgs `
        -WorkingDirectory $BackendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -PassThru

    Save-PidFile -Name 'backend' -ProcessId $proc.Id
    Start-Sleep -Seconds 2
    $listenPid = Get-PortPid -Port $BackendPort
    if ($listenPid) { Save-PidFile -Name 'backend' -ProcessId $listenPid }

    Wait-HttpOk -Url "http://127.0.0.1:$BackendPort/docs" -TimeoutSec 120 -Label 'backend API'
}

function Start-Frontend {
    Ensure-RunDirs
    Stop-ByPidFile -Name 'frontend'
    Stop-PortProcess -Port $FrontendPort -Label 'frontend Vite'

    if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
        Write-Host 'INSTALL frontend npm install ...' -ForegroundColor Cyan
        Push-Location $FrontendDir
        try {
            & (Get-NpmCmd) install
            if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
        } finally { Pop-Location }
    }

    $npm = Get-NpmCmd
    $outLog = Join-Path $LogDir 'frontend.out.log'
    $errLog = Join-Path $LogDir 'frontend.err.log'

    Write-Host "START frontend http://127.0.0.1:$FrontendPort ..." -ForegroundColor Cyan
    $proc = Start-Process -FilePath $npm `
        -ArgumentList @('run', 'dev', '--', '--host', '127.0.0.1', '--port', "$FrontendPort", '--strictPort') `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -PassThru

    Save-PidFile -Name 'frontend' -ProcessId $proc.Id
    Wait-HttpOk -Url "http://127.0.0.1:$FrontendPort" -TimeoutSec 60 -Label 'frontend Vite'
}

function Stop-AppProcesses {
    Stop-ByPidFile -Name 'frontend'
    Stop-ByPidFile -Name 'backend'
    Stop-PortProcess -Port $FrontendPort -Label 'frontend Vite'
    Stop-PortProcess -Port $BackendPort -Label 'backend API'
}

function Show-ServiceStatus {
    Write-Host ''
    Write-Host '========== HaiCi Service Status ==========' -ForegroundColor White
    foreach ($item in @(
        @{ Name = 'MySQL'; Port = $MysqlPort },
        @{ Name = 'Chroma'; Port = $ChromaPort },
        @{ Name = 'Backend'; Port = $BackendPort },
        @{ Name = 'Frontend'; Port = $FrontendPort }
    )) {
        $procId = Get-PortPid -Port $item.Port
        if ($procId) {
            $line = '  {0,-10} :{1,-5} running (PID {2})' -f $item.Name, $item.Port, $procId
            Write-Host $line -ForegroundColor Green
        } else {
            $line = '  {0,-10} :{1,-5} stopped' -f $item.Name, $item.Port
            Write-Host $line -ForegroundColor DarkGray
        }
    }
    Write-Host '  UI:      http://127.0.0.1:5173  (admin / admin)' -ForegroundColor Cyan
    Write-Host '  API:     http://127.0.0.1:8012/docs' -ForegroundColor Cyan
    Write-Host '  Logs:    .run/logs/' -ForegroundColor DarkGray
    Write-Host '===========================================' -ForegroundColor White
}
