# Claude Telegram Agent

Text your computer from anywhere and have Claude actually *do stuff* — run commands,
edit files, hit all your MCP tools (Gmail, Notion, Slack, your CRM, whatever you've
got connected) — 24/7, from your phone. Send it a voice note and it talks back.

It's the **real Claude Code engine** (via the Claude Agent SDK), not a chatbot. We're
not using the official Telegram plugin — that one runs on **bun** and dies on
long-running sessions. This is a standalone bot supervised by your OS, so it relaunches
itself if it ever drops. Rock solid.

Works on **macOS** and **Windows** (Linux too). Uses your **Claude subscription** — no
API key, no extra billing.

---

## What you get

- A Telegram bot that's **you, at your computer** — full shell, full file access, every MCP tool and skill you have in Claude Code.
- **It never silently dies.** Auto-restarts on crash, auto-starts at login, and it's the only thing using your bot token (no dropped messages).
- **It remembers** the conversation and resumes after a restart.
- **Safe stuff runs automatically; risky stuff asks you** with Approve / Deny buttons right in the chat. You decide how locked-down it is.
- **Send it anything:** text, photos (it views them), and files (zips, PDFs, CSVs — it saves and handles them).
- **Voice, both ways (optional):** send a voice note → transcribed locally (free, private) → Claude thinks → it can reply with a spoken voice note.
- **Optional:** log every conversation to a folder (point it at an Obsidian vault if you use one).

---

## The three "brains"

| Job | Engine | Where |
|---|---|---|
| Transcribe your voice → text | **Whisper** (Apple MLX) | 🖥️ Local, on your Mac's GPU — free, private *(optional, Apple Silicon only)* |
| Think / produce the reply | **Claude** (Claude Agent SDK) | ☁️ Cloud, via your Claude subscription |
| Speak the reply → voice note | **ElevenLabs** | ☁️ Cloud, via your `ELEVENLABS_API_KEY` *(optional)* |

Text, images, and files need only the cloud "thinking" brain. Voice-in is a Mac-only
extra; voice-out works anywhere with an ElevenLabs key + `ffmpeg`.

---

## Quick start

Full step-by-step (Mac **and** Windows, ~20 min) is in **[SETUP.md](SETUP.md)**. The short version:

1. **Create a bot** with [@BotFather](https://t.me/BotFather) → copy the token. Get your numeric id from [@userinfobot](https://t.me/userinfobot).
2. **Clone + install deps** into a virtual environment:
   ```bash
   git clone https://github.com/Solnest-AI/claude-telegram-agent.git
   cd claude-telegram-agent
   python -m venv .venv
   # macOS/Linux:
   .venv/bin/python -m pip install -r requirements.txt
   # Windows:
   # .\.venv\Scripts\python -m pip install -r requirements.txt
   ```
3. **Configure:** copy `.env.example` → `.env`, paste in your `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USERS`.
4. **Test run** (foreground), confirm it replies in Telegram, then Ctrl+C:
   ```bash
   .venv/bin/python -u bot.py        # macOS/Linux
   # .\.venv\Scripts\python -u bot.py   # Windows
   ```
5. **Make it always-on:**
   - **macOS:** `bash install-agent.sh`
   - **Windows:** `powershell -ExecutionPolicy Bypass -File .\install-task.ps1`

That's it — it now starts at login and relaunches itself if it ever crashes.

---

## Configure (just edit `.env`, then restart)

| Want this | Set this |
|---|---|
| Careful mode — risky actions ask first *(default)* | `PERMISSION_MODE=default` |
| Full auto — **zero** approval prompts | `PERMISSION_MODE=bypassPermissions` |
| Also auto-run file writes | `AUTO_APPROVE_TOOLS=Bash,BashOutput,Write,Edit` |
| Be asked about Bash too (most careful) | `AUTO_APPROVE_TOOLS=` (empty) |
| Limit which folder Claude works in | `CLAUDE_CWD=/path/to/projects` |
| Save convos to an Obsidian vault | `VAULT_CAPTURE_DIR=/path/to/Vault/Inbox/Telegram` |
| Let a teammate use it too | `TELEGRAM_ALLOWED_USERS=111,222` |
| Spoken replies | fill in `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` |

Every key is documented in [`.env.example`](.env.example).

**In-chat commands:** `/status` (health + what's loaded) · `/new` (wipe memory, fresh convo) · `/id` (your IDs).

---

## Security — read this

This bot gives whoever it listens to **full control of your machine** through Claude.
Treat it accordingly:

- **Only your Telegram id(s)** in `TELEGRAM_ALLOWED_USERS` can talk to it. Everyone else is ignored.
- **Your bot token is the keys to your machine.** It lives only in `.env` (gitignored). Never commit it, never share it. If it leaks, revoke it in @BotFather and make a new one.
- **Start in `default` permission mode** so risky actions ask you first. Only move to `bypassPermissions` once you trust the setup and the machine is yours.
- `logs/` and `state/` hold your activity and any files you sent — they're gitignored on purpose. Don't commit them.

---

## How it works (the important bits)

- **It's the real Claude Code engine.** The Agent SDK spawns Claude under the hood and the bot injects every MCP server from your `~/.claude.json`. Your claude.ai connectors (Gmail, Calendar, Slack, Notion, etc.) load on top automatically a few seconds after startup.
- **Memory** = one long-lived Claude session, saved to disk so a restart picks up where you left off. `/new` starts clean.
- **Approvals:** anything in `AUTO_APPROVE_TOOLS` plus read-only tools run instantly; everything else pings you with buttons and waits.
- **It can't be killed by a flaky connection.** `python-telegram-bot` auto-reconnects, the OS supervisor relaunches the process if it dies, and a single-instance lock means you never get two copies fighting over the token.

---

## License

MIT — see [LICENSE](LICENSE). Built by [Solnest AI](https://github.com/Solnest-AI). Build something cool with it. 🚀
