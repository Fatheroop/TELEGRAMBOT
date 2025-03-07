import os
import json
import logging
import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ----- Conversation states for /batchsend -----
BATCH_COLLECT, BATCH_GET_PREFIX, BS_TARGET_A, BS_TARGET_B = range(100, 104)

# ----- Conversation state for /toc -----
TOC_CHOOSE = 300

# ----- Files for persistent storage -----
GROUPS_FILE = "groups.json"
PASSWORD_FILE = "password.json"  # stores {"password": "admin"} by default

# ----- Global Message Logger for TOC -----
# Logs up to 100 messages per chat.
chat_logs = {}  # {chat_id: [ { "message_id": int, "snippet": str }, ... ]}

# ----- Utility Functions -----
def load_groups():
    try:
        with open(GROUPS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_groups(groups):
    with open(GROUPS_FILE, "w") as f:
        json.dump(groups, f)

def load_password():
    try:
        with open(PASSWORD_FILE, "r") as f:
            data = json.load(f)
            return data.get("password", "admin")
    except Exception:
        return "admin"

def save_password(new_pass):
    with open(PASSWORD_FILE, "w") as f:
        json.dump({"password": new_pass}, f)

def format_file_size(size_bytes):
    if size_bytes is None:
        return "Unknown"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024*1024:
        return f"{size_bytes/1024:.2f} KB"
    elif size_bytes < 1024*1024*1024:
        return f"{size_bytes/1024/1024:.2f} MB"
    else:
        return f"{size_bytes/1024/1024/1024:.2f} GB"

def format_duration(seconds):
    try:
        seconds = int(seconds)
    except:
        return ""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    else:
        return f"{m:02d}:{s:02d}"

# ----- Logging -----
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# ----- Global Message Logger for TOC -----
async def log_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup", "channel"]:
        return
    chat_id = str(chat.id)
    msg = update.effective_message
    if not msg:
        return
    snippet = (msg.text or "")[:30] or "Non-text"
    entry = {"message_id": msg.message_id, "snippet": snippet}
    chat_logs.setdefault(chat_id, []).append(entry)
    if len(chat_logs[chat_id]) > 100:
        chat_logs[chat_id] = chat_logs[chat_id][-100:]

# ----- Authentication -----
def require_login(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.user_data.get("authenticated", False):
            await update.effective_message.reply_text("Access denied. Please login using /login <password>.")
            return
        return await func(update, context)
    return wrapper

# ----- Command Handlers -----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Welcome to BatchSend Bot (Protected)!\n\n"
        "Commands:\n"
        "/login <password> – Log in (default: admin)\n"
        "/changepassword <old> <new> – Change password\n"
        "/addgroup – Add current chat to group list\n"
        "/addprivatechannel <channel_id> [custom name] – Add a private channel manually\n"
        "/toc – Get a TOC of recent messages from a selected group\n"
        "/batchsend – Batch send files\n"
        "/commands – Show command list"
    )
    await update.effective_message.reply_text(text)

async def commands_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /login <password>")
        return
    if args[0] == load_password():
        context.user_data["authenticated"] = True
        await update.effective_message.reply_text("Login successful!")
    else:
        await update.effective_message.reply_text("Incorrect password.")

@require_login
async def changepassword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 2:
        await update.effective_message.reply_text("Usage: /changepassword <old> <new>")
        return
    if args[0] != load_password():
        await update.effective_message.reply_text("Old password incorrect.")
        return
    save_password(args[1])
    await update.effective_message.reply_text("Password changed successfully.")

# ----- Group Management (Protected) -----
@require_login
async def addgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    groups = load_groups()
    chat_id = str(chat.id)
    chat_title = chat.title if chat.title else (chat.username if chat.username else "Unnamed Chat")
    if chat_id in groups:
        await update.effective_message.reply_text(f"Chat '{groups[chat_id]}' is already added.")
    else:
        groups[chat_id] = chat_title
        save_groups(groups)
        await update.effective_message.reply_text(f"Chat '{chat_title}' added successfully.")

@require_login
async def addprivatechannel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /addprivatechannel <channel_id> [custom name]")
        return
    channel_id = args[0]
    if not channel_id.startswith("-100"):
        await update.effective_message.reply_text("Channel ID should start with -100.")
        return
    custom_name = " ".join(args[1:]).strip() if len(args) > 1 else f"PrivateChannel_{channel_id}"
    groups = load_groups()
    if channel_id in groups:
        await update.effective_message.reply_text(f"Channel '{groups[channel_id]}' is already added.")
    else:
        groups[channel_id] = custom_name
        save_groups(groups)
        await update.effective_message.reply_text(f"Private channel '{custom_name}' added successfully.")

# ----- /toc: Table of Contents for a selected group (Protected) -----
@require_login
async def toc_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    groups = load_groups()
    if not groups:
        await update.effective_message.reply_text("No groups available. Use /addgroup to add one.")
        return ConversationHandler.END
    buttons = [[InlineKeyboardButton(title, callback_data=f"toc_group:{chat_id}")]
               for chat_id, title in groups.items()]
    await update.effective_message.reply_text("Select a group for TOC:", reply_markup=InlineKeyboardMarkup(buttons))
    return TOC_CHOOSE

@require_login
async def toc_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    group_id = query.data.split("toc_group:")[1]
    msgs = chat_logs.get(group_id, [])
    if not msgs:
        text = "No messages logged for this group."
    else:
        link_id = group_id[4:] if group_id.startswith("-100") else group_id
        lines = [f"[Msg {m['message_id']}: {m['snippet']}](https://t.me/c/{link_id}/{m['message_id']})" for m in msgs]
        text = "\n".join(lines)
    await query.message.reply_text(text, disable_web_page_preview=True)
    return ConversationHandler.END

# ----- /batchsend Conversation (Protected) -----
@require_login
async def batchsend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["files"] = []
    await update.effective_message.reply_text("Batch Send: Send files one by one. When finished, type /done.")
    return BATCH_COLLECT

@require_login
async def bs_collect_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    file_info = None
    file_type = None
    file_name = None
    additional = ""
    if msg.document:
        file_info = msg.document
        file_type = "document"
        file_name = file_info.file_name
    elif msg.photo:
        file_info = msg.photo[-1]
        file_type = "photo"
        file_name = "photo.jpg"
    elif msg.video:
        file_info = msg.video
        file_type = "video"
        file_name = file_info.file_name if file_info.file_name else "video.mp4"
        additional = str(file_info.duration)  # raw duration in seconds
    else:
        await msg.reply_text("Unsupported file type. Send a document, photo, or video.")
        return BATCH_COLLECT
    context.user_data.setdefault("files", []).append({
        "file_info": file_info,
        "file_type": file_type,
        "file_name": file_name,
        "additional": additional,
        "prefix": None
    })
    await msg.reply_text(f"File received. Total files: {len(context.user_data['files'])}. Send another file or type /done.")
    return BATCH_COLLECT

@require_login
async def batch_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    files = context.user_data.get("files", [])
    if not files:
        await update.effective_message.reply_text("No files received. Batch send cancelled.")
        return ConversationHandler.END
    context.user_data["current_index"] = 0
    current = files[0]
    await update.effective_message.reply_text(f"Batch Send: For file 1 ({current['file_name']}), enter a prefix (or '-' for default).")
    return BATCH_GET_PREFIX

@require_login
async def bs_receive_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    text = msg.text.strip() if msg.text else ""
    idx = context.user_data.get("current_index", 0)
    files = context.user_data.get("files", [])
    current = files[idx]
    current["prefix"] = current["file_name"] if text in ["-", ""] else text
    idx += 1
    context.user_data["current_index"] = idx
    if idx < len(files):
        next_file = files[idx]
        await msg.reply_text(f"Batch Send: For file {idx+1} ({next_file['file_name']}), enter a prefix (or '-' for default).")
        return BATCH_GET_PREFIX
    else:
        buttons = [[InlineKeyboardButton(title, callback_data=f"bs_target:{chat_id}")]
                   for chat_id, title in load_groups().items()]
        await msg.reply_text("Batch Send: Select target group to receive all messages:", reply_markup=InlineKeyboardMarkup(buttons))
        return BS_TARGET_A

@require_login
async def bs_select_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    target = query.data.split("bs_target:")[1]
    context.user_data["target"] = target
    bot = context.bot
    results = []
    for i, fdict in enumerate(context.user_data.get("files", []), start=1):
        try:
            if fdict["file_type"] == "document":
                sent = await bot.send_document(chat_id=target, document=fdict["file_info"].file_id,
                                               caption=f"Forwarded file: {fdict['file_name']}")
            elif fdict["file_type"] == "photo":
                sent = await bot.send_photo(chat_id=target, photo=fdict["file_info"].file_id,
                                            caption="Forwarded photo")
            elif fdict["file_type"] == "video":
                sent = await bot.send_video(chat_id=target, video=fdict["file_info"].file_id,
                                            caption="Forwarded video")
            cid = sent.chat.id
            if isinstance(cid, int) and str(cid).startswith("-100"):
                link_cid = str(cid)[4:]
            else:
                link_cid = str(cid)
            mid = sent.message_id
            hyperlink_url = f"https://t.me/c/{link_cid}/{mid}"
            size_str = format_file_size(getattr(fdict["file_info"], "file_size", None))\n            \n            # Format duration only if numeric\n            dur_raw = fdict.get("additional")\n            dur_str = format_duration(dur_raw) if dur_raw and dur_raw.isdigit() else \"\"\n            suffix = f\" (Size: {size_str}\"\n            if dur_str:\n                suffix += f\", Duration: {dur_str}\"\n            suffix += \")\"\n            hyperlink_text = f\"{fdict.get('prefix', fdict['file_name'])}{suffix}\"\n            hyperlink_msg = f\"[{hyperlink_text}]({hyperlink_url})\"\n            await bot.send_message(chat_id=target, text=hyperlink_msg, parse_mode=\"Markdown\")\n            results.append(f\"File {i} sent successfully.\")\n        except Exception as e:\n            results.append(f\"File {i} error: {e}\")\n    await query.message.reply_text(\"Batch Send Completed:\\n\" + \"\\n\".join(results))\n    return ConversationHandler.END

# ----- Main Function -----
def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set.")
        return
    app = Application.builder().token(BOT_TOKEN).build()

    # Public commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("commands", commands_list))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("changepassword", changepassword))

    # Protected commands
    app.add_handler(CommandHandler("addgroup", addgroup))
    app.add_handler(CommandHandler("addprivatechannel", addprivatechannel))
    app.add_handler(CommandHandler("toc", toc_command))
    app.add_handler(CommandHandler("batchsend", batchsend_command))

    # TOC conversation
    toc_conv = ConversationHandler(
        entry_points=[CommandHandler("toc", toc_command)],
        states={
            TOC_CHOOSE: [CallbackQueryHandler(toc_select_group, pattern=r"^toc_group:")]
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    app.add_handler(toc_conv)

    # Batchsend conversation
    bs_conv = ConversationHandler(
        entry_points=[CommandHandler("batchsend", batchsend_command)],
        states={
            BATCH_COLLECT: [
                MessageHandler(filters.ALL & ~filters.COMMAND, bs_collect_file),
                CommandHandler("done", batch_done)
            ],
            BATCH_GET_PREFIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, bs_receive_prefix)],
            BS_TARGET_A: [CallbackQueryHandler(bs_select_target, pattern=r"^bs_target:")]
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    app.add_handler(bs_conv)

    # Log messages for TOC
    app.add_handler(MessageHandler(filters.ChatType(["group", "supergroup", "channel"]) & ~filters.COMMAND, log_messages))

    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        PORT = int(os.getenv("PORT", "8443"))
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN,
                        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
