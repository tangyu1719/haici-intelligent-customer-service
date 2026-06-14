# Restart all HaiChi services
param(
    [switch]$SkipDocker,
    [switch]$KeepDocker
)

. "$PSScriptRoot\_lib.ps1"

Write-Host '>>> HaiChi restart all services' -ForegroundColor White

Stop-AppProcesses
if (-not $SkipDocker -and -not $KeepDocker) {
    Stop-DockerMiddleware
    Start-Sleep -Seconds 2
    Start-DockerMiddleware | Out-Null
} elseif (-not $SkipDocker) {
    Write-Host 'KEEP  Docker not restarted (--KeepDocker)' -ForegroundColor DarkGray
}

Start-Backend | Out-Null
Start-Frontend | Out-Null
Show-ServiceStatus
