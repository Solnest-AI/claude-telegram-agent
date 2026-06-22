# Build Your Own Always-On Claude Code Agent on Telegram

Text your computer from anywhere and have Claude actually *do stuff* — run commands,
edit files, hit all your MCP tools (Gmail, Notion, Slack, your CRM, whatever you've got
connected) — 24/7, from your phone. No closing the laptop and losing it. No babysitting
a terminal.

This is the exact setup, packaged so you can clone it and go. We're **not** using the
official Telegram plugin — that thing runs on **bun** and dies on long-running sessions,
so the bot just... stops. We're replacing it with a standalone bot that drives the
**real** Claude engine through the Claude Agent SDK and is supervised by your OS so it
relaunches itself if it ever drops. Rock solid.

Works on **macOS** and **Windows** (Linux too). Takes about 20 minutes. Let's go.

---

## What you'll end up with

- A Telegram bot that's **you, at your computer** — full shell, full file access, every MCP tool and skill you have in Claude Code.
- **It never silently dies.** No bun. Auto-restarts on crash, auto-starts at login, and it's the *only* thing using your bot token (no dropped messages).
- **It remembers** the conversation (and resumes after a restart).
- **Safe stuff runs automatically; risky stuff asks you** with Approve / Deny buttons right in the chat. You decide how locked-down it is.
- **Optional:** voice notes both ways, and logging every conversation to a folder (point it at your Obsidian vault if you use one).
- Uses your **Claude subscription** — no API key, no extra billing.

---

## Before you start

