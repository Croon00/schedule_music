# 현재 Windows 사용자가 로그인할 때마다 로컬 개발 서비스를 시작하는
# 사용자별 예약 작업을 등록합니다.

$projectRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $PSScriptRoot "start-local.ps1"
$taskName = "ScheduleMusic Local Services"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`""
$trigger = New-ScheduledTaskTrigger -AtLogOn

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Description "Starts schedule_music API and web UI after user sign-in." `
    -Force | Out-Null

Write-Host "Registered '$taskName'. It will start at your next sign-in."
Write-Host "To start it now: powershell -ExecutionPolicy Bypass -File `"$startScript`""
