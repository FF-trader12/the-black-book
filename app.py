from flask import Flask, request, jsonify
import os
import requests
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

# =========================
# THE BLACK BOOK v0.2
# Football scanner using The Odds API
# =========================

BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("BOT_TOKEN")
    or ""
).strip()

ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "").strip()

VERSION = "the-black-book-v0.2.3-today-accumulator-builder"

# Telegram topic routing
MAIN_CHAT_ID = os.environ.get("MAIN_CHAT_ID", "-1004368159147").strip()
FOOTBALL_CHAT_ID = os.environ.get("FOOTBALL_CHAT_ID", MAIN_CHAT_ID).strip()
FOOTBALL_TOPIC_ID = int(os.environ.get("FOOTBALL_TOPIC_ID", "13") or 13)

RACING_TOPIC_ID = int(os.environ.get("RACING_TOPIC_ID", "11") or 11)
RUGBY_TOPIC_ID = int(os.environ.get("RUGBY_TOPIC_ID", "15") or 15)

# Scanner settings
MIN_FOOTBALL_SCORE = int(os.environ.get("MIN_FOOTBALL_SCORE", "65") or 65)
RUNTIME_MIN_FOOTBALL_SCORE = MIN_FOOTBALL_SCORE
MAX_FOOTBALL_POSTS = int(os.environ.get("MAX_FOOTBALL_POSTS", "3") or 3)
FOOTBALL_SCAN_DAYS = int(os.environ.get("FOOTBALL_SCAN_DAYS", "1") or 1)

# Keep this controlled so the free Odds API credits do not get burned.
FOOTBALL_SPORT_KEYS = [
    x.strip()
    for x in os.environ.get(
        "FOOTBALL_SPORT_KEYS",
        "soccer_epl,soccer_uefa_champs_league,soccer_uefa_europa_league,soccer_fifa_world_cup"
    ).split(",")
    if x.strip()
]

ODDS_REGION = os.environ.get("ODDS_REGION", "uk")
ODDS_MARKETS = os.environ.get("ODDS_MARKETS", "h2h")


# =========================
# Telegram helpers
# =========================

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

    return requests.post(api_url("sendMessage"), json=payload, timeout=20)


def send_to_football_topic(text: str):
    return send_telegram_message(
        FOOTBALL_CHAT_ID,
        text,
        thread_id=FOOTBALL_TOPIC_ID,
    )


# =========================
# Formatting helpers
# =========================

def money(amount):
    try:
        value = float(amount)
    except Exception:
        return "£0"

    if value == int(value):
        return f"£{int(value)}"
    return f"£{value:.2f}"


def decimal_to_fractional(decimal_odds):
    try:
        decimal_odds = float(decimal_odds)
    except Exception:
        return "N/A"

    if decimal_odds <= 1:
        return "N/A"

    profit = decimal_odds - 1
    best_num = 1
    best_den = 1
    best_error = abs(profit - 1)

    for den in range(1, 21):
        num = round(profit * den)
        if num <= 0:
            continue

        error = abs(profit - (num / den))
        if error < best_error:
            best_error = error
            best_num = num
            best_den = den

    return f"{best_num}/{best_den}"


def format_odds(decimal_odds):
    try:
        decimal_odds = float(decimal_odds)
        return f"{decimal_to_fractional(decimal_odds)} ({decimal_odds:.2f})"
    except Exception:
        return "N/A"


def implied_probability(decimal_odds):
    try:
        decimal_odds = float(decimal_odds)
        if decimal_odds <= 0:
            return 0
        return 1 / decimal_odds
    except Exception:
        return 0

def quality_label(score):
    try:
        score = int(score)
    except Exception:
        score = 0

    if score >= 90:
        return "🔥 ELITE"
    if score >= 80:
        return "✅ STRONG"
    if score >= 70:
        return "👀 GOOD"
    if score >= 60:
        return "🟠 WATCHLIST"
    return "⚪ LOW EDGE"


def get_current_threshold():
    return int(globals().get("RUNTIME_MIN_FOOTBALL_SCORE", MIN_FOOTBALL_SCORE))


def set_current_threshold(value):
    global RUNTIME_MIN_FOOTBALL_SCORE

    try:
        value = int(value)
    except Exception:
        return False, "Score must be a number."

    if value < 1 or value > 100:
        return False, "Score must be between 1 and 100."

    RUNTIME_MIN_FOOTBALL_SCORE = value
    return True, f"Football scoring threshold set to {value}."


