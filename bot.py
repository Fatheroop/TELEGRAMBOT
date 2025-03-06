from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Bot settings
settings = {
    "password": "12345",
    "upload_groups": [],  # List of group invite links
    "fetch_groups": [],   # List of group invite links
    "integrated_bots": []  # List of bot tokens
}

# Dictionary to track users entering settings password
user_password_attempts = {}

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("\ud83d\udce4 Upload File", callback_data='upload')],
        [InlineKeyboardButton("\ud83d\udce5 Fetch File", callback_data='fetch_file')],
        [InlineKeyboardButton("\u2699\ufe0f Settings", callback_data='settings')],
        [InlineKeyboardButton("\ud83e\udd16 Manage Bots", callback_data='manage_bots')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=reply_markup)

# Handle button clicks
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "upload":
        await query.message.reply_text("Send the file you want to upload.")
    elif query.data == "fetch_file":
        await query.message.reply_text("Fetching files... Select a group:", reply_markup=get_group_buttons("fetch"))
    elif query.data == "settings":
        user_password_attempts[query.from_user.id] = "settings"
        await query.message.reply_text("Enter the password to access settings:")
    elif query.data == "manage_bots":
        user_password_attempts[query.from_user.id] = "bots"
        await query.message.reply_text("Enter the password to manage integrated bots:")

# Handle password entry
async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in user_password_attempts:
        if update.message.text == settings["password"]:
            option = user_password_attempts[user_id]
            del user_password_attempts[user_id]

            if option == "settings":
                await update.message.reply_text("Settings menu:", reply_markup=get_settings_buttons())
            elif option == "bots":
                await update.message.reply_text("Manage Bots:", reply_markup=get_bot_settings_buttons())
        else:
            await update.message.reply_text("\u274c Wrong password! Try again.")
    else:
        await update.message.reply_text("Invalid command.")

# Get settings menu buttons
def get_settings_buttons():
    keyboard = [
        [InlineKeyboardButton("\u2795 Add Group", callback_data="add_group")],
        [InlineKeyboardButton("\u2796 Remove Group", callback_data="remove_group")],
        [InlineKeyboardButton("\ud83d\udd11 Change Password", callback_data="change_password")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Get bot management buttons
def get_bot_settings_buttons():
    keyboard = [
        [InlineKeyboardButton("\u2795 Add Bot", callback_data="add_bot")],
        [InlineKeyboardButton("\u2796 Remove Bot", callback_data="remove_bot")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Get group selection buttons
def get_group_buttons(action):
    groups = settings["fetch_groups"] if action == "fetch" else settings["upload_groups"]
    keyboard = [[InlineKeyboardButton(f"Group {i+1}", url=group)] for i, group in enumerate(groups)]
    return InlineKeyboardMarkup(keyboard) if groups else None

# Handle file uploads
async def file_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document or update.message.video or update.message.audio or update.message.photo[-1]
    if file:
        await update.message.reply_text("Select a group to upload the file:", reply_markup=get_group_buttons("upload"))

# Handle adding bots
async def add_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings["integrated_bots"].append(update.message.text)
    await update.message.reply_text("\u2705 Bot added successfully!")

# Handle removing bots
async def remove_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text in settings["integrated_bots"]:
        settings["integrated_bots"].remove(update.message.text)
        await update.message.reply_text("\u274c Bot removed successfully!")
    else:
        await update.message.reply_text("Bot not found.")

# Main function
def main():
    app = Application.builder().token("7883838296:AAEbNXZVmiA9GlUsqtKGWhrk-Bs5OTQOmVI").build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, file_upload_handler))

    # Run the bot
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
