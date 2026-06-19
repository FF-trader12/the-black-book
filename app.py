from flask import Flask, request, jsonify
import os
import requests
import itertools
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

app = Flask(__name__)

# =========================
# THE BLACK BOOK v0.3.3
# Safe Value Risky Daily Acca + UK Time
# =========================

BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("BOT_TOKEN")
    or ""
).strip()

ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "").strip()

VERSION = "the-black-book-v0.3.3"

# Telegram topic routing
MAIN_CHAT_ID = os.environ.get("MAIN_CHAT_ID", "-1004368159147").strip()
FOOTBALL_CHAT_ID = os.environ.get("FOOTBALL_CHAT_ID", MAIN_CHAT_ID).strip()
FOOTBALL_TOPIC_ID = int(os.environ.get("FOOTBALL_TOPIC_ID", "13") or 13)

RACING_TOPIC_ID = int(os.environ.get("RACING_TOPIC_ID", "11") or 11)
RUGBY_TOPIC_ID = int(os.environ.get("RUGBY_TOPIC_ID", "15") or 15)

# Scanner settings
MIN_FOOTBALL_SCORE = int(os.environ.get("MIN_FOOTBALL_SCORE", "65") or 65)
MAX_FOOTBALL_POSTS = int(os.environ.get("MAX_FOOTBALL_POSTS", "3") or 3)
CURRENT_MIN_FOOTBALL_SCORE = MIN_FOOTBALL_SCORE
MIN_VALUE_COMBO_SCORE = int(os.environ.get("MIN_VALUE_COMBO_SCORE", "58") or 58)
MIN_RISKY_COMBO_SCORE = int(os.environ.get("MIN_RISKY_COMBO_SCORE", "55") or 55)
MAX_COMBO_LEGS = int(os.environ.get("MAX_COMBO_LEGS", "3") or 3)
DAILY_ACCA_MIN_SCORE = int(os.environ.get("DAILY_ACCA_MIN_SCORE", "70") or 70)
DAILY_ACCA_MAX_LEGS = int(os.environ.get("DAILY_ACCA_MAX_LEGS", "4") or 4)

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
EXTRA_MARKETS_TO_TEST = os.environ.get(
    "EXTRA_MARKETS_TO_TEST",
    "h2h,totals,btts,spreads,alternate_spreads,alternate_totals,team_totals,draw_no_bet,double_chance,player_goalscorer,player_shots,corners,cards"
)


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
        return decimal_to_fractional(decimal_odds)
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
        uk_dt = dt.astimezone(ZoneInfo("Europe/London"))
        return uk_dt.strftime("%d %b %H:%M (UK Time)")
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


def is_event_today(event):
    event_dt = parse_event_datetime(event.get("commence_time"))
    if not event_dt:
        return False

    start = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start <= event_dt < end


def parse_scan_date(args_text=""):
    raw = str(args_text or "").strip().lower()

    if not raw:
        return now_utc().date(), "today"

    token = raw.split()[0].replace("/", ".").replace("-", ".")

    if token in ["today", "todays"]:
        return now_utc().date(), "today"

    if token in ["tomorrow", "tmr", "tmrw"]:
        return (now_utc() + timedelta(days=1)).date(), "tomorrow"

    parts = [p for p in token.split(".") if p]

    try:
        if len(parts) == 3:
            if len(parts[0]) == 4:
                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2])
            else:
                day = int(parts[0])
                month = int(parts[1])
                year = int(parts[2])
                if year < 100:
                    year += 2000

            return datetime(year, month, day, tzinfo=timezone.utc).date(), f"{day:02d}.{month:02d}.{str(year)[-2:]}"
    except Exception:
        pass

    return now_utc().date(), "today"


def event_is_on_date(event, target_date):
    event_dt = parse_event_datetime(event.get("commence_time"))
    if not event_dt:
        return False
    return event_dt.date() == target_date


def scan_date_label(target_date):
    try:
        return target_date.strftime("%d %b %Y")
    except Exception:
        return "Selected date"


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


def quality_label(score):
    if score >= 90:
        return "ELITE"
    if score >= 80:
        return "STRONG"
    if score >= 70:
        return "GOOD"
    if score >= 60:
        return "WATCHLIST"
    return "LOW EDGE"


def clean_api_error(error_text):
    text = str(error_text)
    if "apiKey=" in text:
        text = text.split("apiKey=")[0] + "apiKey=HIDDEN"
    if "422 Client Error" in text:
        return "market not supported"
    if "429 Client Error" in text:
        return "API credit/rate limit hit"
    if "401 Client Error" in text:
        return "API key issue"
    return text[:160]

