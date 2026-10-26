
import os
import sqlite3
import tempfile
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import edge_tts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
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
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL DEFAULT ''
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT NOT NULL
            )
        """)

        user_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(users)"
            ).fetchall()
        }

        if "last_seen" not in user_columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN last_seen TEXT NOT NULL DEFAULT ''"
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_user_date
            ON activity_log(user_id, created_at)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id INTEGER PRIMARY KEY,
                blocked_at TEXT NOT NULL,
                blocked_by INTEGER NOT NULL,
                reason TEXT NOT NULL DEFAULT ''
            )
        """)


def is_blocked(user_id):
    with connect_db() as conn:
        result = conn.execute(
            "SELECT 1 FROM blocked_users WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    return result is not None


def register_user(user):
    timestamp = now_ist().isoformat(timespec="seconds")

    with connect_db() as conn:
        existing = conn.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (user.id,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE users
                SET first_name=?, username=?, last_seen=?
                WHERE user_id=?
                """,
                (
                    user.first_name or "",
                    user.username or "",
                    timestamp,
                    user.id,
                ),
            )
            return False

        conn.execute(
            """
            INSERT INTO users
                (user_id, first_name, username, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user.id,
                user.first_name or "",
                user.username or "",
                timestamp,
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
            """
            SELECT COUNT(*) FROM users
            WHERE substr(first_seen, 1, 10) = ?
            """,
            (today,),
        ).fetchone()[0]

        admins = conn.execute(
            "SELECT COUNT(*) FROM admins"
        ).fetchone()[0]

        blocked = conn.execute(
            "SELECT COUNT(*) FROM blocked_users"
        ).fetchone()[0]

        active = conn.execute(
            """
            SELECT COUNT(*) FROM users
            WHERE substr(last_seen, 1, 10) = ?
            """,
            (today,),
        ).fetchone()[0]

    return total, daily, admins, blocked, active


def log_activity(user_id, action, details=""):
    # Sirf action metadata save hota hai, poora story/script text nahi.
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO activity_log
                (user_id, action, details, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                action,
                (details or "")[:200],
                now_ist().isoformat(timespec="seconds"),
            ),
        )


def get_today_activity(user_id=None, limit=100):
    today = now_ist().date().isoformat()

    with connect_db() as conn:
        if user_id is None:
            rows = conn.execute(
                """
                SELECT a.user_id, a.action, a.details, a.created_at,
                       COALESCE(u.first_name, 'Unknown') AS first_name,
                       COALESCE(u.username, '') AS username
                FROM activity_log AS a
                LEFT JOIN users AS u ON u.user_id = a.user_id
                WHERE substr(a.created_at, 1, 10) = ?
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                (today, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT a.user_id, a.action, a.details, a.created_at,
                       COALESCE(u.first_name, 'Unknown') AS first_name,
                       COALESCE(u.username, '') AS username
                FROM activity_log AS a
                LEFT JOIN users AS u ON u.user_id = a.user_id
                WHERE a.user_id = ?
                  AND substr(a.created_at, 1, 10) = ?
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                (user_id, today, limit),
            ).fetchall()

    return rows


async def send_owner_notification(context, user):
    if not OWNER_ID or user.id == OWNER_ID:
        return

    total, daily, _, _, active = get_stats()
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


async def track_message_activity(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message or is_blocked(user.id):
        return

    is_new = register_user(user)

    if is_new:
        await send_owner_notification(context, user)

    text_value = (message.text or "").strip()

    if text_value.startswith("/"):
        action = "Command"
        details = text_value.split()[0].split("@")[0][:80]
    elif text_value:
        action = "Sent story text"
        details = "Narration request received"
    elif message.voice:
        action, details = "Sent voice message", ""
    elif message.audio:
        action, details = "Sent audio", ""
    elif message.document:
        action, details = "Sent document", ""
    elif message.photo:
        action, details = "Sent photo", ""
    else:
        action, details = "Sent message", ""

    log_activity(user.id, action, details)


async def track_callback_activity(update, context):
    user = update.effective_user
    query = update.callback_query

    if not user or not query or is_blocked(user.id):
        return

    is_new = register_user(user)

    if is_new:
        await send_owner_notification(context, user)

    labels = {
        "mode_single": "Selected Single Voice mode",
        "mode_multi": "Selected Multi-Character mode",
        "admin_stats": "Opened admin statistics",
        "admin_list": "Opened admin list",
        "admin_add_help": "Opened add-admin help",
        "admin_remove_help": "Opened remove-admin help",
        "admin_block_help": "Opened block-user help",
        "admin_unblock_help": "Opened unblock-user help",
        "admin_blocked_list": "Opened blocked-users list",
        "admin_broadcast_help": "Opened broadcast help",
        "admin_activity_help": "Opened activity help",
    }

    log_activity(
        user.id,
        labels.get(query.data, "Selected voice or button"),
        VOICE_LABELS.get(query.data, query.data or ""),
    )


async def activity_command(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if is_blocked(user.id):
        await message.reply_text("🚫 Aapka bot access block hai.")
        return

    if not is_owner(user.id):
        await message.reply_text(
            "⛔ User activity sirf Owner dekh sakta hai."
        )
        return

    target_id = None

    if context.args:
        try:
            target_id = int(context.args[0])
            if target_id <= 0:
                raise ValueError
        except ValueError:
            await message.reply_text(
                "Use: /activity ya /activity USER_ID"
            )
            return

    rows = get_today_activity(user_id=target_id, limit=100)

    if not rows:
        await message.reply_text("Aaj ke liye koi activity log nahi mili.")
        return

    if target_id is not None:
        heading = f"🕘 Aaj ki activity — User ID {target_id}"
    else:
        heading = "🕘 Aaj ki recent user activity (latest 100)"

    lines = [heading, ""]

    for row in rows:
        username = (
            f"@{row['username']}"
            if row["username"]
            else "no username"
        )
        time_text = row["created_at"].split("T")[-1][:8]
        details = f" — {row['details']}" if row["details"] else ""

        lines.append(
            f"{time_text} | {row['first_name']} ({username}) | "
            f"ID {row['user_id']} | {row['action']}{details}"
        )

    output = "\n".join(lines)

    for start_index in range(0, len(output), 3500):
        await message.reply_text(
            output[start_index:start_index + 3500]
        )


async def start(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if is_blocked(user.id):
        await message.reply_text(
            "🚫 Aapka is bot par access block kiya gaya hai."
        )
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


async def choose_voice(update, context):
    query = update.callback_query
    user = query.from_user

    if is_blocked(user.id):
        await query.answer(
            "🚫 Aapka bot access block hai.",
            show_alert=True,
        )
        return

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
            "Abhi narration generator selected voice se poori script "
            "padhega. Alag-alag character voices wala feature abhi "
            "implement nahi hai."
        )
        return

    if choice in VOICES:
        context.user_data["voice"] = choice
        await query.message.reply_text(
            f"✅ Voice selected: {VOICE_LABELS[choice]}"
        )


def admin_keyboard(owner):
    buttons = [
        [
            InlineKeyboardButton(
                "📊 Refresh Statistics",
                callback_data="admin_stats",
            )
        ],
        [
            InlineKeyboardButton(
                "👮 Admin List",
                callback_data="admin_list",
            )
        ],
        [
            InlineKeyboardButton(
                "🚫 Block User Help",
                callback_data="admin_block_help",
            )
        ],
        [
            InlineKeyboardButton(
                "✅ Unblock User Help",
                callback_data="admin_unblock_help",
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Blocked Users",
                callback_data="admin_blocked_list",
            )
        ],
        [
            InlineKeyboardButton(
                "📣 Broadcast Help",
                callback_data="admin_broadcast_help",
            )
        ],
        [
            InlineKeyboardButton(
                "🕘 Today's User Activity",
                callback_data="admin_activity_help",
            )
        ],
    ]

    if owner:
        buttons.extend([
            [
                InlineKeyboardButton(
                    "➕ Add Admin Help",
                    callback_data="admin_add_help",
                )
            ],
            [
                InlineKeyboardButton(
                    "➖ Remove Admin Help",
                    callback_data="admin_remove_help",
                )
            ],
        ])

    return InlineKeyboardMarkup(buttons)


async def admin_panel(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if is_blocked(user.id):
        await message.reply_text("🚫 Aapka bot access block hai.")
        return

    if not is_admin(user.id):
        await message.reply_text(
            "⛔ Ye command sirf authorized admins ke liye hai."
        )
        return

    total, daily, admin_count, blocked, active = get_stats()

    if is_owner(user.id):
        access_text = (
            "Owner access: Full control\n\n"
            "User block: /block USER_ID [reason]\n"
            "User unblock: /unblock USER_ID\n"
            "Blocked list: /blocked\n"
            "Broadcast: /broadcast Aapka message\n"
            "Admin add: /addadmin USER_ID ya /addadmin @username\n"
            "Admin remove: /removeadmin USER_ID\n"
            "Aaj ki activity: /activity\n"
            "Ek user ki activity: /activity USER_ID"
        )
    else:
        access_text = (
            "Admin access: Limited\n"
            "Broadcast aur user blocking ke liye Owner se sampark karein."
        )

    await message.reply_text(
        "🛡️ Super Story Bot — Admin Panel\n\n"
        f"👥 Total users: {total}\n"
        f"📅 Aaj ke naye users: {daily}\n"
        f"👮 Extra admins: {admin_count}\n"
        f"🚫 Blocked users: {blocked}\n"
        f"🟢 Active today: {active}\n\n"
        f"{access_text}",
        reply_markup=admin_keyboard(is_owner(user.id)),
    )


async def admin_buttons(update, context):
    query = update.callback_query
    user = query.from_user

    if is_blocked(user.id):
        await query.answer(
            "🚫 Aapka bot access block hai.",
            show_alert=True,
        )
        return

    if not is_admin(user.id):
        await query.answer("Permission denied.", show_alert=True)
        return

    await query.answer()

    if query.data == "admin_stats":
        total, daily, admin_count, blocked, active = get_stats()

        await query.message.reply_text(
            "📊 Bot Statistics\n\n"
            f"👥 Total users: {total}\n"
            f"📅 Aaj ke naye users: {daily}\n"
            f"👮 Extra admins: {admin_count}\n"
            f"🚫 Blocked users: {blocked}\n"
            f"🟢 Active today: {active}"
        )

    elif query.data == "admin_list":
        if not is_owner(user.id):
            await query.message.reply_text(
                "⛔ Admin list sirf Owner dekh sakta hai."
            )
            return

        with connect_db() as conn:
            rows = conn.execute(
                """
                SELECT a.user_id, a.added_at,
                       COALESCE(u.first_name, '') AS first_name,
                       COALESCE(u.username, '') AS username
                FROM admins AS a
                LEFT JOIN users AS u ON u.user_id = a.user_id
                ORDER BY a.added_at
                """
            ).fetchall()

        if not rows:
            await query.message.reply_text(
                "Abhi koi extra admin nahi hai."
            )
            return

        lines = ["👮 Admin List:"]

        for row in rows:
            display_name = row["first_name"] or "Name unavailable"
            username = (
                f"@{row['username']}"
                if row["username"]
                else "Username unavailable"
            )

            lines.append(
                f"• {display_name}\n"
                f"  Username: {username}\n"
                f"  User ID: {row['user_id']}\n"
                f"  Added: {row['added_at']}"
            )

        await query.message.reply_text("\n".join(lines))

    elif query.data == "admin_add_help":
        if is_owner(user.id):
            await query.message.reply_text(
                "Admin add karne ke liye:\n"
                "/addadmin USER_ID\n\n"
                "Username se add karne ke liye:\n"
                "/addadmin @username\n\n"
                "Username tabhi kaam karega jab user pehle bot "
                "par interact kar chuka ho."
            )

    elif query.data == "admin_remove_help":
        if is_owner(user.id):
            await query.message.reply_text(
                "Admin remove karne ke liye:\n/removeadmin USER_ID"
            )

    elif query.data == "admin_block_help":
        if is_owner(user.id):
            await query.message.reply_text(
                "User block karne ke liye:\n/block USER_ID\n\n"
                "Optional reason:\n/block USER_ID spam"
            )
        else:
            await query.message.reply_text(
                "⛔ User blocking sirf Owner kar sakta hai."
            )

    elif query.data == "admin_unblock_help":
        if is_owner(user.id):
            await query.message.reply_text(
                "User unblock karne ke liye:\n/unblock USER_ID"
            )
        else:
            await query.message.reply_text(
                "⛔ User unblocking sirf Owner kar sakta hai."
            )

    elif query.data == "admin_blocked_list":
        if not is_owner(user.id):
            await query.message.reply_text(
                "⛔ Blocked list sirf Owner dekh sakta hai."
            )
            return

        with connect_db() as conn:
            rows = conn.execute(
                """
                SELECT user_id, blocked_at, blocked_by, reason
                FROM blocked_users
                ORDER BY blocked_at DESC
                LIMIT 100
                """
            ).fetchall()

        if not rows:
            await query.message.reply_text(
                "Abhi koi blocked user nahi hai."
            )
            return

        lines = ["🚫 Blocked users (latest 100):"]

        for row in rows:
            reason = (
                f" | Reason: {row['reason']}"
                if row["reason"]
                else ""
            )
            lines.append(
                f"ID: {row['user_id']} | {row['blocked_at']}{reason}"
            )

        await query.message.reply_text("\n".join(lines))

    elif query.data == "admin_broadcast_help":
        if is_owner(user.id):
            await query.message.reply_text(
                "Broadcast bhejne ke liye command likho:\n"
                "/broadcast Aapka message yahan\n\n"
                "Message registered, non-blocked users ko bheja jayega."
            )
        else:
            await query.message.reply_text(
                "⛔ Broadcast sirf Owner kar sakta hai."
            )

    elif query.data == "admin_activity_help":
        if is_owner(user.id):
            await query.message.reply_text(
                "Aaj ki recent activity: /activity\n"
                "Ek user ki activity: /activity USER_ID\n\n"
                "Privacy ke liye poora story text save nahi hota; "
                "sirf action aur time save hota hai."
            )
        else:
            await query.message.reply_text(
                "⛔ User activity sirf Owner dekh sakta hai."
            )


async def add_admin(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if is_blocked(user.id):
        await message.reply_text("🚫 Aapka bot access block hai.")
        return

    if not is_owner(user.id):
        await message.reply_text(
            "⛔ Sirf Owner admin add kar sakta hai."
        )
        return

    if len(context.args) != 1:
        await message.reply_text(
            "Use: /addadmin USER_ID\n"
            "Ya: /addadmin @username"
        )
        return

    supplied_target = context.args[0].strip()

    if supplied_target.startswith("@"):
        username = supplied_target[1:].lower()

        if not username:
            await message.reply_text(
                "❌ Valid username bhejo, jaise /addadmin @username."
            )
            return

        with connect_db() as conn:
            found = conn.execute(
                """
                SELECT user_id FROM users
                WHERE lower(username) = ?
                LIMIT 1
                """,
                (username,),
            ).fetchone()

        if not found:
            await message.reply_text(
                "❌ Is username ki ID bot ke database mein nahi hai.\n"
                "Us user se pehle bot par /start bhejwao, phir try karo.\n"
                "Ya numeric ID use karo: /addadmin 123456789"
            )
            return

        target_id = int(found["user_id"])

    else:
        try:
            target_id = int(supplied_target)
            if target_id <= 0:
                raise ValueError
        except ValueError:
            await message.reply_text(
                "❌ Username ya numeric ID bhejo:\n"
                "/addadmin @username\n"
                "Ya /addadmin 123456789"
            )
            return

    if target_id == OWNER_ID:
        await message.reply_text(
            "Owner ko alag admin banane ki zarurat nahi."
        )
        return

    with connect_db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO admins (user_id, added_at)
            VALUES (?, ?)
            """,
            (
                target_id,
                now_ist().isoformat(timespec="seconds"),
            ),
        )

    await message.reply_text(
        f"✅ Admin ID {target_id} add kar di gayi.\n"
        "Woh user bot par /admin chala sakta hai."
    )


async def remove_admin(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if is_blocked(user.id):
        await message.reply_text("🚫 Aapka bot access block hai.")
        return

    if not is_owner(user.id):
        await message.reply_text(
            "⛔ Sirf Owner admin remove kar sakta hai."
        )
        return

    if len(context.args) != 1:
        await message.reply_text("Use: /removeadmin USER_ID")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await message.reply_text(
            "❌ Valid numeric Telegram user ID bhejo."
        )
        return

    if target_id == OWNER_ID:
        await message.reply_text(
            "🔒 Owner ko remove nahi kiya ja sakta."
        )
        return

    with connect_db() as conn:
        result = conn.execute(
            "DELETE FROM admins WHERE user_id = ?",
            (target_id,),
        )

    if result.rowcount:
        await message.reply_text(
            f"✅ Admin ID {target_id} remove kar di gayi."
        )
    else:
        await message.reply_text(
            "Is ID ka admin record nahi mila."
        )


async def block_user(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if is_blocked(user.id):
        await message.reply_text("🚫 Aapka bot access block hai.")
        return

    if not is_owner(user.id):
        await message.reply_text(
            "⛔ Sirf Owner user ko block kar sakta hai."
        )
        return

    if not context.args:
        await message.reply_text(
            "Use: /block USER_ID [reason]"
        )
        return

    try:
        target_id = int(context.args[0])
        if target_id <= 0:
            raise ValueError
    except ValueError:
        await message.reply_text(
            "❌ Valid numeric Telegram user ID bhejo."
        )
        return

    if target_id == OWNER_ID:
        await message.reply_text(
            "🔒 Owner ko block nahi kiya ja sakta."
        )
        return

    reason = " ".join(context.args[1:]).strip()[:250]

    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO blocked_users
                (user_id, blocked_at, blocked_by, reason)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                blocked_at=excluded.blocked_at,
                blocked_by=excluded.blocked_by,
                reason=excluded.reason
            """,
            (
                target_id,
                now_ist().isoformat(timespec="seconds"),
                user.id,
                reason,
            ),
        )

    await message.reply_text(
        f"🚫 User ID {target_id} block kar diya gaya."
    )


async def unblock_user(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if is_blocked(user.id):
        await message.reply_text("🚫 Aapka bot access block hai.")
        return

    if not is_owner(user.id):
        await message.reply_text(
            "⛔ Sirf Owner user ko unblock kar sakta hai."
        )
        return

    if len(context.args) != 1:
        await message.reply_text("Use: /unblock USER_ID")
        return

    try:
        target_id = int(context.args[0])
        if target_id <= 0:
            raise ValueError
    except ValueError:
        await message.reply_text(
            "❌ Valid numeric Telegram user ID bhejo."
        )
        return

    with connect_db() as conn:
        result = conn.execute(
            "DELETE FROM blocked_users WHERE user_id = ?",
            (target_id,),
        )

    if result.rowcount:
        await message.reply_text(
            f"✅ User ID {target_id} unblock kar diya gaya."
        )
    else:
        await message.reply_text(
            "Ye user blocked list mein nahi mila."
        )


async def blocked_list(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if is_blocked(user.id):
        await message.reply_text("🚫 Aapka bot access block hai.")
        return

    if not is_owner(user.id):
        await message.reply_text(
            "⛔ Blocked users ki list sirf Owner dekh sakta hai."
        )
        return

    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT user_id, blocked_at, blocked_by, reason
            FROM blocked_users
            ORDER BY blocked_at DESC
            LIMIT 100
            """
        ).fetchall()

    if not rows:
        await message.reply_text(
            "Abhi koi blocked user nahi hai."
        )
        return

    lines = ["🚫 Blocked users (latest 100):"]

    for row in rows:
        reason = (
            f" | Reason: {row['reason']}"
            if row["reason"]
            else ""
        )
        lines.append(
            f"ID: {row['user_id']} | {row['blocked_at']}{reason}"
        )

    await message.reply_text("\n".join(lines))


async def broadcast(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if is_blocked(user.id):
        await message.reply_text("🚫 Aapka bot access block hai.")
        return

    if not is_owner(user.id):
        await message.reply_text(
            "⛔ Broadcast sirf Owner kar sakta hai."
        )
        return

    announcement = (
        message.text.partition(" ")[2].strip()
        if message.text
        else ""
    )

    if not announcement:
        await message.reply_text(
            "Use: /broadcast Aapka message yahan\n\n"
            "Ye text sabhi registered, non-blocked users ko bheja jayega."
        )
        return

    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT user_id FROM users
            WHERE user_id NOT IN (
                SELECT user_id FROM blocked_users
            )
            ORDER BY user_id
            """
        ).fetchall()

    if not rows:
        await message.reply_text(
            "Broadcast bhejne ke liye koi eligible user nahi hai."
        )
        return

    status = await message.reply_text(
        f"📣 Broadcast shuru...\nTargets: {len(rows)}"
    )

    sent = 0
    failed = 0

    for row in rows:
        target_id = row["user_id"]

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=announcement,
            )
            sent += 1
        except TelegramError as exc:
            failed += 1
            print(f"Broadcast failed for {target_id}: {exc}")

        await asyncio.sleep(0.05)

    await status.edit_text(
        "✅ Broadcast complete!\n\n"
        f"📨 Sent: {sent}\n"
        f"⚠️ Failed: {failed}\n"
        f"👥 Total targets: {len(rows)}"
    )


async def narrate(update, context):
    message = update.effective_message
    user = update.effective_user

    if not message or not message.text or not user:
        return

    if is_blocked(user.id):
        await message.reply_text(
            "🚫 Aapka bot access block kiya gaya hai."
        )
        return

    # /start se pehle script bhejne wale users ko bhi register karo.
    is_new = register_user(user)

    if is_new:
        await send_owner_notification(context, user)

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
            suffix=".mp3",
            delete=False,
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
            "❌ Audio generation failed.\n"
            "Please try again later."
        )

    finally:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing"
        )

    if OWNER_ID <= 0:
        raise RuntimeError(
            "OWNER_ID environment variable is missing or invalid"
        )

    init_db()

    app = Application.builder().token(TOKEN).build()

    # Activity tracking handlers ko pehle run karne ke liye group -1.
    app.add_handler(
        MessageHandler(filters.ALL, track_message_activity),
        group=-1,
    )

    app.add_handler(
        CallbackQueryHandler(track_callback_activity),
        group=-1,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("addadmin", add_admin))
    app.add_handler(CommandHandler("removeadmin", remove_admin))
    app.add_handler(CommandHandler("block", block_user))
    app.add_handler(CommandHandler("unblock", unblock_user))
    app.add_handler(CommandHandler("blocked", blocked_list))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("activity", activity_command))

    app.add_handler(
        CallbackQueryHandler(admin_buttons, pattern=r"^admin_")
    )

    app.add_handler(CallbackQueryHandler(choose_voice))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            narrate,
        )
    )

    print("Super Story AI Voice Bot is starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
