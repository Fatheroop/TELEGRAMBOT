import os
import logging
import requests
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from flask import Flask, request
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PASSWORD = os.getenv("BOT_PASSWORD", "12345")

# Bot settings
group_links = []  # Stores group invite links
integrated_bots = []  # Stores integrated bots

# Flask app for webhook
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize Telegram Bot
bot = telegram.Bot(token=BOT_TOKEN)
application = Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Upload File", callback_data='upload')],
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
        await query.message.reply_text("Fetching files... (Feature in development)")
    elif query.data == "settings":
        await query.message.reply_text("Enter password to access settings.")
        context.user_data['awaiting_password'] = True

async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_password', False):
        if update.message.text == PASSWORD:
            keyboard = [[InlineKeyboardButton("Add Group", callback_data='add_group')],
                        [InlineKeyboardButton("Remove Group", callback_data='remove_group')],
                        [InlineKeyboardButton("Change Password", callback_data='change_password')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Settings Unlocked:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Incorrect password!")
        context.user_data['awaiting_password'] = False

async def file_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document or update.message.video or update.message.audio or update.message.photo[-1]
    await update.message.reply_text(f"File received: {file.file_id}. Select a group to upload.")

async def webhook(request):
    if request.method == "POST":
        update = Update.de_json(request.json, bot)
        await application.process_update(update)
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def handle_webhook():
    return webhook(request)

async def main():
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT, password_handler))
    application.add_handler(MessageHandler(filters.Document | filters.Audio | filters.Photo, file_upload_handler))
    
    await bot.setWebhook(WEBHOOK_URL + "/webhook")
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