def short_leg_name(leg):
    leg = str(leg)
    leg = leg.replace(" To Win", " Win")
    leg = leg.replace("Over 2.5 Goals", "Over 2.5")
    leg = leg.replace("Under 2.5 Goals", "Under 2.5")
    leg = leg.replace("BTTS Yes", "BTTS")
    leg = leg.replace("BTTS No", "BTTS No")
    return leg


def compact_legs(legs):
    return " + ".join(short_leg_name(leg) for leg in legs)


def setup_status(score):
    if score >= get_score_threshold():
        return "✅ POST"
    return "❌ BELOW THRESHOLD"



def get_score_threshold():
    return int(globals().get("CURRENT_MIN_FOOTBALL_SCORE", MIN_FOOTBALL_SCORE))


def set_score_threshold(value):
    global CURRENT_MIN_FOOTBALL_SCORE

    try:
        value = int(str(value).strip())
    except Exception:
        return False, "Score must be a number."

    if value < 1 or value > 100:
        return False, "Score must be between 1 and 100."

    CURRENT_MIN_FOOTBALL_SCORE = value
    return True, f"Minimum football score set to {value}."


def build_score_message(args_text=""):
    args_text = str(args_text or "").strip()

    if not args_text:
        return (
            "⚙️ <b>THE BLACK BOOK SCORE</b>\n\n"
            f"Current minimum score: <b>{get_score_threshold()}</b>\n\n"
            "Use:\n"
            "<code>/score 60</code>\n"
            "<code>/score 65</code>\n"
            "<code>/score 70</code>"
        )

    value = args_text.split()[0]
    ok, msg = set_score_threshold(value)

    if ok:
        return (
            "✅ <b>SCORE UPDATED</b>\n\n"
            f"{msg}\n\n"
            "Run <code>/showallfootball</code> or <code>/scanfootball</code>."
        )

    return f"⚠️ <b>SCORE NOT UPDATED</b>\n\n{msg}"


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


def fetch_football_odds(target_date=None):
    all_events_by_id = {}
    errors = []

    # Pull markets separately. If totals or BTTS fails, h2h still works.
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
                    selected_date = target_date or now_utc().date()
                    if not event_is_on_date(event, selected_date):
                        continue

                    event_id = event.get("id") or f"{event.get('home_team')}|{event.get('away_team')}|{event.get('commence_time')}"
                    event["sport_key_used"] = sport_key

                    if event_id not in all_events_by_id:
                        all_events_by_id[event_id] = event
                    else:
                        all_events_by_id[event_id].setdefault("bookmakers", []).extend(event.get("bookmakers", []))

            except Exception as e:
                cleaned = clean_api_error(e)
                if market_name == "h2h" or "API" in cleaned or "limit" in cleaned:
                    errors.append(f"{sport_key}/{market_name}: {cleaned}")

    return list(all_events_by_id.values()), errors


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

    confidence = quality_label(score)

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
# Assessment engine
# =========================

def make_leg(name, odds, leg_type, confidence, bookmaker=None, tags=None):
    if odds is None:
        return None

    try:
        odds = float(odds)
    except Exception:
        return None

    if odds <= 1:
        return None

    return {
        "name": name,
        "odds": odds,
        "type": leg_type,
        "confidence": int(confidence),
        "bookmaker": bookmaker or "Market",
        "tags": tags or [],
    }


def build_candidate_legs(scored):
    prices = scored["prices"]
    fav = scored["favourite"]

    legs = []

    home = prices.get("home")
    away = prices.get("away")
    draw = prices.get("draw")
    over_25 = prices.get("over_25")
    under_25 = prices.get("under_25")
    btts_yes = prices.get("btts_yes")
    btts_no = prices.get("btts_no")

    fav_team = fav["team"]
    fav_odds = fav["odds"]
    fav_prob = implied_probability(fav_odds)

    if fav_prob >= 0.70:
        fav_conf = 88
    elif fav_prob >= 0.62:
        fav_conf = 80
    elif fav_prob >= 0.54:
        fav_conf = 68
    else:
        fav_conf = 52

    leg = make_leg(
        f"{fav_team} To Win",
        fav_odds,
        "winner",
        fav_conf,
        fav.get("bookmaker"),
        tags=["safe", "main"],
    )
    if leg:
        legs.append(leg)

    if draw:
        leg = make_leg(
            "Draw",
            draw["price"],
            "draw",
            42 if draw["price"] >= 3.0 else 55,
            draw["bookmaker"],
            tags=["cover", "hedge"],
        )
        if leg:
            legs.append(leg)

    # Outsider win only as a risky candidate.
    if home and away:
        outsider = home if home["price"] > away["price"] else away
        leg = make_leg(
            f"{outsider['name']} To Win",
            outsider["price"],
            "outsider",
            30,
            outsider["bookmaker"],
            tags=["risky"],
        )
        if leg:
            legs.append(leg)

    if over_25:
        over_conf = 70 if over_25["price"] <= 2.10 else 58
        leg = make_leg(
            "Over 2.5 Goals",
            over_25["price"],
            "goals",
            over_conf,
            over_25["bookmaker"],
            tags=["goals", "value"],
        )
        if leg:
            legs.append(leg)

    if under_25:
        under_conf = 65 if under_25["price"] <= 2.10 else 54
        leg = make_leg(
            "Under 2.5 Goals",
            under_25["price"],
            "goals",
            under_conf,
            under_25["bookmaker"],
            tags=["cover", "goals"],
        )
        if leg:
            legs.append(leg)

    if btts_yes:
        yes_conf = 68 if btts_yes["price"] <= 2.10 else 56
        leg = make_leg(
            "BTTS Yes",
            btts_yes["price"],
            "btts",
            yes_conf,
            btts_yes["bookmaker"],
            tags=["value", "goals"],
        )
        if leg:
            legs.append(leg)

    if btts_no:
        no_conf = 62 if btts_no["price"] <= 2.20 else 52
        leg = make_leg(
            "BTTS No",
            btts_no["price"],
            "btts",
            no_conf,
            btts_no["bookmaker"],
            tags=["cover"],
        )
        if leg:
            legs.append(leg)

    return legs



