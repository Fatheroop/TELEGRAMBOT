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

# ----- Helper functions for formatting -----
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
    if seconds is None:
        return ""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    else:
        return f"{m:02d}:{s:02d}"

# ----- Conversation states for /sendfile (single send) -----
GET_FILE, GET_PREFIX, SF_TARGET_A, SF_TARGET_B = range(4)

# ----- States for /batchsend conversation -----
BATCH_COLLECT, BATCH_GET_PREFIX, BS_TARGET_A, BS_TARGET_B = range(100, 104)

# ----- File for storing attached chats -----
GROUPS_FILE = "groups.json"

def load_groups():
    try:
        with open(GROUPS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_groups(groups):
    with open(GROUPS_FILE, "w") as f:
        json.dump(groups, f)

# ----- Logging -----
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# ----- /start and /commands -----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = (
        "Welcome to FileLink Bot!\n\n"
        "Available commands:\n"
        "/commands – Show command list\n"
        "/addgroup – Add current chat to attached list\n"
        "/addprivatechannel <channel_id> [custom name] – Manually add a private channel\n"
        "/listgroups – List attached chats\n"
        "/retrievemedia – Retrieve media from a Telegram hyperlink\n"
        "/sendfile – Send a file (single file send flow)\n"
        "/batchsend – Batch send multiple files\n"
    )
    await update.effective_message.reply_text(welcome_text)

async def commands_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

# ----- /addgroup -----
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

# ----- /addprivatechannel (manual only) -----
# Usage: /addprivatechannel <channel_id> [custom name]
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

# ----- /listgroups -----
async def listgroups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    groups = load_groups()
    if not groups:
        await update.effective_message.reply_text("No attached chats yet.")
    else:
        text = "Attached Chats:\n" + "\n".join(f"- {title} (ID: {chat_id})" for chat_id, title in groups.items())
        await update.effective_message.reply_text(text)

# ----- /retrievemedia -----
async def retrievemedia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    text = msg.text.strip() if msg.text else ""
    pattern = r"https://t\.me/c/(\d+)/(\d+)"
    match = re.search(pattern, text)
    if not match:
        await msg.reply_text("No valid Telegram hyperlink found. Use: https://t.me/c/<chatid>/<message_id>")
        return
    chat_part, msg_id_str = match.groups()
    try:
        msg_id = int(msg_id_str)
    except ValueError:
        await msg.reply_text("Invalid message ID in the URL.")
        return
    from_chat_id = f"-100{chat_part}"
    try:
        await context.bot.forward_message(
            chat_id=msg.chat.id,
            from_chat_id=from_chat_id,
            message_id=msg_id
        )
        await msg.reply_text("Media retrieved and forwarded.")
    except Exception as e:
        await msg.reply_text(f"Error retrieving media: {e}")

# ----- /sendfile Conversation (Single File Send) -----
async def sendfile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("Sendfile: Please send the file (document, photo, or video).")
    return GET_FILE

async def sf_receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        additional = f"{file_info.duration}"  # duration in seconds; will be reformatted later
    else:
        await msg.reply_text("Unsupported file type. Send a document, photo, or video.")
        return GET_FILE
    context.user_data.update({
        "file_info": file_info,
        "file_type": file_type,
        "file_name": file_name,
        "raw_duration": file_info.duration if hasattr(file_info, "duration") else None
    })
    await msg.reply_text(f"Enter prefix for hyperlink (default: {file_name}). Type '-' for default.")
    return GET_PREFIX

async def sf_receive_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    text = msg.text.strip() if msg.text else ""
    prefix = context.user_data.get("file_name") if text in ["-", ""] else text
    context.user_data["prefix"] = prefix
    groups = load_groups()
    if not groups:
        await msg.reply_text("No attached chats available. Use /addgroup or /addprivatechannel.")
        return ConversationHandler.END
    # Build inline buttons from attached chats
    buttons_a = [[InlineKeyboardButton(title, callback_data=f"sf_targetA:{chat_id}")]
                 for chat_id, title in groups.items()]
    await msg.reply_text("Select target chat for sending the file (Target A):", reply_markup=InlineKeyboardMarkup(buttons_a))
    return SF_TARGET_A

