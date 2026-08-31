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
    ("📢 Join @primeloote", "https://t.me/primeloote", "@primeloote"),
    ("📢 Join @primebackp", "https://t.me/primebackp", "@primebackp"),
    ("📢 Join @sheinstockprime", "https://t.me/sheinstockprime", "@sheinstockprime"),
    ("📢 Join @pexoearner", "https://t.me/pexoearner", "@pexoearner"),
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
            InlineKeyboardButton("🎁 Amazon GC", callback_data="gc"),
            InlineKeyboardButton("💰 My Balance", callback_data="balance"),
        ],
        [
            InlineKeyboardButton("👥 Refer & Earn", callback_data="refer"),
            InlineKeyboardButton("📊 My Stats", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard"),
            InlineKeyboardButton("🎟️ Redeem", callback_data="redeem"),
        ],
        [
            InlineKeyboardButton("📢 Channels", callback_data="channels"),
            InlineKeyboardButton("ℹ️ Help", callback_data="help"),
        ],
    ])


def back_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back")]
    ])


def channel_keyboard(channels=None):
    channels = channels or CHANNELS
    rows = [
        [InlineKeyboardButton(name, url=url)]
        for name, url, _ in channels
    ]
    rows.append([
        InlineKeyboardButton("✅ Verify Join", callback_data="verify")
    ])
    return InlineKeyboardMarkup(rows)


async def check_channels(context, user_id):
    """Check membership in every required channel.

    The bot must be an administrator in each channel for Telegram to
    reliably return membership information for arbitrary users.
    """
    missing = []

    joined_statuses = {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    }

    for name, url, username in CHANNELS:
        try:
            # Resolve the chat first, then check the user's membership.
            chat = await context.bot.get_chat(username)
            member = await context.bot.get_chat_member(chat.id, user_id)

            if member.status not in joined_statuses:
                missing.append((name, url, username))
                log.info(
                    "User %s is not joined in %s (status=%s)",
                    user_id, username, member.status
                )

        except Exception as exc:
            # Any Telegram API error is treated as a failed verification,
            # and the exact error is written to the bot logs.
            log.warning(
                "Membership check failed for user %s in %s: %s",
                user_id, username, exc
            )
            missing.append((name, url, username))

    return missing


