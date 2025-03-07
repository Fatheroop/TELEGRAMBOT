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
# States for /sendfile conversation
GET_FILE, GET_PREFIX, GET_TARGET_A, GET_TARGET_B = range(4)

# States for /batchsend conversation
BATCH_COLLECT = 100
BATCH_GET_PREFIX = 101
BATCH_SELECT_TARGET_A = 102
BATCH_SELECT_TARGET_B = 103

# States for /addprivatechannel conversation
ADD_PRIV_CHOICE = 210
ADD_PRIV_FORWARD = 211
ADD_PRIV_ID = 212
ADD_PRIV_CUSTOMNAME = 213

# -----------------------------
# File to persist attached chats
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

# -----------------------------
# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------------
# Main Menu (persistent inline keyboard)
def get_main_menu_keyboard():
    buttons = [
        [InlineKeyboardButton("Send File", callback_data="menu_sendfile"),
         InlineKeyboardButton("Batch Send", callback_data="menu_batchsend")],
        [InlineKeyboardButton("Retrieve Media", callback_data="menu_retrievemedia")],
        [InlineKeyboardButton("Add Group", callback_data="menu_addgroup"),
         InlineKeyboardButton("Add Private Channel", callback_data="menu_addprivatechannel")],
        [InlineKeyboardButton("List Groups", callback_data="menu_listgroups")]
    ]
    return InlineKeyboardMarkup(buttons)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("Main Menu:", reply_markup=get_main_menu_keyboard())
    elif update.callback_query:
        await update.callback_query.message.reply_text("Main Menu:", reply_markup=get_main_menu_keyboard())

# -----------------------------
# /start command shows main menu
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = "Welcome! Use the menu below to choose an option."
    await update.effective_message.reply_text(text, reply_markup=get_main_menu_keyboard())

# -----------------------------
# Main Menu Handler (for inline buttons)
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "menu_sendfile":
        await sendfile_command(update, context)
    elif data == "menu_batchsend":
        await batchsend_command(update, context)
    elif data == "menu_retrievemedia":
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please send the Telegram hyperlink for media retrieval (format: https://t.me/c/<chatid>/<message_id>)."
        )
    elif data == "menu_addgroup":
        await addgroup(update, context)
    elif data == "menu_addprivatechannel":
        await addprivatechannel_start(update, context)
    elif data == "menu_listgroups":
        await listgroups(update, context)
    else:
        await query.edit_message_text("Invalid selection.")

# -----------------------------
# /addgroup: add current chat to attached list
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
    await show_main_menu(update, context)

