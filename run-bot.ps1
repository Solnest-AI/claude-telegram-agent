# Windows supervisor loop: keeps bot.py alive forever. Relaunches it if it ever exits.
$ErrorActionPreference = "Continue"

# Only one supervisor at a time
$mutex = New-Object System.Threading.Mutex($false, "Local\ClaudeTelegramAgentSupervisor")
if (-not $mutex.WaitOne(0)) { "Another supervisor is already running; exiting." | Out-Host; exit 0 }

$dir = $PSScriptRoot
$py  = Join-Path $dir ".venv\Scripts\python.exe"
$bot = Join-Path $dir "bot.py"
$logDir = Join-Path $dir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$supLog = Join-Path $logDir "supervisor.log"

while ($true) {
    "$(Get-Date -Format o) starting bot.py" | Add-Content $supLog
    try { & $py -u $bot *>> (Join-Path $logDir "bot-stdout.log"); $code = $LASTEXITCODE }
    catch { $code = "exception: $_" }
    "$(Get-Date -Format o) bot.py exited (code=$code); restarting in 5s" | Add-Content $supLog
    Start-Sleep -Seconds 5
}