async def require_verified(update, context):
    user_id = update.effective_user.id
    if is_banned(user_id):
        if update.callback_query:
            await update.callback_query.answer(
                "🚫 Aapka access restricted hai.", show_alert=True
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
                "🔐 Pehle /start karke channels join karein aur Verify Join dabayein."
            )
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)

    if is_banned(user.id):
        await update.message.reply_text("🚫 Aapka access restricted hai.")
        return

    # Referral format: /start ref_123456789
    payload = context.args[0] if context.args else ""
    if payload.startswith("ref_"):
        try:
            referrer_id = int(payload[4:])
        except ValueError:
            referrer_id = None

        if referrer_id and referrer_id != user.id:
            with closing(db()) as conn:
                current = conn.execute(
                    "SELECT referred_by FROM users WHERE user_id=?",
                    (user.id,)
                ).fetchone()
                referrer = conn.execute(
                    "SELECT user_id FROM users WHERE user_id=? AND banned=0",
                    (referrer_id,)
                ).fetchone()

                if current and current["referred_by"] is None and referrer:
                    conn.execute(
                        "UPDATE users SET referred_by=? WHERE user_id=?",
                        (referrer_id, user.id)
                    )
                    conn.commit()

    missing = await check_channels(context, user.id)

    if missing:
        await update.message.reply_text(
            "💰 *AmazonGC Bot*\n\n"
            "🎁 Welcome!\n\n"
            "Bot use karne ke liye pehle neeche diye gaye "
            "sabhi channels join karein.\n\n"
            "Join karne ke baad *✅ Verify Join* dabayein.",
            parse_mode="Markdown",
            reply_markup=channel_keyboard(missing),
        )
        return

    set_verified(user.id)
    await reward_referrer_if_needed(user.id, context)

    await update.message.reply_text(
        "✅ *Verification successful!*\n\n"
        "🎉 Aapke sabhi required channels join hain.\n\n"
        "💰 *AmazonGC Bot is ready to use!*",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    upsert_user(user)

    if is_banned(user.id):
        await safe_edit_message(query, "🚫 Aapka access restricted hai.")
        return

    missing = await check_channels(context, user.id)

    if missing:
        await safe_edit_message(query, 
            "❌ *Verification failed.*\n\n"
            "Pehle ye required channel(s) join karein, "
            "phir *Verify Again* dabayein.",
            parse_mode="Markdown",
            reply_markup=channel_keyboard(missing),
        )
        return

    set_verified(user.id)
    await reward_referrer_if_needed(user.id, context)

    await safe_edit_message(query, 
        "✅ *Verification successful!*\n\n"
        "🎉 Aapke sabhi required channels join hain.\n\n"
        "💰 *AmazonGC Bot is ready to use!*",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )


async def reward_referrer_if_needed(user_id, context):
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT referred_by FROM users WHERE user_id=?", (user_id,)
        ).fetchone()

        if not row or not row["referred_by"]:
            return

        already = conn.execute(
            "SELECT 1 FROM referral_rewards WHERE referred_user=?",
            (user_id,)
        ).fetchone()

        if already:
            return

        referrer_id = row["referred_by"]
        referrer = conn.execute(
            "SELECT user_id FROM users WHERE user_id=? AND banned=0",
            (referrer_id,)
        ).fetchone()

        if not referrer:
            return

        conn.execute(
            "UPDATE users SET points=points+?, referrals=referrals+1 "
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
            f"🎉 Referral verified!\n💰 +{REF_BONUS} points added."
        )
    except Exception:
        pass


async def safe_edit_message(query, text, **kwargs):
    """Edit a Telegram message without crashing if nothing actually changed."""
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            log.info("Skipped unchanged message edit.")
            return
        raise


async def refer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the user's personal referral link."""
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not await require_verified(update, context):
        return

    try:
        me = await context.bot.get_me()
        if not me.username:
            raise RuntimeError("Bot username is not available")

        link = f"https://t.me/{me.username}?start=ref_{user.id}"
        text = (
            "👥 *Refer & Earn*\n\n"
            f"Har successful verified referral par aapko *{REF_BONUS} points* milenge.\n\n"
            "🔗 *Your referral link:*\n"
            f"`{link}`"
        )
        await safe_edit_message(
            query, text, parse_mode="Markdown", reply_markup=back_button()
        )
    except Exception as exc:
        log.exception("Refer & Earn failed for user %s: %s", user.id, exc)
        await query.answer("Refer & Earn me error aa raha hai. Bot logs check karein.", show_alert=True)


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "verify":
        await verify(update, context)
        return

    if not await require_verified(update, context):
        return

    row = get_user(user_id)

    if query.data == "back":
        await safe_edit_message(query, 
            "🏠 *AmazonGC Bot Main Menu*",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    elif query.data == "balance":
        await safe_edit_message(query, 
            f"💰 *My Balance*\n\n⭐ Points: *{row['points']}*",
            parse_mode="Markdown",
            reply_markup=back_button()
        )

    elif query.data == "stats":
        await safe_edit_message(query, 
            f"📊 *My Stats*\n\n"
            f"👤 ID: `{user_id}`\n"
            f"⭐ Points: *{row['points']}*\n"
            f"👥 Referrals: *{row['referrals']}*",
            parse_mode="Markdown",
            reply_markup=back_button()
        )

    elif query.data == "refer":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user_id}"
        await safe_edit_message(query, 
            "👥 *Refer & Earn*\n\n"
            f"Har successful verified referral par aapko "
            f"*{REF_BONUS} points* milenge.\n\n"
            f"🔗 *Your referral link:*\n{link}",
            parse_mode="Markdown",
            reply_markup=back_button()
        )

    elif query.data == "gc":
        await safe_edit_message(query, 
            "🎁 *Amazon GC*\n\n"
            "Available gift cards dekhne ke liye 🎟️ Redeem par tap karein.\n\n"
            "Gift cards sirf admin ke dwara legitimately added "
            "codes se deliver honge.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎟️ Redeem", callback_data="redeem")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back")],
            ])
        )

    elif query.data == "redeem":
        await show_redeem(query)

    elif query.data == "leaderboard":
        await show_leaderboard(query)

    elif query.data == "channels":
        await safe_edit_message(query, 
            "📢 *Required Channels*\n\n"
            "Sabhi channels join rakhna zaroori hai.",
            parse_mode="Markdown",
            reply_markup=channel_keyboard()
        )

    elif query.data == "help":
        await safe_edit_message(query, 
            "ℹ️ *Help*\n\n"
            "1️⃣ Required channels join karein.\n"
            "2️⃣ Verify Join dabayein.\n"
            "3️⃣ Refer & Earn se points earn karein.\n"
            "4️⃣ Sufficient points hone par Redeem use karein.",
            parse_mode="Markdown",
            reply_markup=back_button()
        )


