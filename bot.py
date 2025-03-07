import os
import json
import logging
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

# STATES for /sendfile conversation
GET_FILE, GET_PREFIX, GET_TARGET_GROUP_A, GET_TARGET_GROUP_B = range(4)

# STATES for /batchsend conversation
BATCH_FILE, BATCH_PREFIX = range(100, 102)  # using different numbers to avoid collision

# File to persist attached chats.
GROUPS_FILE = "groups.json"

# Utility functions for attached chats.
def load_groups():
    try:
        with open(GROUPS_FILE, "r") as f:
            groups = json.load(f)
    except Exception:
        groups = {}
    return groups

def save_groups(groups):
    with open(GROUPS_FILE, "w") as f:
        json.dump(groups, f)

# Set up logging.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Basic Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "Welcome!\n\n"
        "Available commands (work in any chat):\n"
        "/sendfile - Send a file to selected chats via inline buttons.\n"
        "/batchsend - Batch send a file to all attached chats.\n"
        "/getmid - Extract message ID from a Telegram hyperlink.\n"
        "/addgroup - Register this chat as attached (for later selection).\n"
        "/listgroups - List all attached chats.\n\n"
        "How to connect chats:\n"
        "1. Add the bot to any chat (private, group, supergroup, or channel) and promote if needed.\n"
        "2. In that chat, type /addgroup to attach it.\n"
        "3. Use /listgroups to see all attached chats."
    )
    await update.effective_message.reply_text(help_text)

# --- Conversation for /sendfile (single-target send) ---

async def sendfile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("Please send me the file (document, photo, or video).")
    return GET_FILE

async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    file_info = None
    file_type = None
    file_name = None
    file_size = None
    additional_info = ""
    if msg.document:
        file_info = msg.document
        file_type = "document"
        file_name = file_info.file_name
        file_size = file_info.file_size
    elif msg.photo:
        file_info = msg.photo[-1]
        file_type = "photo"
        file_name = "photo.jpg"
        file_size = file_info.file_size
    elif msg.video:
        file_info = msg.video
        file_type = "video"
        file_name = file_info.file_name if file_info.file_name else "video.mp4"
        file_size = file_info.file_size
        additional_info = f", duration: {file_info.duration}s"
    else:
        await msg.reply_text("Unsupported file type. Please send a document, photo, or video.")
        return GET_FILE
    context.user_data["file_info"] = file_info
    context.user_data["file_type"] = file_type
    context.user_data["file_name"] = file_name
    context.user_data["file_size"] = file_size
    context.user_data["additional_info"] = additional_info
    await msg.reply_text(
        f"Please provide a prefix for the hyperlink text (default is file name: {file_name}).\n"
        "Send '-' to use the default."
    )
    return GET_PREFIX