# -----------------------------
# /addprivatechannel conversation:
# Option 1: Forward a message from your private channel
# Option 2: Manually enter channel ID then custom name
async def addprivatechannel_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    buttons = [
        [InlineKeyboardButton("Forward Message", callback_data="addPriv_forward"),
         InlineKeyboardButton("Enter Channel ID", callback_data="addPriv_id")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.effective_message.reply_text("How would you like to add your private channel?", reply_markup=reply_markup)
    return ADD_PRIV_CHOICE

async def addprivatechannel_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "addPriv_forward":
        await query.edit_message_text("Please forward a message from your private channel to this chat.")
        return ADD_PRIV_FORWARD
    elif data == "addPriv_id":
        await query.edit_message_text("Please enter the private channel ID (e.g., -1001234567890).")
        return ADD_PRIV_ID
    else:
        await query.edit_message_text("Invalid selection.")
        return ConversationHandler.END

async def addprivatechannel_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    if msg.forward_from_chat and msg.forward_from_chat.type == "channel":
        channel = msg.forward_from_chat
        channel_id = str(channel.id)
        channel_title = channel.title if channel.title else (channel.username if channel.username else "Unnamed Private Channel")
        groups = load_groups()
        if channel_id in groups:
            await msg.reply_text(f"Private channel '{groups[channel_id]}' is already attached.")
        else:
            groups[channel_id] = channel_title
            save_groups(groups)
            await msg.reply_text(f"Private channel '{channel_title}' added successfully.")
        await show_main_menu(update, context)
        return ConversationHandler.END
    else:
        await msg.reply_text("That doesn't appear to be a forwarded message from a private channel. Please forward a valid message or type /cancel.")
        return ADD_PRIV_FORWARD

async def addprivatechannel_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    text = msg.text.strip() if msg.text else ""
    if not text.startswith("-100"):
        await msg.reply_text("Channel ID should start with -100. Please try again or type /cancel.")
        return ADD_PRIV_ID
    context.user_data["new_channel_id"] = text
    await msg.reply_text("Please enter a custom name for this channel, or type '-' to use the default.")
    return ADD_PRIV_CUSTOMNAME

async def addprivatechannel_customname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    custom_name = msg.text.strip() if msg.text else ""
    channel_id = context.user_data.get("new_channel_id")
    if not channel_id:
        await msg.reply_text("Channel ID missing. Please try /addprivatechannel again.")
        return ConversationHandler.END
    groups = load_groups()
    if custom_name == "-" or custom_name == "":
        custom_name = "PrivateChannel_" + channel_id
    groups[channel_id] = custom_name
    save_groups(groups)
    await msg.reply_text(f"Private channel '{custom_name}' added successfully.")
    await show_main_menu(update, context)
    return ConversationHandler.END

# -----------------------------
# /listgroups: list all attached chats
async def listgroups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    groups = load_groups()
    if not groups:
        await update.effective_message.reply_text("No attached chats yet.")
    else:
        msg = "Attached Chats:\n"
        for chat_id, title in groups.items():
            msg += f"- {title} (ID: {chat_id})\n"
        await update.effective_message.reply_text(msg)
    await show_main_menu(update, context)

# -----------------------------
# /retrievemedia: forward media from a Telegram hyperlink
async def retrievemedia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    text = msg.text.strip() if msg.text else ""
    pattern = r"https://t\.me/c/(\d+)/(\d+)"
    match = re.search(pattern, text)
    if not match:
        await msg.reply_text("No valid Telegram hyperlink found. Use format: https://t.me/c/<chatid>/<message_id>")
        return
    chat_part, message_id_str = match.groups()
    try:
        message_id = int(message_id_str)
    except ValueError:
        await msg.reply_text("Invalid message ID in the URL.")
        return
    from_chat_id = f"-100{chat_part}"
    try:
        await context.bot.forward_message(
            chat_id=msg.chat.id,
            from_chat_id=from_chat_id,
            message_id=message_id
        )
        await msg.reply_text("Media retrieved and forwarded below.")
    except Exception as e:
        await msg.reply_text(f"Error retrieving media: {e}")
    await show_main_menu(update, context)

# -----------------------------
# /sendfile conversation (single file send)
async def sendfile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("Please send me the file (document, photo, or video).")
    return GET_FILE

async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    file_info, file_type, file_name, file_size, additional_info = None, None, None, None, ""
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
        f"Please provide a prefix for the hyperlink text (default is: {file_name}).\nSend '-' to use the default."
    )
    return GET_PREFIX

async def receive_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    text = msg.text.strip() if msg.text else ""
    prefix = context.user_data.get("file_name", "File") if text in ["-", ""] else text
    context.user_data["prefix"] = prefix
    groups = load_groups()
    if not groups:
        await msg.reply_text("No attached chats available. Please use /addgroup or /addprivatechannel.")
        return ConversationHandler.END
    buttons = []
    for chat_id, title in groups.items():
        buttons.append([InlineKeyboardButton(text=title, callback_data=f"targetA:{chat_id}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await msg.reply_text("Select the target chat for sending the file (Target A):", reply_markup=reply_markup)
    return GET_TARGET_A

async def select_target_a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    return GET_TARGET_B

async def select_target_b(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    await show_main_menu(update, context)
    return ConversationHandler.END

# -----------------------------
# /batchsend conversation (optimized)
async def batchsend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["files"] = []
    await update.effective_message.reply_text("Batch Send: Please send the files one by one. When finished, type /done.")
    return BATCH_COLLECT

async def batch_collect_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    file_info, file_type, file_name, file_size, additional_info = None, None, None, None, ""
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
        return BATCH_COLLECT
    file_dict = {
        "file_info": file_info,
        "file_type": file_type,
        "file_name": file_name,
        "file_size": file_size,
        "additional_info": additional_info,
        "prefix": None,
    }
    context.user_data["files"].append(file_dict)
    await msg.reply_text(f"File received. Total files: {len(context.user_data['files'])}.\nSend another file or type /done if finished.")
    return BATCH_COLLECT

async def batch_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    files = context.user_data.get("files", [])
    if not files:
        await update.effective_message.reply_text("No files received. Batch send cancelled.")
        return ConversationHandler.END
    context.user_data["current_index"] = 0
    current_file = files[0]
    await update.effective_message.reply_text(f"Batch Send: For file 1 ({current_file['file_name']}), please provide a prefix (send '-' to use default).")
    return BATCH_GET_PREFIX

async def batch_receive_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    text = msg.text.strip() if msg.text else ""
    index = context.user_data.get("current_index", 0)
    files = context.user_data.get("files", [])
    current_file = files[index]
    prefix = current_file["file_name"] if text in ["-", ""] else text
    current_file["prefix"] = prefix
    index += 1
    context.user_data["current_index"] = index
    if index < len(files):
        next_file = files[index]
        await msg.reply_text(f"Batch Send: For file {index+1} ({next_file['file_name']}), please provide a prefix (send '-' to use default).")
        return BATCH_GET_PREFIX
    else:
        buttons = []
        groups = load_groups()
        if not groups:
            await msg.reply_text("No attached chats available. Please use /addgroup or /addprivatechannel.")
            return ConversationHandler.END
        for chat_id, title in groups.items():
            buttons.append([InlineKeyboardButton(text=title, callback_data=f"batchTargetA:{chat_id}")])
        reply_markup = InlineKeyboardMarkup(buttons)
        await msg.reply_text("Batch Send: Select the target chat for sending the files (Target A):", reply_markup=reply_markup)
        return BATCH_SELECT_TARGET_A

async def batch_select_target_a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("batchTargetA:"):
        target_a = data.split("batchTargetA:")[1]
        context.user_data["target_group_a"] = target_a
        await query.edit_message_text(f"Batch Send: Selected Target A: {target_a}")
    else:
        await query.edit_message_text("Invalid selection.")
        return ConversationHandler.END
    buttons = []
    groups = load_groups()
    for chat_id, title in groups.items():
        buttons.append([InlineKeyboardButton(text=title, callback_data=f"batchTargetB:{chat_id}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.reply_text("Batch Send: Select the target chat for sending the hyperlink messages (Target B):", reply_markup=reply_markup)
    return BATCH_SELECT_TARGET_B

async def batch_select_target_b(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("batchTargetB:"):
        target_b = data.split("batchTargetB:")[1]
        context.user_data["target_group_b"] = target_b
        await query.edit_message_text(f"Batch Send: Selected Target B: {target_b}")
    else:
        await query.edit_message_text("Invalid selection.")
        return ConversationHandler.END
    bot = context.bot
    results = []
    target_a = context.user_data["target_group_a"]
    target_b = context.user_data["target_group_b"]
    for idx, fdict in enumerate(context.user_data["files"], start=1):
        try:
            if fdict["file_type"] == "document":
                sent_message = await bot.send_document(
                    chat_id=target_a,
                    document=fdict["file_info"].file_id,
                    caption=f"Forwarded file: {fdict['file_name']}"
                )
            elif fdict["file_type"] == "photo":
                sent_message = await bot.send_photo(
                    chat_id=target_a,
                    photo=fdict["file_info"].file_id,
                    caption="Forwarded photo"
                )
            elif fdict["file_type"] == "video":
                sent_message = await bot.send_video(
                    chat_id=target_a,
                    video=fdict["file_info"].file_id,
                    caption="Forwarded video"
                )
            cid = sent_message.chat.id
            if isinstance(cid, int) and str(cid).startswith("-100"):
                link_cid = str(cid)[4:]
            else:
                link_cid = str(cid)
            mid = sent_message.message_id
            hyperlink_url = f"https://t.me/c/{link_cid}/{mid}"
            file_size = fdict.get("file_size", "Unknown")
            additional_info = fdict.get("additional_info", "")
            suffix = f" (Size: {file_size} bytes{additional_info})"
            prefix = fdict.get("prefix", fdict["file_name"])
            hyperlink_text = f"{prefix}{suffix}"
            hyperlink_message = f"[{hyperlink_text}]({hyperlink_url})"
            await bot.send_message(chat_id=target_b, text=hyperlink_message, parse_mode="Markdown")
            results.append(f"File {idx} sent successfully.")
        except Exception as e:
            results.append(f"File {idx} error: {e}")
    await query.message.reply_text("Batch Send Completed:\n" + "\n".join(results))
    await show_main_menu(update, context)
    return ConversationHandler.END

# -----------------------------
# /retrievemedia: retrieve media from hyperlink
async def retrievemedia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    text = msg.text.strip() if msg.text else ""
    pattern = r"https://t\.me/c/(\d+)/(\d+)"
    match = re.search(pattern, text)
    if not match:
        await msg.reply_text("No valid Telegram hyperlink found. Use format: https://t.me/c/<chatid>/<message_id>")
        return
    chat_part, message_id_str = match.groups()
    try:
        message_id = int(message_id_str)
    except ValueError:
        await msg.reply_text("Invalid message ID in the URL.")
        return
    from_chat_id = f"-100{chat_part}"
    try:
        await context.bot.forward_message(
            chat_id=msg.chat.id,
            from_chat_id=from_chat_id,
            message_id=message_id
        )
        await msg.reply_text("Media retrieved and forwarded below.")
    except Exception as e:
        await msg.reply_text(f"Error retrieving media: {e}")
    await show_main_menu(update, context)

# -----------------------------
# Main function: register handlers and run bot
def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set.")
        return
    application = Application.builder().token(BOT_TOKEN).build()

    # Main menu handler for inline buttons (all options start with "menu_")
    application.add_handler(CallbackQueryHandler(main_menu_handler, pattern="^menu_"))

    # /start command
    application.add_handler(CommandHandler("start", start))

    # /addgroup command
    application.add_handler(CommandHandler("addgroup", addgroup))

    # /addprivatechannel conversation
    addpriv_conv = ConversationHandler(
        entry_points=[CommandHandler("addprivatechannel", addprivatechannel_start)],
        states={
            ADD_PRIV_CHOICE: [CallbackQueryHandler(addprivatechannel_choice)],
            ADD_PRIV_FORWARD: [MessageHandler(filters.ALL & ~filters.COMMAND, addprivatechannel_forward)],
            ADD_PRIV_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, addprivatechannel_id)],
            ADD_PRIV_CUSTOMNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addprivatechannel_customname)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    application.add_handler(addpriv_conv)

    # /listgroups command
    application.add_handler(CommandHandler("listgroups", listgroups))

    # /retrievemedia command
    application.add_handler(CommandHandler("retrievemedia", retrievemedia))

    # /sendfile conversation (entry via /sendfile or main menu)
    sendfile_conv = ConversationHandler(
        entry_points=[
            CommandHandler("sendfile", sendfile_command),
            CallbackQueryHandler(lambda u, c: sendfile_command(u, c), pattern="^menu_sendfile$")
        ],
        states={
            GET_FILE: [MessageHandler(filters.ALL & ~filters.COMMAND, receive_file)],
            GET_PREFIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prefix)],
            GET_TARGET_A: [CallbackQueryHandler(select_target_a, pattern=r"^targetA:")],
            GET_TARGET_B: [CallbackQueryHandler(select_target_b, pattern=r"^targetB:")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    application.add_handler(sendfile_conv)

    # /batchsend conversation (entry via /batchsend or main menu)
    batchsend_conv = ConversationHandler(
        entry_points=[
            CommandHandler("batchsend", batchsend_command),
            CallbackQueryHandler(lambda u, c: batchsend_command(u, c), pattern="^menu_batchsend$")
        ],
        states={
            BATCH_COLLECT: [
                MessageHandler(filters.ALL & ~filters.COMMAND, batch_collect_file),
                CommandHandler("done", batch_done)
            ],
            BATCH_GET_PREFIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, batch_receive_prefix)],
            BATCH_SELECT_TARGET_A: [CallbackQueryHandler(batch_select_target_a, pattern=r"^batchTargetA:")],
            BATCH_SELECT_TARGET_B: [CallbackQueryHandler(batch_select_target_b, pattern=r"^batchTargetB:")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    application.add_handler(batchsend_conv)

    # Run webhook if WEBHOOK_URL is set; otherwise, run polling.
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
