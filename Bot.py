

import os
import sqlite3
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

import edge_tts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_FILE = os.getenv("DB_FILE", "super_story_users.db")
IST = ZoneInfo("Asia/Kolkata")

VOICES = {
    "male": "hi-IN-MadhurNeural",
    "female": "hi-IN-SwaraNeural",
    "boy": "hi-IN-MadhurNeural",
    "girl": "hi-IN-SwaraNeural",
    "deep_male": "hi-IN-PrabhatNeural",
    "soft_female": "hi-IN-SwaraNeural",
}

VOICE_LABELS = {
    "male": "Male voice",
    "female": "Female voice",
    "boy": "Boy voice",
    "girl": "Girl voice",
    "deep_male": "Deep male voice",
    "soft_female": "Soft female voice",
}

KEYBOARD = [
    [
        InlineKeyboardButton("🎙️ Single Voice", callback_data="mode_single"),
        InlineKeyboardButton("🎭 Multi-Character", callback_data="mode_multi"),
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
        InlineKeyboardButton("Deep male", callback_data="deep_male"),
        InlineKeyboardButton("Soft female", callback_data="soft_female"),
    ],
]


def now_ist():
    return datetime.now(IST)


def connect_db():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                first_seen TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT NOT NULL
            )
        """)


def register_user(user):
    timestamp = now_ist().isoformat(timespec="seconds")

    with connect_db() as conn:
        existing = conn.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (user.id,),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE users SET first_name=?, username=? WHERE user_id=?",
                (user.first_name or "", user.username or "", user.id),
            )
            return False

        conn.execute(
            """
            INSERT INTO users (user_id, first_name, username, first_seen)
            VALUES (?, ?, ?, ?)
            """,
            (
                user.id,
                user.first_name or "",
                user.username or "",
                timestamp,
            ),
        )

    return True


def is_admin(user_id):
    if OWNER_ID and user_id == OWNER_ID:
        return True

    with connect_db() as conn:
        result = conn.execute(
            "SELECT 1 FROM admins WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    return result is not None


def is_owner(user_id):
    return OWNER_ID != 0 and user_id == OWNER_ID


def get_stats():
    today = now_ist().date().isoformat()

    with connect_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        daily = conn.execute(
            "SELECT COUNT(*) FROM users WHERE substr(first_seen, 1, 10) = ?",
            (today,),
        ).fetchone()[0]

        admins = conn.execute(
            "SELECT COUNT(*) FROM admins"
        ).fetchone()[0]

    return total, daily, admins


async def send_owner_notification(context, user):
    if not OWNER_ID or user.id == OWNER_ID:
        return

    total, daily, _ = get_stats()
    username = f"@{user.username}" if user.username else "Nahi hai"

    try:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=(
                "🆕 Naya user bot par aaya!\n\n"
                f"Naam: {user.first_name or 'Unknown'}\n"
                f"Username: {username}\n"
                f"User ID: {user.id}\n\n"
                f"👥 Total users: {total}\n"
                f"📅 Aaj ke naye users: {daily}"
            ),
        )
    except Exception as exc:
        print(f"Owner notification failed: {exc}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    is_new = register_user(user)

    if is_new:
        await send_owner_notification(context, user)

    context.user_data.setdefault("voice", "female")
    context.user_data.setdefault("mode", "single")

    await message.reply_text(
        "🎙️ Welcome to Super Story AI Voice Bot!\n\n"
        "Apni story script text mein bhejo, main narration audio banaunga.\n"
        "Neeche se voice aur mode choose karo.",
        reply_markup=InlineKeyboardMarkup(KEYBOARD),
    )


async def choose_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data

    if choice == "mode_single":
        context.user_data["mode"] = "single"
        await query.message.reply_text(
            "🎙️ Single Voice mode selected!\nAb story ka text bhejo."
        )
        return

    if choice == "mode_multi":
        context.user_data["mode"] = "multi"
        await query.message.reply_text(
            "🎭 Multi-Character mode selected.\n\n"
            "Abhi narration generator selected voice se poori script padhega. "
            "Alag-alag character voices wala feature abhi implement nahi hai."
        )
        return

    if choice in VOICES:
        context.user_data["voice"] = choice
        await query.message.reply_text(
            f"✅ Voice selected: {VOICE_LABELS[choice]}"
        )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if not is_admin(user.id):
        await message.reply_text("⛔ Ye command sirf authorized admins ke liye hai.")
        return

    total, daily, admin_count = get_stats()

    buttons = [
        [InlineKeyboardButton("📊 Refresh Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("👮 Admin List", callback_data="admin_list")],
    ]

    if is_owner(user.id):
        buttons.extend([
            [InlineKeyboardButton("➕ Add Admin Help", callback_data="admin_add_help")],
            [InlineKeyboardButton("➖ Remove Admin Help", callback_data="admin_remove_help")],
        ])

    await message.reply_text(
        "🛡️ Super Story Bot — Admin Panel\n\n"
        f"👥 Total users: {total}\n"
        f"📅 Aaj ke naye users: {daily}\n"
        f"👮 Extra admins: {admin_count}\n\n"
        + (
            "Owner access: Full control\n\n"
            "Admin add karne ke liye:\n/addadmin USER_ID\n\n"
            "Admin remove karne ke liye:\n/removeadmin USER_ID"
            if is_owner(user.id)
            else "Admin access: Limited"
        ),
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    if not is_admin(user.id):
        await query.message.reply_text("⛔ Permission denied.")
        return

    if query.data == "admin_stats":
        total, daily, admin_count = get_stats()
        await query.message.reply_text(
            "📊 Bot Statistics\n\n"
            f"👥 Total users: {total}\n"
            f"📅 Aaj ke naye users: {daily}\n"
            f"👮 Extra admins: {admin_count}"
        )

    elif query.data == "admin_list":
        if not is_owner(user.id):
            await query.message.reply_text("⛔ Admin list sirf Owner dekh sakta hai.")
            return

        with connect_db() as conn:
            rows = conn.execute(
                "SELECT user_id, added_at FROM admins ORDER BY added_at"
            ).fetchall()

        if not rows:
            await query.message.reply_text("Abhi koi extra admin nahi hai.")
            return

        lines = ["👮 Admin List:"]
        for row in rows:
            lines.append(f"• ID: {row['user_id']} — {row['added_at']}")

        await query.message.reply_text("\n".join(lines))

    elif query.data == "admin_add_help":
        if is_owner(user.id):
            await query.message.reply_text(
                "Admin add karne ke liye command bhejo:\n"
                "/addadmin 123456789\n\n"
                "123456789 ki jagah us user ki Telegram numeric ID likho."
            )

    elif query.data == "admin_remove_help":
        if is_owner(user.id):
            await query.message.reply_text(
                "Admin remove karne ke liye command bhejo:\n"
                "/removeadmin 123456789"
            )


async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if not is_owner(user.id):
        await message.reply_text("⛔ Sirf Owner admin add kar sakta hai.")
        return

    if len(context.args) != 1:
        await message.reply_text("Use: /addadmin USER_ID")
        return

    try:
        target_id = int(context.args[0])
        if target_id <= 0:
            raise ValueError
    except ValueError:
        await message.reply_text("❌ Valid numeric Telegram user ID bhejo.")
        return

    if target_id == OWNER_ID:
        await message.reply_text("Owner ko alag admin banane ki zarurat nahi.")
        return

    with connect_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO admins (user_id, added_at) VALUES (?, ?)",
            (target_id, now_ist().isoformat(timespec="seconds")),
        )

    await message.reply_text(
        f"✅ Admin ID {target_id} add kar di gayi.\n"
        "Woh user bot par /admin chala sakta hai."
    )


async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if not is_owner(user.id):
        await message.reply_text("⛔ Sirf Owner admin remove kar sakta hai.")
        return

    if len(context.args) != 1:
        await message.reply_text("Use: /removeadmin USER_ID")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await message.reply_text("❌ Valid numeric Telegram user ID bhejo.")
        return

    if target_id == OWNER_ID:
        await message.reply_text("🔒 Owner ko remove nahi kiya ja sakta.")
        return

    with connect_db() as conn:
        result = conn.execute(
            "DELETE FROM admins WHERE user_id = ?",
            (target_id,),
        )

    if result.rowcount:
        await message.reply_text(f"✅ Admin ID {target_id} remove kar di gayi.")
    else:
        await message.reply_text("Is ID ka admin record nahi mila.")


async def narrate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return

    script = message.text.strip()

    if len(script) > 4000:
        await message.reply_text(
            "Please send a shorter script (maximum 4000 characters)."
        )
        return

    if not script:
        return

    voice = context.user_data.get("voice", "female")
    voice_id = VOICES.get(voice, VOICES["female"])

    progress = await message.reply_text(
        "🎧 Creating your narration...\n📊 Progress: 10%"
    )

    path = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".mp3", delete=False
        ) as temp_file:
            path = temp_file.name

        await progress.edit_text(
            "🎙️ Generating narration...\n📊 Progress: 35%"
        )

        communicate = edge_tts.Communicate(script, voice_id)
        await communicate.save(path)

        await progress.edit_text(
            "📤 Uploading audio...\n📊 Progress: 85%"
        )

        with open(path, "rb") as audio:
            await message.reply_audio(
                audio=audio,
                title="Story narration",
            )

        await progress.edit_text(
            "✅ Narration complete!\n🎧 Your audio is ready."
        )

    except Exception as exc:
        print(f"Narration error: {exc}")
        await progress.edit_text(
            "❌ Audio generation failed.\nPlease try again later."
        )

    finally:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing")

    if OWNER_ID <= 0:
        raise RuntimeError("OWNER_ID environment variable is missing or invalid")

    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("addadmin", add_admin))
    app.add_handler(CommandHandler("removeadmin", remove_admin))

    app.add_handler(CallbackQueryHandler(admin_buttons, pattern=r"^admin_"))
    app.add_handler(CallbackQueryHandler(choose_voice))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, narrate)
    )

    print("Super Story AI Voice Bot is starting...")
    app.run_polling()


if __name__ == "__main__":
    main()

