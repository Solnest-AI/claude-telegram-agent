"""
Always-on Telegram -> Claude Code agent (cross-platform: macOS / Windows / Linux).

A standalone bot that drives the REAL Claude engine on your machine 24/7 with
full access to your MCP tools, skills, files, and shell. Replaces the official
telegram plugin (which runs on bun and dies on long-running sessions).

  - polls Telegram with python-telegram-bot (robust auto-reconnect, no bun)
  - drives Claude via the Claude Agent SDK, injecting your MCP servers from
    ~/.claude.json with setting_sources=[] (clean isolation: no inherited hooks)
  - keeps ONE long-lived session => conversation memory; resumes across restarts
  - safe/read-only tools auto-run; risky ones (Write/Edit/mutating MCP) ask you
    to Approve/Deny on Telegram. Bash auto-runs by default (see AUTO_APPROVE_TOOLS)
  - text + images + files work everywhere; voice-in (local Whisper) is an optional
    Apple-Silicon extra; voice-out (ElevenLabs) is optional and cross-platform
  - optionally logs a full audit of every turn to a folder (e.g. an Obsidian vault)

Keep it alive with the supervisor for your OS: a launchd LaunchAgent on macOS
(install-agent.sh) or a Scheduled Task on Windows (install-task.ps1) — both
start it at login and restart it on crash. See SETUP.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

# --------------------------------------------------------------------------- #
# Config (everything is driven by the .env next to this file)
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Make stdout/stderr encoding-safe so a stray non-ASCII char in a log line can
# never crash the unattended bot.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USERS = {
    int(x) for x in os.environ.get("TELEGRAM_ALLOWED_USERS", "").replace(" ", "").split(",") if x
}
USER_NAME = os.environ.get("USER_NAME", "Me")
CLAUDE_CWD = os.environ.get("CLAUDE_CWD", os.path.expanduser("~"))
PERMISSION_MODE = os.environ.get("PERMISSION_MODE", "default").strip() or "default"
APPROVAL_TIMEOUT = int(os.environ.get("APPROVAL_TIMEOUT", "300"))
# Model the agent runs on. Leave ANTHROPIC_MODEL empty to use whatever your Claude
# subscription/CLI defaults to (most portable — works on any plan). Set it (e.g.
# claude-opus-4-8) only if you want to pin a specific model you have access to.
MODEL = os.environ.get("ANTHROPIC_MODEL", "").strip()
# Local MLX Whisper model for transcribing voice messages (Apple Silicon GPU).
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo").strip()
# ElevenLabs text-to-speech (spoken replies). Empty key disables it.
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
if ELEVENLABS_API_KEY.startswith("PASTE_"):
    ELEVENLABS_API_KEY = ""
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5").strip()
TTS_MAX_CHARS = int(os.environ.get("TTS_MAX_CHARS", "1000"))
# Tools that auto-run WITHOUT asking (on top of read-only tools). Bash is here by
# default so you aren't prompted for every shell command. For ZERO approvals on
# everything, set PERMISSION_MODE=bypassPermissions instead.
AUTO_APPROVE_TOOLS = {
    t.strip() for t in os.environ.get("AUTO_APPROVE_TOOLS", "Bash,BashOutput").split(",") if t.strip()
}
STATE_DIR = Path(os.environ.get("STATE_DIR", BASE_DIR / "state"))
# Folder that conversation transcripts are appended to (dated .md). Point it at an
# Obsidian vault folder if you want. Set to "none" to disable transcript capture.
_vault_raw = os.environ.get("VAULT_CAPTURE_DIR", str(BASE_DIR / "transcripts"))
VAULT_ENABLED = _vault_raw.strip().lower() not in ("", "none", "off")
VAULT_CAPTURE_DIR = Path(_vault_raw)
LOG_DIR = BASE_DIR / "logs"

# MCP servers from ~/.claude.json to SKIP injecting (e.g. ones that are broken/slow).
MCP_EXCLUDE = {s.strip() for s in os.environ.get("MCP_EXCLUDE", "").split(",") if s.strip()}
# "all" enables every discovered skill; "none" disables; or a comma list of names.
SKILLS_CONFIG = os.environ.get("SKILLS", "all").strip()
CLAUDE_JSON = Path(os.path.expanduser("~")) / ".claude.json"

STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FILE = STATE_DIR / "session_id.txt"

TG_LIMIT = 4000  # Telegram hard limit is 4096; leave headroom

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
logger = logging.getLogger("tg-agent")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
_fh = RotatingFileHandler(LOG_DIR / "bot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
logger.addHandler(_fh)
logger.addHandler(_sh)

# --------------------------------------------------------------------------- #
# Globals shared with the can_use_tool callback
# --------------------------------------------------------------------------- #
CLIENT: ClaudeSDKClient | None = None
APP: Application | None = None
PRIMARY_CHAT: int = next(iter(ALLOWED_USERS), 0)  # in private chats user_id == chat_id
ACTIVE_CHAT: int = PRIMARY_CHAT
QUERY_LOCK = asyncio.Lock()
PENDING: dict[str, dict] = {}  # req_id -> {"fut": Future, "label": str}
TURN_APPROVALS: list[tuple[str, str]] = []  # per-turn (tool, approved|denied|timeout)
VAULT_RESULT_MAX = int(os.environ.get("VAULT_RESULT_MAX", "800"))  # truncate tool-result previews

# --------------------------------------------------------------------------- #
# Tool risk classification
# --------------------------------------------------------------------------- #
SAFE_TOOLS = {
    "Read", "Glob", "Grep", "LS", "NotebookRead", "TodoWrite",
    "WebSearch", "WebFetch", "Task", "BashOutput",
}
RISKY_TOOLS = {"Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "KillBash", "KillShell"}
MUTATING_VERBS = (
    "create", "update", "delete", "remove", "send", "post", "cancel", "charge",
    "refund", "merge", "deploy", "apply", "write", "set_", "add_", "upload",
    "void", "pause", "execute", "insert", "move", "duplicate", "edit_",
    "activate", "deactivate", "publish", "draft", "label", "modify", "patch",
)
READONLY_HINTS = (
    "get_", "list_", "search", "read", "fetch", "find", "check", "status",
    "_get", "retrieve", "describe", "_info", "lookup", "view", "query", "ping",
)


def is_safe(tool_name: str, tool_input: dict) -> bool:
    """Auto-allow read-only ops; everything else asks you via Telegram."""
    if tool_name in RISKY_TOOLS:
        return False
    if tool_name in SAFE_TOOLS:
        return True
    if tool_name.startswith("mcp__"):
        low = tool_name.lower()
        if any(v in low for v in MUTATING_VERBS):
            return False
        if any(s in low for s in READONLY_HINTS):
            return True
        return False  # unknown MCP verb -> ask
    return False  # unknown tool -> ask


def summarize(tool_name: str, tool_input: dict) -> str:
    try:
        if tool_name == "Bash":
            return "$ " + str(tool_input.get("command", ""))[:600]
        if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            return "file: " + str(tool_input.get("file_path") or tool_input.get("notebook_path") or "?")
        if tool_input:
            parts = []
            for k, v in tool_input.items():
                parts.append(f"{k}={str(v)[:120]}")
                if len(parts) >= 4:
                    break
            return "\n".join(parts)[:600]
    except Exception:
        pass
    return "(no details)"


def _result_text(block) -> str:
    """Extract a text preview from a ToolResultBlock (content may be str or list)."""
    try:
        c = getattr(block, "content", None)
        if c is None:
            return ""
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            out = []
            for item in c:
                t = getattr(item, "text", None)
                if t is None and isinstance(item, dict):
                    t = item.get("text") or item.get("content")
                out.append(str(t) if t is not None else str(item))
            return " ".join(out)
        return str(c)
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Permission callback (bridges SDK <-> Telegram inline buttons)
# --------------------------------------------------------------------------- #
async def can_use_tool(tool_name: str, tool_input: dict, context):
    if tool_name in AUTO_APPROVE_TOOLS or is_safe(tool_name, tool_input):
        return PermissionResultAllow()

    req_id = uuid.uuid4().hex[:8]
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    PENDING[req_id] = {"fut": fut, "label": tool_name}

    body = (
        f"⚠️ Approval needed\n"
        f"Tool: {tool_name}\n"
        f"{summarize(tool_name, tool_input)}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"ok:{req_id}"),
        InlineKeyboardButton("⛔ Deny", callback_data=f"no:{req_id}"),
    ]])
    try:
        await APP.bot.send_message(ACTIVE_CHAT or PRIMARY_CHAT, body[:TG_LIMIT], reply_markup=kb)
    except Exception as e:
        logger.error("failed to send approval prompt: %s", e)
        PENDING.pop(req_id, None)
        return PermissionResultDeny(message="Could not deliver approval prompt; denied.")

    try:
        approved = await asyncio.wait_for(fut, timeout=APPROVAL_TIMEOUT)
    except asyncio.TimeoutError:
        PENDING.pop(req_id, None)
        TURN_APPROVALS.append((tool_name, "timeout"))
        logger.info("approval timed out for %s", tool_name)
        return PermissionResultDeny(message="No approval within timeout; denied.")

    if approved:
        TURN_APPROVALS.append((tool_name, "approved"))
        logger.info("APPROVED %s", tool_name)
        return PermissionResultAllow()
    TURN_APPROVALS.append((tool_name, "denied"))
    logger.info("DENIED %s", tool_name)
    return PermissionResultDeny(message="Denied by user.")


# --------------------------------------------------------------------------- #
# Session / memory persistence
# --------------------------------------------------------------------------- #
def load_session() -> str | None:
    try:
        if SESSION_FILE.exists():
            sid = SESSION_FILE.read_text(encoding="utf-8").strip()
            return sid or None
    except Exception:
        pass
    return None


def save_session(sid: str | None):
    if not sid:
        return
    try:
        SESSION_FILE.write_text(sid, encoding="utf-8")
    except Exception as e:
        logger.error("failed to save session id: %s", e)


def capture_to_vault(user_text, reply, actions, approvals, sid, error=None):
    """Append a FULL audit record of one turn: the message, every tool the agent
    ran (with inputs + a result preview), approval decisions, the reply, and any
    error. Called for every turn — including failed ones."""
    if not VAULT_ENABLED:
        return
    try:
        VAULT_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        day = datetime.now().strftime("%Y-%m-%d")
        f = VAULT_CAPTURE_DIR / f"{day}.md"
        new = not f.exists()
        ts = datetime.now().strftime("%H:%M:%S")
        block = []
        if new:
            block.append(f"# Telegram Agent — {day}\n")
        block.append(f"## {ts} — {USER_NAME}\n{user_text}\n")

        if actions:
            block.append("**Actions:**")
            for a in actions:
                line = f"- `{pretty_tool(a['tool'])}` — {a.get('input','')}".rstrip()
                block.append(line)
                if a.get("result"):
                    res = a["result"].replace("\n", " ")[:VAULT_RESULT_MAX]
                    block.append(f"    ↳ {res}")
            block.append("")
        if approvals:
            block.append("**Approvals:** " + ", ".join(f"{t}: {d}" for t, d in approvals) + "\n")
        if error:
            block.append(f"### ⚠️ Error\n{error}\n")
        else:
            block.append(f"### Claude\n{reply}\n")
        block.append(f"<sub>session: {sid or '?'}</sub>\n")
        block.append("\n---\n")
        with f.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(block) + "\n")
    except Exception as e:
        logger.error("vault capture failed: %s", e)


# --------------------------------------------------------------------------- #
# Claude client lifecycle
# --------------------------------------------------------------------------- #
def load_mcp_servers() -> dict:
    """Inject your local MCP servers from ~/.claude.json.

    We do NOT use setting_sources to load them, because that also drags in your
    hooks and pre-approval rules (which would bypass the phone-approval callback).
    Injecting mcp_servers + setting_sources=[] gives full local-MCP parity with
    clean isolation. (Your claude.ai connectors load automatically on top of this.)
    """
    try:
        with CLAUDE_JSON.open(encoding="utf-8") as f:
            servers = json.load(f).get("mcpServers", {})
    except Exception as e:
        logger.error("could not read mcpServers from %s: %s", CLAUDE_JSON, e)
        return {}
    kept = {k: v for k, v in servers.items() if k not in MCP_EXCLUDE}
    logger.info("injecting %d MCP servers: %s", len(kept), ", ".join(sorted(kept)))
    return kept


def skills_option():
    if SKILLS_CONFIG.lower() in ("all",):
        return "all"
    if SKILLS_CONFIG.lower() in ("", "none", "off"):
        return None
    return [s.strip() for s in SKILLS_CONFIG.split(",") if s.strip()]


async def build_client(resume: str | None) -> ClaudeSDKClient:
    opts = dict(
        cwd=CLAUDE_CWD,
        mcp_servers=load_mcp_servers(),    # full local MCP parity
        setting_sources=[],                # isolation: no inherited hooks / pre-approvals
        skills=skills_option(),            # enable skills without loading settings
        permission_mode=PERMISSION_MODE,   # "default" -> can_use_tool gates risky ops
        can_use_tool=can_use_tool,
        resume=resume,
        include_partial_messages=False,
    )
    if MODEL:                              # pin a model only if ANTHROPIC_MODEL is set
        opts["model"] = MODEL
    options = ClaudeAgentOptions(**opts)
    client = ClaudeSDKClient(options=options)
    await client.connect()
    return client


async def reconnect(fresh: bool = False):
    global CLIENT
    try:
        if CLIENT:
            await CLIENT.disconnect()
    except Exception:
        pass
    resume = None if fresh else load_session()
    if fresh:
        try:
            SESSION_FILE.unlink(missing_ok=True)
        except Exception:
            pass
    try:
        CLIENT = await build_client(resume)
    except Exception as e:
        logger.error("reconnect with resume failed (%s); starting fresh", e)
        CLIENT = await build_client(None)


# --------------------------------------------------------------------------- #
# Telegram helpers
# --------------------------------------------------------------------------- #
def authorized(update: Update) -> bool:
    u = update.effective_user
    return bool(u and u.id in ALLOWED_USERS)


async def send_chunked(chat_send, text: str):
    text = text or "(no text response)"
    while text:
        chunk = text[:TG_LIMIT]
        if len(text) > TG_LIMIT:
            cut = chunk.rfind("\n")
            if cut > 1000:
                chunk = chunk[:cut]
        await chat_send(chunk)
        text = text[len(chunk):].lstrip("\n")


def pretty_tool(name: str) -> str:
    if name.startswith("mcp__"):
        return name.split("__", 2)[-1]
    return name


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    await update.message.reply_text(
        "✅ Claude agent online.\n"
        "I have full access to this machine, all your MCP tools, and your skills.\n"
        "I remember our conversation. Send me text or a voice note. \U0001f399️\n\n"
        "Commands: /new (fresh memory), /status, /id"
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    async with QUERY_LOCK:
        await reconnect(fresh=True)
    await update.message.reply_text("\U0001f9f9 Memory cleared. Starting a fresh conversation.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    sid = load_session()
    lines = [
        "\U0001f7e2 Online",
        f"cwd: {CLAUDE_CWD}",
        f"permission mode: {PERMISSION_MODE}",
        f"auto-approve: {', '.join(sorted(AUTO_APPROVE_TOOLS)) or '(read-only only)'}",
        f"session: {sid or '(new)'}",
    ]
    try:
        if CLIENT:
            status = await CLIENT.get_mcp_status()
            servers = getattr(status, "servers", None)
            if servers is not None:
                lines.append(f"MCP servers loaded: {len(servers)}")
    except Exception as e:
        lines.append(f"MCP status err: {e}")
    await update.message.reply_text("\n".join(lines))


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"your id: {update.effective_user.id}\nchat id: {update.effective_chat.id}\n"
        f"authorized: {authorized(update)}"
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not (q.from_user and q.from_user.id in ALLOWED_USERS):
        return
    action, _, req_id = (q.data or "").partition(":")
    entry = PENDING.pop(req_id, None)
    approved = action == "ok"
    label = entry["label"] if entry else "?"
    if entry and not entry["fut"].done():
        entry["fut"].set_result(approved)
    try:
        await q.edit_message_text(("✅ Approved: " if approved else "⛔ Denied: ") + label)
    except Exception:
        pass


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ACTIVE_CHAT
    if not authorized(update):
        await update.message.reply_text("Not authorized.")
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    ACTIVE_CHAT = update.effective_chat.id

    if QUERY_LOCK.locked():
        await update.message.reply_text("⏳ Still working on the previous request — queued.")

    async with QUERY_LOCK:
        await handle_query(update, text)


def _transcribe_voice(path: str) -> str:
    """Blocking local transcription via MLX Whisper (Apple Silicon GPU).
    Imported lazily so the bot still starts even if mlx-whisper isn't installed
    (it's an optional, Mac-only extra — see SETUP.md)."""
    try:
        import mlx_whisper
    except ImportError as e:
        raise RuntimeError(
            "Voice transcription needs mlx-whisper (Apple Silicon Mac only). "
            "Install it with `pip install mlx-whisper`, or just send text instead."
        ) from e
    result = mlx_whisper.transcribe(path, path_or_hf_repo=WHISPER_MODEL)
    return (result.get("text") or "").strip()


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Voice notes / audio / video notes -> transcribe locally -> run as a normal turn."""
    global ACTIVE_CHAT
    if not authorized(update):
        await update.message.reply_text("Not authorized.")
        return
    msg = update.message
    media = msg.voice or msg.audio or msg.video_note
    if media is None:
        return
    ACTIVE_CHAT = update.effective_chat.id

    note = await msg.reply_text("\U0001f399️ Transcribing…")
    tmp_path = None
    try:
        tg_file = await media.get_file()
        suffix = ".ogg" if msg.voice else (".mp3" if msg.audio else ".mp4")
        fd, tmp_path = tempfile.mkstemp(suffix=suffix, dir=str(STATE_DIR))
        os.close(fd)
        await tg_file.download_to_drive(tmp_path)
        text = await asyncio.to_thread(_transcribe_voice, tmp_path)
    except Exception as e:
        logger.exception("voice transcription failed")
        try:
            await note.edit_text(f"⚠️ Couldn't transcribe that: {e}")
        except Exception:
            pass
        return
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    if not text:
        try:
            await note.edit_text("\U0001f399️ (couldn't make out any speech)")
        except Exception:
            pass
        return
    try:
        await note.edit_text(f"\U0001f399️ “{text}”")
    except Exception:
        pass

    if QUERY_LOCK.locked():
        await msg.reply_text("⏳ Still working on the previous request — queued.")
    async with QUERY_LOCK:
        await handle_query(update, text, speak=True)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Photos / image documents -> save locally -> agent views them via the Read tool."""
    global ACTIVE_CHAT
    if not authorized(update):
        await update.message.reply_text("Not authorized.")
        return
    msg = update.message
    # Telegram sends photos as a list of sizes (largest last); also accept image documents.
    media = None
    suffix = ".jpg"
    if msg.photo:
        media = msg.photo[-1]
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        media = msg.document
        suffix = os.path.splitext(msg.document.file_name or "")[1] or ".png"
    if media is None:
        return
    ACTIVE_CHAT = update.effective_chat.id

    note = await msg.reply_text("\U0001f5bc️ Got the image, looking…")
    try:
        tg_file = await media.get_file()
        img_dir = STATE_DIR / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        img_path = str(img_dir / f"tg-{uuid.uuid4().hex}{suffix}")
        await tg_file.download_to_drive(img_path)
    except Exception as e:
        logger.exception("photo download failed")
        try:
            await note.edit_text(f"⚠️ Couldn't fetch that image: {e}")
        except Exception:
            pass
        return

    caption = (msg.caption or "").strip()
    prompt = (
        f"[Ryan sent an image. It is saved locally at: {img_path}\n"
        f"View it with the Read tool, then respond to it.]"
    )
    if caption:
        prompt += f"\nHis message with the image: {caption}"

    if QUERY_LOCK.locked():
        await msg.reply_text("⏳ Still working on the previous request — queued.")
    async with QUERY_LOCK:
        await handle_query(update, prompt)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any non-image file (zip, pdf, csv, etc.) -> save locally -> hand the path to the agent."""
    global ACTIVE_CHAT
    if not authorized(update):
        await update.message.reply_text("Not authorized.")
        return
    msg = update.message
    doc = msg.document
    if doc is None:
        return
    ACTIVE_CHAT = update.effective_chat.id

    name = doc.file_name or f"file-{uuid.uuid4().hex}"
    size = doc.file_size or 0
    # Telegram Bot API getFile caps at ~20MB.
    if size and size > 20 * 1024 * 1024:
        await msg.reply_text(
            f"⚠️ That file is {size // (1024*1024)}MB — over Telegram's 20MB bot limit. "
            "Drop it in a folder on the Mac (or Google Drive → make offline) and tell me the path instead."
        )
        return

    note = await msg.reply_text(f"\U0001f4ce Got “{name}”, saving…")
    try:
        tg_file = await doc.get_file()
        files_dir = STATE_DIR / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        safe = name.replace("/", "_").replace("..", "_")
        file_path = str(files_dir / f"{uuid.uuid4().hex[:8]}-{safe}")
        await tg_file.download_to_drive(file_path)
    except Exception as e:
        logger.exception("document download failed")
        try:
            await note.edit_text(f"⚠️ Couldn't fetch that file: {e}")
        except Exception:
            pass
        return

    caption = (msg.caption or "").strip()
    prompt = (
        f"[Ryan sent a file via Telegram.\n"
        f"Saved locally at: {file_path}\n"
        f"Original name: {name} ({size} bytes)\n"
        f"Inspect/handle it as needed (unzip, read, etc.).]"
    )
    if caption:
        prompt += f"\nHis message with the file: {caption}"

    try:
        await note.edit_text(f"\U0001f4ce Saved “{name}” — on it.")
    except Exception:
        pass

    if QUERY_LOCK.locked():
        await msg.reply_text("⏳ Still working on the previous request — queued.")
    async with QUERY_LOCK:
        await handle_query(update, prompt)


def _clean_for_tts(text: str) -> str:
    """Strip code/markdown/URLs so the spoken version sounds natural."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)    # fenced code blocks
    text = re.sub(r"`([^`]*)`", r"\1", text)               # inline code
    text = re.sub(r"https?://\S+", "", text)               # URLs
    text = re.sub(r"[*_#>|]+", "", text)                    # markdown symbols
    text = re.sub(r"[ \t]*\n[ \t]*", ". ", text)           # newlines -> sentence breaks
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _synthesize_speech(text: str) -> bytes | None:
    """ElevenLabs TTS -> OGG/Opus bytes for a Telegram voice note. Blocking; run in a thread."""
    if not (ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID):
        return None
    import time
    import httpx
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    # ElevenLabs (esp. free/scoped keys) can throw a transient 401 during request
    # bursts, so retry once. Log the response body so real failures are diagnosable.
    mp3 = None
    last_err = None
    for attempt in range(2):
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=60.0)
            if r.status_code == 200:
                mp3 = r.content
                break
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            last_err = repr(e)
        logger.warning("ElevenLabs TTS attempt %d failed: %s", attempt + 1, last_err)
        if attempt == 0:
            time.sleep(1.5)
    if mp3 is None:
        raise RuntimeError(f"ElevenLabs TTS failed after retries: {last_err}")
    # Telegram voice notes must be OGG/Opus -> transcode with ffmpeg (stdin->stdout).
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "pipe:1"],
        input=mp3, capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("ffmpeg mp3->ogg failed: " + proc.stderr.decode("utf-8", "replace")[:300])
    return proc.stdout


