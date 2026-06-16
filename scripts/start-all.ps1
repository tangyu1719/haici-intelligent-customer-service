# Start all HaiCi services: Docker + backend + frontend
param(
    [switch]$SkipDocker,
    [switch]$SkipFrontend,
    [switch]$SkipBackend
)

. "$PSScriptRoot\_lib.ps1"

Write-Host '>>> HaiCi start all services' -ForegroundColor White

if (-not $SkipDocker) {
    Start-DockerMiddleware | Out-Null
} else {
    Write-Host 'SKIP  Docker middleware (--SkipDocker)' -ForegroundColor DarkGray
}

if (-not $SkipBackend) {
    Start-Backend | Out-Null
}

if (-not $SkipFrontend) {
    Start-Frontend | Out-Null
}

Show-ServiceStatus
