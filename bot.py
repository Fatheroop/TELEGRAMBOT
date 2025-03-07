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

# -----------------------------
# Conversation states for /batchsend
BATCH_COLLECT, BATCH_GET_PREFIX, BS_TARGET_A, BS_TARGET_B = range(100, 104)

# File to store attached chats
GROUPS_FILE = "groups.json"
# File to store the bot password
PASSWORD_FILE = "password.json"

# -----------------------------
# Utility functions
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

def save_password(new_password):
    with open(PASSWORD_FILE, "w") as f:
        json.dump({"password": new_password}, f)

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

# -----------------------------
# Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------
# Authentication Decorator
def require_login(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.user_data.get("authenticated", False):
            await update.effective_message.reply_text("Access denied. Please login using /login <password>.")
            return
        return await func(update, context)
    return wrapper

# -----------------------------
# /login command
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /login <password>")
        return
    user_input = args[0]
    current_password = load_password()
    if user_input == current_password:
        context.user_data["authenticated"] = True
        await update.effective_message.reply_text("Login successful!")
    else:
        await update.effective_message.reply_text("Incorrect password.")

# -----------------------------
# /changepassword command
@require_login
async def changepassword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 2:
        await update.effective_message.reply_text("Usage: /changepassword <old_password> <new_password>")
        return
    old, new = args[0], args[1]
    if old != load_password():
        await update.effective_message.reply_text("Old password incorrect.")
        return
    save_password(new)
    await update.effective_message.reply_text("Password changed successfully.")

# -----------------------------
# /addgroup: add current chat to attached list
@require_login
async def addgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    groups = load_groups()
    chat_id = str(chat.id)
    chat_title = chat.title if chat.title else (chat.username if chat.username else "Unnamed Chat")
    if chat_id in groups:
        await update.effective_message.reply_text(f"Chat '{groups[chat_id]}' is already attached.")
    else:
        groups[chat_id] = chat_title
        save_groups(groups)
        await update.effective_message.reply_text(f"Chat '{chat_title}' added successfully.")

# -----------------------------
# /addprivatechannel: manual only (usage: /addprivatechannel <channel_id> [custom name])
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
        await update.effective_message.reply_text(f"Channel '{groups[channel_id]}' is already attached.")
    else:
        groups[channel_id] = custom_name
        save_groups(groups)
        await update.effective_message.reply_text(f"Private channel '{custom_name}' added successfully.")

# -----------------------------
# /listgroups: list attached chats
@require_login
async def listgroups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    groups = load_groups()
    if not groups:
        await update.effective_message.reply_text("No attached chats yet.")
    else:
        text = "Attached Chats:\n" + "\n".join(f"- {title} (ID: {chat_id})" for chat_id, title in groups.items())
        await update.effective_message.reply_text(text)

# -----------------------------
# /batchsend Conversation (only batch send is supported for efficiency)
@require_login
async def batchsend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["files"] = []
    await update.effective_message.reply_text("Batch Send: Send files one by one. When finished, type /done.")
    return BATCH_COLLECT

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
        additional = str(file_info.duration)  # store raw duration (seconds)
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
    await msg.reply_text(f"File received. Total: {len(context.user_data['files'])}. Send another file or type /done.")
    return BATCH_COLLECT

async def batch_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    files = context.user_data.get("files", [])
    if not files:
        await update.effective_message.reply_text("No files received. Batch send cancelled.")
        return ConversationHandler.END
    context.user_data["current_index"] = 0
    current = files[0]
    await update.effective_message.reply_text(f"Batch Send: For file 1 ({current['file_name']}), enter a prefix (or '-' for default).")
    return BATCH_GET_PREFIX

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
        # Show inline buttons for target selection using attached chats
        groups = load_groups()
        if not groups:
            await msg.reply_text("No attached chats available. Use /addgroup or /addprivatechannel.")
            return ConversationHandler.END
        buttons_a = [[InlineKeyboardButton(title, callback_data=f"bs_targetA:{chat_id}")]
                     for chat_id, title in groups.items()]
        await msg.reply_text("Batch Send: Select target chat for sending files (Target A):", reply_markup=InlineKeyboardMarkup(buttons_a))
        return BS_TARGET_A

async def bs_select_target_a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    target_a = query.data.split("bs_targetA:")[1]
    context.user_data["target_a"] = target_a
    buttons_b = [[InlineKeyboardButton(title, callback_data=f"bs_targetB:{chat_id}")]
                 for chat_id, title in load_groups().items()]
    await query.message.reply_text("Batch Send: Select target chat for sending hyperlinks (Target B):", reply_markup=InlineKeyboardMarkup(buttons_b))
    return BS_TARGET_B

async def bs_select_target_b(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    target_b = query.data.split("bs_targetB:")[1]
    context.user_data["target_b"] = target_b
    bot = context.bot
    results = []
    for i, fdict in enumerate(context.user_data.get("files", []), start=1):
        try:
            if fdict["file_type"] == "document":
                sent = await bot.send_document(
                    chat_id=context.user_data["target_a"],
                    document=fdict["file_info"].file_id,
                    caption=f"Forwarded file: {fdict['file_name']}"
                )
            elif fdict["file_type"] == "photo":
                sent = await bot.send_photo(
                    chat_id=context.user_data["target_a"],
                    photo=fdict["file_info"].file_id,
                    caption="Forwarded photo"
                )
            elif fdict["file_type"] == "video":
                sent = await bot.send_video(
                    chat_id=context.user_data["target_a"],
                    video=fdict["file_info"].file_id,
                    caption="Forwarded video"
                )
            cid = sent.chat.id
            if isinstance(cid, int) and str(cid).startswith("-100"):
                link_cid = str(cid)[4:]
            else:
                link_cid = str(cid)
            mid = sent.message_id
            hyperlink_url = f"https://t.me/c/{link_cid}/{mid}"
            size_str = format_file_size(getattr(fdict["file_info"], "file_size", None))
            dur_str = format_duration(fdict.get("additional")) if fdict.get("additional") and fdict.get("additional").isdigit() else ""
            suffix = f" (Size: {size_str}"
            if dur_str:
                suffix += f", Duration: {dur_str}"
            suffix += ")"
            hyperlink_text = f"{fdict.get('prefix', fdict['file_name'])}{suffix}"
            hyperlink_msg = f"[{hyperlink_text}]({hyperlink_url})"
            await bot.send_message(chat_id=context.user_data["target_b"], text=hyperlink_msg, parse_mode="Markdown")
            results.append(f"File {i} sent successfully.")
        except Exception as e:
            results.append(f"File {i} error: {e}")
    await query.message.reply_text("Batch Send Completed:\n" + "\n".join(results))
    return ConversationHandler.END

def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set.")
        return
    app = Application.builder().token(BOT_TOKEN).build()

    # Public commands: /start and /commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("commands", commands_list))

    # Protected commands: require login
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("changepassword", changepassword))
    app.add_handler(CommandHandler("addgroup", addgroup))
    app.add_handler(CommandHandler("addprivatechannel", addprivatechannel))
    app.add_handler(CommandHandler("listgroups", listgroups))
    app.add_handler(CommandHandler("batchsend", batchsend_command))

    # Batchsend conversation
    bs_conv = ConversationHandler(
        entry_points=[CommandHandler("batchsend", batchsend_command)],
        states={
            BATCH_COLLECT: [
                MessageHandler(filters.ALL & ~filters.COMMAND, bs_collect_file),
                CommandHandler("done", batch_done)
            ],
            BATCH_GET_PREFIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, bs_receive_prefix)],
            BS_TARGET_A: [CallbackQueryHandler(bs_select_target_a, pattern=r"^bs_targetA:")],
            BS_TARGET_B: [CallbackQueryHandler(bs_select_target_b, pattern=r"^bs_targetB:")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    app.add_handler(bs_conv)

    # Run webhook if WEBHOOK_URL is set, otherwise run polling.
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        PORT = int(os.getenv("PORT", "8443"))
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN,
                        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
