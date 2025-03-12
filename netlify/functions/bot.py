import os
import json
import asyncio
import logging
import requests
import nest_asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
)
import telegram.ext.filters as filters
from deep_translator import GoogleTranslator  # For translation

# Apply nest_asyncio so that asyncio.run works in serverless environments
nest_asyncio.apply()

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Retrieve the bot token from environment variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set.")

MAX_CAPTION_LENGTH = 1024

# Conversation states
CONFIRM, ASK_IMAGES, ASK_TRANSLATE, ASK_SEASON = range(4)

# --- Helper Functions ---

def search_media(query: str, media_type: str):
    """
    Searches for the given query in the specified media type ("anime" or "manga").
    Returns a list of result dictionaries.
    """
    url = f"https://api.jikan.moe/v4/{media_type}?q={query}&limit=10"
    response = requests.get(url)
    if response.status_code != 200:
        return []
    data = response.json()
    return data.get("data", [])


def select_best_match(results: list, query: str):
    """
    Selects the best match from a list of results.
    Checks for an exact title match (ignoring case) or returns the first result.
    """
    query_lower = query.lower()
    for item in results:
        title = item.get("title", "").lower()
        if title == query_lower or query_lower in title:
            return item
    return results[0] if results else None


def get_media_info(query: str):
    """
    Searches first in anime; if not found then in manga.
    Returns a dictionary with media details and a 'media_type' key ("Anime" or "Manga").
    Also retrieves the broadcast field (airing schedule) for anime.
    """
    anime_results = search_media(query, "anime")
    best = select_best_match(anime_results, query) if anime_results else None
    media_type = "Anime" if best else None

    if not best:
        manga_results = search_media(query, "manga")
        best = select_best_match(manga_results, query) if manga_results else None
        if best:
            media_type = "Manga"

    if not best:
        return None

    title = best.get("title", "N/A")
    synopsis = best.get("synopsis", "N/A")
    genres_list = [genre.get("name") for genre in best.get("genres", [])]
    genres = ", ".join(genres_list) if genres_list else "N/A"

    # For anime, use "aired" for end date and "broadcast" for schedule; for manga, use "published"
    date_info = "Not available"
    broadcast = "Not available"
    if media_type == "Anime":
        aired = best.get("aired", {})
        date_info = aired.get("to", "Not available")
        broadcast = best.get("broadcast", "Not available")
    else:
        published = best.get("published", {})
        date_info = published.get("to", "Not available")

    image_url = best.get("images", {}).get("jpg", {}).get("image_url", "")
    mal_id = best.get("mal_id")

    # Attempt to fetch character information
    characters = []
    if mal_id:
        char_url = f"https://api.jikan.moe/v4/{media_type.lower()}/{mal_id}/characters"
        char_resp = requests.get(char_url)
        if char_resp.status_code == 200:
            char_data = char_resp.json()
            for item in char_data.get("data", []):
                char_name = item.get("character", {}).get("name", "N/A")
                char_img = item.get("character", {}).get("images", {}).get("jpg", {}).get("image_url", "")
                characters.append((char_name, char_img))

    return {
        "media_type": media_type,
        "title": title,
        "synopsis": synopsis,
        "genres": genres,
        "date_info": date_info,
        "broadcast": broadcast,
        "image_url": image_url,
        "characters": characters,
    }

# --- Conversation Handler Functions ---

async def media_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Entry point: Search for media using the user's query and ask for confirmation.
    """
    query = update.message.text
    context.user_data['query'] = query
    info = get_media_info(query)
    if not info:
        await update.message.reply_text("Sorry, no media found for your query.")
        return ConversationHandler.END
    context.user_data['info'] = info
    reply = f"I found: {info['title']}. Is that the anime/manga you meant? (Yes/No)"
    await update.message.reply_text(reply)
    return CONFIRM


async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handle the user's confirmation of the found media.
    """
    answer = update.message.text.lower()
    if answer in ['yes', 'y']:
        await update.message.reply_text("Do you want images? (Yes/No)")
        return ASK_IMAGES
    else:
        await update.message.reply_text("Okay, please refine your query.")
        return ConversationHandler.END