async def receive_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    text = msg.text.strip() if msg.text else ""
    prefix = context.user_data.get("file_name", "File") if text in ["-", ""] else text
    context.user_data["prefix"] = prefix
    groups = load_groups()
    if not groups:
        await msg.reply_text("No attached chats available. Please use /addgroup in a chat to attach it.")
        return ConversationHandler.END
    buttons = []
    for chat_id, title in groups.items():
        buttons.append([InlineKeyboardButton(text=title, callback_data=f"targetA:{chat_id}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await msg.reply_text("Select the target chat for forwarding the file (Target A):", reply_markup=reply_markup)
    return GET_TARGET_GROUP_A

async def select_target_group_a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("targetA:"):
        target_a = data.split("targetA:")[1]
        context.user_data["target_group_a"] = target_a
        await query.edit_message_text(f"Selected Target A: {target_a}")
    else:
        await query.edit_message_text("Invalid selection.")
        return ConversationHandler.END
    buttons = []
    groups = load_groups()
    for chat_id, title in groups.items():
        buttons.append([InlineKeyboardButton(text=title, callback_data=f"targetB:{chat_id}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.reply_text("Select the target chat for sending the hyperlink message (Target B):", reply_markup=reply_markup)
    return GET_TARGET_GROUP_B

async def select_target_group_b(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("targetB:"):
        target_b = data.split("targetB:")[1]
        context.user_data["target_group_b"] = target_b
        await query.edit_message_text(f"Selected Target B: {target_b}")
    else:
        await query.edit_message_text("Invalid selection.")
        return ConversationHandler.END
    bot = context.bot
    target_a = context.user_data["target_group_a"]
    file_info = context.user_data["file_info"]
    file_type = context.user_data["file_type"]
    try:
        if file_type == "document":
            sent_message = await bot.send_document(
                chat_id=target_a,
                document=file_info.file_id,
                caption=f"Forwarded file: {context.user_data.get('file_name')}"
            )
        elif file_type == "photo":
            sent_message = await bot.send_photo(
                chat_id=target_a,
                photo=file_info.file_id,
                caption="Forwarded photo"
            )
        elif file_type == "video":
            sent_message = await bot.send_video(
                chat_id=target_a,
                video=file_info.file_id,
                caption="Forwarded video"
            )
    except Exception as e:
        await query.message.reply_text(f"Error sending file to Target A: {e}")
        return ConversationHandler.END
    try:
        chat_id = sent_message.chat.id
        if isinstance(chat_id, int) and str(chat_id).startswith("-100"):
            link_chat_id = str(chat_id)[4:]
        else:
            link_chat_id = str(chat_id)
        message_id = sent_message.message_id
        hyperlink_url = f"https://t.me/c/{link_chat_id}/{message_id}"
    except Exception as e:
        await query.message.reply_text(f"Error constructing hyperlink: {e}")
        return ConversationHandler.END
    file_size = context.user_data.get("file_size", "Unknown")
    additional_info = context.user_data.get("additional_info", "")
    suffix = f" (Size: {file_size} bytes{additional_info})"
    prefix = context.user_data.get("prefix", context.user_data.get("file_name", "File"))
    hyperlink_text = f"{prefix}{suffix}"
    hyperlink_message = f"[{hyperlink_text}]({hyperlink_url})"
    try:
        await bot.send_message(
            chat_id=context.user_data["target_group_b"],
            text=hyperlink_message,
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.message.reply_text(f"Error sending hyperlink message to Target B: {e}")
        return ConversationHandler.END
    await query.message.reply_text("File forwarded and hyperlink message sent successfully!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# --- Conversation for /batchsend (send file to all attached chats) ---

async def batchsend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("Batch Send: Please send me the file (document, photo, or video).")
    return BATCH_FILE

async def batch_receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    file_info = None
    file_type = None
    file_name = None
    file_size = None
    additional_info = ""
    if msg.document:
        file_info = msg.document
        file_type = "document"
        file_name = file_info.file_name
        file_size = file_info.file_size
    elif msg.photo:
        file_info = msg.photo[-1]
        file_type = "photo"
        file_name = "photo.jpg"
        file_size = file_info.file_size
    elif msg.video:
        file_info = msg.video
        file_type = "video"
        file_name = file_info.file_name if file_info.file_name else "video.mp4"
        file_size = file_info.file_size
        additional_info = f", duration: {file_info.duration}s"
    else:
        await msg.reply_text("Unsupported file type. Please send a document, photo, or video.")
        return BATCH_FILE
    context.user_data["file_info"] = file_info
    context.user_data["file_type"] = file_type
    context.user_data["file_name"] = file_name
    context.user_data["file_size"] = file_size
    context.user_data["additional_info"] = additional_info
    await msg.reply_text(
        f"Batch Send: Please provide a prefix for the hyperlink text (default is file name: {file_name}).\n"
        "Send '-' to use the default."
    )
    return BATCH_PREFIX

async def batch_receive_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    text = msg.text.strip() if msg.text else ""
    prefix = context.user_data.get("file_name", "File") if text in ["-", ""] else text
    context.user_data["prefix"] = prefix
    groups = load_groups()
    if not groups:
        await msg.reply_text("No attached chats available. Please use /addgroup in a chat to attach it.")
        return ConversationHandler.END
    # For batch send, we iterate over all attached chats.
    bot = context.bot
    results = []
    for chat_id, title in groups.items():
        try:
            if context.user_data["file_type"] == "document":
                sent_message = await bot.send_document(
                    chat_id=chat_id,
                    document=context.user_data["file_info"].file_id,
                    caption=f"Forwarded file: {context.user_data.get('file_name')}"
                )
            elif context.user_data["file_type"] == "photo":
                sent_message = await bot.send_photo(
                    chat_id=chat_id,
                    photo=context.user_data["file_info"].file_id,
                    caption="Forwarded photo"
                )
            elif context.user_data["file_type"] == "video":
                sent_message = await bot.send_video(
                    chat_id=chat_id,
                    video=context.user_data["file_info"].file_id,
                    caption="Forwarded video"
                )
            # Build hyperlink from sent message.
            cid = sent_message.chat.id
            if isinstance(cid, int) and str(cid).startswith("-100"):
                link_cid = str(cid)[4:]
            else:
                link_cid = str(cid)
            mid = sent_message.message_id
            hyperlink_url = f"https://t.me/c/{link_cid}/{mid}"
            file_size = context.user_data.get("file_size", "Unknown")
            additional_info = context.user_data.get("additional_info", "")
            suffix = f" (Size: {file_size} bytes{additional_info})"
            prefix = context.user_data.get("prefix", context.user_data.get("file_name", "File"))
            hyperlink_text = f"{prefix}{suffix}"
            hyperlink_message = f"[{hyperlink_text}]({hyperlink_url})"
            await bot.send_message(chat_id=chat_id, text=hyperlink_message, parse_mode="Markdown")
            results.append(f"{title} (ID: {chat_id})")
        except Exception as e:
            results.append(f"{title} (ID: {chat_id}): Error: {e}")
    await msg.reply_text("Batch send completed:\n" + "\n".join(results))
    return ConversationHandler.END

# --- Command for /getmid (extract message id from hyperlink) ---

async def getmid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    text = msg.text.strip() if msg.text else ""
    # Expecting a URL in format: https://t.me/c/<chatid>/<message_id>
    import re
    pattern = r"https://t\.me/c/(\d+)/(\d+)"
    match = re.search(pattern, text)
    if match:
        chat_part, message_id = match.groups()
        await msg.reply_text(f"Extracted Message ID: {message_id}")
    else:
        await msg.reply_text("No valid Telegram hyperlink found. Please ensure the URL is in the format: https://t.me/c/<chatid>/<message_id>")

# --- Commands for managing attached chats ---

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

async def listgroups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    groups = load_groups()
    if not groups:
        await update.effective_message.reply_text("No attached chats yet.")
    else:
        msg = "Attached Chats:\n"
        for chat_id, title in groups.items():
            msg += f"- {title} (ID: {chat_id})\n"
        await update.effective_message.reply_text(msg)

# --- Main function ---

def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set.")
        return
    application = Application.builder().token(BOT_TOKEN).build()
    # Conversation for /sendfile
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("sendfile", sendfile_command)],
        states={
            GET_FILE: [MessageHandler(filters.ALL & ~filters.COMMAND, receive_file)],
            GET_PREFIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prefix)],
            GET_TARGET_GROUP_A: [CallbackQueryHandler(select_target_group_a, pattern=r"^targetA:")],
            GET_TARGET_GROUP_B: [CallbackQueryHandler(select_target_group_b, pattern=r"^targetB:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    # Conversation for /batchsend
    batch_conv = ConversationHandler(
        entry_points=[CommandHandler("batchsend", batchsend_command)],
        states={
            BATCH_FILE: [MessageHandler(filters.ALL & ~filters.COMMAND, batch_receive_file)],
            BATCH_PREFIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, batch_receive_prefix)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(batch_conv)
    # Command for /getmid
    application.add_handler(CommandHandler("getmid", getmid_command))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addgroup", addgroup))
    application.add_handler(CommandHandler("listgroups", listgroups))
    # Run using webhook if WEBHOOK_URL is set.
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        PORT = int(os.getenv("PORT", "8443"))
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        application.run_polling()

if __name__ == "__main__":
    main()
