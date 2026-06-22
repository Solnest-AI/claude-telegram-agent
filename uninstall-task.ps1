# Windows: stop and remove the bot's Scheduled Task + any running copies.
$ErrorActionPreference = "Continue"
$dir = $PSScriptRoot
$taskName = "ClaudeTelegramAgent"
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match [regex]::Escape($dir) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "Stopped and removed."
