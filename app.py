import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 THE BLACK BOOK\n\n"
        "Bot Status: ONLINE ✅\n\n"
        "Commands:\n"
        "/top - Demo setup\n"
        "/risky - Demo risky bet\n"
        "/help - Help menu"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 THE BLACK BOOK HELP\n\n"
        "/start\n"
        "/top\n"
        "/risky\n"
        "/help"
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 THE BLACK BOOK\n\n"
        "🔥 TOP DEMO SETUP\n\n"
        "🟢 SAFE\n"
        "Stake: £10\n"
        "Odds: 2/1\n"
        "Return: £30\n\n"
        "Bet:\n"
        "• Over 1.5 Goals\n"
        "• Over 4.5 Corners\n"
        "• England Over 0.5 Goals\n\n"
        "🟡 VALUE\n"
        "Stake: £10\n"
        "Odds: 7/2\n"
        "Return: £45\n\n"
        "🔵 COVER\n"
        "Stake: £4\n"
        "Odds: 6/4\n"
        "Return: £10\n\n"
        "🔴 RISKY\n"
        "Stake: £3\n"
        "Odds: 10/1\n"
        "Return: £33"
    )


async def risky(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔴 RISKY SETUP\n\n"
        "Stake: £3\n"
        "Odds: 10/1\n"
        "Return: £33\n\n"
        "• England Win\n"
        "• Kane Anytime Scorer\n"
        "• BTTS Yes\n"
        "• Over 2.5 Goals"
    )


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("risky", risky))

    print("The Black Book Bot Running...")
    app.run_polling()


if __name__ == "__main__":
    main()