def combo_has_conflict(legs):
    names = {leg["name"] for leg in legs}
    result_types = {"winner", "draw", "outsider"}

    if "Over 2.5 Goals" in names and "Under 2.5 Goals" in names:
        return True
    if "BTTS Yes" in names and "BTTS No" in names:
        return True
    if sum(1 for leg in legs if leg["type"] in result_types) > 1:
        return True

    return False


def combo_correlation_score(legs):
    names = {leg["name"] for leg in legs}
    types = {leg["type"] for leg in legs}

    score = 50

    if "winner" in types and "goals" in types:
        score += 25
    if "winner" in types and "Over 2.5 Goals" in names:
        score += 8
    if "winner" in types and "Under 2.5 Goals" in names:
        score += 6
    if "goals" in types and "btts" in types and "Over 2.5 Goals" in names and "BTTS Yes" in names:
        score += 14
    if "draw" in types and "Under 2.5 Goals" in names:
        score += 6
    if "outsider" in types:
        score -= 16

    return max(0, min(score, 100))


def combo_value_score(odds):
    if odds < 1.30:
        return 10
    if odds < 1.60:
        return 38
    if odds < 2.10:
        return 64
    if odds < 3.50:
        return 88
    if odds < 5.50:
        return 78
    if odds < 8.50:
        return 58
    return 32


def combo_risk_penalty(legs, odds):
    penalty = 0

    if len(legs) == 2:
        penalty += 4
    elif len(legs) >= 3:
        penalty += 14

    if odds >= 6:
        penalty += 6
    if odds >= 10:
        penalty += 16
    if any(leg["type"] == "outsider" for leg in legs):
        penalty += 18

    return penalty


def assess_combo(legs):
    if not legs or combo_has_conflict(legs):
        return None

    odds = 1.0
    for leg in legs:
        odds *= float(leg["odds"])

    odds = round(odds, 2)

    confidence = sum(leg["confidence"] for leg in legs) / len(legs)
    value = combo_value_score(odds)
    correlation = combo_correlation_score(legs)
    risk_penalty = combo_risk_penalty(legs, odds)

    types = {leg["type"] for leg in legs}
    bonus = 0

    if "winner" in types and "goals" in types:
        bonus += 12
    if len(legs) == 1 and "winner" in types:
        bonus += 2
    if "draw" in types:
        bonus -= 4
    if "outsider" in types:
        bonus -= 10

    final_score = round(
        (confidence * 0.42)
        + (value * 0.30)
        + (correlation * 0.28)
        + bonus
        - risk_penalty
    )

    final_score = max(0, min(100, final_score))

    return {
        "legs": legs,
        "leg_names": [leg["name"] for leg in legs],
        "odds": odds,
        "score": int(final_score),
        "confidence_component": int(confidence),
        "value_component": int(value),
        "correlation_component": int(correlation),
        "risk_penalty": int(risk_penalty),
        "type_count": len(legs),
    }


def generate_candidate_combos(scored):
    legs = build_candidate_legs(scored)
    combos = []
    max_legs = max(1, min(MAX_COMBO_LEGS, 3))

    for size in range(1, max_legs + 1):
        for parts in itertools.combinations(legs, size):
            assessed = assess_combo(list(parts))
            if assessed:
                combos.append(assessed)

    unique = {}
    for combo in combos:
        key = tuple(sorted(combo["leg_names"]))
        if key not in unique or combo["score"] > unique[key]["score"]:
            unique[key] = combo

    combos = list(unique.values())
    combos.sort(key=lambda item: (item["score"], item["odds"]), reverse=True)
    return combos