async def _maybe_speak(update: Update, reply: str):
    """Send a spoken voice-note version of the reply (best-effort; never raises)."""
    if not (ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID and reply):
        return
    spoken = _clean_for_tts(reply)
    if not spoken:
        return
    if len(spoken) > TTS_MAX_CHARS:
        logger.info("reply too long to speak (%d chars > %d); text only", len(spoken), TTS_MAX_CHARS)
        return
    try:
        ogg = await asyncio.to_thread(_synthesize_speech, spoken)
        if ogg:
            await update.message.reply_voice(voice=ogg)
    except Exception as e:
        logger.error("TTS failed: %s", e)


async def handle_query(update: Update, text: str, speak: bool = False):
    global TURN_APPROVALS
    TURN_APPROVALS = []
    status_msg = await update.message.reply_text("\U0001f914 Working…")
    actions: list[dict] = []
    by_id: dict[str, dict] = {}
    parts: list[str] = []
    sid: str | None = None
    try:
        await CLIENT.query(text)
        async for msg in CLIENT.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        a = {"tool": block.name,
                             "input": summarize(block.name, block.input or {}),
                             "result": None}
                        actions.append(a)
                        tid = getattr(block, "id", None)
                        if tid:
                            by_id[tid] = a
                        try:
                            await status_msg.edit_text(f"\U0001f527 {pretty_tool(block.name)}…")
                        except Exception:
                            pass
            elif isinstance(msg, UserMessage):
                content = getattr(msg, "content", None)
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, ToolResultBlock):
                            a = by_id.get(getattr(block, "tool_use_id", None))
                            if a is not None:
                                a["result"] = _result_text(block)
            elif isinstance(msg, ResultMessage):
                sid = msg.session_id
                save_session(sid)
    except Exception as e:
        logger.exception("query failed")
        try:
            await status_msg.edit_text(f"⚠️ Error: {e}\nReconnecting…")
        except Exception:
            pass
        capture_to_vault(text, "", actions, list(TURN_APPROVALS), sid, error=str(e))
        await reconnect(fresh=False)
        return

    reply = "".join(parts).strip()
    if not reply:
        reply = "✅ Done." if actions else "(no response)"
    try:
        await status_msg.delete()
    except Exception:
        pass
    await send_chunked(update.message.reply_text, reply)
    capture_to_vault(text, reply, actions, list(TURN_APPROVALS), sid)
    if speak:
        await _maybe_speak(update, reply)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