def safe_float(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def kickoff_text(commence_time):
    raw = str(commence_time or "").strip()
    if not raw:
        return "Unknown"

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%d %b %H:%M UTC")
    except Exception:
        return raw

def parse_event_datetime(commence_time):
    raw = str(commence_time or "").strip()
    if not raw:
        return None

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def is_event_in_scan_window(event, days=None):
    """Default is today only in UTC. Use FOOTBALL_SCAN_DAYS to widen later."""
    days = FOOTBALL_SCAN_DAYS if days is None else int(days)
    event_dt = parse_event_datetime(event.get("commence_time"))

    if not event_dt:
        return False

    start = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)

    return start <= event_dt < end


def compact_league_name(sport_key):
    mapping = {
        "soccer_epl": "EPL",
        "soccer_fifa_world_cup": "World Cup",
        "soccer_italy_serie_a": "Serie A",
        "soccer_germany_dfb_pokal": "DFB-Pokal",
        "soccer_sweden_allsvenskan": "Sweden",
        "soccer_norway_eliteserien": "Norway",
        "soccer_league_of_ireland": "Ireland",
        "soccer_conmebol_copa_libertadores": "Libertadores",
        "soccer_conmebol_copa_sudamericana": "Sudamericana",
    }
    return mapping.get(str(sport_key), str(sport_key).replace("soccer_", "").replace("_", " ").title())


def build_compact_bet_line(leg, odds):
    return f"{leg} @ {format_odds(odds)}"


# =========================
# Odds API helpers
# =========================

def odds_api_get(path, params=None):
    if not ODDS_API_KEY:
        raise ValueError("Missing THE_ODDS_API_KEY in Render environment variables.")

    url = f"https://api.the-odds-api.com/v4{path}"
    final_params = params.copy() if params else {}
    final_params["apiKey"] = ODDS_API_KEY

    response = requests.get(url, params=final_params, timeout=25)

    # Invalid sport key, no need to crash the whole scan.
    if response.status_code == 404:
        return None

    response.raise_for_status()
    return response.json()


def get_active_sports():
    return odds_api_get("/sports", params={}) or []


def get_available_soccer_sports():
    soccer = []

    try:
        sports = get_active_sports()
    except Exception:
        return soccer

    for item in sports:
        key = item.get("key", "")
        group = item.get("group", "")
        active = item.get("active", False)

        if active and ("soccer" in key.lower() or group.lower() == "soccer"):
            soccer.append({
                "key": key,
                "title": item.get("title", key),
                "description": item.get("description", ""),
            })

    return soccer


def clean_api_error(error_text):
    """Keep Telegram errors readable and never expose API keys in chat."""
    text = str(error_text)

    if "apiKey=" in text:
        text = text.split("apiKey=")[0] + "apiKey=HIDDEN"

    if "422 Client Error" in text:
        return "Market not supported for this league with current settings"

    if "401 Client Error" in text:
        return "API key issue - check THE_ODDS_API_KEY"

    if "429 Client Error" in text:
        return "Odds API credit/rate limit hit"

    if len(text) > 140:
        text = text[:140] + "..."

    return text


def fetch_football_odds():
    """
    Pull h2h first because it is broadly supported.
    Then try totals and btts separately. If they fail, h2h still works.
    Also filters to today's fixtures by default.
    """
    events_by_id = {}
    errors = []

    market_attempts = ["h2h", "totals", "btts"]

    for sport_key in FOOTBALL_SPORT_KEYS:
        for market_name in market_attempts:
            try:
                data = odds_api_get(
                    f"/sports/{sport_key}/odds",
                    params={
                        "regions": ODDS_REGION,
                        "markets": market_name,
                        "oddsFormat": "decimal",
                        "dateFormat": "iso",
                    },
                )

                if not data:
                    continue

                for event in data:
                    if not is_event_in_scan_window(event):
                        continue

                    event_id = event.get("id") or f"{event.get('home_team')}|{event.get('away_team')}|{event.get('commence_time')}"
                    event["sport_key_used"] = sport_key

                    if event_id not in events_by_id:
                        events_by_id[event_id] = event
                    else:
                        existing = events_by_id[event_id]
                        existing_bookmakers = existing.setdefault("bookmakers", [])
                        existing_bookmakers.extend(event.get("bookmakers", []))

            except Exception as e:
                # h2h is essential. totals/btts are optional, so keep optional errors quiet unless useful.
                cleaned = clean_api_error(e)
                if market_name == "h2h" or "API key" in cleaned or "limit" in cleaned:
                    errors.append(f"{sport_key}/{market_name}: {cleaned}")

    return list(events_by_id.values()), errors