1. **A computer that stays on** — macOS (Apple Silicon recommended) or Windows 10/11. (The bot is cross-platform; only the always-on bits differ per OS.)
2. **Claude Code installed and logged in.** Open a terminal, run `claude`, sign in with your subscription at least once. That's what the bot rides on.
3. **Python 3.10+.**
   - macOS: `python3 --version` (install via [python.org](https://www.python.org/downloads/) or `brew install python` if missing).
   - Windows: `py --version` — if missing, grab it from [python.org/downloads](https://www.python.org/downloads/) and **check "Add to PATH"** during install.
4. **Git** (to clone the repo) — or just download the repo ZIP from GitHub.
5. **A Telegram account** + the app.
6. ~20 minutes.

---

## Step 1 — Create your Telegram bot

1. In Telegram, search for **[@BotFather](https://t.me/BotFather)** and open the chat.
2. Send `/newbot`.
3. Give it a name (e.g. "My Claude Agent") and a username ending in `bot` (e.g. `yourname_claude_bot`).
4. BotFather sends you a **token** that looks like `8717809381:AAH...long-string`. **Copy it and keep it safe** — that token is the keys to your machine. Don't share it.

---

## Step 2 — Get your Telegram user ID

The bot will only listen to *you*. You need your numeric Telegram ID.

1. In Telegram, search for **[@userinfobot](https://t.me/userinfobot)** and open it.
2. Send it any message. It replies with your **Id** (a number like `123456789`).
3. Copy that number.

---

## Step 3 — Get the project + install dependencies

Clone the repo (or download the ZIP and unzip it), then create an isolated Python
environment and install the dependencies.

**macOS / Linux** (Terminal):
```bash
git clone https://github.com/Solnest-AI/claude-telegram-agent.git
cd claude-telegram-agent
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

**Windows** (PowerShell):
```powershell
git clone https://github.com/Solnest-AI/claude-telegram-agent.git
cd claude-telegram-agent
py -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
```

---

## Step 4 — Configure

Copy the template to `.env` and fill in the two required values.

**macOS / Linux:**
```bash
cp .env.example .env
```
**Windows:**
```powershell
copy .env.example .env
```

Open `.env` in any editor and set:

- `TELEGRAM_BOT_TOKEN=` your token from Step 1
- `TELEGRAM_ALLOWED_USERS=` your id from Step 2 (comma-separate to allow more people)

Everything else has a safe default. Notably `PERMISSION_MODE=default` means risky
actions (file writes, deletes, sends) ask you for Approve/Deny first — leave it there
to start. Every key is explained inline in the file.

---

## Step 5 — (Only if you used the official Telegram plugin) turn it off

Skip this if you never set up the official `telegram` channel plugin. If you did,
disable it so it stops fighting your new bot for the same connection:

```bash
claude plugin disable telegram@claude-plugins-official
```

If you're **reusing the same bot token** the plugin used, also clear it from the
plugin's own `.env` and restart any open Claude Code windows. Using a brand-new
BotFather bot (Step 1) avoids all of this.

---

## Step 6 — Test run

Run it in the foreground so you can watch it connect.

**macOS / Linux:**
```bash
.venv/bin/python -u bot.py
```
**Windows:**
```powershell
.\.venv\Scripts\python -u bot.py
```

Within ~30 seconds you should see `Telegram polling started. Bot is live.` and get a
"Claude agent online" message in Telegram. Send it a quick "hi" to confirm it replies.
Then press **Ctrl+C** to stop the test.

---

## Step 7 — Make it always-on

### macOS (launchd)

```bash
bash install-agent.sh
```

That writes a LaunchAgent that starts the bot at login and restarts it on crash.
Manage it:

```bash
# Restart after editing .env or bot.py
launchctl kickstart -k gui/$(id -u)/com.claude-telegram-agent

# Watch logs
tail -f logs/bot.log

# Stop + remove
bash uninstall-agent.sh
```

### Windows (Scheduled Task)

```powershell
powershell -ExecutionPolicy Bypass -File .\install-task.ps1
```

That registers a task that starts the bot at logon and relaunches it if it ever
crashes. Manage it:

```powershell
# Restart after editing .env or bot.py
.\uninstall-task.ps1 ; .\install-task.ps1

# Stop + remove
.\uninstall-task.ps1
```

Logs are in `logs\` either way.

---

## Step 8 — Use it

Message your bot. Try:

- "what's running on this machine right now"
- "create a folder on my desktop called test and put a hello.txt in it" → you'll get an **Approve/Deny** prompt for the file write
- "search my Notion for the onboarding doc" (if you have the Notion connector)
- "what's on my calendar tomorrow"
- send it a **photo** ("what's in this screenshot?") or a **file** (a zip/PDF/CSV) — it saves it and works with it

**Commands:** `/status` (health + what's loaded), `/new` (wipe memory, fresh convo), `/id` (your IDs).

---

## Optional: voice

### Voice-out — spoken replies (any OS)

When you send a **voice note**, the bot can reply with a spoken voice note via
ElevenLabs. You need:

1. **`ffmpeg`** installed (it transcodes the audio):
   - macOS: `brew install ffmpeg`
   - Windows: `winget install Gyan.FFmpeg` (or download from [ffmpeg.org](https://ffmpeg.org/) and add to PATH)
2. An **ElevenLabs API key** and a **voice id**. In `.env` set `ELEVENLABS_API_KEY` and
   `ELEVENLABS_VOICE_ID`, then restart. Leave `ELEVENLABS_API_KEY` blank to keep replies text-only.

### Voice-in — transcribe your voice notes locally (Apple Silicon Mac only)

Transcription runs locally on your Mac's GPU (free, private) using Apple's MLX. Install
the optional dependency:

```bash
.venv/bin/python -m pip install -r requirements-voice.txt
```

Then restart. Now voice notes get transcribed and run as a normal turn. (On Windows/
Linux this isn't available — text, images, files and voice-OUT still work; the bot just
tells you it can't transcribe inbound voice.)

---

## Make it yours (edit `.env`, then restart)

| Want this | Set this |
|---|---|
| Stop **all** approval prompts (full auto) | `PERMISSION_MODE=bypassPermissions` |
| Also auto-run file writes | `AUTO_APPROVE_TOOLS=Bash,BashOutput,Write,Edit` |
| Go back to careful (ask for Bash too) | `AUTO_APPROVE_TOOLS=` (leave empty) |
| Save convos to your Obsidian vault | `VAULT_CAPTURE_DIR=/path/to/Vault/Inbox/Telegram` |
| Limit which folder Claude works in | `CLAUDE_CWD=/path/to/projects` |
| Only load certain skills | `SKILLS=skill-one,skill-two` |
| Skip a broken/slow MCP server | `MCP_EXCLUDE=server-name` |
| Let a teammate use it too | `TELEGRAM_ALLOWED_USERS=111,222` |
| Pin a specific model | `ANTHROPIC_MODEL=claude-opus-4-8` (only if your plan has it) |

---

## Troubleshooting

- **No reply on Telegram.** Check `logs/bot.log`. Most common: token typo in `.env`, or your id isn't in `TELEGRAM_ALLOWED_USERS` (send `/id` — if it says `authorized: False`, fix the id).
- **`Conflict: terminated by other getUpdates`** in the log = something else is using the same bot token. You've got the old plugin or a second copy running. Do Step 5, and make sure only one copy of `bot.py` is running.
- **Connectors (Slack/Notion/etc.) not showing up.** Give it ~15s after startup — they connect lazily. If one says "needs auth," authorize it in the Claude desktop app; the bot picks it up.
- **It didn't come back after a reboot.** Both the macOS LaunchAgent and the Windows task start at **login** — make sure you actually logged in.
- **Python errors on start.** Re-run the `pip install -r requirements.txt` step inside the project's `.venv`.
- **"Couldn't transcribe that… mlx-whisper."** Voice-in is Apple-Silicon only and needs the optional dep — see the voice section above, or just send text.

---

## Run it before login (headless box)

The LaunchAgent / Scheduled Task start the bot when you log in, which is fine for a
machine you're on. For a truly headless box that should run before any login:

- **macOS:** convert the LaunchAgent to a system-level LaunchDaemon (runs as a user with your Claude login).
- **Windows:** install it as a real service with [NSSM](https://nssm.cc/) pointed at `.venv\Scripts\python.exe -u bot.py`, "Log on as" your user account, auto-start + restart-on-exit.

Most people don't need this; the login task is plenty.

---

That's the whole thing. Once it's running you'll wonder how you worked without it — fire
off a task from your phone while you're out, approve the one risky step, and it's done by
the time you're back.

Drop questions in the community and post what you build with it. 🚀
