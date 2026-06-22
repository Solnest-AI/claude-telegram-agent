#!/bin/bash
# Stop and remove the Telegram->Claude agent LaunchAgent.
set -uo pipefail

LABEL="${LABEL:-com.claude-telegram-agent}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "Stopped and removed '$LABEL'."
