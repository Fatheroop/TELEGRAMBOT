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

# Define conversation states for the file process.
GET_FILE, GET_PREFIX, GET_TARGET_GROUP_A, GET_TARGET_GROUP_B = range(4)

# File to persist attached chats.
GROUPS_FILE = "groups.json"

# Utility functions to load and save attached chats.
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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Basic Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "Welcome!\n\n"
        "Available commands (works in any chat):\n"
        "/sendfile - Start the file forwarding process.\n"
        "/addgroup - Register this chat as attached (for later selection).\n"
        "/listgroups - List all attached chats.\n\n"
        "How to connect chats:\n"
        "1. Add the bot to any chat (group, supergroup, or channel) and promote it if needed.\n"
        "2. In that chat, type /addgroup to attach it.\n"
        "3. Use /listgroups to see all attached chats."
    )
    await update.message.reply_text(help_text)

# --- Conversation for sending files and creating hyperlink message ---
async def sendfile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Please send me the file (document, photo, or video).")
    return GET_FILE

async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    file_info = None
    file_type = None
    file_name = None
    file_size = None
    additional_info = ""

    if message.document:
        file_info = message.document
        file_type = "document"
        file_name = file_info.file_name
        file_size = file_info.file_size
    elif message.photo:
        file_info = message.photo[-1]
        file_type = "photo"
        file_name = "photo.jpg"
        file_size = file_info.file_size
    elif message.video:
        file_info = message.video
        file_type = "video"
        file_name = file_info.file_name if file_info.file_name else "video.mp4"
        file_size = file_info.file_size
        additional_info = f", duration: {file_info.duration}s"
    else:
        await update.message.reply_text("Unsupported file type. Please send a document, photo, or video.")
        return GET_FILE

    context.user_data['file_info'] = file_info
    context.user_data['file_type'] = file_type
    context.user_data['file_name'] = file_name
    context.user_data['file_size'] = file_size
    context.user_data['additional_info'] = additional_info

    await update.message.reply_text(
        f"Please provide a prefix for the hyperlink text (default is file name: {file_name}).\n"
        "Send '-' to use the default."
    )
    return GET_PREFIX

async def receive_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "-" or not text:
        prefix = context.user_data.get('file_name', 'File')
    else:
        prefix = text
    context.user_data['prefix'] = prefix

    # Instead of requiring text input, show an inline keyboard populated from attached chats.
    groups = load_groups()
    if not groups:
        await update.message.reply_text("No attached chats available. Please use /addgroup in a chat to attach it.")
        return ConversationHandler.END

    buttons = []
    for chat_id, title in groups.items():
        buttons.append([InlineKeyboardButton(text=title, callback_data=f"targetA:{chat_id}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Select the target chat for forwarding the file (Target A):", reply_markup=reply_markup)
    return GET_TARGET_GROUP_A

async def select_target_group_a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()  # Acknowledge the callback
    data = query.data
    if data.startswith("targetA:"):
        target_a = data.split("targetA:")[1]
        context.user_data['target_group_a'] = target_a
        await query.edit_message_text(f"Selected Target A: {target_a}")
    else:
        await query.edit_message_text("Invalid selection.")
        return ConversationHandler.END

    # Ask for target group B using inline keyboard.
    groups = load_groups()
    buttons = []
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
        context.user_data['target_group_b'] = target_b
        await query.edit_message_text(f"Selected Target B: {target_b}")
    else:
        await query.edit_message_text("Invalid selection.")
        return ConversationHandler.END

    # Now forward the file to target A and send the hyperlink to target B.
    bot = context.bot
    target_a = context.user_data['target_group_a']
    file_info = context.user_data['file_info']
    file_type = context.user_data['file_type']

    sent_message = None
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
        # For supergroups/channels, adjust the chat id format.
        if isinstance(chat_id, int) and str(chat_id).startswith("-100"):
            link_chat_id = str(chat_id)[4:]
        else:
            link_chat_id = str(chat_id)
        message_id = sent_message.message_id
        hyperlink_url = f"https://t.me/c/{link_chat_id}/{message_id}"
    except Exception as e:
        await query.message.reply_text(f"Error constructing hyperlink: {e}")
        return ConversationHandler.END

    file_size = context.user_data.get('file_size', 'Unknown')
    additional_info = context.user_data.get('additional_info', '')
    suffix = f" (Size: {file_size} bytes{additional_info})"

    prefix = context.user_data.get('prefix', context.user_data.get('file_name', 'File'))
    hyperlink_text = f"{prefix}{suffix}"
    hyperlink_message = f"[{hyperlink_text}]({hyperlink_url})"

    try:
        await bot.send_message(
            chat_id=context.user_data['target_group_b'],
            text=hyperlink_message,
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.message.reply_text(f"Error sending hyperlink message to Target B: {e}")
        return ConversationHandler.END

    await query.message.reply_text("File forwarded and hyperlink message sent successfully!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# --- Commands for managing attached chats ---
async def addgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    # Allow any chat type (private, group, supergroup, channel)
    groups = load_groups()
    chat_id = str(chat.id)
    # Use chat title if available, otherwise the username; fallback to "Unnamed Chat".
    chat_title = chat.title if chat.title else (chat.username if chat.username else "Unnamed Chat")
    if chat_id in groups:
        await update.message.reply_text(f"Chat '{groups[chat_id]}' is already attached.")
    else:
        groups[chat_id] = chat_title
        save_groups(groups)
        await update.message.reply_text(f"Chat '{chat_title}' added successfully.")

async def listgroups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    groups = load_groups()
    if not groups:
        await update.message.reply_text("No attached chats yet.")
    else:
        msg = "Attached Chats:\n"
        for chat_id, title in groups.items():
            msg += f"- {title} (ID: {chat_id})\n"
        await update.message.reply_text(msg)

# --- Main function ---
def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("sendfile", sendfile_command)],
        states={
            GET_FILE: [MessageHandler(filters.ALL & ~filters.COMMAND, receive_file)],
            GET_PREFIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prefix)],
            # Use callback query handlers for target selection.
            GET_TARGET_GROUP_A: [CallbackQueryHandler(select_target_group_a, pattern=r"^targetA:")],
            GET_TARGET_GROUP_B: [CallbackQueryHandler(select_target_group_b, pattern=r"^targetB:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addgroup", addgroup))
    application.add_handler(CommandHandler("listgroups", listgroups))

    # Use webhook mode if WEBHOOK_URL is set; otherwise use polling.
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

if __name__ == '__main__':
    main()
