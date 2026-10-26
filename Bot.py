
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
VOICE_MODES = {
    "single": "🎙️ Single Voice",
    "multi": "🎭 Multi-Character Voice",
}

keyboard = [
    [
        InlineKeyboardButton("🎙️ Single Voice", callback_data="mode_single"),
        InlineKeyboardButton("🎭 Multi-Character Voice", callback_data="mode_multi"),
    ],
    [
        InlineKeyboardButton("Male voice", callback_data="male"),
        InlineKeyboardButton("Female voice", callback_data="female"),
    ],
    [
        InlineKeyboardButton("Boy voice", callback_data="boy"),
        InlineKeyboardButton("Girl voice", callback_data="girl"),
    ],
    [
        InlineKeyboardButton("Deep male voice", callback_data="deep_male"),
        InlineKeyboardButton("Soft female voice", callback_data="soft_female"),
    ],
]
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

    choice = query.data

    if choice == "mode_single":
        context.user_data["mode"] = "single"
        await query.message.reply_text(
            "🎙️ Single Voice mode selected!\n"
            "Ab story ka text bhejo."
        )
        return

    if choice == "mode_multi":
        context.user_data["mode"] = "multi"
        await query.message.reply_text(
            "🎭 Multi-Character Voice mode selected!\n\n"
            "Dialogue is format mein bhejo:\n"
            "Narrator: Ek din ek hero aaya.\n"
            "Hero: Main tumhe bachaunga!\n"
            "Heroine: Mujhe tum par bharosa hai.\n"
            "Villain: Tum mujhe nahi hara sakte!"
        )
        return

    context.user_data["voice"] = choice
    await query.message.reply_text(f"Voice selected: {choice}")

async def narrate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    script = (update.message.text or "").strip()
    if not script:
        return

    if len(script) > 4000:
        await update.message.reply_text(
            "Please send a shorter script (maximum 4000 characters)."
        )
        return

    voice = context.user_data.get("voice", "female")
    mode = context.user_data.get("mode", "single")

    progress_msg = await update.message.reply_text(
        "🎧 Creating your narration...\n"
        "📊 Progress: 0%"
    )

    path = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".mp3", delete=False
        ) as f:
            path = f.name

        await progress_msg.edit_text(
            "🎙️ Preparing your voice...\n"
            "📊 Progress: 10%"
        )

        communicate = edge_tts.Communicate(script, VOICES[voice])

        await progress_msg.edit_text(
            "🎙️ Generating narration...\n"
            "📊 Progress: 25%"
        )

        await communicate.save(path)

        await progress_msg.edit_text(
            "📤 Uploading your audio...\n"
            "📊 Progress: 85%"
        )

        with open(path, "rb") as audio:
            await update.message.reply_audio(
                audio=audio,
                title="Story narration"
            )

        await progress_msg.edit_text(
            "✅ Narration complete!\n"
            "🎧 Your audio is ready."
        )

    except Exception:
        await progress_msg.edit_text(
            "❌ Audio generation failed.\n"
            "Please try again later."
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