_LOCK_SOCK = None


def acquire_single_instance_lock(port: int = 49737) -> bool:
    """Prevent two bot instances from polling the same token (Telegram 409 guard)."""
    global _LOCK_SOCK
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
        _LOCK_SOCK = s  # keep ref alive for process lifetime
        return True
    except OSError:
        return False


async def main():
    global APP, CLIENT
    if not acquire_single_instance_lock():
        logger.error("Another bot instance already holds the lock; exiting to avoid double-polling.")
        sys.exit(0)
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN missing. Fill in .env.")
        sys.exit(1)
    if not ALLOWED_USERS:
        logger.error("TELEGRAM_ALLOWED_USERS missing.")
        sys.exit(1)

    # concurrent_updates(True) is REQUIRED: on_message awaits the approval Future
    # that on_button resolves. With default sequential processing the button update
    # would queue behind the blocked message handler -> deadlock -> approvals time out.
    APP = Application.builder().token(TOKEN).concurrent_updates(True).build()
    APP.add_handler(CommandHandler("start", cmd_start))
    APP.add_handler(CommandHandler("new", cmd_new))
    APP.add_handler(CommandHandler("status", cmd_status))
    APP.add_handler(CommandHandler("id", cmd_id))
    APP.add_handler(CallbackQueryHandler(on_button))
    APP.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    APP.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE, on_voice))
    APP.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_photo))
    APP.add_handler(MessageHandler(filters.Document.ALL & ~filters.Document.IMAGE, on_document))

    logger.info("connecting Claude Agent SDK (loading MCP)…")
    CLIENT = await build_client(load_session())
    logger.info("Claude client connected.")

    await APP.initialize()
    await APP.start()
    await APP.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram polling started. Bot is live.")

    try:
        await APP.bot.send_message(
            PRIMARY_CHAT,
            "✅ Claude agent online. Full access to this machine, your MCP tools, and skills.\n"
            "I remember our chat. Risky actions ask for approval here. Send me anything. /status /new",
        )
    except Exception as e:
        logger.warning("startup ping failed: %s", e)

    await asyncio.Event().wait()  # run forever; launchd KeepAlive supervises


if __name__ == "__main__":
    asyncio.run(main())
