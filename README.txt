# AmazonGC Telegram Bot

Features:
- Mandatory channel verification
- Main menu
- Balance / points
- Referral tracking and referral rewards
- Leaderboard
- Gift-card inventory and redemption
- Admin points management
- Admin ban/unban
- Admin broadcast
- SQLite database

## Railway variables

Required:
BOT_TOKEN=your_bot_token
ADMIN_IDS=your_telegram_numeric_user_id

Optional:
REF_BONUS=20
DB_PATH=amazon_gc_bot.db

## Start command

python bot.py

## Admin commands

/admin
/users
/addcode CODE COST
/addpoints USER_ID AMOUNT
/ban USER_ID
/unban USER_ID
/broadcast MESSAGE

IMPORTANT:
- Never put BOT_TOKEN in GitHub.
- Add the bot as administrator in all required channels.
- Only use gift-card codes that you legitimately own or are authorized to distribute.