async def show_redeem(query):
    user_id = query.from_user.id
    row = get_user(user_id)

    with closing(db()) as conn:
        cards = conn.execute(
            "SELECT id, cost FROM giftcards "
            "WHERE claimed_by IS NULL ORDER BY cost ASC"
        ).fetchall()

    if not cards:
        await safe_edit_message(query, 
            "🎟️ *Redeem*\n\n❌ Abhi koi gift card available nahi hai.",
            parse_mode="Markdown",
            reply_markup=back_button()
        )
        return

    lines = [
        "🎟️ *Redeem Gift Card*\n",
        f"⭐ Your points: *{row['points']}*\n",
    ]
    buttons = []

    for card in cards[:20]:
        lines.append(
            f"🎁 Card #{card['id']} — *{card['cost']} points*"
        )
        buttons.append([
            InlineKeyboardButton(
                f"🎁 Redeem #{card['id']} — {card['cost']}⭐",
                callback_data=f"claim:{card['id']}"
            )
        ])

    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])

    await safe_edit_message(query, 
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not await require_verified(update, context):
        return

    try:
        card_id = int(query.data.split(":", 1)[1])
    except Exception:
        await query.answer("Invalid request.", show_alert=True)
        return

    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        user = conn.execute(
            "SELECT points FROM users WHERE user_id=?", (user_id,)
        ).fetchone()

        card = conn.execute(
            "SELECT id, code, cost FROM giftcards "
            "WHERE id=? AND claimed_by IS NULL",
            (card_id,)
        ).fetchone()

        if not user or not card:
            conn.rollback()
            await query.answer(
                "Gift card unavailable.", show_alert=True
            )
            return

        if user["points"] < card["cost"]:
            conn.rollback()
            await query.answer(
                f"Not enough points. Need {card['cost']} points.",
                show_alert=True
            )
            return

        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "UPDATE users SET points=points-? WHERE user_id=?",
            (card["cost"], user_id)
        )
        conn.execute(
            "UPDATE giftcards SET claimed_by=?, claimed_at=? "
            "WHERE id=? AND claimed_by IS NULL",
            (user_id, now, card_id)
        )
        conn.execute(
            "INSERT INTO claims(user_id, code, cost, claimed_at) "
            "VALUES(?,?,?,?)",
            (user_id, card["code"], card["cost"], now)
        )
        conn.commit()

    await safe_edit_message(query, 
        "🎉 *Redeem Successful!*\n\n"
        f"🎁 Gift Card: `{card['code']}`\n"
        f"⭐ Points used: *{card['cost']}*\n\n"
        "⚠️ Code ko kisi ke saath share na karein.",
        parse_mode="Markdown",
        reply_markup=back_button()
    )