def select_best_setup(scored):
    combos = generate_candidate_combos(scored)
    fav = scored["favourite"]
    fav_name = f"{fav['team']} To Win"

    singles = [c for c in combos if c["type_count"] == 1]
    doubles = [c for c in combos if c["type_count"] == 2]
    trebles = [c for c in combos if c["type_count"] >= 3]

    fav_safe = next((c for c in singles if c["leg_names"] == [fav_name]), None)
    safe_candidates = [
        c for c in singles
        if c["odds"] <= 2.40
        and c["score"] >= 45
        and not any(leg["type"] == "outsider" for leg in c["legs"])
    ]
    safe = fav_safe if fav_safe and fav_safe["score"] >= 45 else max(
        safe_candidates,
        key=lambda c: (c["score"], -c["odds"]),
        default=None,
    )

    value_candidates = [
        c for c in doubles
        if any(leg["type"] == "winner" for leg in c["legs"])
        and any(leg["type"] == "goals" for leg in c["legs"])
        and 1.70 <= c["odds"] <= 5.50
        and c["score"] >= MIN_VALUE_COMBO_SCORE
    ]

    if not value_candidates:
        value_candidates = [
            c for c in doubles
            if 1.70 <= c["odds"] <= 5.50
            and c["score"] >= MIN_VALUE_COMBO_SCORE
        ]

    value = max(value_candidates, key=lambda c: (c["score"], c["odds"]), default=None)
    cover = safe

    if not cover:
        draw_single = next((c for c in singles if c["leg_names"] == ["Draw"]), None)
        if draw_single and draw_single["odds"] <= 5.50:
            cover = draw_single

    risky_candidates = [
        c for c in (trebles + doubles)
        if 2.70 <= c["odds"] <= 9.00
        and c["score"] >= MIN_RISKY_COMBO_SCORE
        and any(leg["type"] == "winner" for leg in c["legs"])
    ]
    risky = max(risky_candidates, key=lambda c: (c["score"], c["odds"]), default=None)

    best_combo_score = max([c["score"] for c in combos], default=0)

    return {
        "safe": safe,
        "cover": cover,
        "value": value,
        "risky": risky,
        "combos": combos,
        "best_combo_score": best_combo_score,
    }


def fixture_assessment_score(scored, setup):
    score = scored["score"]

    value = setup.get("value")
    risky = setup.get("risky")
    safe = setup.get("safe")

    if value:
        score += int((value["score"] - 50) * 0.35)
    else:
        score -= 10

    if risky:
        score += int((risky["score"] - 50) * 0.15)
    else:
        score -= 3

    if safe and safe["score"] >= 55:
        score += 3

    return max(0, min(100, score))



def build_combo_section(label, combo, stake):
    if not combo:
        return ""

    return (
        f"{label}\n"
        f"{compact_legs(combo['leg_names'])}\n"
        f"{format_odds(combo['odds'])} | {money(stake)} → {money(float(stake) * float(combo['odds']))}"
    )



def build_previewfootball_message(limit=5, target_date=None):
    events, errors = fetch_football_odds(target_date)
    rows = []

    for event in events:
        scored = score_football_event(event)
        if not scored:
            continue

        setup = select_best_setup(scored)
        assessed_score = fixture_assessment_score(scored, setup)

        rows.append({
            "event": event,
            "scored": scored,
            "setup": setup,
            "assessed_score": assessed_score,
        })

    rows.sort(key=lambda r: (r["assessed_score"], r["setup"]["best_combo_score"]), reverse=True)

    lines = [
        "🧠 <b>THE BLACK BOOK PREVIEW</b>",
        "",
        f"Date: <b>{scan_date_label(target_date or now_utc().date())}</b>",
        f"Fixtures: <b>{len(events)}</b>",
        f"Post score: <b>{get_score_threshold()}</b>",
        "",
    ]

    if not rows:
        lines.append("No scorable fixtures found.")
    else:
        for index, row in enumerate(rows[:limit], start=1):
            event = row["event"]
            setup = row["setup"]
            home = event.get("home_team", "Home")
            away = event.get("away_team", "Away")
            status = "✅ POST" if row["assessed_score"] >= get_score_threshold() else "❌ NO POST"
            value = setup.get("value")
            pick = value or setup.get("safe")

            lines.append(
                f"<b>{index}. {home} vs {away}</b>\n"
                f"{status} | Fixture <b>{row['assessed_score']}/100</b> | Combo <b>{setup['best_combo_score']}/100</b>\n"
                f"Pick: {compact_legs(pick['leg_names']) + ' @ ' + format_odds(pick['odds']) if pick else 'None'}\n"
            )

    if errors:
        lines.append("<b>API notes:</b>")
        for err in errors[:4]:
            lines.append(f"• {err}")

    return "\n".join(lines)


