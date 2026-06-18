from flask import Flask, request, jsonify
import os
import requests
from datetime import datetime, timezone

app = Flask(__name__)

# Supports both names so it works with your current Render variable.
BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("BOT_TOKEN")
    or ""
).strip()

VERSION = "the-black-book-v0.1-flask-test"


def now_utc():
    return datetime.now(timezone.utc)


def api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"


def send_telegram_message(chat_id, text: str, thread_id=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if thread_id is not None:
        payload["message_thread_id"] = thread_id

    return requests.post(api_url("sendMessage"), json=payload, timeout=15)


def build_start_message():
    return (
        "📖 <b>THE BLACK BOOK</b>\n\n"
        "Bot Status: <b>ONLINE ✅</b>\n"
        f"Version: <b>{VERSION}</b>\n\n"
        "Commands:\n"
        "• /top - Demo SAFE / VALUE / COVER / RISKY setup\n"
        "• /risky - Demo risky setup only\n"
        "• /chatid - Show current chat/topic ID\n"
        "• /help - Show help menu\n\n"
        "Find The Edge."
    )


def build_help_message():
    return (
        "📖 <b>THE BLACK BOOK HELP</b>\n\n"
        "<b>Available Commands</b>\n\n"
        "• /start - Bot intro\n"
        "• /top - Demo SAFE / VALUE / COVER / RISKY setup\n"
        "• /risky - Demo risky setup only\n"
        "• /chatid - Show current chat/topic ID\n"
        "• /help - Show this menu\n\n"
        "<b>Coming Later</b>\n"
        "• Real fixture scanner\n"
        "• Odds analysis\n"
        "• Hedge engine\n"
        "• Outcome tracking\n"
        "• Daily automatic alerts"
    )


def build_top_message():
    return (
        "📖 <b>THE BLACK BOOK</b>\n\n"
        "🔥 <b>TOP DEMO SETUP</b>\n\n"
        "Match: <b>England vs Croatia</b>\n"
        "Setup Score: <b>84%</b>\n"
        "Confidence: <b>HIGH</b>\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🟢 <b>SAFE</b>\n"
        "Stake: <b>£10</b>\n"
        "Odds: <b>2/1</b>\n"
        "Return: <b>£30</b>\n\n"
        "<b>Bet:</b>\n"
        "• Over 1.5 Goals\n"
        "• Over 4.5 Corners\n"
        "• England Over 0.5 Goals\n\n"
        "Purpose: Highest probability setup.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🟡 <b>VALUE ⭐</b>\n"
        "Stake: <b>£10</b>\n"
        "Odds: <b>7/2</b>\n"
        "Return: <b>£45</b>\n\n"
        "<b>Bet:</b>\n"
        "• Both Teams To Score\n"
        "• Over 2.5 Goals\n"
        "• Over 4.5 Corners\n\n"
        "Purpose: Best risk/reward setup.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🔵 <b>COVER</b>\n"
        "Stake: <b>£4</b>\n"
        "Odds: <b>6/4</b>\n"
        "Return: <b>£10</b>\n\n"
        "<b>Bet:</b>\n"
        "• England Over 1.5 Team Goals\n\n"
        "Purpose: Can win with the value bet and can still cover if the value bet fails.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🔴 <b>RISKY ⚠️</b>\n"
        "Stake: <b>£3</b>\n"
        "Odds: <b>10/1</b>\n"
        "Return: <b>£33</b>\n\n"
        "<b>Bet:</b>\n"
        "• England Win\n"
        "• Kane Anytime Scorer\n"
        "• BTTS Yes\n"
        "• Over 2.5 Goals\n\n"
        "⚠️ High risk / low probability / bigger return.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🤖 <b>BOT PLAY</b>\n"
        "Best Single Bet: <b>🟡 VALUE</b>\n"
        "Best Combo: <b>🟡 VALUE + 🔵 COVER</b>\n\n"
        "Responsible note: this is demo output only. No outcome is guaranteed."
    )


def build_risky_message():
    return (
        "📖 <b>THE BLACK BOOK</b>\n\n"
        "🔴 <b>RISKY ⚠️ DEMO SETUP</b>\n\n"
        "Match: <b>England vs Croatia</b>\n\n"
        "Stake: <b>£3</b>\n"
        "Odds: <b>10/1</b>\n"
        "Return: <b>£33</b>\n\n"
        "<b>Bet:</b>\n"
        "• England Win\n"
        "• Kane Anytime Scorer\n"
        "• BTTS Yes\n"
        "• Over 2.5 Goals\n\n"
        "Risk Level: <b>HIGH</b>\n\n"
        "⚠️ This section is for small-stake, high-return setups only."
    )


def build_chatid_message(chat_id, thread_id):
    return (
        "📖 <b>THE BLACK BOOK CHAT ID</b>\n\n"
        f"Chat ID: <code>{chat_id}</code>\n"
        f"Topic ID: <code>{thread_id}</code>\n\n"
        "Use these IDs later for routing sport alerts into the correct topic."
    )


@app.route("/", methods=["GET"])
def home():
    return "The Black Book Bot is running", 200


@app.route("/version", methods=["GET"])
def version():
    return VERSION, 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "version": VERSION,
        "utc": now_utc().isoformat(),
        "bot_token_loaded": bool(BOT_TOKEN),
    }), 200


@app.route("/set-webhook", methods=["GET"])
def set_webhook():
    if not BOT_TOKEN:
        return jsonify({"ok": False, "error": "Missing TELEGRAM_BOT_TOKEN or BOT_TOKEN"}), 500

    webhook_url = request.host_url.rstrip("/") + "/telegram-webhook"

    # Telegram requires HTTPS for webhooks. Render sometimes passes http internally,
    # so force the public webhook URL to https.
    webhook_url = webhook_url.replace("http://", "https://", 1)

    response = requests.post(
        api_url("setWebhook"),
        json={"url": webhook_url},
        timeout=15,
    )

    return jsonify({
        "ok": response.status_code == 200,
        "webhook_url": webhook_url,
        "telegram_response": response.json(),
    }), response.status_code


@app.route("/delete-webhook", methods=["GET"])
def delete_webhook():
    if not BOT_TOKEN:
        return jsonify({"ok": False, "error": "Missing TELEGRAM_BOT_TOKEN or BOT_TOKEN"}), 500

    response = requests.post(api_url("deleteWebhook"), timeout=15)

    return jsonify({
        "ok": response.status_code == 200,
        "telegram_response": response.json(),
    }), response.status_code


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json(force=True)

        message = update.get("message") or update.get("edited_message")
        if not message:
            return jsonify({"ok": True, "ignored": "no_message"}), 200

        text = str(message.get("text", "")).strip()
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        thread_id = message.get("message_thread_id")

        if not chat_id:
            return jsonify({"ok": True, "ignored": "no_chat_id"}), 200

        lower_text = text.lower()

        if lower_text.startswith("/start"):
            reply = build_start_message()

        elif lower_text.startswith("/help"):
            reply = build_help_message()

        elif lower_text.startswith("/top"):
            reply = build_top_message()

        elif lower_text.startswith("/risky"):
            reply = build_risky_message()

        elif lower_text.startswith("/chatid"):
            reply = build_chatid_message(chat_id, thread_id)

        else:
            return jsonify({"ok": True, "ignored": "not_a_command"}), 200

        tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        return jsonify({
            "ok": tg_response.status_code == 200,
            "telegram_status": tg_response.status_code,
            "telegram_response": tg_response.json(),
        }), 200

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