# =========================
# Market extraction
# =========================

def get_best_market_prices(event):
    home = event.get("home_team", "")
    away = event.get("away_team", "")

    prices = {
        "home": None,
        "away": None,
        "draw": None,
        "over_25": None,
        "under_25": None,
        "btts_yes": None,
        "btts_no": None,
        "bookmakers": set(),
    }

    for bookmaker in event.get("bookmakers", []):
        title = bookmaker.get("title", bookmaker.get("key", "Bookmaker"))
        prices["bookmakers"].add(title)

        for market in bookmaker.get("markets", []):
            key = market.get("key")

            for outcome in market.get("outcomes", []):
                name = outcome.get("name")
                price = safe_float(outcome.get("price"))
                point = safe_float(outcome.get("point"))

                if price is None:
                    continue

                if key == "h2h":
                    if name == home:
                        if prices["home"] is None or price > prices["home"]["price"]:
                            prices["home"] = {"name": name, "price": price, "bookmaker": title}
                    elif name == away:
                        if prices["away"] is None or price > prices["away"]["price"]:
                            prices["away"] = {"name": name, "price": price, "bookmaker": title}
                    elif str(name).lower() == "draw":
                        if prices["draw"] is None or price > prices["draw"]["price"]:
                            prices["draw"] = {"name": name, "price": price, "bookmaker": title}

                elif key == "totals" and point is not None and abs(point - 2.5) < 0.01:
                    if str(name).lower() == "over":
                        if prices["over_25"] is None or price > prices["over_25"]["price"]:
                            prices["over_25"] = {"name": "Over 2.5 Goals", "price": price, "bookmaker": title}
                    elif str(name).lower() == "under":
                        if prices["under_25"] is None or price > prices["under_25"]["price"]:
                            prices["under_25"] = {"name": "Under 2.5 Goals", "price": price, "bookmaker": title}

                elif key == "btts":
                    if str(name).lower() == "yes":
                        if prices["btts_yes"] is None or price > prices["btts_yes"]["price"]:
                            prices["btts_yes"] = {"name": "BTTS Yes", "price": price, "bookmaker": title}
                    elif str(name).lower() == "no":
                        if prices["btts_no"] is None or price > prices["btts_no"]["price"]:
                            prices["btts_no"] = {"name": "BTTS No", "price": price, "bookmaker": title}

    prices["bookmaker_count"] = len(prices["bookmakers"])
    prices["bookmakers"] = sorted(list(prices["bookmakers"]))

    return prices


def choose_favourite(prices):
    home = prices.get("home")
    away = prices.get("away")

    if not home or not away:
        return None

    if home["price"] <= away["price"]:
        return {
            "team": home["name"],
            "odds": home["price"],
            "bookmaker": home["bookmaker"],
            "side": "home",
        }

    return {
        "team": away["name"],
        "odds": away["price"],
        "bookmaker": away["bookmaker"],
        "side": "away",
    }


# =========================
# Scoring engine
# =========================