def build_settings_message():
    return (
        "⚙️ <b>THE BLACK BOOK SETTINGS</b>\\n\\n"
        f"Version: <b>{VERSION}</b>\\n"
        f"Post score: <b>{get_score_threshold()}</b>\\n"
        f"Max posts: <b>{MAX_FOOTBALL_POSTS}</b>\\n"
        f"Max combo legs: <b>{MAX_COMBO_LEGS}</b>\\n"
        f"Value combo min: <b>{MIN_VALUE_COMBO_SCORE}</b>\\n"
        f"Risky combo min: <b>{MIN_RISKY_COMBO_SCORE}</b>\\n"
        f"Sports: <code>{','.join(FOOTBALL_SPORT_KEYS)}</code>"
    )

# =========================
# Bet setup generation
# =========================

def build_bet_section(label, stake, odds, legs, purpose, bookmaker=None, include=True):
    if not include or odds is None or not legs:
        return ""

    return (
        f"{label}\n"
        f"{compact_legs(legs)}\n\n"
        f"Odds: <b>{format_odds(odds)}</b>\n"
        f"Stake: <b>{money(stake)}</b>\n"
        f"Return: <b>{money(float(stake) * float(odds))}</b>"
    )


def generate_football_builds(scored):
    setup = select_best_setup(scored)

    sections = []

    sections.append(build_combo_section("🟢 <b>SAFE</b>", setup.get("safe"), 10))
    sections.append(build_combo_section("🔵 <b>COVER</b>", setup.get("cover"), 4))
    sections.append(build_combo_section("🟡 <b>VALUE ⭐</b>", setup.get("value"), 10))
    sections.append(build_combo_section("🔴 <b>RISKY ⚠️</b>", setup.get("risky"), 3))

    return [section for section in sections if section.strip()]



def build_football_setup_message(scored):
    event = scored["event"]
    setup = select_best_setup(scored)
    assessed_score = fixture_assessment_score(scored, setup)

    home = event.get("home_team", "Home")
    away = event.get("away_team", "Away")
    sport_key = event.get("sport_key_used", event.get("sport_key", "football"))
    kickoff = kickoff_text(event.get("commence_time"))

    safe = setup.get("safe")
    cover = setup.get("cover")
    value = setup.get("value")
    risky = setup.get("risky")

    if not value and not risky:
        return None

    sections = []

    if safe:
        sections.append(build_combo_section("🟢 <b>SAFE</b>", safe, 10))

    if cover and cover != safe:
        sections.append(build_combo_section("🔵 <b>COVER</b>", cover, 4))

    if value:
        sections.append(build_combo_section("🟡 <b>VALUE ⭐</b>", value, 10))

    if risky and risky != value:
        sections.append(build_combo_section("🔴 <b>RISKY ⚠️</b>", risky, 3))

    bot_pick = "🟡 VALUE" if value else "🔴 RISKY"

    return (
        "📖 <b>THE BLACK BOOK</b>\n\n"
        f"<b>{home} vs {away}</b>\n"
        f"🏆 {compact_league_name(sport_key)} | ⏰ {kickoff}\n\n"
        f"🔥 Fixture: <b>{assessed_score}/100</b> | 🧠 Combo: <b>{setup['best_combo_score']}/100</b>\n"
        f"📊 <b>{quality_label(assessed_score)}</b>\n\n"
        + "\n\n".join(sections)
        + "\n\n🎯 <b>BOT PICK:</b> "
        f"{bot_pick}"
    )


# =========================
# Scanner runner
# =========================

def scan_football(target_date=None):
    events, errors = fetch_football_odds(target_date)
    scored_events = []

    for event in events:
        scored = score_football_event(event)

        if not scored:
            continue

        setup = select_best_setup(scored)
        assessed_score = fixture_assessment_score(scored, setup)

        if assessed_score < get_score_threshold():
            continue

        message = build_football_setup_message(scored)

        if not message:
            continue

        scored["message"] = message
        scored["assessment_score"] = assessed_score
        scored["setup"] = setup
        scored_events.append(scored)

    scored_events.sort(key=lambda item: item.get("assessment_score", item["score"]), reverse=True)

    return scored_events[:MAX_FOOTBALL_POSTS], errors, len(events)


