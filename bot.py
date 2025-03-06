import os
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    CallbackContext,
)

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("RENDER_WEBHOOK_URL")
ADMIN_PASSWORD = "12345"  # Default admin password

if not TOKEN or not WEBHOOK_URL:
    raise ValueError("Error: TELEGRAM_BOT_TOKEN or RENDER_WEBHOOK_URL is missing in .env file!")

# Initialize the bot application
app = Application.builder().token(TOKEN).build()

# Global dictionaries to track user sessions and group data
user_sessions = {}  # e.g., { chat_id: { "step": "waiting_for_file", ... } }
group_data = {}     # To store group details for file operations (dummy implementation)

# ======================= Command and Callback Handlers =======================

# /start command: show main menu
async def start(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("📤 Upload File", callback_data="upload")],
        [InlineKeyboardButton("📥 Fetch File", callback_data="fetch")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🔹 Select an option:", reply_markup=reply_markup)

# Initiate file upload process
async def upload_file(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("📂 Send the file you want to upload.")
    user_sessions[query.message.chat_id] = {"step": "waiting_for_file"}

# Receive file and ask for group selection
async def receive_file(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    if user_id not in user_sessions or user_sessions[user_id].get("step") != "waiting_for_file":
        return

    # Use available media types from the message:
    file = update.message.document or update.message.video or update.message.audio or update.message.photo[-1]
    file_type = (
        "document" if update.message.document
        else "video" if update.message.video
        else "audio" if update.message.audio
        else "photo"
    )
    user_sessions[user_id] = {
        "step": "waiting_for_group",
        "file": file,
        "file_type": file_type
    }
    await update.message.reply_text("📌 Select the group/topic to upload to.")

# Dummy fetch file handler (to be implemented)
async def fetch_file(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if not group_data:
        await query.message.reply_text("❌ No files found.")
        return
    keyboard = [[InlineKeyboardButton(f"{group}", callback_data=f"fetch_{group}")]
                for group in group_data]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("📂 Choose a group:", reply_markup=reply_markup)

# Settings: ask for password
async def settings(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("🔑 Enter password to access settings.")
    user_sessions[query.message.chat_id] = {"step": "waiting_for_password"}

# Verify the provided password for settings access
async def verify_password(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    if user_id not in user_sessions or user_sessions[user_id].get("step") != "waiting_for_password":
        return

    if update.message.text == ADMIN_PASSWORD:
        keyboard = [
            [InlineKeyboardButton("➕ Add Bot", callback_data="add_bot")],
            [InlineKeyboardButton("➖ Remove Bot", callback_data="remove_bot")],
            [InlineKeyboardButton("🔧 Manage Groups", callback_data="manage_groups")],
            [InlineKeyboardButton("🔑 Change Password", callback_data="change_password")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("⚙️ Settings Menu:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("❌ Incorrect password!")
    user_sessions[user_id]["step"] = None

# Handle button callbacks
async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if query.data == "upload":
        await upload_file(update, context)
    elif query.data == "fetch":
        await fetch_file(update, context)
    elif query.data == "settings":
        await settings(update, context)

# ======================= Register Handlers =======================
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
# Use the correct filters for media: documents, photos, audio, and video.
app.add_handler(MessageHandler(
    filters.Document.ALL | filters.PHOTO | filters.AUDIO | filters.VIDEO, 
    receive_file
))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, verify_password))

# ======================= Main Function: Webhook Setup and Run =======================
async def main():
    print("🚀 Bot is starting...")
    # Set webhook for Render deployment
    await app.bot.set_webhook(WEBHOOK_URL)
    # Run webhook listener
    await app.run_webhook(
        listen="0.0.0.0",
        port=8443,
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL
    )

# ======================= Run the Bot =======================
if __name__ == "__main__":
    asyncio.run(main())
