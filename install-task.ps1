# Windows: make the bot start at logon and relaunch on crash. Run once (PowerShell).
#   powershell -ExecutionPolicy Bypass -File .\install-task.ps1
$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
$vbs = Join-Path $dir "launch-hidden.vbs"
$taskName = "ClaudeTelegramAgent"

if (-not (Test-Path (Join-Path $dir ".env"))) {
    throw "No .env found. Copy .env.example to .env and fill in your token + Telegram id first."
}
if (-not (Test-Path (Join-Path $dir ".venv\Scripts\python.exe"))) {
    throw "No .venv found. Create it and install requirements first (see SETUP.md)."
}

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument ('"{0}"' -f $vbs)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Registered '$taskName' (starts at logon)."
Start-ScheduledTask -TaskName $taskName
Write-Host "Started it now. Give it ~30s, then message your bot."