def score_football_event(event):
    prices = get_best_market_prices(event)
    favourite = choose_favourite(prices)

    if not favourite:
        return None

    fav_odds = favourite["odds"]
    fav_prob = implied_probability(fav_odds)

    score = 0
    reasons = []
    warnings = []

    # Favourite strength
    if fav_prob >= 0.72:
        score += 28
        reasons.append("Strong favourite profile")
    elif fav_prob >= 0.62:
        score += 24
        reasons.append("Good favourite profile")
    elif fav_prob >= 0.54:
        score += 18
        reasons.append("Moderate favourite profile")
    else:
        score += 8
        warnings.append("Favourite is not strongly priced")

    # Price sanity
    if 1.35 <= fav_odds <= 2.10:
        score += 14
        reasons.append("Favourite odds inside usable range")
    elif fav_odds < 1.35:
        score += 6
        warnings.append("Favourite odds may be too short")
    else:
        score += 4
        warnings.append("Favourite odds may be too risky")

    # Goals market
    over_25 = prices.get("over_25")
    under_25 = prices.get("under_25")

    if over_25 and under_25:
        over_prob = implied_probability(over_25["price"])
        under_prob = implied_probability(under_25["price"])

        if over_prob >= under_prob:
            score += 18
            reasons.append("Goal market supports an attacking game")
        elif abs(over_prob - under_prob) <= 0.04:
            score += 13
            reasons.append("Goal market is balanced")
        else:
            score += 7
            warnings.append("Goal market leans lower scoring")
    else:
        score += 4
        warnings.append("Limited goal market data")

    # BTTS market
    btts_yes = prices.get("btts_yes")
    btts_no = prices.get("btts_no")

    if btts_yes and btts_no:
        yes_prob = implied_probability(btts_yes["price"])
        no_prob = implied_probability(btts_no["price"])

        if yes_prob >= no_prob:
            score += 12
            reasons.append("BTTS market supports both teams scoring")
        else:
            score += 9
            reasons.append("BTTS market supports cleaner favourite script")
    else:
        score += 3
        warnings.append("Limited BTTS market data")

    # Bookmaker coverage
    bookmaker_count = prices.get("bookmaker_count", 0)

    if bookmaker_count >= 5:
        score += 14
        reasons.append("Multiple bookmakers available")
    elif bookmaker_count >= 3:
        score += 10
        reasons.append("Reasonable bookmaker coverage")
    elif bookmaker_count >= 1:
        score += 5
        warnings.append("Limited bookmaker coverage")

    # Market coverage
    available_markets = 0
    for key in ["home", "away", "draw", "over_25", "under_25", "btts_yes", "btts_no"]:
        if prices.get(key):
            available_markets += 1

    if available_markets >= 6:
        score += 14
        reasons.append("Good market coverage")
    elif available_markets >= 4:
        score += 8
        reasons.append("Basic market coverage")
    else:
        score += 2
        warnings.append("Not enough markets to build full setup")

    score = min(score, 100)

    if score >= 90:
        confidence = "ELITE"
    elif score >= 80:
        confidence = "STRONG"
    elif score >= 70:
        confidence = "GOOD"
    elif score >= 60:
        confidence = "WATCHLIST"
    else:
        confidence = "LOW EDGE"

    return {
        "event": event,
        "prices": prices,
        "favourite": favourite,
        "score": score,
        "confidence": confidence,
        "reasons": reasons,
        "warnings": warnings,
    }


# =========================
# Bet setup generation
# =========================

