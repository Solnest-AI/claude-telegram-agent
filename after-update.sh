#!/usr/bin/env bash
# After new code lands (update.py, or update.py --undo): install any new
# packages, check the new code loads, then restart the always-on bot so it runs
# the new code. ~/.solnest/autoupdate.py runs this by itself after every
# automatic update; if it fails, the old version is put back and this runs again.
#
#   bash after-update.sh
#
# Restarts only a bot that was made always-on (install-agent.sh on macOS,
# install-task.ps1 on Windows). A bot never installed as a service is left alone.
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"
say() { printf '[after-update] %s\n' "$*"; }

PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe
[ -x "$PY" ] || { say "no .venv in this folder: run SETUP.md Step 3 first"; exit 1; }

# 1. Packages. Voice-in is optional: refresh it only where it is installed.
"$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if "$PY" -c "import mlx_whisper" >/dev/null 2>&1; then
    "$PY" -m pip install --quiet --disable-pip-version-check -r requirements-voice.txt
fi

# 2. The new code must at least load, or the old version goes back.
"$PY" -m py_compile bot.py
"$PY" -c "import telegram.ext, claude_agent_sdk, dotenv"

# 3. Restart the always-on bot so it runs the new code.
case "$(uname -s)" in
    Darwin)
        # Find this folder's LaunchAgent by what it runs, so a custom LABEL works too.
        plist="$(grep -l -F "<string>$DIR/bot.py</string>" "$HOME"/Library/LaunchAgents/*.plist 2>/dev/null | head -1 || true)"
        if [ -n "$plist" ]; then
            label="$(basename "$plist" .plist)"
            LABEL="$label" bash install-agent.sh >/dev/null
            say "restarted $label"
        else
            say "not installed as a service here, nothing to restart"
        fi
        ;;
    MINGW*|MSYS*|CYGWIN*)
        # The Scheduled Task runs run-bot.ps1, which relaunches bot.py within 5
        # seconds of it exiting. Ending this folder's bot.py is the restart.
        TG_BOT="$(pwd -W | sed 's#/#\\#g')\\bot.py" powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '
            if (-not (Get-ScheduledTask -TaskName "ClaudeTelegramAgent" -ErrorAction SilentlyContinue)) {
                "[after-update] not installed as a service here, nothing to restart"; exit 0 }
            $bot = $env:TG_BOT.ToLower()
            Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($bot) } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            "[after-update] restarted the bot (its supervisor starts the new code)"'
        ;;
    *)
        say "restart the bot yourself to run the new code"
        ;;
esac
say "done"
