from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

# Dictionary to store settings
settings = {
    "password": "12345",
    "upload_groups": [],
    "fetch_groups": [],
    "integrated_bots": []
}

def start(update: Update, context: CallbackContext):
    keyboard = [[InlineKeyboardButton("Upload", callback_data='upload')],
                [InlineKeyboardButton("Fetch File", callback_data='fetch_file')],
                [InlineKeyboardButton("Settings", callback_data='settings')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Welcome to the bot! Choose an option:", reply_markup=reply_markup)

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data == "upload":
        query.message.reply_text("Send the file you want to upload.")
    elif query.data == "fetch_file":
        if settings["fetch_groups"]:
            keyboard = [[InlineKeyboardButton(link, callback_data=f'fetch_{link}')]
                        for link in settings["fetch_groups"]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.message.reply_text("Select a group to fetch files:", reply_markup=reply_markup)
        else:
            query.message.reply_text("No groups available for fetching.")
    elif query.data == "settings":
        query.message.reply_text("Enter password to access settings.")

def file_upload_handler(update: Update, context: CallbackContext):
    file = update.message.document or update.message.video or update.message.audio or update.message.photo[-1]
    update.message.reply_text("Send the group invitation link to upload the file.")
    context.user_data["file_to_upload"] = file

def group_link_handler(update: Update, context: CallbackContext):
    file = context.user_data.get("file_to_upload")
    if file:
        group_link = update.message.text
        update.message.reply_text(f"File uploaded to {group_link}: {file.file_id}")
        settings["upload_groups"].append(group_link)
        context.user_data["file_to_upload"] = None
    else:
        update.message.reply_text("Invalid request. Please send a file first.")

def password_handler(update: Update, context: CallbackContext):
    user_input = update.message.text
    if user_input == settings["password"]:
        keyboard = [[InlineKeyboardButton("Add Upload Group", callback_data='add_upload_group')],
                    [InlineKeyboardButton("Add Fetch Group", callback_data='add_fetch_group')],
                    [InlineKeyboardButton("Change Password", callback_data='change_password')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text("Settings unlocked. Choose an option:", reply_markup=reply_markup)
    else:
        update.message.reply_text("Incorrect password. Try again.")

def add_group_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.data == "add_upload_group":
        query.message.reply_text("Send the invitation link of the group to add it for uploads.")
        context.user_data["adding_upload_group"] = True
    elif query.data == "add_fetch_group":
        query.message.reply_text("Send the invitation link of the group to add it for fetching.")
        context.user_data["adding_fetch_group"] = True

def group_invite_handler(update: Update, context: CallbackContext):
    link = update.message.text
    if context.user_data.get("adding_upload_group"):
        settings["upload_groups"].append(link)
        update.message.reply_text(f"Added upload group: {link}")
        context.user_data["adding_upload_group"] = False
    elif context.user_data.get("adding_fetch_group"):
        settings["fetch_groups"].append(link)
        update.message.reply_text(f"Added fetch group: {link}")
        context.user_data["adding_fetch_group"] = False
    else:
        update.message.reply_text("Invalid request.")

def main():
    updater = Updater("7883838296:AAEbNXZVmiA9GlUsqtKGWhrk-Bs5OTQOmVI", use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(CallbackQueryHandler(add_group_handler, pattern='add_.*'))
    dp.add_handler(MessageHandler(Filters.document | Filters.video | Filters.audio | Filters.photo, file_upload_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, password_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, group_link_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, group_invite_handler))
    
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
