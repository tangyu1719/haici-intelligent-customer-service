# Stop all HaiCi services: frontend + backend + Docker
param(
    [switch]$SkipDocker,
    [switch]$KeepDocker
)

. "$PSScriptRoot\_lib.ps1"

Write-Host '>>> HaiCi stop all services' -ForegroundColor White

Stop-AppProcesses

if (-not $SkipDocker -and -not $KeepDocker) {
    Stop-DockerMiddleware
} else {
    Write-Host 'KEEP  Docker middleware still running' -ForegroundColor DarkGray
}

Show-ServiceStatus
