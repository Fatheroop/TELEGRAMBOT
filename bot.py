import os
import asyncio
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("RENDER_WEBHOOK_URL")

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Password for settings
SETTINGS_PASSWORD = "12345"
user_states = {}

# Start command
async def start(update: Update, context):
    await update.message.reply_text("Welcome! Use /menu to access options.")

# Main menu
async def menu(update: Update, context):
    keyboard = [
        [InlineKeyboardButton("📤 Upload File", callback_data="upload")],
        [InlineKeyboardButton("📥 Fetch File", callback_data="fetch")],
        [InlineKeyboardButton("⚙ Settings", callback_data="settings")],
    ]
    await update.message.reply_text("Choose an option:", reply_markup=InlineKeyboardMarkup(keyboard))

# Upload file handler
async def file_upload_handler(update: Update, context):
    file = update.message.document or update.message.video or update.message.audio or update.message.photo
    if file:
        await update.message.reply_text(f"File received: {file.file_id}")

# Fetch file (dummy example)
async def fetch_file(update: Update, context):
    await update.callback_query.message.reply_text("Fetching file... (Feature in progress)")

# Settings menu
async def settings(update: Update, context):
    query = update.callback_query
    await query.message.reply_text("Enter password to access settings:")
    user_states[query.from_user.id] = "awaiting_password"

# Password verification
async def password_check(update: Update, context):
    user_id = update.message.from_user.id
    if user_states.get(user_id) == "awaiting_password":
        if update.message.text == SETTINGS_PASSWORD:
            keyboard = [
                [InlineKeyboardButton("➕ Add Bot", callback_data="add_bot")],
                [InlineKeyboardButton("➖ Remove Bot", callback_data="remove_bot")],
                [InlineKeyboardButton("🔄 Change Password", callback_data="change_password")],
            ]
            await update.message.reply_text("Settings unlocked:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text("Incorrect password! Try again.")
        user_states[user_id] = None

# Webhook setup
async def set_webhook():
    app = Application.builder().token(TOKEN).build()
    await app.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook set to: {WEBHOOK_URL}")

# Main function
async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CallbackQueryHandler(fetch_file, pattern="fetch"))
    app.add_handler(CallbackQueryHandler(settings, pattern="settings"))
    app.add_handler(MessageHandler(filters.TEXT, password_check))
    app.add_handler(MessageHandler(filters.ATTACHMENT, file_upload_handler))
    
    # Start webhook
    logger.info("Bot is running...")
    await app.run_webhook(listen="0.0.0.0", port=8443, url_path=TOKEN, webhook_url=WEBHOOK_URL)

# Start bot with correct event loop
if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
