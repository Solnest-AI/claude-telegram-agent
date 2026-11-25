# Claude Telegram Agent — repo context

An always-on Telegram bot that drives the **real Claude Code engine** on your own
machine via the Claude Agent SDK. Text or voice-note it from your phone; it runs
shell, files, your MCP tools, and skills, and replies in text (and voice when you
spoke to it). Read `README.md` for the overview and `SETUP.md` for install.
Setting it up for someone? Do every step of `SETUP.md`, including Step 7b (automatic updates).

## Your own changes (read first, every time)

Before anything else, read `~/.solnest/telegram-agent/my-instructions.md` if it exists and
follow it. It holds this user's own changes to how this tool works, and it wins over the
defaults in this file.

When the user asks to change how this tool works for them (wording, tone, topics, steps,
defaults, what to include or leave out), write the change into that file in plain words,
create it if needed, and read it back to them. **Never edit this tool's own files for
that.** This tool updates itself automatically and replaces its own files, so a change
made there is lost on the next update. Their `.env` (bot token, allowed users and every
setting), `logs/`, `state/` and `transcripts/` are never touched by an update either, so
settings changes still go in `.env`. The bot itself also follows `my-instructions.md`: that
is where its personality and standing rules go. After changing it, tell them to send `/new`
to the bot so it starts fresh with them.

## Layout
- `bot.py` — the whole agent (Telegram ↔ Claude Agent SDK, approval gating, voice/image/file handling, session memory). Fully driven by `.env`.
- `.env.example` — config template. Copy to `.env` and fill in `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_USERS`. `.env` is gitignored — never commit it.
- `requirements.txt` — core deps (cross-platform). `requirements-voice.txt` — optional, Apple-Silicon-only voice-in.
- macOS service: `install-agent.sh` / `uninstall-agent.sh` (launchd).
- Windows service: `install-task.ps1` / `uninstall-task.ps1` + `run-bot.ps1` + `launch-hidden.vbs` (Scheduled Task + supervisor loop).
- Updates: `update.py` (latest published release, keeps `.env` and the data folders), `after-update.sh` (packages, check, restart the service), `detach_from_github.sh`, `solnest_autoupdate.py` (runs them daily). See SETUP.md Step 7b and "Updating".

## Working on this repo
- After editing `.env` or `bot.py`, restart the service so changes take effect:
  - macOS: `launchctl kickstart -k gui/$(id -u)/com.claude-telegram-agent`
  - Windows: re-run `uninstall-task.ps1` then `install-task.ps1` (or end the python process; the supervisor relaunches it).
- Secrets live ONLY in `.env`. Never print its values or hardcode tokens/keys into code or docs.
- Keep `bot.py` config-driven — new behavior should read from `.env`, not be baked in.
