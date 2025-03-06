import os
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Load environment variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("RENDER_APP_URL")  # Set this in Render

# Configure logging
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Password-protected settings
BOT_PASSWORD = "12345"
admin_access = False  # Track admin login

def check_password(user_input):
    global admin_access
    if user_input == BOT_PASSWORD:
        admin_access = True
        return "Access granted. You can now modify settings."
    return "Incorrect password. Try again."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Upload", callback_data='upload')],
                [InlineKeyboardButton("Fetch File", callback_data='fetch')],
                [InlineKeyboardButton("Settings", callback_data='settings')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "upload":
        await query.message.reply_text("Send the file you want to upload.")
    elif query.data == "fetch":
        await query.message.reply_text("Fetching files...")
    elif query.data == "settings":
        await query.message.reply_text("Enter password to access settings:")

async def file_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document or update.message.photo or update.message.audio
    if file:
        await update.message.reply_text(f"File received: {file.file_name}")
    else:
        await update.message.reply_text("Please send a valid file.")

async def webhook_setup():
    app = Application.builder().token(TOKEN).build()
    await app.bot.set_webhook(url=WEBHOOK_URL)
    logger.info("Webhook set successfully.")

async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ATTACHMENT, file_upload_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