async def sf_select_target_a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    target_a = query.data.split("sf_targetA:")[1]
    context.user_data["target_a"] = target_a
    buttons_b = [[InlineKeyboardButton(title, callback_data=f"sf_targetB:{chat_id}")]
                 for chat_id, title in load_groups().items()]
    await query.message.reply_text("Select target chat for sending the hyperlink (Target B):", reply_markup=InlineKeyboardMarkup(buttons_b))
    return SF_TARGET_B

async def sf_select_target_b(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    target_b = query.data.split("sf_targetB:")[1]
    context.user_data["target_b"] = target_b
    bot = context.bot
    try:
        if context.user_data["file_type"] == "document":
            sent_msg = await bot.send_document(
                chat_id=context.user_data["target_a"],
                document=context.user_data["file_info"].file_id,
                caption=f"Forwarded file: {context.user_data['file_name']}"
            )
        elif context.user_data["file_type"] == "photo":
            sent_msg = await bot.send_photo(
                chat_id=context.user_data["target_a"],
                photo=context.user_data["file_info"].file_id,
                caption="Forwarded photo"
            )
        elif context.user_data["file_type"] == "video":
            sent_msg = await bot.send_video(
                chat_id=context.user_data["target_a"],
                video=context.user_data["file_info"].file_id,
                caption="Forwarded video"
            )
        # Build hyperlink from sent message
        chat_id = sent_msg.chat.id
        if isinstance(chat_id, int) and str(chat_id).startswith("-100"):
            link_chat = str(chat_id)[4:]
        else:
            link_chat = str(chat_id)
        msg_id = sent_msg.message_id
        hyperlink_url = f"https://t.me/c/{link_chat}/{msg_id}"
        size_bytes = getattr(context.user_data["file_info"], "file_size", None)
        size_str = format_file_size(size_bytes) if size_bytes else "Unknown"
        dur = context.user_data.get("raw_duration")
        dur_str = format_duration(dur) if dur else ""
        suffix = f" (Size: {size_str}"
        if dur_str:
            suffix += f", Duration: {dur_str}"
        suffix += ")"
        hyperlink_text = f"{context.user_data.get('prefix')}{suffix}"
        hyperlink_msg = f"[{hyperlink_text}]({hyperlink_url})"
        await bot.send_message(chat_id=context.user_data["target_b"], text=hyperlink_msg, parse_mode="Markdown")
        await query.message.reply_text("File and hyperlink sent successfully.")
    except Exception as e:
        await query.message.reply_text(f"Error: {e}")
    return ConversationHandler.END

# ----- /batchsend Conversation -----
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
        additional = f"{file_info.duration}"  # raw duration in seconds
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
        buttons_a = [[InlineKeyboardButton(title, callback_data=f"bs_targetA:{chat_id}")]
                     for chat_id, title in load_groups().items()]
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
            size_bytes = getattr(fdict["file_info"], "file_size", None)
            size_str = format_file_size(size_bytes) if size_bytes else "Unknown"
            dur = fdict.get("additional")
            dur_str = format_duration(dur) if dur and dur.isdigit() else ""
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

# ----- Helper formatting functions -----
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

# ----- Main Function -----
def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set.")
        return
    app = Application.builder().token(BOT_TOKEN).build()

    # /start and /commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("commands", commands_list))

    # /addgroup
    app.add_handler(CommandHandler("addgroup", addgroup))

    # /addprivatechannel
    app.add_handler(CommandHandler("addprivatechannel", addprivatechannel))

    # /listgroups
    app.add_handler(CommandHandler("listgroups", listgroups))

    # /retrievemedia
    app.add_handler(CommandHandler("retrievemedia", retrievemedia))

    # /sendfile conversation
    sf_conv = ConversationHandler(
        entry_points=[CommandHandler("sendfile", sendfile_command)],
        states={
            GET_FILE: [MessageHandler(filters.ALL & ~filters.COMMAND, sf_receive_file)],
            GET_PREFIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, sf_receive_prefix)],
            SF_TARGET_A: [CallbackQueryHandler(sf_select_target_a, pattern=r"^sf_targetA:")],
            SF_TARGET_B: [CallbackQueryHandler(sf_select_target_b, pattern=r"^sf_targetB:")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    app.add_handler(sf_conv)

    # /batchsend conversation
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

    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        PORT = int(os.getenv("PORT", "8443"))
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN,
                        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
