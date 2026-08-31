import os
import sqlite3
import logging
from contextlib import closing
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    MessageHandler, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
DB_PATH = os.getenv("DB_PATH", "amazon_gc_bot.db")

CHANNELS = [
    ("ðŸ“¢ Join @primeloote", "https://t.me/primeloote", "@primeloote"),
    ("ðŸ“¢ Join @primebackp", "https://t.me/primebackp", "@primebackp"),
    ("ðŸ“¢ Join @sheinstockprime", "https://t.me/sheinstockprime", "@sheinstockprime"),
    ("ðŸ“¢ Join @pexoearner", "https://t.me/pexoearner", "@pexoearner"),
]

REF_BONUS = int(os.getenv("REF_BONUS", "20"))

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("amazongc")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(db()) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            points INTEGER NOT NULL DEFAULT 0,
            referrals INTEGER NOT NULL DEFAULT 0,
            referred_by INTEGER,
            verified INTEGER NOT NULL DEFAULT 0,
            banned INTEGER NOT NULL DEFAULT 0,
            joined_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS giftcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            cost INTEGER NOT NULL,
            claimed_by INTEGER,
            claimed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            cost INTEGER NOT NULL,
            claimed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS referral_rewards (
            referred_user INTEGER PRIMARY KEY,
            referrer INTEGER NOT NULL,
            rewarded_at TEXT NOT NULL
        );
        """)
        conn.commit()


def upsert_user(user):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO users(user_id, username, first_name, joined_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name
        """, (
            user.id, user.username or "", user.first_name or "",
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()


def get_user(user_id):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        

def is_banned(user_id):
    row = get_user(user_id)
    return bool(row and row["banned"])


def set_verified(user_id):
    with closing(db()) as conn:
        conn.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
        conn.commit()


def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("ðŸŽ Amazon GC", callback_data="gc"),
            InlineKeyboardButton("ðŸ’° My Balance", callback_data="balance"),
        ],
        [
            InlineKeyboardButton("ðŸ‘¥ Refer & Earn", callback_data="refer"),
            InlineKeyboardButton("ðŸ“Š My Stats", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("ðŸ† Leaderboard", callback_data="leaderboard"),
            InlineKeyboardButton("ðŸŽŸï¸ Redeem", callback_data="redeem"),
        ],
        [
            InlineKeyboardButton("ðŸ“¢ Channels", callback_data="channels"),
            InlineKeyboardButton("â„¹ï¸ Help", callback_data="help"),
        ],
    ])


def back_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("â¬…ï¸ Back to Menu", callback_data="back")]
    ])


def channel_keyboard(channels=None):
    channels = channels or CHANNELS
    rows = [
        [InlineKeyboardButton(name, url=url)]
        for name, url, _ in channels
    ]
    rows.append([
        InlineKeyboardButton("âœ… Verify Join", callback_data="verify")
    ])
    return InlineKeyboardMarkup(rows)


async def check_channels(context, user_id):
    missing = []
    for name, url, username in CHANNELS:
        try:
            member = await context.bot.get_chat_member(username, user_id)
            if member.status in (
                ChatMemberStatus.LEFT,
                ChatMemberStatus.KICKED,
            ):
                missing.append((name, url, username))
        except Exception as exc:
            log.warning("Membership check failed for %s: %s", username, exc)
            missing.append((name, url, username))
    return missing


async def require_verified(update, context):
    user_id = update.effective_user.id
    if is_banned(user_id):
        if update.callback_query:
            await update.callback_query.answer(
                "ðŸš« Aapka access restricted hai.", show_alert=True
            )
        return False

    row = get_user(user_id)
    if not row or not row["verified"]:
        if update.callback_query:
            await update.callback_query.answer(
                "Pehle verification complete karein.", show_alert=True
            )
        else:
            await update.message.reply_text(
                "ðŸ” Pehle /start karke channels join karein aur Verify Join dabayein."
            )
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    referrals=referrals+1 "
            "WHERE user_id=?",
            (REF_BONUS, referrer_id)
        )
        conn.execute(
            "INSERT INTO referral_rewards(referred_user, referrer, rewarded_at) "
            "VALUES(?,?,?)",
            (user_id, referrer_id, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()

    try:
        await context.bot.send_message(
            referrer_id,
            f"ðŸŽ‰ Referral verified!\nðŸ’° +{REF_BONUS} points added."
        )
    except Exception:
        pass


async def safe_edit_message(query, text, **kwargs):
    """Edit a Telegram message without crashing if nothing actually changed."""
    try:
                        f"{i}. {name} â€” â­ {r['points']} | ðŸ‘¥ {r['referrals']}"
            )

    await safe_edit_message(query, 
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=back_button()
    )


def is_admin(user_id):
    return user_id in ADMIN_IDS


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("â›” Admin only.")
        return

    await update.message.reply_text(
        "ðŸ‘‘ *Admin Panel*\n\n"
        "/users â€” user statistics\n"
        "/addcode CODE COST â€” add gift card\n"
        "/addpoints USER_ID AMOUNT â€” add points\n"
        "/ban USER_ID â€” ban\n"
        "/unban USER_ID â€” unban\n"
        "/broadcast TEXT â€” broadcast",
        parse_mode="Markdown"
    )


async def addcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
                    sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"ðŸ“£ Broadcast done.\n"
        f"âœ… Sent: {sent}\n"
        f"âŒ Failed: {failed}"
    )


async def text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await require_verified(update, context):
        await update.message.reply_text(
            "ðŸ  Main Menu:",
            reply_markup=main_menu()
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable missing")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("addcode", addcode))
    app.add_handler(CommandHandler("addpoints", addpoints))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast))

    app.add_handler(CallbackQueryHandler(verify, pattern=r"^verify$"))
    app.add_handler(CallbackQueryHandler(claim, pattern=r"^claim:\d+$"))
    app.add_handler(CallbackQueryHandler(callbacks))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_fallback)
    )

    log.info("AmazonGC Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