def run_football_scan(post_to_topic=True, target_date=None):
    setups, errors, scanned_count = scan_football(target_date)

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
        "📖 <b>THE BLACK BOOK SCAN</b>\n\n"
        f"📅 Date: <b>{scan_date_label(target_date or now_utc().date())}</b>\n"
        f"⚽ Fixtures: <b>{scanned_count}</b>\n"
        f"🔥 Setups: <b>{len(setups)}</b>\n"
        f"📤 Posted: <b>{posts_sent}</b>\n"
        f"⚙️ Score: <b>{get_score_threshold()}</b>\n\n"
    )

    if not setups:
        summary += "No qualifying setups found today. Run /showallfootball to see scores.\n"

    if errors:
        summary += "\n<b>API notes:</b>\n" + "\n".join([f"• {e}" for e in errors[:5]]) + "\n"

    if send_errors:
        summary += "\n<b>Telegram send errors:</b>\n" + "\n".join(send_errors[:3]) + "\n"

    return {
        "setups": setups,
        "errors": errors,
        "scanned_count": scanned_count,
        "posts_sent": posts_sent,
        "summary": summary,
    }


def scan_all_football_scores(limit=10, target_date=None):
    events, errors = fetch_football_odds(target_date)
    scored_events = []

    for event in events:
        scored = score_football_event(event)
        if scored:
            scored_events.append(scored)

    scored_events.sort(key=lambda item: item.get("assessment_score", item["score"]), reverse=True)
    return scored_events[:limit], errors, len(events)


def build_showallfootball_message(limit=10, target_date=None):
    scored_events, errors, scanned_count = scan_all_football_scores(limit=limit, target_date=target_date)

    lines = [
        "⚽ <b>THE BLACK BOOK FOOTBALL SCORES</b>",
        "",
        f"Date: <b>{scan_date_label(target_date or now_utc().date())}</b>",
        f"Fixtures scanned: <b>{scanned_count}</b>",
        f"Showing top: <b>{len(scored_events)}</b>",
        f"Post threshold: <b>{get_score_threshold()}</b>",
        "",
    ]

    if not scored_events:
        lines.append("No scorable football fixtures found today.")
    else:
        for i, scored in enumerate(scored_events, start=1):
            event = scored["event"]
            home = event.get("home_team", "Home")
            away = event.get("away_team", "Away")
            fav = scored["favourite"]
            setup = select_best_setup(scored)
            assessed_score = fixture_assessment_score(scored, setup)
            status = setup_status(assessed_score)
            value = setup.get("value")
            lines.append(
                f"<b>{i}. {home} vs {away}</b>\n"
                f"{status} — <b>{assessed_score}/100</b> — {quality_label(assessed_score)}\n"
                f"Best: {compact_legs(value['leg_names']) + ' @ ' + format_odds(value['odds']) if value else fav['team'] + ' @ ' + format_odds(fav['odds'])}\n"
            )

    if errors:
        lines.append("<b>API notes:</b>")
        for err in errors[:4]:
            lines.append(f"• {err}")

    return "\n".join(lines)


def acca_line(row, combo_type):
    event = row["event"]
    combo = row[combo_type]
    home = event.get("home_team", "Home")
    away = event.get("away_team", "Away")
    kickoff = kickoff_text(event.get("commence_time"))

    return (
        f"<b>{home} vs {away}</b>\n"
        f"🕒 {kickoff}\n"
        f"{compact_legs(combo['leg_names'])}\n"
        f"{format_odds(combo['odds'])} | Score <b>{row['assessment_score']}/100</b>"
    )


def build_acca_section(title, rows, combo_type, stake):
    selected = [row for row in rows if row.get(combo_type)]
    selected = selected[:DAILY_ACCA_MAX_LEGS]

    if len(selected) < 2:
        return (
            f"{title}\n"
            "Not enough qualifying picks."
        )

    total_odds = 1.0
    lines = [title, ""]

    for index, row in enumerate(selected, start=1):
        combo = row[combo_type]
        total_odds *= float(combo["odds"])
        lines.append(f"<b>{index}.</b> {acca_line(row, combo_type)}\n")

    total_odds = round(total_odds, 2)

    lines.extend([
        "━━━━━━━━━━",
        f"Total odds: <b>{format_odds(total_odds)}</b>",
        f"Stake: <b>{money(stake)}</b>",
        f"Return: <b>{money(float(stake) * float(total_odds))}</b>",
    ])

    return "\n".join(lines)