def build_bet_section(label, stake, odds, legs, purpose, bookmaker=None, include=True):
    if not include or odds is None or not legs:
        return ""

    return (
        f"{label}
"
        f"{money(stake)} stake | {format_odds(odds)} | Return {money(float(stake) * float(odds))}
"
        + (f"{bookmaker}
" if bookmaker else "")
        + "
".join([f"• {leg}" for leg in legs])
        + f"
<i>{purpose}</i>
"
    )


def generate_football_builds(scored):
    prices = scored["prices"]
    fav = scored["favourite"]

    fav_team = fav["team"]
    fav_odds = fav["odds"]

    home_price = prices.get("home")
    away_price = prices.get("away")
    draw_price = prices.get("draw")
    over_25 = prices.get("over_25")
    under_25 = prices.get("under_25")
    btts_yes = prices.get("btts_yes")
    btts_no = prices.get("btts_no")

    sections = []

    # SAFE: low-risk 1-2 leg setup.
    safe_legs = [f"{fav_team} To Win"]
    safe_odds = fav_odds
    safe_bookmaker = fav["bookmaker"]

    if over_25 and over_25["price"] <= 1.85:
        safe_legs.append("Over 2.5 Goals")
        safe_odds = round(safe_odds * over_25["price"], 2)
        safe_bookmaker = "Estimated Acca"

    sections.append(build_bet_section(
        "🟢 <b>SAFE</b>",
        10,
        safe_odds,
        safe_legs,
        "Safer route from favourite/goal markets.",
        bookmaker=safe_bookmaker,
        include=True,
    ))

    # VALUE: 2-3 leg accumulator when markets exist.
    value_legs = []
    value_odds = None
    value_bookmaker = "Estimated Acca"

    if fav_odds and over_25 and btts_yes:
        value_legs = [f"{fav_team} To Win", "Over 2.5 Goals", "BTTS Yes"]
        value_odds = round(fav_odds * over_25["price"] * btts_yes["price"], 2)
    elif fav_odds and over_25:
        value_legs = [f"{fav_team} To Win", "Over 2.5 Goals"]
        value_odds = round(fav_odds * over_25["price"], 2)
    elif fav_odds and btts_yes:
        value_legs = [f"{fav_team} To Win", "BTTS Yes"]
        value_odds = round(fav_odds * btts_yes["price"], 2)
    elif draw_price:
        value_legs = ["Draw"]
        value_odds = draw_price["price"]
        value_bookmaker = draw_price["bookmaker"]
    else:
        value_legs = [f"{fav_team} To Win"]
        value_odds = fav_odds
        value_bookmaker = fav["bookmaker"]

    sections.append(build_bet_section(
        "🟡 <b>VALUE ⭐</b>",
        10,
        value_odds,
        value_legs,
        "Best risk/reward angle available.",
        bookmaker=value_bookmaker,
        include=value_odds is not None,
    ))

    # COVER: protection angle, should not duplicate value where possible.
    cover_legs = []
    cover_odds = None
    cover_bookmaker = None

    if under_25 and draw_price:
        cover_legs = ["Draw", "Under 2.5 Goals"]
        cover_odds = round(draw_price["price"] * under_25["price"], 2)
        cover_bookmaker = "Estimated Acca"
    elif btts_no and fav_odds <= 1.90:
        cover_legs = [f"{fav_team} To Win", "BTTS No"]
        cover_odds = round(fav_odds * btts_no["price"], 2)
        cover_bookmaker = "Estimated Acca"
    elif draw_price:
        cover_legs = ["Draw"]
        cover_odds = draw_price["price"]
        cover_bookmaker = draw_price["bookmaker"]

    sections.append(build_bet_section(
        "🔵 <b>COVER</b>",
        4,
        cover_odds,
        cover_legs,
        "Protection angle if the main route is messy.",
        bookmaker=cover_bookmaker,
        include=cover_odds is not None,
    ))

    # RISKY: highest upside angle.
    risky_legs = []
    risky_odds = None
    risky_bookmaker = "Estimated Acca"

    if fav_odds and over_25 and btts_yes:
        risky_legs = [f"{fav_team} To Win", "Over 2.5 Goals", "BTTS Yes"]
        risky_odds = round(fav_odds * over_25["price"] * btts_yes["price"], 2)
    elif home_price and away_price and draw_price:
        outsider = home_price if home_price["price"] > away_price["price"] else away_price
        risky_legs = [f"{outsider['name']} To Win", "Draw cover unavailable"]
        risky_odds = outsider["price"]
        risky_bookmaker = outsider["bookmaker"]
    elif draw_price:
        risky_legs = ["Draw"]
        risky_odds = draw_price["price"]
        risky_bookmaker = draw_price["bookmaker"]

    sections.append(build_bet_section(
        "🔴 <b>RISKY ⚠️</b>",
        3,
        risky_odds,
        risky_legs,
        "Small stake only.",
        bookmaker=risky_bookmaker,
        include=risky_odds is not None,
    ))

    return [section for section in sections if section.strip()]


def build_football_setup_message(scored):
    event = scored["event"]
    prices = scored["prices"]
    fav = scored["favourite"]

    home = event.get("home_team", "Home")
    away = event.get("away_team", "Away")
    sport_key = event.get("sport_key_used", event.get("sport_key", "football"))
    kickoff = kickoff_text(event.get("commence_time"))

    sections = generate_football_builds(scored)

    if not sections:
        return None

    reasons = scored["reasons"][:2]
    reason_line = " | ".join(reasons) if reasons else "Market data supports setup"

    bot_pick = "🟢 SAFE"
    if any("VALUE" in section for section in sections):
        bot_pick = "🟡 VALUE"

    return (
        "⚽ <b>THE BLACK BOOK</b>

"
        f"<b>{home} vs {away}</b>
"
        f"{compact_league_name(sport_key)} | {kickoff}

"
        f"Score: <b>{scored['score']}/100</b> | <b>{scored['confidence']}</b>
"
        f"Fav: <b>{fav['team']}</b> @ {format_odds(fav['odds'])}

"
        + "
".join(sections)
        + "
"
        f"🎯 <b>Bot Pick:</b> {bot_pick}
"
        f"📌 <i>{reason_line}</i>
"
        "<i>Acca odds marked Estimated Acca are calculated from available single-market odds.</i>"
    )


# =========================
# Scanner runner
# =========================

def scan_football():
    events, errors = fetch_football_odds()
    scored_events = []

    for event in events:
        scored = score_football_event(event)

        if not scored:
            continue

        if scored["score"] < get_current_threshold():
            continue

        message = build_football_setup_message(scored)

        if not message:
            continue

        scored["message"] = message
        scored_events.append(scored)

    scored_events.sort(key=lambda item: item["score"], reverse=True)

    return scored_events[:MAX_FOOTBALL_POSTS], errors, len(events)


def run_football_scan(post_to_topic=True):
    setups, errors, scanned_count = scan_football()

    posts_sent = 0
    send_errors = []

    if post_to_topic:
        for setup in setups:
            response = send_to_football_topic(setup["message"])

            if response.status_code == 200:
                posts_sent += 1
            else:
                send_errors.append(response.text)

    summary = (
        "📖 <b>THE BLACK BOOK SCAN COMPLETE</b>\n\n"
        f"⚽ Today fixtures scanned: <b>{scanned_count}</b>\n"
        f"🔥 Setups found: <b>{len(setups)}</b>\n"
        f"📤 Posts sent: <b>{posts_sent}</b>\n"
        f"🎯 Market mode: <b>{ODDS_MARKETS}</b>\n"
        f"⚙️ Threshold: <b>{get_current_threshold()}</b>\n\n"
    )

    if not setups:
        summary += "No qualifying football setups found for today.\n"

    if errors:
        summary += "\n<b>API notes:</b>\n"
        for err in errors[:4]:
            summary += f"• {err}\n"

    if send_errors:
        summary += "\n<b>Telegram send errors:</b>\n"
        for err in send_errors[:2]:
            summary += f"• {clean_api_error(err)}\n"

    return {
        "setups": setups,
        "errors": errors,
        "scanned_count": scanned_count,
        "posts_sent": posts_sent,
        "summary": summary,
    }


# =========================
# Bot messages
# =========================

def build_start_message():
    return (
        "📖 <b>THE BLACK BOOK</b>\n\n"
        "Bot Status: <b>ONLINE ✅</b>\n"
        f"Version: <b>{VERSION}</b>\n\n"
        "Commands:\n"
        "• /scan - Run all active scanners\n"
        "• /scanfootball - Scan football only\n"
        "• /showallfootball - Show today top scored fixtures\n"
        "• /setscoring - View/change scoring threshold\n"
        "• /sports - Show available soccer sport keys\n"
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
        "• /scan - Run all active scanners\n"
        "• /scanfootball - Scan football only\n"
        "• /showallfootball - Show today top scored fixtures\n"
        "• /setscoring 65 - Change scoring threshold\n"
        "• /sports - Show available soccer sport keys from Odds API\n"
        "• /top - Demo SAFE / VALUE / COVER / RISKY setup\n"
        "• /risky - Demo risky setup only\n"
        "• /chatid - Show current chat/topic ID\n"
        "• /help - Show this menu\n\n"
        "<b>Current Status</b>\n"
        "• Football scanner active\n"
        "• Racing scanner planned\n"
        "• Rugby scanner planned\n\n"
        "<b>Posting Rule</b>\n"
        "No edge = no post."
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


def build_sports_message():
    soccer = get_available_soccer_sports()

    if not soccer:
        return (
            "⚽ <b>FOOTBALL LEAGUES</b>\n\n"
            "Could not load soccer sport keys from The Odds API.\n"
            "Check THE_ODDS_API_KEY or try again later."
        )

    preferred = [
        "soccer_epl",
        "soccer_fifa_world_cup",
        "soccer_italy_serie_a",
        "soccer_germany_dfb_pokal",
        "soccer_sweden_allsvenskan",
        "soccer_norway_eliteserien",
        "soccer_league_of_ireland",
        "soccer_conmebol_copa_libertadores",
        "soccer_conmebol_copa_sudamericana",
    ]

    by_key = {item["key"]: item for item in soccer}
    enabled = [key for key in FOOTBALL_SPORT_KEYS if key in by_key]

    lines = [
        "⚽ <b>FOOTBALL LEAGUES</b>",
        "",
        "<b>Currently scanning:</b>",
    ]

    if enabled:
        for key in enabled:
            item = by_key[key]
            lines.append(f"✅ <b>{item['title']}</b>\n<code>{key}</code>")
    else:
        lines.append("No active scanned leagues matched the API list.")

    lines.append("")
    lines.append("<b>Recommended available keys:</b>")

    count = 0
    for key in preferred:
        if key in by_key:
            item = by_key[key]
            lines.append(f"• <b>{item['title']}</b>\n<code>{key}</code>")
            count += 1

    if count == 0:
        for item in soccer[:8]:
            lines.append(f"• <b>{item['title']}</b>\n<code>{item['key']}</code>")

    lines.append("")
    lines.append("Render variable:")
    lines.append("<code>FOOTBALL_SPORT_KEYS</code>")

    return "\n".join(lines)


# =========================
# Flask routes
# =========================

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
        "odds_api_loaded": bool(ODDS_API_KEY),
        "football_chat_id": FOOTBALL_CHAT_ID,
        "football_topic_id": FOOTBALL_TOPIC_ID,
        "min_football_score": get_current_threshold(),
        "football_sport_keys": FOOTBALL_SPORT_KEYS,
    }), 200