async def show_leaderboard(query):
    with closing(db()) as conn:
        rows = conn.execute(
            "SELECT first_name, username, points, referrals "
            "FROM users WHERE banned=0 "
            "ORDER BY points DESC, referrals DESC LIMIT 10"
        ).fetchall()

    lines = ["🏆 *Leaderboard*\n"]

    if not rows:
        lines.append("No users yet.")
    else:
        for i, r in enumerate(rows, 1):
            name = r["first_name"] or r["username"] or "User"
            lines.append(
                f"{i}. {name} — ⭐ {r['points']} | 👥 {r['referrals']}"
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
        await update.message.reply_text("⛔ Admin only.")
        return

    await update.message.reply_text(
        "👑 *Admin Panel*\n\n"
        "/users — user statistics\n"
        "/addcode CODE COST — add gift card\n"
        "/addpoints USER_ID AMOUNT — add points\n"
        "/ban USER_ID — ban\n"
        "/unban USER_ID — unban\n"
        "/broadcast TEXT — broadcast",
        parse_mode="Markdown"
    )


async def addcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /addcode CODE COST")
        return

    code = context.args[0].strip()

    try:
                cost = int(context.args[1])
        if cost <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("COST positive number hona chahiye.")
        return

    try:
        with closing(db()) as conn:
            conn.execute(
                "INSERT INTO giftcards(code,cost) VALUES(?,?)",
                (code, cost)
            )
            conn.commit()
        await update.message.reply_text("✅ Gift card added.")
    except sqlite3.IntegrityError:
        await update.message.reply_text("❌ Ye code already added hai.")


async def addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: /addpoints USER_ID AMOUNT"
        )
        return

    try:
        uid = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "USER_ID aur AMOUNT number hone chahiye."
        )
        return

    with closing(db()) as conn:
        cur = conn.execute(
            "UPDATE users SET points=points+? WHERE user_id=?",
            (amount, uid)
        )
        conn.commit()

    await update.message.reply_text(
        "✅ Points updated." if cur.rowcount else "❌ User not found."
    )


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    with closing(db()) as conn:
        total = conn.execute(
            "SELECT COUNT(*) c FROM users"
        ).fetchone()["c"]
        verified = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE verified=1"
        ).fetchone()["c"]
        banned = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE banned=1"
        ).fetchone()["c"]

    await update.message.reply_text(
        f"📊 Users: {total}\n"
        f"✅ Verified: {verified}\n"
        f"🚫 Banned: {banned}"
    )


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id) or len(context.args) != 1:
        return

    uid = int(context.args[0])

    with closing(db()) as conn:
        conn.execute(
            "UPDATE users SET banned=1 WHERE user_id=?", (uid,)
        )
        conn.commit()

    await update.message.reply_text("🚫 User banned.")


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id) or len(context.args) != 1:
        return

    uid = int(context.args[0])

    with closing(db()) as conn:
        conn.execute(
            "UPDATE users SET banned=0 WHERE user_id=?", (uid,)
        )
        conn.commit()

    await update.message.reply_text("✅ User unbanned.")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text.partition(" ")[2].strip()

    if not text:
        await update.message.reply_text(
            "Usage: /broadcast your message"
        )
        return

    with closing(db()) as conn:
        ids = [
            r["user_id"]
            for r in conn.execute(
                "SELECT user_id FROM users WHERE banned=0"
            ).fetchall()
        ]

    sent = failed = 0

    for uid in ids:
        try:
            await context.bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"📣 Broadcast done.\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}"
    )


async def text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await require_verified(update, context):
        await update.message.reply_text(
            "🏠 Main Menu:",
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
    app.add_handler(CallbackQueryHandler(refer_callback, pattern=r"^refer$"))
    app.add_handler(CallbackQueryHandler(callbacks))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_fallback)
    )

    log.info("AmazonGC Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
