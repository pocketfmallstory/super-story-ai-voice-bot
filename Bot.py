
import os
import asyncio
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import edge_tts

TOKEN = os.getenv("BOT_TOKEN")

VOICES = {
    "male": "hi-IN-MadhurNeural",
    "female": "hi-IN-SwaraNeural",
    "boy": "hi-IN-MadhurNeural",
    "girl": "hi-IN-SwaraNeural",
    "deep_male": "hi-IN-MadhurNeural",
    "soft_female": "hi-IN-SwaraNeural",
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("Male voice", callback_data="male"),
        InlineKeyboardButton("Female voice", callback_data="female"),
    ]]
    context.user_data["voice"] = context.user_data.get("voice", "female")
    await update.message.reply_text(
        "🎙️ Welcome to Super Story AI Voice Bot!\n\n"
        "Send your story script as a text message and I will turn it into narration audio.\n"
        "Choose your voice below.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def choose_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["voice"] = query.data
    await query.message.reply_text(f"Voice selected: {query.data}")

async def narrate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    script = (update.message.text or "").strip()
    if not script:
        return
    if len(script) > 4000:
        await update.message.reply_text("Please send a shorter script (maximum 4000 characters).")
        return

    voice = context.user_data.get("voice", "female")
    await update.message.reply_text("🎧 Creating your narration...")

    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name
        communicate = edge_tts.Communicate(script, VOICES[voice])
        await communicate.save(path)
        with open(path, "rb") as audio:
            await update.message.reply_audio(audio=audio, title="Story narration")
    except Exception:
        await update.message.reply_text(
            "Audio generation failed. Please try again later."
        )
    finally:
        if path and os.path.exists(path):
            os.remove(path)

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(choose_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, narrate))
    app.run_polling()

if __name__ == "__main__":
    main()