@app.route("/set-webhook", methods=["GET"])
def set_webhook():
    if not BOT_TOKEN:
        return jsonify({"ok": False, "error": "Missing TELEGRAM_BOT_TOKEN or BOT_TOKEN"}), 500

    webhook_url = request.host_url.rstrip("/") + "/telegram-webhook"
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


@app.route("/scheduled-scan", methods=["GET", "POST"])
def scheduled_scan():
    result = run_football_scan(post_to_topic=True)

    return jsonify({
        "ok": True,
        "version": VERSION,
        "scanned_count": result["scanned_count"],
        "qualifying_setups": len(result["setups"]),
        "posts_sent": result["posts_sent"],
        "errors": result["errors"][:5],
    }), 200


@app.route("/scan-football", methods=["GET", "POST"])
def scan_football_route():
    result = run_football_scan(post_to_topic=True)

    return jsonify({
        "ok": True,
        "version": VERSION,
        "scanned_count": result["scanned_count"],
        "qualifying_setups": len(result["setups"]),
        "posts_sent": result["posts_sent"],
        "summary": result["summary"],
        "errors": result["errors"][:5],
    }), 200


@app.route("/show-all-football", methods=["GET", "POST"])
def show_all_football_route():
    scored_events, errors, scanned_count = scan_all_football_scores(limit=10)

    return jsonify({
        "ok": True,
        "version": VERSION,
        "scanned_count": scanned_count,
        "returned": len(scored_events),
        "threshold": get_current_threshold(),
        "top_scores": [
            {
                "match": f"{item['event'].get('home_team')} vs {item['event'].get('away_team')}",
                "score": item["score"],
                "confidence": item["confidence"],
                "favourite": item["favourite"]["team"],
                "favourite_odds": item["favourite"]["odds"],
            }
            for item in scored_events
        ],
        "errors": errors[:5],
    }), 200


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
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/help"):
            reply = build_help_message()
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/top"):
            reply = build_top_message()
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/risky"):
            reply = build_risky_message()
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/chatid"):
            reply = build_chatid_message(chat_id, thread_id)
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/showallfootball") or lower_text.startswith("/showfootball"):
            reply = build_showallfootball_message(limit=10)
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/setscoring"):
            args_text = text[len("/setscoring"):].strip()
            reply = build_setscoring_message(args_text)
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/sports"):
            reply = build_sports_message()
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/scanfootball") or lower_text.startswith("/scan"):
            result = run_football_scan(post_to_topic=True)
            tg_response = send_telegram_message(chat_id, result["summary"], thread_id=thread_id)

        else:
            return jsonify({"ok": True, "ignored": "not_a_command"}), 200

        return jsonify({
            "ok": tg_response.status_code == 200,
            "telegram_status": tg_response.status_code,
            "telegram_response": tg_response.json(),
        }), 200

    except Exception as e:
        try:
            update = request.get_json(silent=True) or {}
            message = update.get("message") or update.get("edited_message") or {}
            chat = message.get("chat", {})
            error_chat_id = chat.get("id")
            error_thread_id = message.get("message_thread_id")

            if error_chat_id:
                send_telegram_message(
                    error_chat_id,
                    f"⚠️ <b>Black Book Error</b>\n\n<code>{str(e)}</code>",
                    thread_id=error_thread_id,
                )
        except Exception:
            pass

        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