def build_daily_acca_message(target_date=None):
    events, errors = fetch_football_odds(target_date)
    rows = []

    for event in events:
        scored = score_football_event(event)
        if not scored:
            continue

        setup = select_best_setup(scored)
        assessed_score = fixture_assessment_score(scored, setup)

        if assessed_score < DAILY_ACCA_MIN_SCORE:
            continue

        rows.append({
            "event": event,
            "assessment_score": assessed_score,
            "safe": setup.get("safe"),
            "value": setup.get("value"),
            "risky": setup.get("risky"),
        })

    rows.sort(key=lambda row: row["assessment_score"], reverse=True)

    lines = [
        "🧾 <b>THE BLACK BOOK DAILY ACCAS</b>",
        "",
        f"Date: <b>{scan_date_label(target_date or now_utc().date())}</b>",
        f"Fixtures checked: <b>{len(events)}</b>",
        f"Qualifying fixtures: <b>{len(rows)}</b>",
        f"Min score: <b>{DAILY_ACCA_MIN_SCORE}</b>",
        "",
    ]

    if len(rows) < 2:
        lines.append("Not enough strong picks to build daily accas.")
        if errors:
            lines.append("")
            lines.append("<b>API notes:</b>")
            for err in errors[:4]:
                lines.append(f"• {err}")
        return "\n".join(lines)

    lines.append(build_acca_section("🟢 <b>SAFE ACCA</b>", rows, "safe", 2))
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(build_acca_section("🟡 <b>VALUE ACCA ⭐</b>", rows, "value", 1))
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(build_acca_section("🔴 <b>RISKY ACCA ⚠️</b>", rows, "risky", 1))

    if errors:
        lines.append("")
        lines.append("<b>API notes:</b>")
        for err in errors[:4]:
            lines.append(f"• {err}")

    lines.append("")
    lines.append("<i>Accas are higher risk. Keep stakes small.</i>")

    return "\n".join(lines)


# =========================
# Bot messages
# =========================

def build_start_message():
    return (
        "📖 <b>THE BLACK BOOK</b>\n\n"
        "Bot Status: <b>ONLINE ✅</b>\n"
        f"Version: <b>{VERSION}</b>\n\n"
        "<b>Main Commands</b>\n"
        "• /scanfootball - Run football scanner and post qualifying setups\n"
        "• /previewfootball - Preview assessed fixtures before posting\n"
        "• /showallfootball - Show selected date fixture scores\n• /dailyacca 20.06.26 - Safe/Value/Risky daily accas\n\n"
        "<b>Settings</b>\n"
        "• /score - View current post score\n"
        "• /score 60 - Change post score\n"
        "• /settings - Show scanner settings\n\n"
        "<b>Data / Setup</b>\n"
        "• /marketsfootball - Test available Odds API markets\n"
        "• /sports - Show available soccer sport keys\n"
        "• /chatid - Show current chat/topic ID\n"
        "• /help - Show help menu\n\n"
        "Find The Edge."
    )


def build_help_message():
    return (
        "📖 <b>THE BLACK BOOK HELP</b>\n\n"
        "<b>Football</b>\n"
        "• /scanfootball - Scan football and post qualifying setups\n"
        "• /previewfootball - Show assessed fixtures and candidate combos\n"
        "• /showallfootball - Show selected date fixture scores\n• /dailyacca 20.06.26 - Safe/Value/Risky daily accas\n\n"
        "<b>Controls</b>\n"
        "• /score - Show current post score\n"
        "• /score 60 - Lower/raise post threshold\n"
        "• /settings - Show active settings\n\n"
        "<b>Data</b>\n"
        "• /marketsfootball - Test which bet-builder markets are available\n"
        "• /sports - Show available soccer sport keys\n"
        "• /chatid - Show current chat/topic ID\n\n"
        "<b>Demo</b>\n"
        "• /top - Demo old SAFE / VALUE / COVER / RISKY card\n"
        "• /risky - Demo risky setup only\n\n"
        "<b>Posting Rule</b>\n"
        "The bot posts only when the assessment score passes your /score threshold."
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
            "⚽ <b>AVAILABLE SOCCER SPORTS</b>\n\n"
            "Could not load soccer sport keys from The Odds API.\n"
            "Check THE_ODDS_API_KEY or try again later."
        )

    lines = ["⚽ <b>AVAILABLE SOCCER SPORTS</b>\n"]

    for item in soccer[:40]:
        lines.append(f"• <code>{item['key']}</code> — {item['title']}")

    lines.append(
        "\nTo control which competitions are scanned, set this Render variable:\n"
        "<code>FOOTBALL_SPORT_KEYS</code>"
    )

    return "\n".join(lines)


