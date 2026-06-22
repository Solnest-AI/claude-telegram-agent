# Claude Telegram Agent — repo context

An always-on Telegram bot that drives the **real Claude Code engine** on your own
machine via the Claude Agent SDK. Text or voice-note it from your phone; it runs
shell, files, your MCP tools, and skills, and replies in text (and voice when you
spoke to it). Read `README.md` for the overview and `SETUP.md` for install.

## Layout
- `bot.py` — the whole agent (Telegram ↔ Claude Agent SDK, approval gating, voice/image/file handling, session memory). Fully driven by `.env`.
- `.env.example` — config template. Copy to `.env` and fill in `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_USERS`. `.env` is gitignored — never commit it.
- `requirements.txt` — core deps (cross-platform). `requirements-voice.txt` — optional, Apple-Silicon-only voice-in.
- macOS service: `install-agent.sh` / `uninstall-agent.sh` (launchd).
- Windows service: `install-task.ps1` / `uninstall-task.ps1` + `run-bot.ps1` + `launch-hidden.vbs` (Scheduled Task + supervisor loop).

## Working on this repo
- After editing `.env` or `bot.py`, restart the service so changes take effect:
  - macOS: `launchctl kickstart -k gui/$(id -u)/com.claude-telegram-agent`
  - Windows: re-run `uninstall-task.ps1` then `install-task.ps1` (or end the python process; the supervisor relaunches it).
- Secrets live ONLY in `.env`. Never print its values or hardcode tokens/keys into code or docs.
- Keep `bot.py` config-driven — new behavior should read from `.env`, not be baked in.
