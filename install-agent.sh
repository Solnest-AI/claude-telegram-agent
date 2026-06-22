#!/bin/bash
# Install the Telegram->Claude agent as a macOS launchd LaunchAgent.
# KeepAlive => auto-restart on crash. RunAtLoad + login session => starts at login.
# Run once:  bash install-agent.sh
set -euo pipefail

# Service label. Override with LABEL=... bash install-agent.sh if you want your own.
LABEL="${LABEL:-com.claude-telegram-agent}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$DIR/.venv/bin/python"
BOT="$DIR/bot.py"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

# --- sanity checks -------------------------------------------------------- #
[ -x "$PY" ]   || { echo "ERROR: venv python not found at $PY  (create it + run the pip install step first — see SETUP.md)"; exit 1; }
[ -f "$BOT" ]  || { echo "ERROR: bot.py not found at $BOT"; exit 1; }
[ -f "$DIR/.env" ] || { echo "ERROR: no .env found. Copy .env.example to .env and fill in your token + Telegram id first."; exit 1; }
if grep -q "PASTE_YOUR_TOKEN_HERE\|PASTE_YOUR_ID_HERE" "$DIR/.env" 2>/dev/null; then
  echo "ERROR: .env still has placeholders. Fill in TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USERS first."
  exit 1
fi

mkdir -p "$DIR/logs" "$HOME/Library/LaunchAgents"

# --- write the plist ------------------------------------------------------ #
# PATH must include /opt/homebrew/bin so the Claude Agent SDK can find `claude`
# and `node` (launchd's default PATH does NOT include Homebrew).
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>-u</string>
        <string>$BOT</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$DIR</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>$HOME</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>$DIR/logs/launchd-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/logs/launchd-stderr.log</string>
</dict>
</plist>
PLISTEOF

echo "Wrote $PLIST"

# --- (re)load it ---------------------------------------------------------- #
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST"
launchctl enable "gui/$UID_NUM/$LABEL"
launchctl kickstart -k "gui/$UID_NUM/$LABEL"

echo "Loaded and started '$LABEL'."
echo "Give it ~30s, then message your bot. Logs: $DIR/logs/bot.log"