def inspect_available_markets_for_football():
    """
    Tests likely football market names one by one.
    This tells us what The Odds API actually returns for your key/plan/leagues.
    """
    supported = []
    unsupported = []
    sample_details = []

    market_names = [x.strip() for x in EXTRA_MARKETS_TO_TEST.split(",") if x.strip()]
    sport_keys = FOOTBALL_SPORT_KEYS[:3]

    for sport_key in sport_keys:
        for market_name in market_names:
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
                    unsupported.append(f"{sport_key}/{market_name}: no data")
                    continue

                found = False
                for event in data[:3]:
                    for bookmaker in event.get("bookmakers", []):
                        for market in bookmaker.get("markets", []):
                            if market.get("key") == market_name:
                                found = True
                                if len(sample_details) < 8:
                                    sample_details.append(
                                        f"{market_name}: {event.get('home_team')} vs {event.get('away_team')}"
                                    )

                if found:
                    supported.append(f"{sport_key}/{market_name}")
                else:
                    unsupported.append(f"{sport_key}/{market_name}: no market returned")

            except Exception as e:
                unsupported.append(f"{sport_key}/{market_name}: {clean_api_error(e)}")

    return supported, unsupported, sample_details


def build_marketsfootball_message():
    supported, unsupported, sample_details = inspect_available_markets_for_football()

    lines = [
        "🧪 <b>FOOTBALL MARKET TEST</b>",
        "",
        "<b>Returning data:</b>",
    ]

    if supported:
        for item in supported[:20]:
            lines.append(f"✅ <code>{item}</code>")
    else:
        lines.append("No extra markets confirmed yet.")

    lines.append("")
    lines.append("<b>Samples:</b>")
    if sample_details:
        for item in sample_details[:8]:
            lines.append(f"• {item}")
    else:
        lines.append("No samples returned.")

    lines.append("")
    lines.append("<b>Unavailable / failed:</b>")
    for item in unsupported[:12]:
        lines.append(f"❌ {item}")

    lines.append("")
    lines.append("This proves whether corners/player props are available on your current Odds API plan.")

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
        "min_football_score": get_score_threshold(),
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


@app.route("/preview-football", methods=["GET", "POST"])
def preview_football_route():
    target_date, _ = parse_scan_date(request.args.get("date", ""))
    message = build_previewfootball_message(limit=8, target_date=target_date)

    return jsonify({
        "ok": True,
        "version": VERSION,
        "preview": message,
    }), 200


@app.route("/daily-acca", methods=["GET", "POST"])
def daily_acca_route():
    target_date, _ = parse_scan_date(request.args.get("date", ""))
    message = build_daily_acca_message(target_date=target_date)

    return jsonify({
        "ok": True,
        "version": VERSION,
        "acca": message,
    }), 200


@app.route("/markets-football", methods=["GET", "POST"])
def markets_football_route():
    supported, unsupported, sample_details = inspect_available_markets_for_football()

    return jsonify({
        "ok": True,
        "version": VERSION,
        "supported": supported,
        "unsupported": unsupported[:25],
        "samples": sample_details,
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

        elif lower_text.startswith("/version"):
            reply = f"📖 <b>THE BLACK BOOK</b>\n\nVersion: <b>{VERSION}</b>"
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

        elif lower_text.startswith("/previewtomorrow"):
            target_date, _ = parse_scan_date("tomorrow")
            reply = build_previewfootball_message(limit=8, target_date=target_date)
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/previewfootball") or lower_text.startswith("/preview"):
            command = text.split()[0]
            args_text = text[len(command):].strip()
            target_date, _ = parse_scan_date(args_text)
            reply = build_previewfootball_message(limit=8, target_date=target_date)
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/dailyaccatomorrow") or lower_text.startswith("/accatomorrow"):
            target_date, _ = parse_scan_date("tomorrow")
            reply = build_daily_acca_message(target_date=target_date)
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/dailyacca") or lower_text.startswith("/acca"):
            command = text.split()[0]
            args_text = text[len(command):].strip()
            target_date, _ = parse_scan_date(args_text)
            reply = build_daily_acca_message(target_date=target_date)
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/settings"):
            reply = build_settings_message()
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/score"):
            args_text = text[len("/score"):].strip()
            reply = build_score_message(args_text)
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/marketsfootball") or lower_text.startswith("/footballmarkets"):
            reply = build_marketsfootball_message()
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/showallfootball") or lower_text.startswith("/showfootball"):
            command = text.split()[0]
            args_text = text[len(command):].strip()
            target_date, _ = parse_scan_date(args_text)
            reply = build_showallfootball_message(limit=10, target_date=target_date)
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/sports"):
            reply = build_sports_message()
            tg_response = send_telegram_message(chat_id, reply, thread_id=thread_id)

        elif lower_text.startswith("/scantomorrow"):
            target_date, _ = parse_scan_date("tomorrow")
            result = run_football_scan(post_to_topic=True, target_date=target_date)
            tg_response = send_telegram_message(chat_id, result["summary"], thread_id=thread_id)

        elif lower_text.startswith("/scanfootball") or lower_text.startswith("/scan"):
            command = text.split()[0]
            args_text = text[len(command):].strip()
            target_date, _ = parse_scan_date(args_text)
            result = run_football_scan(post_to_topic=True, target_date=target_date)
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