async def ask_images_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Ask the user if they want images.
    """
    answer = update.message.text.lower()
    context.user_data['images'] = answer in ['yes', 'y']
    await update.message.reply_text("Do you want to translate the synopsis to English? (Yes/No)")
    return ASK_TRANSLATE


async def ask_translate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Ask the user if they want to translate the synopsis.
    """
    answer = update.message.text.lower()
    context.user_data['translate'] = answer in ['yes', 'y']
    await update.message.reply_text("If the series has multiple seasons, enter the season number (or type 'skip' to use default).")
    return ASK_SEASON


async def ask_season_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handle season input. If a season number is provided, re-search with season info.
    Then prepare and send the final response.
    """
    answer = update.message.text.lower()
    if answer == 'skip':
        season = None
    else:
        try:
            season = int(answer)
        except ValueError:
            season = None
    context.user_data['season'] = season

    query = context.user_data['query']
    info = context.user_data['info']

    if season:
        new_query = f"{query} season {season}"
        new_info = get_media_info(new_query)
        if new_info:
            info = new_info
            context.user_data['info'] = info

    # Build the reply message
    reply_text = (
        f"Type: {info['media_type']}\n"
        f"Title: {info['title']}\n\n"
        f"Synopsis: {info['synopsis']}\n\n"
        f"Genres: {info['genres']}\n\n"
        f"Date Info: {info['date_info']}\n"
        f"Broadcast: {info['broadcast']}\n\n"
        f"Characters:\n"
    )
    for char in info["characters"]:
        reply_text += f"- {char[0]}\n"

    if len(reply_text) > MAX_CAPTION_LENGTH:
        reply_text = reply_text[: MAX_CAPTION_LENGTH - 3] + "..."

    # Translate synopsis if requested
    if context.user_data.get('translate'):
        try:
            translated_synopsis = GoogleTranslator(source='auto', target='en').translate(info['synopsis'])
            reply_text = reply_text.replace(info['synopsis'], translated_synopsis)
        except Exception as e:
            logger.error("Translation error: %s", e)

    # Send the final response based on the images option
    if context.user_data.get('images'):
        try:
            await update.message.reply_photo(photo=info["image_url"], caption=reply_text)
        except Exception as e:
            logger.error("Error sending photo: %s", e)
            await update.message.reply_text(reply_text)
        for char in info["characters"]:
            if char[1]:
                try:
                    await update.message.reply_photo(photo=char[1], caption=char[0])
                except Exception as e:
                    logger.error("Error sending character photo: %s", e)
    else:
        await update.message.reply_text(reply_text)

    return ConversationHandler.END


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    await update.message.reply_text("Hello! Send me the name of an anime or manga, and I'll fetch its details for you.")


# --- Build the Application ---

# Create the Application instance and register handlers (this is built once per function invocation)
application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, media_query_handler)],
    states={
        CONFIRM: [MessageHandler(filters.TEXT, confirm_handler)],
        ASK_IMAGES: [MessageHandler(filters.TEXT, ask_images_handler)],
        ASK_TRANSLATE: [MessageHandler(filters.TEXT, ask_translate_handler)],
        ASK_SEASON: [MessageHandler(filters.TEXT, ask_season_handler)],
    },
    fallbacks=[CommandHandler("cancel", cancel_handler)],
)
application.add_handler(CommandHandler("start", start_command))
application.add_handler(conv_handler)

# --- Netlify Function Handler ---

async def process_update_async(update_data):
    """Process a Telegram update asynchronously."""
    update = Update.de_json(update_data, application.bot)
    await application.process_update(update)

def handler(event, context):
    """
    Netlify function entry point.
    Expects the HTTP request body to be the JSON update from Telegram.
    """
    try:
        update_data = json.loads(event["body"])
    except Exception as e:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"Invalid JSON: {str(e)}"})
        }
    try:
        asyncio.run(process_update_async(update_data))
    except Exception as e:
        logger.error("Error processing update: %s", e)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
    return {
        "statusCode": 200,
        "body": json.dumps({"status": "ok"})
    }
