#!/usr/bin/env python3
# LEO X ALL-IN-ONE SHOP v18.7 – PREMIUM EMOJI FIX + STABILITY (Custom Emoji in Buttons + OCR + All Features)
import asyncio
import html
import json
import logging
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Keep the original Telegram button class under a private name.
# The UI wrapper below only adds Telegram 9.4+ button styling/custom-emoji
# fields when supported; it falls back to the normal button automatically.
_TelegramInlineKeyboardButton = InlineKeyboardButton

# ---------- Tesseract OCR (optional) ----------
try:
    import pytesseract
    from PIL import Image
    import io
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    pytesseract = None
    Image = None

# ---------- Gemini ----------
try:
    import google.generativeai as genai
except ImportError:
    genai = None

# ---------- Smile.one (MLBB Auto Top-up from wee.py) ----------
try:
    import cloudscraper
    from bs4 import BeautifulSoup
    SMILE_AVAILABLE = True
except ImportError:
    SMILE_AVAILABLE = False
    cloudscraper = None
    BeautifulSoup = None

# ---------------- CONFIG ----------------
BOT_TOKEN = "8275446095:AAHUYrowbdPI0Q9fk0edmEKkaXnKnUoFzlE"
GEMINI_API_KEY = "AQ.Ab8RN6Jghec9VDkQFrSWbff3DZbGW3gJK11lBIsMYfKkLbK6CQ"

# Smile.one / MLBB Auto Top-up settings (from wee.py)
COOKIE_FILE = "cookies.json"
SMILE_PRICES_FILE = "smile_prices.json"
MMK_EXCHANGE_RATE = 85   # 1 Smile Coin ≈ X MMK (adjust as needed)


OWNER_ID = int(os.getenv("OWNER_ID", "7308292609"))
ADMIN_IDS = {OWNER_ID}
KPAY_NUMBER = os.getenv("KPAY_NUMBER", "09687512062")
KPAY_NAME = os.getenv("KPAY_NAME", "Ma Chit Su")
WAVE_NUMBER = os.getenv("WAVE_NUMBER", "09687512062")
WAVE_NAME = os.getenv("WAVE_NAME", "Ye Htet Aung")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "kiki20251").lstrip("@")
MIN_RECHARGE = int(os.getenv("MIN_RECHARGE", "5000"))
USD_RATE = int(os.getenv("USD_RATE", "4700"))
ITEMS_PER_PAGE = 8
DB_PATH = os.getenv("LEO_DB_PATH", "kiki_shop.db")

GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-1.5-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-1.5-pro")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("leo-shop")

# ==================== SMILE.ONE CORE (from wee.py) ====================
# Fully automatic MLBB top-up via Smile.one. Used only for the 'mlbb' category.
TRANSLATIONS = {
    "Pacote de Valor por Tempo Limitado": "Limited Time Value Pack",
    "Passe Semanal de Diamante": "Weekly Diamond Pass",
    "Passagem do crepúsculo": "Twilight Pass",
    "Diamante": "Diamond",
    "Sucesso": "Success",
    "Pendente": "Pending",
    "Falhou": "Failed",
    "Pacote Semanal Elite": "Elite Weekly Bundle",
    "Pacote Mensal Épico": "Epic Monthly Bundle",
    "Disponível Uma Vez Por Semana": "Available Once Per Week",
    "Disponível Uma Vez Por Mês": "Available Once Per Month",
    "Saldo insuficiente": "Insufficient Balance"
}

def load_smile_prices():
    if os.path.exists(SMILE_PRICES_FILE):
        try:
            with open(SMILE_PRICES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_smile_prices(data):
    with open(SMILE_PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

class SmileOneBot:
    def __init__(self):
        self.base_url = "https://www.smile.one"
        self.user_agent = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        if SMILE_AVAILABLE:
            self.scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'android', 'mobile': True})
        else:
            self.scraper = None
        self.headers = {
            "User-Agent": self.user_agent,
            "Referer": f"{self.base_url}/br/customer/order",
            "X-Requested-With": "XMLHttpRequest"
        }
        self.market_data = None
        self.last_market_update = None
        self.mmk_rate = MMK_EXCHANGE_RATE

    def translate(self, text):
        for pt, en in TRANSLATIONS.items():
            if pt in text:
                text = text.replace(pt, en)
        return text

    def save_cookie(self, raw):
        try:
            d = {c.split('=', 1)[0].strip(): c.split('=', 1)[1].strip() for c in raw.split(';') if '=' in c}
            with open(COOKIE_FILE, 'w') as f:
                json.dump({"parsed_dict": d}, f)
            self.market_data = None  # force refresh
            return True, "✅ Cookie သိမ်းဆည်းပြီးပါပြီ!"
        except Exception as e:
            return False, f"❌ Cookie error: {str(e)}"

    def check_auth(self):
        if not SMILE_AVAILABLE or not self.scraper:
            return False, "cloudscraper not installed", None
        if not os.path.exists(COOKIE_FILE):
            return False, "NO_SESSION", None
        try:
            with open(COOKIE_FILE, 'r') as f:
                cookies = json.load(f).get("parsed_dict", {})
            res = self.scraper.get(f"{self.base_url}/br/customer/order", cookies=cookies, headers=self.headers)
            soup = BeautifulSoup(res.text, 'html.parser')
            det = soup.find('div', class_='user-details')
            if det:
                name = det.find('div', class_='user-name').get_text().strip()
                bal_elem = soup.find('div', class_='balance-coins')
                if bal_elem:
                    bal_parts = bal_elem.find_all('p')
                    if len(bal_parts) > 1:
                        bal = bal_parts[1].get_text().strip()
                        return True, "AUTH_SUCCESS", {"name": name, "saldo": f"{bal} coin"}
            return False, "DENIED", None
        except Exception as e:
            return False, f"ERROR: {str(e)}", None

    def id_check(self, u_id, z_id, product_pid=None):
        """Check MLBB account. Returns (ok, username_or_error) for backward compat,
        or use id_check_full for richer info."""
        ok, info = self.id_check_full(u_id, z_id, product_pid)
        if ok:
            return True, info.get("username", "Unknown")
        return False, info if isinstance(info, str) else info.get("error", "Invalid ID")

    def id_check_full(self, u_id, z_id, product_pid=None):
        """Rich account check. Returns (True, dict) or (False, error_str)."""
        if not os.path.exists(COOKIE_FILE):
            return False, "Auth Required"
        with open(COOKIE_FILE, 'r') as f:
            cookies = json.load(f).get("parsed_dict", {})
        try:
            pid = product_pid or "22590"
            payload = {
                "user_id": u_id,
                "zone_id": z_id,
                "pid": str(pid),
                "checkrole": "1",
                "pay_methond": "smilecoin",
                "channel_method": "smilecoin"
            }
            res = self.scraper.post(
                f"{self.base_url}/merchant/mobilelegends/checkrole",
                data=payload, cookies=cookies, headers=self.headers
            )
            data = res.json() if res is not None else {}
            if data.get('code') != 200:
                return False, data.get('info', 'Invalid ID')

            username = data.get('username') or data.get('role') or data.get('name') or "Unknown"
            region = (
                data.get('region')
                or data.get('country')
                or data.get('server_name')
                or data.get('zone_name')
                or guess_mlbb_region(z_id)
            )
            # Some Smile responses include first-purchase / double flags
            double_info = data.get('double') or data.get('first_charge') or data.get('bonus') or {}
            return True, {
                "username": str(username),
                "region": str(region) if region else "Myanmar / Global",
                "raw": data,
                "double_info": double_info,
            }
        except Exception as e:
            return False, f"Connection Error: {str(e)}"

    def get_market(self, force_refresh=False):
        if not force_refresh and self.market_data and self.last_market_update:
            if (datetime.now() - self.last_market_update).seconds < 300:
                return self.market_data
        try:
            if not os.path.exists(COOKIE_FILE):
                return None
            with open(COOKIE_FILE, 'r') as f:
                cookies = json.load(f).get("parsed_dict", {})
            res = self.scraper.get(f"{self.base_url}/br/merchant/mobilelegends",
                                   cookies=cookies, headers=self.headers)
            match = re.search(r"info\s*=\s*JSON\.parse\('(.*?)'\);", res.text, re.DOTALL)
            data = json.loads(match.group(1)) if match else {}
            soup = BeautifulSoup(res.text, 'html.parser')
            pkgs = []
            custom_prices = load_smile_prices()

            for item in soup.find_all('li', class_='fr fs', id=True):
                pid = item.get('id')
                raw_name = item.find('h3').get_text(strip=True) if item.find('h3') else "Unknown"
                name = self.translate(raw_name)

                coin_price = 0
                if pid in data and 'smilecoin' in data[pid] and 'total_amount' in data[pid]['smilecoin']:
                    try:
                        coin_price = float(data[pid]['smilecoin']['total_amount'])
                    except Exception:
                        coin_price = 0

                if pid in custom_prices:
                    mmk_price = custom_prices[pid].get("price", int(coin_price * self.mmk_rate))
                    display_name = custom_prices[pid].get("name", name)
                else:
                    mmk_price = int(coin_price * self.mmk_rate)
                    display_name = name

                pkgs.append({
                    "pid": pid,
                    "name": display_name,
                    "coin_value": coin_price,
                    "mmk_price": int(mmk_price),
                    "raw_name": name
                })
            self.market_data = pkgs
            self.last_market_update = datetime.now()
            return pkgs
        except Exception as e:
            log.error("[SmileOne] Market Error: %s", e)
            return None

    async def topup_diamonds(self, uid, zone_id, product, quantity=1):
        auth, status, profile = self.check_auth()
        if not auth:
            return False, "❌ Authentication failed. Cookie စစ်ပါ။"

        try:
            with open(COOKIE_FILE, 'r') as f:
                cookies = json.load(f).get("parsed_dict", {})

            res_init = self.scraper.get(f"{self.base_url}/br/merchant/mobilelegends", cookies=cookies)
            soup = BeautifulSoup(res_init.text, 'html.parser')
            csrf_input = soup.find('input', {'name': '_csrf'})
            if not csrf_input:
                return False, "❌ CSRF token မရပါ။ Cookie expire ဖြစ်နေနိုင်သည်။"
            csrf_token = csrf_input['value']

            query_payload = {
                "user_id": uid,
                "zone_id": zone_id,
                "pid": product['pid'],
                "checkrole": "",
                "pay_methond": "smilecoin",
                "channel_method": "smilecoin"
            }
            res_query = self.scraper.post(f"{self.base_url}/merchant/mobilelegends/query",
                                          data=query_payload, cookies=cookies, headers=self.headers)
            query_data = res_query.json()
            if query_data.get('code') != 200:
                return False, f"❌ User check failed: {query_data.get('info', 'Unknown')}"

            username = query_data.get('username', 'Unknown')
            flowid = query_data.get('flowid')

            success_count = 0
            for i in range(quantity):
                pay_payload = {
                    "_csrf": csrf_token,
                    "user_id": uid,
                    "zone_id": zone_id,
                    "pay_methond": "smilecoin",
                    "product_id": product['pid'],
                    "channel_method": "smilecoin",
                    "flowid": flowid,
                    "email": "",
                    "coupon_id": ""
                }
                res_pay = self.scraper.post(f"{self.base_url}/merchant/mobilelegends/pay",
                                            data=pay_payload, cookies=cookies, headers=self.headers, allow_redirects=False)
                redirect_url = res_pay.headers.get('Location') or res_pay.headers.get('x-redirect')
                if redirect_url:
                    if not redirect_url.startswith('http'):
                        redirect_url = f"{self.base_url}{redirect_url}"
                    res_final = self.scraper.get(redirect_url, cookies=cookies)
                    if "sucesso" in res_final.text.lower():
                        success_count += 1
                if i < quantity - 1:
                    await asyncio.sleep(1.5)

            if success_count > 0:
                return True, f"✅ {success_count}/{quantity} အောင်မြင်ပါသည်!\n👤 Username: <code>{html.escape(str(username))}</code>"
            return False, "❌ Topup မအောင်မြင်ပါ။ Balance သို့မဟုတ် Cookie စစ်ပါ။"
        except Exception as e:
            return False, f"❌ Error: {html.escape(str(e))}"

# Global Smile.one instance
smile = SmileOneBot() if SMILE_AVAILABLE else None


def guess_mlbb_region(zone_id) -> str:
    """Best-effort region label for MLBB zone. Myanmar shops usually serve MM + Global."""
    try:
        z = int(str(zone_id).strip())
    except (TypeError, ValueError):
        return "Myanmar / Global"
    # Common Myanmar / SEA-facing zones vary; keep friendly label for local users.
    # Exact country mapping is not publicly stable, so default to Myanmar-friendly text.
    if z in (9364, 9301, 9302, 9303, 9304, 9401, 9402, 9501):
        return "Myanmar"
    if 9000 <= z <= 9999:
        return "Myanmar / SEA"
    return "Myanmar / Global"


def count_wp_bought_for_game(game_id: str) -> int:
    """How many Weekly Pass units already bought (pending+completed) for this ML account."""
    try:
        with db() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(COALESCE(quantity,1)), 0) AS q
                FROM orders
                WHERE game_id = ?
                  AND category = 'mlbb'
                  AND status IN ('pending', 'completed')
                  AND (
                    LOWER(item_name) LIKE '%weeklypass%'
                    OR LOWER(item_name) LIKE '%weekly pass%'
                    OR LOWER(item_name) LIKE '%passe semanal%'
                    OR LOWER(item_name) LIKE '%weekly diamond%'
                  )
                """,
                (game_id,),
            ).fetchone()
            return int(row["q"] or 0) if row else 0
    except Exception:
        log.exception("count_wp_bought_for_game")
        return 0


def get_2x_diamond_status(game_id: str) -> dict:
    """
    Track first-purchase 2x tiers from our completed Smile/orders for this account.
    Keys: 50, 150, 250, 500  -> True if still eligible (not yet bought), False if used.
    """
    status = {50: True, 150: True, 250: True, 500: True}
    try:
        with db() as conn:
            rows = conn.execute(
                """
                SELECT item_name FROM orders
                WHERE game_id = ?
                  AND category = 'mlbb'
                  AND status = 'completed'
                """,
                (game_id,),
            ).fetchall()
        for r in rows:
            name = (r["item_name"] or "").lower()
            # Match common package name patterns: "Dia 50", "50 x 2", "50+50", etc.
            for tier in (50, 150, 250, 500):
                if (
                    f"dia {tier}" in name
                    or f"{tier} x 2" in name
                    or f"{tier}+{tier}" in name
                    or re.search(rf'\b{tier}\b', name)
                ):
                    # Prefer matching exact small tiers; avoid matching larger packages containing the number
                    if tier == 50 and re.search(r'\b(150|250|500|514|600)\b', name):
                        continue
                    if tier == 150 and re.search(r'\b(250|500|514|600)\b', name):
                        continue
                    if tier == 250 and re.search(r'\b(500|514|600)\b', name):
                        continue
                    status[tier] = False
    except Exception:
        log.exception("get_2x_diamond_status")
    return status


def format_2x_status_line(status: dict) -> str:
    lines = []
    for tier in (50, 150, 250, 500):
        ok = status.get(tier, True)
        icon = "✅ 2ဆ ရနိုင်သေး" if ok else "❌ 2ဆ မရတော့"
        lines.append(f"• {tier}+{tier} : {icon}")
    return "\n".join(lines)

# ---------- PREMIUM CUSTOM EMOJI ID REGISTRY ----------
# User-supplied Premium Emoji IDs.  Keep every supplied ID in one registry so
# the whole bot can reuse them consistently.  Category icons are mapped by
# meaning rather than by the leading Unicode character (important because the
# same Unicode emoji can represent different products).
PREMIUM_EMOJI_IDS = {

    "pin": "6224042021523300107",                 # 📌 pin
    "pin_alt": "6224042021523300107",            # 📌 pin (same supplied icon)
    "weekly_pass": "6222067612172427504",        # 💎 weekly pass
    "diamond": "6221952906480855415",            # 💎 ML Dia
    "pubg_mobile": "6223982583470891633",       # 🏆 PUBG Mobile
    "broadcast": "6183898156208496749",         # 📢 broadcast
    "kpay": "6167781248480584221",              # 🇲🇲 K-Pay
    "wavepay": "6165469048541815178",           # ⭐ Wave Pay
    "myanmar_flag": "6224197718382747321",      # 🇲🇲 Myanmar flat
    "buy_now": "6221954521388556644",           # 💳 ဝယ်ရန်
    "thank_you": "6221807766651019159",         # ❤️ ကျေးဇူးတင်
    "hourglass": "6224324157924975216",         # ⏳ processing/hourglass
    "done": "6087158252703850104",              # ✅ done
    "rocket": "6221964464237846356",            # 🚀 rocket
    "noti_alert": "6086616567133509891",        # 🟡 notification
    "uc": "6086661153189016167",                # 🎮 UC
    "rush": "6174856622985192486",              # 🔜
    "pubg_pack": "6185914385655930182",         # 🛡️ PUBG pack
    "mail": "6102503603916774694",              # ✉️
    "update": "6102446132959387332",            # 🔄 update
    "money": "6102775243418378788",             # 💵
    "bot": "6149867356500795652",               # 🤖 bot
    "profile": "6215083750535994607",           # 👤 profile
    "processing": "6215270603088208727",        # processing
    "recharge_coin": "5373160591609331472",     # 💵 recharge coin
    "done_alt": "6183528943639862338",          # 🤩 done
    "tg_premium_pack": "6053089412470809869",   # 🎁 Telegram Premium pack
    "love_deep_game": "6174806316033252733",    # 💇 Love & Deep game
    "home": "6052869235267355274",                # 🏠 home (original bot icon)
    "waiting": "6052932100703657517",            # 🤩 waiting
    "finding": "6055461930930282795",            # 🔎 finding
    "online": "6055565761764662753",             # 🟢 online
    "active": "6055619581999852646",             # ⚡ active
    "freefire_game": "6131800542210432439",     # 💰 Free Fire game
    # Older IDs retained for compatibility with previous saved configuration.
    "pin_1": "6224042021523300107",
    "pin_2": "6224042021523300107",
    "uc_1": "6086661153189016167",
    "uc_2": "6086661153189016167",
}

# Correct category icons from the user's latest supplied list.
CUSTOM_EMOJI_MAP = {
    "love_deepspace": PREMIUM_EMOJI_IDS["love_deep_game"],
    "mlbb": PREMIUM_EMOJI_IDS["diamond"],
    "mytel": PREMIUM_EMOJI_IDS["buy_now"],
    "magic_chess": PREMIUM_EMOJI_IDS["hourglass"],
    "pubg_uc": PREMIUM_EMOJI_IDS["uc"],
    "pubg_voucher": PREMIUM_EMOJI_IDS["pubg_pack"],
    "telegram_premium": PREMIUM_EMOJI_IDS["tg_premium_pack"],
    "pubg_pack": PREMIUM_EMOJI_IDS["pubg_pack"],
    "mochichat": PREMIUM_EMOJI_IDS["profile"],
    "freefire": PREMIUM_EMOJI_IDS["freefire_game"],
}

# Verified Unicode -> Premium ID mapping supplied for this bot.
# Ambiguous product/category icons are handled by category context.
PREMIUM_TEXT_EMOJI_MAP = {
    "🇲🇲": PREMIUM_EMOJI_IDS["myanmar_flag"],
    "📌": PREMIUM_EMOJI_IDS["pin"],
    "💎": PREMIUM_EMOJI_IDS["diamond"],
    "🏆": PREMIUM_EMOJI_IDS["pubg_mobile"],
    "📢": PREMIUM_EMOJI_IDS["broadcast"],
    "💳": PREMIUM_EMOJI_IDS["buy_now"],
    "❤️": PREMIUM_EMOJI_IDS["thank_you"],
    "⏳": PREMIUM_EMOJI_IDS["hourglass"],
    "⌛": PREMIUM_EMOJI_IDS["hourglass"],
    "✅": PREMIUM_EMOJI_IDS["done"],
    "🚀": PREMIUM_EMOJI_IDS["rocket"],
    "🟡": PREMIUM_EMOJI_IDS["noti_alert"],
    "🎮": PREMIUM_EMOJI_IDS["uc"],
    "🔜": PREMIUM_EMOJI_IDS["rush"],
    "🛡️": PREMIUM_EMOJI_IDS["pubg_pack"],
    "✉️": PREMIUM_EMOJI_IDS["mail"],
    "🔄": PREMIUM_EMOJI_IDS["update"],
    "💵": PREMIUM_EMOJI_IDS["money"],
    "🤖": PREMIUM_EMOJI_IDS["bot"],
    "👤": PREMIUM_EMOJI_IDS["profile"],
    "💰": PREMIUM_EMOJI_IDS["freefire_game"],
    "🪙": PREMIUM_EMOJI_IDS["recharge_coin"],
    "🤩": PREMIUM_EMOJI_IDS["done_alt"],
    "🎁": PREMIUM_EMOJI_IDS["tg_premium_pack"],
    "💇": PREMIUM_EMOJI_IDS["love_deep_game"],
    "🎉": PREMIUM_EMOJI_IDS["done_alt"],
    "🙏": PREMIUM_EMOJI_IDS["thank_you"],
    "🛍️": PREMIUM_EMOJI_IDS["buy_now"],
    "📊": PREMIUM_EMOJI_IDS["profile"],
    "📅": PREMIUM_EMOJI_IDS["update"],
    "🎟️": PREMIUM_EMOJI_IDS["rush"],
    "⭐": PREMIUM_EMOJI_IDS["weekly_pass"],
    "📜": PREMIUM_EMOJI_IDS["mail"],
    "👥": PREMIUM_EMOJI_IDS["profile"],
    "🏅": PREMIUM_EMOJI_IDS["done_alt"],
    "💡": PREMIUM_EMOJI_IDS["bot"],
    "📞": PREMIUM_EMOJI_IDS["broadcast"],
    "💬": PREMIUM_EMOJI_IDS["mail"],
    "🛠️": PREMIUM_EMOJI_IDS["processing"],
    "🚫": PREMIUM_EMOJI_IDS["noti_alert"],
    "⛔": PREMIUM_EMOJI_IDS["noti_alert"],
    "❌": PREMIUM_EMOJI_IDS["noti_alert"],
    "🔴": PREMIUM_EMOJI_IDS["noti_alert"],
    "🟢": PREMIUM_EMOJI_IDS["done"],
    "🔔": PREMIUM_EMOJI_IDS["noti_alert"],
    "🔕": PREMIUM_EMOJI_IDS["noti_alert"],
    "🔥": PREMIUM_EMOJI_IDS["rocket"],
    "✨": PREMIUM_EMOJI_IDS["hourglass"],
    "🌸": PREMIUM_EMOJI_IDS["profile"],
    "🩷": PREMIUM_EMOJI_IDS["love_deep_game"],
    "📱": PREMIUM_EMOJI_IDS["wavepay"],
    "🆔": PREMIUM_EMOJI_IDS["profile"],
    "📦": PREMIUM_EMOJI_IDS["pubg_pack"],
    "🎰": PREMIUM_EMOJI_IDS["processing"],
    "🏆": PREMIUM_EMOJI_IDS["pubg_mobile"],
    "🌙": PREMIUM_EMOJI_IDS["weekly_pass"],
    "📂": PREMIUM_EMOJI_IDS["profile"],
    "📶": PREMIUM_EMOJI_IDS["buy_now"],
    "🔐": PREMIUM_EMOJI_IDS["profile"],
    "➡️": PREMIUM_EMOJI_IDS["rush"],
    "◀️": PREMIUM_EMOJI_IDS["update"],
    "▶️": PREMIUM_EMOJI_IDS["rush"],
    "🔙": PREMIUM_EMOJI_IDS["rush"],
    "📄": PREMIUM_EMOJI_IDS["profile"],
    "🔎": PREMIUM_EMOJI_IDS["finding"],
    "⚡": PREMIUM_EMOJI_IDS["active"],
}

# Custom emoji icons are assigned explicitly per button/category.
BUTTON_CUSTOM_EMOJI_MAP = dict(PREMIUM_TEXT_EMOJI_MAP)


def get_custom_emoji_id(category_key: str) -> Optional[str]:
    return CUSTOM_EMOJI_MAP.get(category_key)


def premium_emoji_html(emoji_id: Optional[str], fallback: str = "✨") -> str:
    """Return a Telegram HTML custom emoji entity with a safe fallback."""
    if emoji_id:
        return f'<tg-emoji emoji-id="{html.escape(str(emoji_id), quote=True)}">{fallback}</tg-emoji>'
    return fallback


def _protect_tg_emoji_tags(text: str):
    protected = []
    pattern = re.compile(r'<tg-emoji\b[^>]*>.*?</tg-emoji>', re.S | re.I)
    def repl(m):
        protected.append(m.group(0))
        return f"\x00TGEMOJI{len(protected)-1}\x00"
    return pattern.sub(repl, text), protected


def premiumize_text(text: str) -> str:
    """Convert supplied Unicode emoji to Premium Emoji entities.

    Known supplied IDs are used first. Unknown emoji are converted to a safe
    supplied Premium bot icon instead of being silently left as a normal emoji.
    """
    if not text or "<tg-emoji" in text:
        protected_text, protected = _protect_tg_emoji_tags(text)
    else:
        protected_text, protected = text, []

    for emoji_char in sorted(PREMIUM_TEXT_EMOJI_MAP, key=len, reverse=True):
        emoji_id = PREMIUM_TEXT_EMOJI_MAP[emoji_char]
        tag = premium_emoji_html(emoji_id, emoji_char)
        protected_text = protected_text.replace(emoji_char, tag)

    # Only replace emoji for which the user supplied a verified Premium Emoji ID.
    # Unknown emoji are left untouched instead of being incorrectly replaced by
    # the generic bot icon. This prevents misleading UI/icon assignments.

    for i, tag in enumerate(protected):
        protected_text = protected_text.replace(f"\x00TGEMOJI{i}\x00", tag)
    return protected_text


def _button_style(text: str, callback_data: Optional[str]) -> Optional[str]:
    value = f"{text} {callback_data or ''}".lower()
    if any(x in value for x in ("approve", "success", "confirm", "daily", "claim", "spin_do")):
        return "success"
    if any(x in value for x in ("reject", "delete", "remove", "logout", "danger")):
        return "danger"
    if any(x in value for x in ("home", "back", "recharge", "pay|", "shop", "dashboard", "history", "referral", "contact")):
        return "primary"
    return None


def _leading_custom_emoji_id(text: str) -> Optional[str]:
    for emoji_char, emoji_id in sorted(BUTTON_CUSTOM_EMOJI_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if text.startswith(emoji_char):
            return emoji_id
    if text:
        cp = ord(text[0])
        if (0x1F000 <= cp <= 0x1FAFF) or (0x2700 <= cp <= 0x27BF):
            return PREMIUM_EMOJI_IDS["bot"]
    return None


def _make_button(*args, **kwargs):
    text = kwargs.get("text")
    if text is None and args:
        text = args[0]
    text = str(text or "")
    callback_data = kwargs.get("callback_data")
    if callback_data is None and len(args) >= 3:
        callback_data = args[2]

    kwargs.setdefault("style", _button_style(text, callback_data))
    if not kwargs.get("icon_custom_emoji_id"):
        custom_id = _leading_custom_emoji_id(text)
        if custom_id:
            kwargs["icon_custom_emoji_id"] = custom_id

    try:
        return _TelegramInlineKeyboardButton(*args, **kwargs)
    except TypeError:
        kwargs.pop("style", None)
        kwargs.pop("icon_custom_emoji_id", None)
        return _TelegramInlineKeyboardButton(*args, **kwargs)

InlineKeyboardButton = _make_button


def create_button_with_custom_emoji(text: str, emoji_char: str, emoji_id: str, callback_data: str) -> InlineKeyboardButton:
    return _make_button(
        text=text,
        callback_data=callback_data,
        icon_custom_emoji_id=str(emoji_id),
    )

PRICES = {
    'mlbb': {
        'default_emoji': '💎',
        'name': 'MLBB Diamond ',
        'id_label': '🩷 Player ID & Server',
        'items': {
            'Weeklypass ⭐': 1.44,
            'Twilight Pass ⭐': 7.5,
            'Limited-Time Value Pack ⭐': 0.29,
            'Weekly Elite Bundle ⭐': 0.8,
            'Monthly Epic Bundle ⭐': 3.88,
            'Dia 50 x 2 ⭐': 0.8,
            'Dia 150 x 2 ⭐': 2.46,
            'Dia 250 x 2 ⭐': 3.9,
            'Dia 500 x 2 ⭐': 7.58,
            'Dia 11 ⭐': 0.23,
            'Dia 22 ⭐': 0.44,
            'Dia 33 ⭐': 0.63,
            'Dia 44 ⭐': 0.82,
            'Dia 56 ⭐': 1.0,
            'Dia 112 ⭐': 1.66,
            'Dia 86 ⭐': 1.27,
            'Dia 172 ⭐': 2.55,
            'Dia 257': 3.77,
            'Dia 343': 4.92,
            'Dia 429': 6.23,
            'Dia 514': 7.15,
            'Dia 600': 8.45,
            'Dia 706': 9.87,
            'Dia 878': 11.76,
            'Dia 963': 13.31,
            'Dia 1049': 14.28,
            'Dia 1135': 16.01,
            'Dia 1412': 18.77,
            'Dia 2195': 29.78,
            'Dia 3688': 50.82,
            'Dia 5532': 76.47,
            'Dia 9288': 117.0
        }
    }
}

# ---------------- HELPERS ----------------
def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))

def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def db():
    conn = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def price_to_coins(raw_price) -> int:
    try:
        if isinstance(raw_price, (int, float)) and raw_price < 100:
            return int(round(float(raw_price) * USD_RATE))
        return int(round(float(raw_price)))
    except (TypeError, ValueError):
        return 0

def price_display(raw_price) -> str:
    coins = price_to_coins(raw_price)
    if isinstance(raw_price, (int, float)) and raw_price < 100:
        return f"{raw_price:g}$ = {coins:,} MMK"
    return f"{coins:,} MMK"

def status_icon(status: str) -> str:
    return {"pending": "⏳", "completed": "✅", "rejected": "❌"}.get(status, "ℹ️")

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def maintenance_mode() -> bool:
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='maintenance'"
            ).fetchone()
            return bool(row and row["value"] == "1")
    except Exception:
        log.exception("maintenance_mode")
        return False

def set_setting(key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

def load_settings():
    global USD_RATE
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='usd_rate'"
            ).fetchone()
            if row:
                USD_RATE = int(row["value"])
    except Exception:
        log.exception("load_settings")

# ---------- Custom Emoji Helpers ----------
def extract_custom_emoji_id(text: str) -> Optional[int]:
    m = re.search(r"<tg-emoji\s+emoji-id=['\"](\d+)['\"]", text)
    return int(m.group(1)) if m else None

def get_cat_emoji_info(key: str) -> Tuple[str, Optional[int]]:
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT emoji, emoji_id FROM category_emojis WHERE category_key=?",
                (key,)
            ).fetchone()
            if row:
                return row["emoji"], row["emoji_id"]
    except:
        pass
    default = PRICES.get(key, {}).get("default_emoji", "✨")
    return default, None

def set_cat_emoji(key: str, emoji: str, emoji_id: Optional[int] = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO category_emojis(category_key, emoji, emoji_id) VALUES(?,?,?) "
            "ON CONFLICT(category_key) DO UPDATE SET emoji=excluded.emoji, emoji_id=excluded.emoji_id",
            (key, emoji, emoji_id),
        )

def build_entities_for_emojis(text: str, emoji_map: Dict[str, Optional[int]]) -> List[Dict]:
    entities = []
    offset = 0
    for emoji_char, emoji_id in emoji_map.items():
        if not emoji_id:
            continue
        idx = text.find(emoji_char, offset)
        while idx != -1:
            entities.append({
                "type": "custom_emoji",
                "offset": idx,
                "length": len(emoji_char),
                "custom_emoji_id": str(emoji_id)
            })
            offset = idx + len(emoji_char)
            idx = text.find(emoji_char, offset)
    return entities

# ---------- TESSERACT OCR + SLIP PARSING ----------
def ocr_image(image_bytes: bytes) -> Optional[str]:
    if not TESSERACT_AVAILABLE:
        return None
    try:
        image = Image.open(io.BytesIO(image_bytes))
        gray = image.convert('L')
        try:
            text = pytesseract.image_to_string(gray, lang='mya+eng')
        except:
            text = pytesseract.image_to_string(gray, lang='eng')
        return text.strip()
    except Exception as e:
        log.error("Tesseract OCR failed: %s", e)
        return None

def parse_slip_text(text: str) -> Dict[str, str]:
    result = {
        "method": None,
        "name": None,
        "transaction_id": None,
        "date": None,
        "time": None,
        "last5": None
    }
    if not text:
        return result

    full_text = " ".join([line.strip() for line in text.splitlines() if line.strip()])

    if re.search(r'K[- ]?Pay|KBZ|Kpay', full_text, re.I):
        result["method"] = "K-Pay"
    elif re.search(r'Wave[- ]?Pay|Wave Money|WavePay', full_text, re.I):
        result["method"] = "Wave Pay"

    name_patterns = [
        r'(?:Name|အမည်)\s*[:;]?\s*([^\d\n]+)',
        r'(?:မည်|အမည်)\s+([^\d\n]+)',
        r'([A-Za-z][\w\s\.]+)(?=\s*09\d{9,})',
    ]
    for pattern in name_patterns:
        m = re.search(pattern, full_text)
        if m:
            name = m.group(1).strip()
            if len(name) > 2 and len(name) < 40:
                result["name"] = name
                break

    txn_patterns = [
        r'(?:Ref|Txn|Trx|Transaction|ID|ကိုးကား)\s*[:;]?\s*([A-Za-z0-9]{6,20})',
        r'(?:နံပါတ်|ကိုးကားနံပါတ်)\s*[:;]?\s*([A-Za-z0-9]{6,20})',
        r'([A-Za-z0-9]{8,20})(?=\s+Date|အချိန်|Time|ငွေပမာဏ)',
    ]
    for pattern in txn_patterns:
        m = re.search(pattern, full_text)
        if m:
            result["transaction_id"] = m.group(1).strip()
            break

    date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', full_text)
    if date_match:
        result["date"] = date_match.group(1)
    time_match = re.search(r'(\d{1,2}[:.]\d{2}(?:\s*(?:AM|PM))?)', full_text, re.I)
    if time_match:
        result["time"] = time_match.group(1)

    if result["transaction_id"]:
        txn = result["transaction_id"]
        if len(txn) >= 5:
            result["last5"] = txn[-5:]
    if not result["last5"]:
        digits = re.findall(r'\d{5,}', full_text)
        if digits:
            for d in digits:
                if len(d) >= 5:
                    result["last5"] = d[-5:]
                    break

    return result

# ---------- DATABASE ----------
def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            coin_balance INTEGER NOT NULL DEFAULT 0,
            referral_count INTEGER NOT NULL DEFAULT 0,
            referred_by INTEGER DEFAULT 0,
            last_checkin TEXT,
            streak_count INTEGER DEFAULT 0,
            last_checkin_date TEXT,
            is_banned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS referrals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            referrer_reward INTEGER NOT NULL,
            referred_reward INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            item_name TEXT NOT NULL,
            amount INTEGER NOT NULL,
            payment_method TEXT NOT NULL,
            game_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            admin_note TEXT DEFAULT '',
            transaction_last5 TEXT DEFAULT '',
            proof_file_id TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS recharges(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            payment_method TEXT NOT NULL,
            last_5_digits TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            admin_note TEXT DEFAULT '',
            proof_file_id TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS category_emojis(
            category_key TEXT PRIMARY KEY,
            emoji TEXT NOT NULL,
            emoji_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS promo_codes(
            code TEXT PRIMARY KEY,
            reward INTEGER NOT NULL,
            max_uses INTEGER NOT NULL DEFAULT 0,
            used_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS used_promos(
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            used_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, code)
        );

        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_favorites(
            user_id INTEGER NOT NULL,
            category_key TEXT NOT NULL,
            item_name TEXT NOT NULL,
            PRIMARY KEY(user_id, category_key, item_name)
        );

        CREATE TABLE IF NOT EXISTS monthly_rewards(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month_year TEXT NOT NULL UNIQUE,
            distributed_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS voucher_stock(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_key TEXT NOT NULL,
            item_name TEXT NOT NULL,
            code TEXT NOT NULL,
            is_used INTEGER DEFAULT 0,
            used_by INTEGER DEFAULT NULL,
            used_at TEXT DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_follows(
            user_id INTEGER NOT NULL,
            category_key TEXT NOT NULL,
            item_name TEXT NOT NULL,
            last_notified_price REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, category_key, item_name)
        );

        CREATE TABLE IF NOT EXISTS daily_missions(
            user_id INTEGER NOT NULL,
            mission_date TEXT NOT NULL,
            mission_type TEXT NOT NULL,
            progress INTEGER DEFAULT 0,
            target INTEGER DEFAULT 5,
            claimed INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, mission_date, mission_type)
        );

        CREATE TABLE IF NOT EXISTS spin_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            prize_name TEXT NOT NULL,
            prize_value TEXT NOT NULL,
            cost INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS admins(
            user_id INTEGER PRIMARY KEY
        );

        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_recharges_user ON recharges(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_recharges_status ON recharges(status);
        CREATE INDEX IF NOT EXISTS idx_referrals_created ON referrals(created_at);
        CREATE INDEX IF NOT EXISTS idx_voucher_stock ON voucher_stock(category_key, item_name, is_used);
        CREATE INDEX IF NOT EXISTS idx_spin_history_user ON spin_history(user_id, created_at DESC);
        """)

        for table, columns in {
            "users": {
                "last_checkin": "TEXT",
                "streak_count": "INTEGER DEFAULT 0",
                "last_checkin_date": "TEXT",
                "referral_count": "INTEGER NOT NULL DEFAULT 0",
                "referred_by": "INTEGER DEFAULT 0",
                "is_banned": "INTEGER NOT NULL DEFAULT 0",
                "web_pin_hash": "TEXT DEFAULT ''",
            },
            "referrals": {
                "referrer_reward": "INTEGER NOT NULL DEFAULT 0",
                "referred_reward": "INTEGER NOT NULL DEFAULT 0",
                "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
            },
            "recharges": {
                "admin_message_id": "INTEGER",
                "admin_chat_id": "INTEGER",
            },
        }.items():
            existing_cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for col, definition in columns.items():
                if col not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
                    except sqlite3.OperationalError:
                        log.exception("migration failed: %s.%s", table, col)

        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_referrals_referred ON referrals(referred_id)")
        except sqlite3.IntegrityError:
            log.warning("Existing duplicate referral rows detected; unique index not created")

        existing = {
            row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()
        }
        for name, definition in {
            "admin_note": "TEXT DEFAULT ''",
            "transaction_last5": "TEXT DEFAULT ''",
            "proof_file_id": "TEXT DEFAULT ''",
            "completed_at": "TEXT",
            "quantity": "INTEGER NOT NULL DEFAULT 1",
        }.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {definition}")

        existing = {
            row["name"] for row in conn.execute("PRAGMA table_info(recharges)").fetchall()
        }
        for name, definition in {
            "admin_note": "TEXT DEFAULT ''",
            "proof_file_id": "TEXT DEFAULT ''",
            "completed_at": "TEXT",
        }.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE recharges ADD COLUMN {name} {definition}")

        existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(category_emojis)").fetchall()}
        if "emoji_id" not in existing_cols:
            conn.execute("ALTER TABLE category_emojis ADD COLUMN emoji_id INTEGER")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_referrals_created ON referrals(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_voucher_stock ON voucher_stock(category_key, item_name, is_used)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_spin_history_user ON spin_history(user_id, created_at DESC)")

        global ADMIN_IDS
        db_admins = conn.execute("SELECT user_id FROM admins").fetchall()
        for row in db_admins:
            ADMIN_IDS.add(row["user_id"])
        ADMIN_IDS.add(OWNER_ID)

        for key, data in PRICES.items():
            forced_id = CUSTOM_EMOJI_MAP.get(key)
            row = conn.execute(
                "SELECT category_key FROM category_emojis WHERE category_key=?",
                (key,)
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO category_emojis(category_key, emoji, emoji_id) VALUES(?,?,?)",
                    (key, data["default_emoji"], forced_id)
                )
            elif forced_id:
                # Keep the user's latest supplied Premium ID as the canonical
                # category icon, even if an older DB stored a wrong/null ID.
                conn.execute(
                    "UPDATE category_emojis SET emoji_id=? WHERE category_key=?",
                    (forced_id, key),
                )

        default_tiers = json.dumps({"10000": 2.0, "50000": 2.5})
        conn.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES('recharge_tiers', ?)",
            (default_tiers,)
        )

    load_settings()

def ensure_user(tg_user) -> bool:
    try:
        with db() as conn:
            conn.execute("""
                INSERT INTO users(user_id,username,first_name,last_name)
                VALUES(?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name
            """, (
                tg_user.id, tg_user.username or "", tg_user.first_name or "",
                tg_user.last_name or "",
            ))
        return True
    except Exception:
        log.exception("ensure_user")
        return False

def get_user(user_id):
    try:
        with db() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
    except Exception:
        log.exception("get_user")
        return None

def is_banned(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["is_banned"])

def balance(user_id: int) -> int:
    row = get_user(user_id)
    return int(row["coin_balance"]) if row else 0

def change_balance(user_id: int, amount: int, conn=None) -> bool:
    own = conn is None
    conn = conn or db()
    try:
        cur = conn.execute(
            "UPDATE users SET coin_balance=coin_balance+? WHERE user_id=?",
            (int(amount), user_id),
        )
        if cur.rowcount != 1:
            raise ValueError("user does not exist")
        return True
    except Exception as e:
        log.error("change_balance failed: %s", e)
        return False
    finally:
        if own:
            conn.close()

# ---------- RECHARGE BONUS / TIERS ----------
def get_recharge_tiers():
    try:
        with db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='recharge_tiers'").fetchone()
            if row:
                return json.loads(row["value"])
            return {"10000": 2.0, "50000": 2.5}
    except:
        return {"10000": 2.0, "50000": 2.5}

def calculate_recharge_bonus(amount: int) -> int:
    tiers = get_recharge_tiers()
    bonus_percent = 0
    for threshold, percent in sorted(tiers.items(), key=lambda x: int(x[0])):
        if amount >= int(threshold):
            bonus_percent = percent
    return int(amount * bonus_percent / 100)

# ---------- CHECK-IN STREAK ----------
def process_checkin(user_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    with db() as conn:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT last_checkin, streak_count, last_checkin_date FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
        if not row:
            conn.rollback()
            raise ValueError("user not found")
        if row["last_checkin"] == today:
            conn.rollback()
            return False, 0, 0, balance(user_id)

        streak = row["streak_count"] or 0
        last_date = row["last_checkin_date"]
        if last_date == yesterday:
            streak += 1
        else:
            streak = 1

        reward = 100 if random.random() < 0.01 else random.randint(10, 99)
        extra = 0
        if streak % 7 == 0:
            extra = 500
            reward += extra

        conn.execute(
            "UPDATE users SET last_checkin=?, streak_count=?, last_checkin_date=?, coin_balance=coin_balance+? WHERE user_id=?",
            (today, streak, today, reward, user_id)
        )
        conn.commit()
        return True, reward, extra, balance(user_id)

# ---------- VOUCHER AUTO-DELIVERY ----------
def add_voucher_stock(category_key, item_name, code):
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO voucher_stock(category_key, item_name, code) VALUES(?,?,?)",
                (category_key, item_name, code)
            )
        return True
    except:
        return False

def get_unused_voucher(category_key, item_name):
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT id, code FROM voucher_stock WHERE category_key=? AND item_name=? AND is_used=0 LIMIT 1",
                (category_key, item_name)
            ).fetchone()
            return row
    except:
        return None

def mark_voucher_used(voucher_id, user_id):
    try:
        with db() as conn:
            conn.execute(
                "UPDATE voucher_stock SET is_used=1, used_by=?, used_at=? WHERE id=?",
                (user_id, now_text(), voucher_id)
            )
        return True
    except:
        return False

# ---------- PRICE ALERTS / FOLLOWS ----------
def follow_item(user_id, category_key, item_name):
    try:
        with db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO user_follows(user_id, category_key, item_name) VALUES(?,?,?)",
                (user_id, category_key, item_name)
            )
        return True
    except:
        return False

def unfollow_item(user_id, category_key, item_name):
    try:
        with db() as conn:
            conn.execute(
                "DELETE FROM user_follows WHERE user_id=? AND category_key=? AND item_name=?",
                (user_id, category_key, item_name)
            )
        return True
    except:
        return False

def get_followers(category_key, item_name):
    try:
        with db() as conn:
            return conn.execute(
                "SELECT user_id FROM user_follows WHERE category_key=? AND item_name=?",
                (category_key, item_name)
            ).fetchall()
    except:
        return []

# ---------- DAILY INVITE MISSION ----------
def check_daily_mission(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT progress, target, claimed FROM daily_missions WHERE user_id=? AND mission_date=? AND mission_type='invite'",
                (user_id, today)
            ).fetchone()
            if row:
                return row["progress"], row["target"], row["claimed"]
            conn.execute(
                "INSERT INTO daily_missions(user_id, mission_date, mission_type, progress, target) VALUES(?,?,'invite',0,5)",
                (user_id, today)
            )
            return 0, 5, 0
    except:
        return 0, 5, 0

def update_mission_progress(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as c FROM referrals WHERE referrer_id=? AND DATE(created_at)=?",
                (user_id, today)
            ).fetchone()["c"]
            conn.execute(
                "UPDATE daily_missions SET progress=? WHERE user_id=? AND mission_date=? AND mission_type='invite'",
                (count, user_id, today)
            )
    except:
        pass

def claim_mission(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with db() as conn:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT progress, target, claimed FROM daily_missions WHERE user_id=? AND mission_date=? AND mission_type='invite'",
                (user_id, today)
            ).fetchone()
            if not row or row["claimed"] == 1:
                conn.rollback()
                return False, "Mission not found or already claimed"
            if row["progress"] < row["target"]:
                conn.rollback()
                return False, f"Need {row['target']} invites, you have {row['progress']}"
            conn.execute(
                "UPDATE daily_missions SET claimed=1 WHERE user_id=? AND mission_date=? AND mission_type='invite'",
                (user_id, today)
            )
            conn.execute(
                "UPDATE users SET coin_balance=coin_balance+500 WHERE user_id=?",
                (user_id,)
            )
            conn.commit()
            return True, 500
    except Exception as e:
        log.exception("claim_mission")
        return False, str(e)

# ---------- GENERATORS ----------
def generate_checkin_reward() -> int:
    return 100 if random.random() < 0.01 else random.randint(10, 99)

def generate_referral_reward() -> int:
    # 0.1% jackpot, 1% rare reward, otherwise 25–100 Coins.
    roll = random.random()
    if roll < 0.001:
        return 5000
    if roll < 0.011:
        return 999
    return random.randint(25, 100)

def process_referral(referrer_id: int, referred_id: int):
    if referrer_id == referred_id:
        return False, 0, 0
    with db() as conn:
        conn.execute("BEGIN")
        ref = conn.execute(
            "SELECT user_id FROM users WHERE user_id=?", (referrer_id,)
        ).fetchone()
        user = conn.execute(
            "SELECT referred_by FROM users WHERE user_id=?", (referred_id,)
        ).fetchone()
        if not ref or not user or user["referred_by"]:
            conn.rollback()
            return False, 0, 0
        rr = generate_referral_reward()
        ur = generate_referral_reward()
        try:
            conn.execute(
                "INSERT INTO referrals(referrer_id,referred_id,referrer_reward,referred_reward)"
                " VALUES(?,?,?,?)",
                (referrer_id, referred_id, rr, ur),
            )
        except sqlite3.IntegrityError:
            conn.rollback()
            return False, 0, 0
        conn.execute(
            "UPDATE users SET referral_count=referral_count+1, coin_balance=coin_balance+? "
            "WHERE user_id=?", (rr, referrer_id)
        )
        conn.execute(
            "UPDATE users SET referred_by=?, coin_balance=coin_balance+? "
            "WHERE user_id=?",
            (referrer_id, ur, referred_id),
        )
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute(
            "INSERT OR IGNORE INTO daily_missions(user_id, mission_date, mission_type, progress, target) "
            "VALUES(?,?, 'invite', 0, 5)",
            (referrer_id, today),
        )
        conn.execute(
            "UPDATE daily_missions SET progress = progress + 1 "
            "WHERE user_id=? AND mission_date=? AND mission_type='invite'",
            (referrer_id, today),
        )
        conn.commit()
        return True, rr, ur

# ---------- SPENDING LOCK ----------
def count_active_referrals(user_id: int) -> int:
    try:
        with db() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS active
                FROM referrals r
                WHERE r.referrer_id = ?
                  AND EXISTS (
                      SELECT 1 FROM orders o
                      WHERE o.user_id = r.referred_id AND o.status = 'completed'
                      UNION
                      SELECT 1 FROM recharges rc
                      WHERE rc.user_id = r.referred_id AND rc.status = 'completed'
                  )
            """, (user_id,)).fetchone()
            return row["active"] if row else 0
    except Exception:
        log.exception("count_active_referrals")
        return 0

def can_spend_coins(user_id: int) -> bool:
    try:
        user = get_user(user_id)
        if not user:
            return False
        if user["referral_count"] < 5:
            return False
        return count_active_referrals(user_id) >= 5
    except Exception:
        log.exception("can_spend_coins")
        return False

# ---------- LEADERBOARD ----------
def get_top_inviters(limit=3, days=30):
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with db() as conn:
            rows = conn.execute("""
                SELECT
                    u.user_id,
                    u.username,
                    u.first_name,
                    COUNT(r.id) AS referral_count
                FROM referrals r
                JOIN users u ON u.user_id = r.referrer_id
                WHERE r.created_at >= ?
                  AND EXISTS (
                      SELECT 1 FROM orders o
                      WHERE o.user_id = r.referred_id AND o.status = 'completed'
                      UNION
                      SELECT 1 FROM recharges rc
                      WHERE rc.user_id = r.referred_id AND rc.status = 'completed'
                  )
                GROUP BY u.user_id
                ORDER BY referral_count DESC
                LIMIT ?
            """, (cutoff, limit)).fetchall()
            return rows
    except Exception:
        log.exception("get_top_inviters")
        return []

def get_user_inviter_dashboard(user_id: int):
    try:
        with db() as conn:
            rows = conn.execute("""
                SELECT
                    u.user_id,
                    u.username,
                    u.first_name,
                    u.coin_balance,
                    (SELECT COUNT(*) FROM orders o WHERE o.user_id = u.user_id AND o.status = 'completed') AS completed_orders,
                    (SELECT COUNT(*) FROM recharges rc WHERE rc.user_id = u.user_id AND rc.status = 'completed') AS completed_recharges
                FROM referrals r
                JOIN users u ON u.user_id = r.referred_id
                WHERE r.referrer_id = ?
                ORDER BY r.created_at DESC
            """, (user_id,)).fetchall()
            return rows
    except Exception:
        log.exception("get_user_inviter_dashboard")
        return []

# ---------- MONTHLY REWARDS ----------
def has_monthly_rewards_been_distributed(month_year: str) -> bool:
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT 1 FROM monthly_rewards WHERE month_year = ?",
                (month_year,)
            ).fetchone()
            return row is not None
    except Exception:
        return False

def mark_monthly_rewards_distributed(month_year: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO monthly_rewards(month_year) VALUES(?)",
            (month_year,)
        )

def distribute_monthly_rewards():
    now = datetime.now()
    month_year = now.strftime("%Y-%m")

    # Claim the month atomically. If another admin process already claimed it,
    # do not distribute twice.
    try:
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "INSERT OR IGNORE INTO monthly_rewards(month_year) VALUES(?)",
                (month_year,),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return None

            cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            top = conn.execute("""
                SELECT
                    u.user_id,
                    u.username,
                    u.first_name,
                    COUNT(r.id) AS referral_count
                FROM referrals r
                JOIN users u ON u.user_id = r.referrer_id
                WHERE r.created_at >= ?
                  AND EXISTS (
                      SELECT 1 FROM orders o
                      WHERE o.user_id = r.referred_id AND o.status = 'completed'
                      UNION
                      SELECT 1 FROM recharges rc
                      WHERE rc.user_id = r.referred_id AND rc.status = 'completed'
                  )
                GROUP BY u.user_id
                ORDER BY referral_count DESC, u.user_id ASC
                LIMIT 3
            """, (cutoff,)).fetchall()

            if not top:
                conn.execute("DELETE FROM monthly_rewards WHERE month_year=?", (month_year,))
                conn.commit()
                return []

            rewards = [5999, 3999, 1599]
            winners = []
            for idx, row in enumerate(top):
                reward = rewards[idx]
                cur = conn.execute(
                    "UPDATE users SET coin_balance = coin_balance + ? WHERE user_id = ?",
                    (reward, row["user_id"]),
                )
                if cur.rowcount == 1:
                    winners.append({
                        "user_id": row["user_id"],
                        "username": row["username"],
                        "first_name": row["first_name"],
                        "referral_count": row["referral_count"],
                        "reward": reward,
                        "rank": idx + 1,
                    })

            conn.commit()
            return winners
    except Exception:
        log.exception("distribute_monthly_rewards")
        return None

# ---------- SPIN HISTORY ----------
def log_spin(user_id: int, prize_name: str, prize_value, cost: int):
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO spin_history(user_id, prize_name, prize_value, cost) VALUES(?,?,?,?)",
                (user_id, prize_name, str(prize_value), cost)
            )
    except Exception:
        log.exception("log_spin")

def get_spin_history(user_id: int, limit=20):
    try:
        with db() as conn:
            return conn.execute(
                "SELECT prize_name, prize_value, cost, created_at FROM spin_history WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
    except Exception:
        return []

# ---------- ORDER / RECHARGE FUNCTIONS ----------
def create_order(user_id, category, item_name, amount, payment_method, game_id, quantity=1):
    quantity = max(1, int(quantity or 1))
    with db() as conn:
        cur = conn.execute("""
            INSERT INTO orders(user_id,category,item_name,amount,payment_method,game_id,quantity)
            VALUES(?,?,?,?,?,?,?)
        """, (user_id, category, item_name, int(amount), payment_method, game_id, quantity))
        return cur.lastrowid

def get_order(order_id):
    try:
        with db() as conn:
            return conn.execute(
                "SELECT * FROM orders WHERE id=?", (order_id,)
            ).fetchone()
    except Exception:
        log.exception("get_order")
        return None

def create_recharge(user_id, amount, method, last5, proof_file_id):
    with db() as conn:
        cur = conn.execute("""
            INSERT INTO recharges(user_id,amount,payment_method,last_5_digits,proof_file_id)
            VALUES(?,?,?,?,?)
        """, (user_id, int(amount), method, last5, proof_file_id))
        return cur.lastrowid

def get_recharge(recharge_id):
    try:
        with db() as conn:
            return conn.execute(
                "SELECT * FROM recharges WHERE id=?", (recharge_id,)
            ).fetchone()
    except Exception:
        log.exception("get_recharge")
        return None

def complete_order_once(order_id: int):
    with db() as conn:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT * FROM orders WHERE id=?", (order_id,)
        ).fetchone()
        if not row:
            conn.rollback()
            return None, "not_found"
        if row["status"] != "pending":
            conn.rollback()
            return row, "already_processed"
        conn.execute(
            "UPDATE orders SET status='completed',completed_at=? WHERE id=? AND status='pending'",
            (now_text(), order_id),
        )
        conn.commit()
        return get_order(order_id), "completed"

def reject_order_once(order_id: int):
    with db() as conn:
        conn.execute("BEGIN")
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not row:
            conn.rollback()
            return None, "not_found"
        if row["status"] != "pending":
            conn.rollback()
            return row, "already_processed"
        conn.execute(
            "UPDATE orders SET status='rejected',completed_at=? WHERE id=? AND status='pending'",
            (now_text(), order_id),
        )
        if row["payment_method"] == "wallet":
            conn.execute(
                "UPDATE users SET coin_balance=coin_balance+? WHERE user_id=?",
                (row["amount"], row["user_id"]),
            )
        conn.commit()
        return get_order(order_id), "rejected"

def complete_recharge_once(recharge_id: int):
    with db() as conn:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT * FROM recharges WHERE id=?", (recharge_id,)
        ).fetchone()
        if not row:
            conn.rollback()
            return None, "not_found"
        if row["status"] != "pending":
            conn.rollback()
            return row, "already_processed"
        conn.execute(
            "UPDATE recharges SET status='completed',completed_at=? "
            "WHERE id=? AND status='pending'",
            (now_text(), recharge_id),
        )
        conn.execute(
            "UPDATE users SET coin_balance=coin_balance+? WHERE user_id=?",
            (row["amount"], row["user_id"]),
        )
        bonus = calculate_recharge_bonus(row["amount"])
        if bonus > 0:
            conn.execute(
                "UPDATE users SET coin_balance=coin_balance+? WHERE user_id=?",
                (bonus, row["user_id"]),
            )
        conn.commit()
        return get_recharge(recharge_id), "completed", bonus

def reject_recharge_once(recharge_id: int):
    with db() as conn:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT * FROM recharges WHERE id=?", (recharge_id,)
        ).fetchone()
        if not row:
            conn.rollback()
            return None, "not_found"
        if row["status"] != "pending":
            conn.rollback()
            return row, "already_processed"
        conn.execute(
            "UPDATE recharges SET status='rejected',completed_at=? WHERE id=? AND status='pending'",
            (now_text(), recharge_id),
        )
        conn.commit()
        return get_recharge(recharge_id), "rejected", 0

def user_orders(user_id, limit=10):
    try:
        with db() as conn:
            return conn.execute(
                "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
    except Exception:
        log.exception("user_orders")
        return []

def user_recharges(user_id, limit=10):
    try:
        with db() as conn:
            return conn.execute(
                "SELECT * FROM recharges WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
    except Exception:
        log.exception("user_recharges")
        return []

def use_promo(user_id: int, code: str):
    code = code.strip().upper()
    with db() as conn:
        conn.execute("BEGIN")
        promo = conn.execute(
            "SELECT * FROM promo_codes WHERE code=?", (code,)
        ).fetchone()
        if not promo:
            conn.rollback()
            return False, "Promo Code မတွေ့ပါ။"
        if promo["max_uses"] > 0 and promo["used_count"] >= promo["max_uses"]:
            conn.rollback()
            return False, "Promo Code အသုံးပြုခွင့် ပြည့်သွားပါပြီ။"
        if conn.execute(
            "SELECT 1 FROM used_promos WHERE user_id=? AND code=?",
            (user_id, code),
        ).fetchone():
            conn.rollback()
            return False, "ဤ Promo Code ကို အသုံးပြုပြီးသားပါ။"
        conn.execute(
            "INSERT INTO used_promos(user_id,code) VALUES(?,?)", (user_id, code)
        )
        conn.execute(
            "UPDATE promo_codes SET used_count=used_count+1 WHERE code=?",
            (code,),
        )
        conn.execute(
            "UPDATE users SET coin_balance=coin_balance+? WHERE user_id=?",
            (promo["reward"], user_id),
        )
        conn.commit()
        return True, int(promo["reward"])

# ---------------- GEMINI ----------------
gemini_model = None
if genai and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel(GEMINI_CHAT_MODEL)
        log.info("Gemini initialized with model: %s", GEMINI_CHAT_MODEL)
    except Exception:
        log.exception("Gemini client initialization failed")

async def gemini_text(prompt: str) -> Optional[str]:
    if not gemini_model:
        return None
    async def call(model_name):
        model = genai.GenerativeModel(model_name)
        response = await asyncio.to_thread(model.generate_content, prompt)
        return response.text.strip() if response and response.text else ""
    for model_name in (GEMINI_CHAT_MODEL, GEMINI_FALLBACK_MODEL):
        try:
            reply = await call(model_name)
            if reply:
                return reply
        except Exception as exc:
            log.warning("Gemini text model %s failed: %s", model_name, exc)
    return None

async def gemini_extract_last5(image_bytes: bytes, mime_type: str, caption: str) -> Optional[str]:
    if not gemini_model:
        return None
    prompt = """
You are a payment-slip OCR assistant.
Inspect the attached payment screenshot.
Task: find a transaction/reference number and return ONLY its final 5 digits.
Rules:
- Return exactly 5 ASCII digits when the slip clearly contains a transaction/reference number.
- Do not invent digits.
- If no reliable 5-digit suffix is visible, return NO_MATCH.
- Ignore phone numbers, account numbers, amounts, dates, OTPs and unrelated 5-digit strings.
User caption (may contain a hint, but do not blindly trust it):
""" + (caption or "(none)")
    try:
        def call():
            model = genai.GenerativeModel(GEMINI_CHAT_MODEL)
            response = model.generate_content(
                [
                    {"mime_type": mime_type or "image/jpeg", "data": image_bytes},
                    prompt
                ]
            )
            return response.text.strip() if response and response.text else ""
        out = await asyncio.to_thread(call)
        match = re.search(r"(?<!\d)(\d{5})(?!\d)", out)
        return match.group(1) if match else None
    except Exception as exc:
        log.warning("Gemini vision failed: %s", exc)
        return None

# ---------- PREMIUM MESSAGE HELPERS ----------
# Helpers are defined above so they are also available to global message wrappers.

# ---------- KEYBOARDS (WITH CUSTOM EMOJI IN BUTTONS) ----------
def main_menu(user_id):
    bal = balance(user_id)
    rows = [
        [InlineKeyboardButton("🛍️ MLBB Dia ဝယ်မယ်", callback_data="shop", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["buy_now"], style="success")],
        [
            InlineKeyboardButton(f"💎 Wallet: {bal:,}", callback_data="balance", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["diamond"], style="primary"),
            InlineKeyboardButton("💳 ငွေဖြည့်မည်", callback_data="recharge", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["buy_now"], style="primary"),
        ],
        [InlineKeyboardButton("📊 Account Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("📅 Daily Check-in", callback_data="daily_checkin")],
        [
            InlineKeyboardButton("⭐ Favorites", callback_data="favorites"),
        ],
        [
            InlineKeyboardButton("📜 Order History", callback_data="history"),
            InlineKeyboardButton("👥 Referral", callback_data="referral"),
        ],
        [
            InlineKeyboardButton("🏆 Rewards", callback_data="lucky_draw")
        ],
        [
            InlineKeyboardButton("💡 Feedback", callback_data="send_feedback"),
            InlineKeyboardButton("🏅 Top Inviters", callback_data="inviter_dashboard"),
        ],
        [
            InlineKeyboardButton("📞 Admin Contact", callback_data="contact"),
            InlineKeyboardButton("📌 Daily Mission", callback_data="daily_mission"),
        ],
        [InlineKeyboardButton("💬 Chat", url="https://t.me/kiki20251")],
    ]
    # Admin-only shortcut (visible only to OWNER / promoted admins)
    if is_admin(user_id):
        rows.insert(0, [
            InlineKeyboardButton(
                "🛠️ ADMIN PANEL",
                callback_data="admin_open",
                icon_custom_emoji_id=PREMIUM_EMOJI_IDS["bot"],
                style="danger",
            )
        ])
    return InlineKeyboardMarkup(rows)


def admin_panel_keyboard():
    """Button-based Admin Panel (no need for /commands for common tasks)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠️ ADMIN PANEL", callback_data="noop", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["bot"])],
        [
            InlineKeyboardButton("⏳ Pending Queue", callback_data="adminpanel|pending"),
            InlineKeyboardButton("📊 Stats", callback_data="adminpanel|stats"),
        ],
        [
            InlineKeyboardButton("💎 Smile Auth / Balance", callback_data="adminpanel|smileauth"),
            InlineKeyboardButton("🔄 Refresh Smile Market", callback_data="adminpanel|smile_refresh"),
        ],
        [
            InlineKeyboardButton("📦 Smile Packages (MLBB)", callback_data="adminpanel|smileprices"),
            InlineKeyboardButton("💵 Set Smile Rate", callback_data="adminpanel|smilerate"),
        ],
        [
            InlineKeyboardButton("🔐 Set Smile Cookie", callback_data="adminpanel|cookie"),
            InlineKeyboardButton("✏️ Set Smile Price", callback_data="adminpanel|setsmileprice"),
        ],
        [
            InlineKeyboardButton("🪙 Add / Deduct Coins", callback_data="adminpanel|coins"),
            InlineKeyboardButton("📢 Broadcast", callback_data="adminpanel|broadcast"),
        ],
        [
            InlineKeyboardButton("🎟️ Promos", callback_data="adminpanel|promos"),
            InlineKeyboardButton("📦 Voucher Stock", callback_data="adminpanel|stock"),
        ],
        [
            InlineKeyboardButton("🏆 Distribute Monthly Rewards", callback_data="adminpanel|distributerewards"),
            InlineKeyboardButton("⚙️ Maintenance", callback_data="adminpanel|maintenance"),
        ],
        [
            InlineKeyboardButton("👤 User Info", callback_data="adminpanel|userinfo"),
            InlineKeyboardButton("🚫 Ban / Unban", callback_data="adminpanel|ban"),
        ],
        [InlineKeyboardButton("📋 Full Command List", callback_data="adminpanel|help")],
        [InlineKeyboardButton("🏠 Close Panel", callback_data="back_main")],
    ])


def category_menu():
    """Create the category menu using the corrected Premium Emoji IDs."""
    keys = list(PRICES)
    rows = []
    for i in range(0, len(keys), 2):
        row = []
        for key in keys[i:i+2]:
            category = PRICES[key]
            emoji_char = category['default_emoji']
            emoji_id = get_custom_emoji_id(key)
            # Use the category's canonical premium ID, not the Unicode emoji's
            # generic mapping.
            button_text = f"{emoji_char} {category['name']}"
            callback_data = f"cat|{key}|0"
            if emoji_id:
                btn = create_button_with_custom_emoji(button_text, emoji_char, emoji_id, callback_data)
            else:
                btn = InlineKeyboardButton(button_text, callback_data=callback_data)
            row.append(btn)
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="back_main", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["home"] if "home" in PREMIUM_EMOJI_IDS else PREMIUM_EMOJI_IDS["done"])])
    return InlineKeyboardMarkup(rows)


def _item_group(category_key: str, item_name: str) -> str:
    """Stable human-readable product grouping without changing DB item names."""
    n = item_name.lower().strip()
    if category_key == "mlbb":
        if "twilight" in n:
            return "🌙 Twilight Pass"
        if "weeklypass" in n or "weekly elite" in n or "monthly epic" in n or "value pack" in n:
            return "⭐ Pass & Bundles"
        if " x 2" in n:
            return "💎 2× Dia Packages"
        if re.search(r'\bdia\s+(11|22|33|44|56|86|112|172)\b', n):
            return "💎 Small Dia"
        if n.startswith("dia "):
            return "💎 Dia Packages"
        return "📦 Other"
    if category_key == "magic_chess":
        if "weekly card" in n:
            return "⭐ Weekly Card"
        if " x 2" in n:
            return "💎 2× Dia Packages"
        if n.startswith("dia "):
            return "💎 Dia Packages"
        return "📦 Other"
    if category_key == "love_deepspace":
        if "pass" in n or "pack" in n:
            return "⭐ Pass & Packs"
        if "crystals" in n:
            return "💎 Crystal + Dia Packages"
        return "📦 Other"
    if category_key == "pubg_uc":
        return "🎮 UC Packages"
    if category_key == "pubg_voucher":
        return "🎁 UC Voucher Packages"
    if category_key == "telegram_premium":
        return "⭐ Premium Plans"
    if category_key == "pubg_pack":
        if "prime" in n:
            return "⭐ Prime Plans"
        if "elite pass" in n:
            return "🏆 Elite Pass"
        return "📦 PUBG Packs"
    if category_key == "mochichat":
        if "monthly pass" in n:
            return "⭐ Monthly Pass"
        return "💰 Beans"
    if category_key == "freefire":
        return "💎 Diamond Packages"
    if category_key == "mytel":
        return "📶 Data Packages"
    return "📦 Items"


def _grouped_items(category_key: str):
    """Return (original_index, name, price, group) in grouped display order."""
    raw = list(PRICES[category_key]["items"].items())
    indexed = [(idx, name, price, _item_group(category_key, name)) for idx, (name, price) in enumerate(raw)]
    group_order = []
    for row in indexed:
        if row[3] not in group_order:
            group_order.append(row[3])
    rank = {g: i for i, g in enumerate(group_order)}
    indexed.sort(key=lambda x: (rank[x[3]], x[0]))
    return indexed


def price_menu(category_key, page=0, user_id=None):
    grouped = _grouped_items(category_key)
    total_pages = max(1, (len(grouped) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * ITEMS_PER_PAGE
    shown = grouped[start:start + ITEMS_PER_PAGE]
    rows = []
    last_group = None
    for original_idx, name, raw, group in shown:
        if group != last_group:
            rows.append([InlineKeyboardButton(f"{group}", callback_data="noop", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["processing"])])
            last_group = group
        followed = False
        if user_id:
            try:
                with db() as conn:
                    f = conn.execute(
                        "SELECT 1 FROM user_follows WHERE user_id=? AND category_key=? AND item_name=?",
                        (user_id, category_key, name)
                    ).fetchone()
                    followed = bool(f)
            except Exception:
                log.exception("price_menu follow lookup")
        follow_btn = "🔕" if followed else "🔔"
        group_id = PREMIUM_EMOJI_IDS["weekly_pass"] if "pass" in group.lower() else PREMIUM_EMOJI_IDS["diamond"]
        if category_key == "pubg_uc" or "uc" in name.lower():
            group_id = PREMIUM_EMOJI_IDS["uc"]
        elif category_key == "freefire":
            group_id = PREMIUM_EMOJI_IDS["freefire_game"]
        elif category_key == "love_deepspace":
            group_id = PREMIUM_EMOJI_IDS["love_deep_game"] if "pass" in group.lower() else PREMIUM_EMOJI_IDS["diamond"]
        rows.append([
            InlineKeyboardButton(
                f"✨ {name} • {price_display(raw)}",
                callback_data=f"prc|{category_key}|{original_idx}",
                icon_custom_emoji_id=group_id,
            ),
            InlineKeyboardButton("❤️", callback_data=f"fav|add|{category_key}|{original_idx}", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["thank_you"]),
            InlineKeyboardButton(follow_btn, callback_data=f"follow|{category_key}|{original_idx}", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["noti_alert"]),
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"cat|{category_key}|{page-1}", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["update"]))
    nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["profile"]))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"cat|{category_key}|{page+1}", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["rush"]))
    rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 Categories", callback_data="shop", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["rush"])])
    return InlineKeyboardMarkup(rows)


def price_group_summary(category_key: str) -> str:
    grouped = _grouped_items(category_key)
    groups = []
    for _, _, _, group in grouped:
        if group not in groups:
            groups.append(group)
    return "\n".join(f"• {g}" for g in groups)

def back_home():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="back_main", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["home"])]] )

def payment_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 K-Pay", callback_data="pay|kpay", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["kpay"])],
        [InlineKeyboardButton("📱 Wave Pay", callback_data="pay|wave", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["wavepay"])],
        [InlineKeyboardButton("🪙 Wallet Coins", callback_data="pay|coin")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_shop")],
    ])

def recharge_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 K-Pay", callback_data="recharge|kpay", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["kpay"])],
        [InlineKeyboardButton("📱 Wave Pay", callback_data="recharge|wave", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["wavepay"])],
        [InlineKeyboardButton("🏠 Home", callback_data="back_main")],
    ])

def admin_action_buttons(kind, item_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🟢  APPROVE", callback_data=f"admin|approve|{kind}|{item_id}", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["done"]),
        InlineKeyboardButton("🔴  REJECT", callback_data=f"admin|reject|{kind}|{item_id}", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["noti_alert"]),
    ]])

def admin_status_markup(kind, item_id, status):
    if status == "completed":
        label = "🟢 APPROVED"
    elif status == "rejected":
        label = "🔴 REJECTED"
    else:
        return admin_action_buttons(kind, item_id)
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data="noop")]])

async def safe_edit(query, text, markup=None):
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    except TelegramError as exc:
        if "Message is not modified" not in str(exc):
            log.warning("safe_edit: %s", exc)

async def answer_and_delete(query, text, markup=None, entities=None):
    try:
        await query.message.delete()
    except TelegramError:
        pass
    try:
        await query.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            entities=entities
        )
    except TelegramError as exc:
        log.warning("answer_and_delete send failed: %s", exc)

async def safe_edit_admin_recharge(query, row):
    status = row["status"]
    status_line = "🟢 <b>APPROVED</b>" if status == "completed" else "🔴 <b>REJECTED</b>"
    caption = (
        f"💳 <b>Recharge #{row['id']}</b> — {status_line}\n\n"
        f"👤 User: <code>{row['user_id']}</code>\n"
        f"💰 Amount: <code>{row['amount']:,} MMK</code>\n"
        f"💳 Method: <b>{esc(row['payment_method']).upper()}</b>\n"
        f"🔢 Last 5: <code>{esc(row['last_5_digits'])}</code>\n"
        f"🕒 Created: <code>{esc(row['created_at'])}</code>"
    )
    try:
        await query.edit_message_caption(
            caption=caption,
            reply_markup=admin_status_markup("recharge", row["id"], status),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError as exc:
        if "not modified" not in str(exc).lower():
            try:
                await query.edit_message_text(
                    caption,
                    reply_markup=admin_status_markup("recharge", row["id"], status),
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                log.exception("safe_edit_admin_recharge")

# ---------- GLOBAL PREMIUM EMOJI OUTPUT WRAPPERS ----------
# Existing business logic can keep using normal Unicode emoji. These wrappers
# transparently convert them to the supplied Premium Emoji IDs at send time.
try:
    from telegram import Bot, Message
    _ORIGINAL_MESSAGE_REPLY_TEXT = Message.reply_text
    _ORIGINAL_BOT_SEND_MESSAGE = Bot.send_message
    _ORIGINAL_BOT_SEND_PHOTO = Bot.send_photo

    async def _premium_reply_text(self, text=None, *args, **kwargs):
        if text is not None and not kwargs.get("entities"):
            original = str(text)
            converted = premiumize_text(original)
            if converted != original:
                text = converted
                kwargs.setdefault("parse_mode", ParseMode.HTML)
        return await _ORIGINAL_MESSAGE_REPLY_TEXT(self, text, *args, **kwargs)

    async def _premium_send_message(self, chat_id, text=None, *args, **kwargs):
        if text is not None and not kwargs.get("entities"):
            original = str(text)
            converted = premiumize_text(original)
            if converted != original:
                text = converted
                kwargs.setdefault("parse_mode", ParseMode.HTML)
        return await _ORIGINAL_BOT_SEND_MESSAGE(self, chat_id, text, *args, **kwargs)

    async def _premium_send_photo(self, chat_id, photo, *args, **kwargs):
        caption = kwargs.get("caption")
        if caption and not kwargs.get("caption_entities"):
            original = str(caption)
            converted = premiumize_text(original)
            if converted != original:
                kwargs["caption"] = converted
                kwargs.setdefault("parse_mode", ParseMode.HTML)
        return await _ORIGINAL_BOT_SEND_PHOTO(self, chat_id, photo, *args, **kwargs)

    Message.reply_text = _premium_reply_text
    Bot.send_message = _premium_send_message
    Bot.send_photo = _premium_send_photo
except Exception:
    log.exception("premium output wrappers initialization failed")

# ---------- USER HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return
    ensure_user(user)

    if maintenance_mode() and not is_admin(user.id):
        await update.message.reply_text("🛠️ ဆိုင်ကို ခေတ္တ Maintenance လုပ်နေပါသည်။")
        return
    if is_banned(user.id):
        await update.message.reply_text("🚫 သင့်အကောင့်ကို ပိတ်ထားပါသည်။")
        return

    context.user_data.clear()

    if context.args and context.args[0].startswith("ref_"):
        try:
            ref_id = int(context.args[0].split("_", 1)[1])
            ok, rr, ur = process_referral(ref_id, user.id)
            if ok:
                await update.message.reply_text(
                    f"🎉 Referral bonus +{ur:,} Coins ရရှိပါပြီ။\n"
                    f"👤 သင့်ကိုခေါ်သောသူလည်း +{rr:,} Coins ရရှိပါပြီ။\n"
                    f"💡 သတိပြုရန် - သင်၏ wallet coins ကိုသုံးရန် အနည်းဆုံး ခေါ်ထားသော သူငယ်ချင်း ၅ ဦး နှင့် ၎င်းတို့တစ်ဦးစီတွင် ပြီးစီးသော order/recharge တစ်ခုစီ ရှိရပါမည်။"
                )
                try:
                    await context.bot.send_message(
                        ref_id,
                        f"👥 Referral အောင်မြင်ပါပြီ။ +{rr:,} Coins ရရှိပါပြီ။",
                    )
                except TelegramError:
                    pass
        except (ValueError, IndexError):
            pass

    full_name = " ".join(
        p for p in [user.first_name or "", user.last_name or ""] if p
    ).strip() or "User"
    username_display = f"@{user.username}" if user.username else "—"
    urow = get_user(user.id)
    ref_count = urow["referral_count"] if urow else 0
    bal = balance(user.id)

    welcome = (
        f"✨ <b>Ki Ki ALL-IN-ONE SHOP Bot</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👋 မင်္ဂလာပါ <b>{esc(full_name)}</b>\n\n"
        f"👤 Name: <b>{esc(full_name)}</b>\n"
        f"🔗 Username: <code>{esc(username_display)}</code>\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"💎 Balance: <code>{bal:,}</code> Coins\n"
        f"👥 Referrals: <code>{ref_count}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👇 လိုအပ်သော Menu ကို ရွေးပါ။"
    )

    # Try to show user's Telegram profile photo
    photo_sent = False
    try:
        photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        if photos and photos.total_count > 0 and photos.photos:
            # Largest size of the first (most recent) profile photo
            best = photos.photos[0][-1]
            await update.message.reply_photo(
                photo=best.file_id,
                caption=welcome,
                reply_markup=main_menu(user.id),
                parse_mode=ParseMode.HTML,
            )
            photo_sent = True
    except TelegramError:
        log.exception("start profile photo")
    except Exception:
        log.exception("start profile photo unexpected")

    if not photo_sent:
        await update.message.reply_text(
            welcome,
            reply_markup=main_menu(user.id),
            parse_mode=ParseMode.HTML,
        )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()
    uid = q.from_user.id
    ensure_user(q.from_user)

    if is_banned(uid):
        await answer_and_delete(q, "🚫 သင့်အကောင့်ကို ပိတ်ထားပါသည်။")
        return
    data = q.data or ""

    if data == "noop":
        return

    # ----- Open Admin Panel (button from main menu) -----
    if data == "admin_open":
        if not is_admin(uid):
            await q.answer("⛔ Admin only", show_alert=True)
            return
        await answer_and_delete(
            q,
            "🛠️ <b>ADMIN PANEL</b>\n\n"
            "ခလုပ်များဖြင့် စီမံနိုင်ပါသည်။\n"
            "• Pending Queue → Order / Recharge Approve\n"
            "• Smile Auth / Cookie / Prices\n"
            "• Coins · Broadcast · Ban · Stats\n\n"
            f"Admin ID: <code>{uid}</code>",
            admin_panel_keyboard(),
        )
        return

    if data == "back_main":
        context.user_data.clear()
        await answer_and_delete(
            q,
            f"🏠 <b>Ki Ki SHOP</b>\n\n💎 Balance: <code>{balance(uid):,}</code> Coins",
            main_menu(uid),
        )
        return

    if data in ("shop", "back_shop"):
        for key in ("category_key", "selected_item", "selected_price", "game_id",
                    "payment_method", "order_id", "waiting_game_id",
                    "waiting_screenshot"):
            context.user_data.pop(key, None)
        await answer_and_delete(q, "💎 <b>Dia ဝယ်လိုက်တာနဲ့ ချက်ချင်းရောက်! ⚡️</b>\n\n"
            "🚀 နှိပ်လိုက်တာနဲ့ Dia တန်းရောက်!\n"
            "⏰ 24/7 အချိန်မရွေး ဝယ်ယူနိုင်ပါတယ်။\n\n"
            "💎 ဝယ်ယူပြီးတာနဲ့ သင့် Acc ထဲကို Dia ချက်ချင်းရောက်ရှိ\n"
            "⚡️ စောင့်စရာမလို\n"
            "⚡️ အချိန်မရွေး ဝယ်လို့ရ\n"
            "⚡️ ဝယ်ပြီးတာနဲ့ တန်းရောက်\n\n"
            "🔥 <b>လိုချင်တဲ့အချိန် ဝယ် — ချက်ချင်းရ!</b>\n"
            "💎 မြန်ဆန် • လွယ်ကူ • 24/7 Service", category_menu())
        return

    if data.startswith("cat|"):
        parts = data.split("|")
        if len(parts) != 3 or parts[1] not in PRICES:
            await answer_and_delete(q, "❌ Category မမှန်ပါ။", category_menu())
            return
        key = parts[1]
        try:
            page = int(parts[2])
        except ValueError:
            page = 0
        context.user_data["category_key"] = key
        context.user_data["user_id"] = uid

        # ===== MLBB → use live Smile.one packages (from wee.py) =====
        if key == "mlbb" and smile is not None:
            await answer_and_delete(q, "⏳ <b>MLBB Packages တင်နေသည်...</b>", None)
            pkgs = smile.get_market()
            if not pkgs:
                await context.bot.send_message(
                    uid,
                    "❌ Smile.one market မရပါ။\n"
                    "Admin မှ Cookie / Auth စစ်ဆေးပေးရန် လိုအပ်သည်။\n"
                    f"Admin: @{esc(ADMIN_USERNAME)}",
                    reply_markup=category_menu(),
                    parse_mode=ParseMode.HTML,
                )
                return
            # Show packages in pages of 8
            total_pages = max(1, (len(pkgs) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
            page = max(0, min(page, total_pages - 1))
            start = page * ITEMS_PER_PAGE
            shown = pkgs[start:start + ITEMS_PER_PAGE]
            rows = []
            for i, p in enumerate(shown):
                real_idx = start + i
                label = f"{p['name'][:22]} • {p['mmk_price']:,}"
                rows.append([InlineKeyboardButton(label, callback_data=f"smilebuy|{real_idx}")])
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"cat|mlbb|{page-1}"))
            if page < total_pages - 1:
                nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"cat|mlbb|{page+1}"))
            if nav:
                rows.append(nav)
            rows.append([InlineKeyboardButton("🔄 Refresh Market", callback_data="smile_refresh")])
            rows.append([InlineKeyboardButton("🏠 Home", callback_data="back_main")])
            text = (
                f"💎 <b>MLBB Auto Top-up (Smile Coin)</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💰 သင့်လက်ကျန်: <code>{balance(uid):,} Coins</code>\n"
                f"📦 Packages: {len(pkgs)} | Page {page+1}/{total_pages}\n\n"
                f"🇲🇲 Myanmar Server / Global Server နှစ်မျိုးလုံး\n"
                f"UID + Zone ID ထည့်ပြီး ဝယ်နိုင်ပါတယ်။\n\n"
                f"ဝယ်လိုသော Package ကို ရွေးပါ။\n"
                f"<i>အလိုအလျောက် top-up ဖြစ်ပါမည် (Admin approve မလိုပါ)</i>"
            )
            await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)
            return
        # ===== end MLBB special path =====

        emoji_char = PRICES[key]['default_emoji']
        emoji_id = get_custom_emoji_id(key)
        premium_head = premium_emoji_html(emoji_id, emoji_char)
        text = (
            f"{premium_head} <b>{esc(PRICES[key]['name'])}</b>\n\n"
            f"<b>📂 Item Categories</b>\n{esc(price_group_summary(key))}\n\n"
            f"ပစ္စည်းကို ရွေးပါ။"
        )
        await answer_and_delete(
            q,
            text,
            price_menu(key, page, uid),
        )
        return

    if data.startswith("prc|"):
        parts = data.split("|")
        if len(parts) != 3:
            return
        key = parts[1]
        try:
            idx = int(parts[2])
            items = list(PRICES[key]["items"].items())
            item_name, raw = items[idx]
        except (KeyError, ValueError, IndexError):
            await answer_and_delete(q, "❌ Item မတွေ့ပါ။", category_menu())
            return
        context.user_data.update({
            "category_key": key,
            "selected_item": item_name,
            "selected_price": raw,
            "order_quantity": 1,
            "waiting_game_id": True,
        })
        await answer_and_delete(
            q,
            f"📦 <b>{esc(item_name)}</b>\n"
            f"💰 <code>{esc(price_display(raw))}</code>\n\n"
            f"🎮 {esc(PRICES[key]['id_label'])} ကို Chat ထဲရိုက်ပို့ပါ။",
            back_home(),
        )
        return

    if data.startswith("fav|"):
        parts = data.split("|")
        if len(parts) == 4 and parts[1] == "add":
            key = parts[2]
            try:
                item = list(PRICES[key]["items"])[int(parts[3])]
            except (KeyError, ValueError, IndexError):
                await q.answer("Item မတွေ့ပါ။", show_alert=True)
                return
            with db() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO user_favorites(user_id,category_key,item_name) VALUES(?,?,?)",
                    (uid, key, item),
                )
            await q.answer("⭐ Favorites ထဲထည့်ပြီးပါပြီ။", show_alert=True)
        return

    if data.startswith("follow|"):
        parts = data.split("|")
        if len(parts) == 3:
            key = parts[1]
            try:
                idx = int(parts[2])
                items = list(PRICES[key]["items"].items())
                item_name = items[idx][0]
            except:
                await q.answer("Item not found", show_alert=True)
                return
            with db() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM user_follows WHERE user_id=? AND category_key=? AND item_name=?",
                    (uid, key, item_name)
                ).fetchone()
                if exists:
                    conn.execute(
                        "DELETE FROM user_follows WHERE user_id=? AND category_key=? AND item_name=?",
                        (uid, key, item_name)
                    )
                    await q.answer("🔕 Unfollowed this item.", show_alert=True)
                else:
                    conn.execute(
                        "INSERT INTO user_follows(user_id, category_key, item_name) VALUES(?,?,?)",
                        (uid, key, item_name)
                    )
                    await q.answer("🔔 You will get alerts for this item!", show_alert=True)
            emoji_char = PRICES[key]['default_emoji']
            emoji_id = get_custom_emoji_id(key)
            text = (
                f"{premium_emoji_html(emoji_id, emoji_char)} <b>{esc(PRICES[key]['name'])}</b>\n\n"
                f"<b>📂 Item Categories</b>\n{esc(price_group_summary(key))}\n\n"
                f"ပစ္စည်းကို ရွေးပါ။"
            )
            await answer_and_delete(q, text, price_menu(key, 0, uid))
        return

    if data == "favorites":
        with db() as conn:
            favs = conn.execute(
                "SELECT category_key,item_name FROM user_favorites WHERE user_id=? ORDER BY rowid DESC",
                (uid,),
            ).fetchall()
        if not favs:
            await answer_and_delete(q, "⭐ Favorites မရှိသေးပါ။", main_menu(uid))
            return
        text = "⭐ <b>Favorites</b>\n\n"
        for row in favs:
            text += f"• {esc(PRICES.get(row['category_key'], {}).get('name', row['category_key']))} — <code>{esc(row['item_name'])}</code>\n"
        await answer_and_delete(q, text[:4090], main_menu(uid))
        return

    if data == "balance":
        await answer_and_delete(
            q,
            f"💎 <b>Wallet</b>\n\n"
            f"Balance: <code>{balance(uid):,}</code> Coins\n"
            f"Referral count: <code>{get_user(uid)['referral_count']}</code>",
            main_menu(uid),
        )
        return

    if data == "dashboard":
        orders = user_orders(uid, 5)
        recs = user_recharges(uid, 5)
        text = (
            f"📊 <b>Dashboard</b>\n\n"
            f"👤 ID: <code>{uid}</code>\n"
            f"💎 Balance: <code>{balance(uid):,}</code>\n"
            f"👥 Referrals: <code>{get_user(uid)['referral_count']}</code>\n\n"
            f"📦 <b>Recent Orders</b>\n"
        )
        text += "".join(
            f"• #{r['id']} {esc(r['item_name'])} {status_icon(r['status'])}\n"
            for r in orders
        ) or "• မရှိသေးပါ\n"
        text += "\n💳 <b>Recent Recharges</b>\n"
        text += "".join(
            f"• #{r['id']} {r['amount']:,} MMK {status_icon(r['status'])}\n"
            for r in recs
        ) or "• မရှိသေးပါ\n"
        await answer_and_delete(q, text[:4090], main_menu(uid))
        return

    if data == "daily_checkin":
        try:
            ok, reward, extra, bal = process_checkin(uid)
        except Exception:
            log.exception("checkin")
            await answer_and_delete(q, "❌ Check-in လုပ်ရာတွင် အမှားဖြစ်သွားပါသည်။", main_menu(uid))
            return
        if not ok:
            await answer_and_delete(q, f"⚠️ ယနေ့ Check-in ပြုလုပ်ပြီးပါပြီ။\n💎 {bal:,} Coins", main_menu(uid))
        else:
            msg = f"🎉 <b>Check-in အောင်မြင်ပါပြီ!</b>\n\n+{reward:,} Coins"
            if extra > 0:
                msg += f"\n🎊 Weekly Jackpot! +{extra:,} Extra Coins!"
            msg += f"\n💎 Balance: {bal:,}"
            await answer_and_delete(q, msg, main_menu(uid))
        return

    if data == "redeem_promo":
        context.user_data["waiting_promo"] = True
        await answer_and_delete(q, "🎟️ Promo Code ကို Chat ထဲရိုက်ပို့ပါ။", back_home())
        return

    if data == "send_feedback":
        context.user_data["waiting_feedback"] = True
        await answer_and_delete(q, "💡 အကြံပြုချက်/တိုင်ကြားချက်ကို Chat ထဲရေးပို့ပါ။", back_home())
        return

    if data == "history":
        rows = user_orders(uid, 10)
        if not rows:
            await answer_and_delete(q, "📜 Order History မရှိသေးပါ။", main_menu(uid))
            return
        text = "📜 <b>Order History</b>\n\n"
        for r in rows:
            text += (
                f"🆔 #{r['id']} | {status_icon(r['status'])}\n"
                f"📦 {esc(r['item_name'])}\n"
                f"💰 {r['amount']:,} Coins\n"
                f"🕒 {esc(r['created_at'])}\n"
                f"────────────\n"
            )
        await answer_and_delete(q, text[:4090], main_menu(uid))
        return

    if data == "recharge":
        await answer_and_delete(
            q,
            f"💳 <b>Wallet Recharge</b>\n\nအနည်းဆုံး <code>{MIN_RECHARGE:,} MMK</code>\nPayment method ရွေးပါ။",
            recharge_menu(),
        )
        return

    if data.startswith("recharge|"):
        method = data.split("|", 1)[1]
        if method not in ("kpay", "wave"):
            return
        context.user_data.update({"recharge_method": method, "waiting_recharge_amt": True})
        name = KPAY_NAME if method == "kpay" else WAVE_NAME
        number = KPAY_NUMBER if method == "kpay" else WAVE_NUMBER
        await answer_and_delete(
            q,
            f"💳 <b>{method.upper()}</b>\n\n"
            f"👤 {esc(name)}\n📱 <code>{esc(number)}</code>\n\n"
            f"ငွေဖြည့်မည့် amount ကို MMK ဖြင့် ရိုက်ပို့ပါ။\n"
            f"Minimum: <code>{MIN_RECHARGE:,}</code>",
            back_home(),
        )
        return

    if data.startswith("pay|"):
        method = data.split("|", 1)[1]
        if method not in ("kpay", "wave", "coin"):
            return
        key = context.user_data.get("category_key")
        item = context.user_data.get("selected_item")
        raw = context.user_data.get("selected_price")
        game_id = context.user_data.get("game_id")
        if not key or not item or raw is None or not game_id:
            await answer_and_delete(q, "❌ Order session မပြည့်စုံတော့ပါ။ Shop မှ ပြန်ရွေးပါ။", main_menu(uid))
            return

        quantity = int(context.user_data.get("order_quantity", 1) or 1)
        quantity = max(1, min(quantity, 10))
        if "weeklypass" in str(item).lower():
            with db() as conn:
                used = conn.execute(
                    "SELECT COALESCE(SUM(COALESCE(quantity,1)),0) AS q FROM orders "
                    "WHERE user_id=? AND category=? AND item_name=? AND game_id=? "
                    "AND status IN ('pending','completed')",
                    (uid, key, item, game_id),
                ).fetchone()["q"]
            if int(used) + quantity > 10:
                remain = max(0, 10 - int(used))
                await answer_and_delete(
                    q,
                    f"❌ ဒီ ML account မှာ Weekly Pass စုစုပေါင်း အများဆုံး 10 Weekly Pass ပဲ ထည့်နိုင်ပါတယ်.\n\n"
                    f"လက်ရှိ: <code>{int(used)}</code> WP\n"
                    f"ကျန်: <code>{remain}</code> WP\n\n"
                    f"ကျေးဇူးပြု၍ {remain} WP ထက် မပိုဘဲ ပြန်ရွေးပါ။",
                    main_menu(uid),
                )
                return
        amount = price_to_coins(raw) * quantity
        if method == "coin":
            if not can_spend_coins(uid):
                await answer_and_delete(
                    q,
                    "❌ သင်၏ wallet coins ကိုသုံးရန် အနည်းဆုံး ခေါ်ထားသော သူငယ်ချင်း ၅ ဦး နှင့် ၎င်းတို့တစ်ဦးစီတွင် အနည်းဆုံး ပြီးစီးသော order/recharge တစ်ခုစီ ရှိရပါမည်။\n\n"
                    "ကျေးဇူးပြု၍ သင်၏ referral များကို ပထမဦးဆုံး order/recharge တင်ခိုင်းပါ။",
                    main_menu(uid)
                )
                return
            with db() as conn:
                conn.execute("BEGIN")
                cur = conn.execute(
                    "UPDATE users SET coin_balance=coin_balance-? "
                    "WHERE user_id=? AND coin_balance>=?",
                    (amount, uid, amount),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    await answer_and_delete(
                        q,
                        f"❌ Wallet မလုံလောက်ပါ။\nလိုအပ်: <code>{amount:,}</code>\nလက်ကျန်: <code>{balance(uid):,}</code>",
                        main_menu(uid),
                    )
                    return
                cur = conn.execute("""
                    INSERT INTO orders(user_id,category,item_name,amount,payment_method,game_id,quantity)
                    VALUES(?,?,?,?,?,?,?)
                """, (uid, key, item, amount, "wallet", game_id, quantity))
                oid = cur.lastrowid
                conn.commit()

            await notify_admin_order(context, oid)
            context.user_data.clear()
            await answer_and_delete(
                q,
                f"✅ <b>Order #{oid} တင်ပြီးပါပြီ။</b>\n\n"
                f"📦 {esc(item)}\n💰 {amount:,} Coins\n"
                f"💎 Balance: {balance(uid):,}\n\nAdmin မှ စစ်ဆေးပြီး ပစ္စည်း/Code ပို့ပေးပါမည်။",
                main_menu(uid),
            )
            return

        context.user_data["payment_method"] = method
        oid = create_order(uid, key, item, amount, method, game_id, quantity)
        context.user_data["order_id"] = oid
        name = KPAY_NAME if method == "kpay" else WAVE_NAME
        number = KPAY_NUMBER if method == "kpay" else WAVE_NUMBER
        context.user_data["waiting_screenshot"] = True
        await answer_and_delete(
            q,
            f"💳 <b>{method.upper()} Payment</b>\n\n"
            f"👤 {esc(name)}\n📱 <code>{esc(number)}</code>\n"
            f"💰 <code>{amount:,} MMK</code>\n\n"
            f"1. အထက်ပါ account သို့ ငွေလွှဲပါ။\n"
            f"2. Screenshot ကို ပို့ပါ။\n"
            f"3. Caption ထဲတွင် transaction နောက်ဆုံး ၅ လုံး ထည့်ပါ။\n\n"
            f"Order: <code>#{oid}</code>",
            back_home(),
        )
        return

    if data == "referral":
        try:
            bot = await context.bot.get_me()
            link = f"https://t.me/{bot.username}?start=ref_{uid}"
        except TelegramError:
            link = "Bot username unavailable"
        with db() as conn:
            refs = conn.execute(
                "SELECT u.first_name,u.username,r.created_at FROM referrals r "
                "JOIN users u ON u.user_id=r.referred_id WHERE r.referrer_id=? "
                "ORDER BY r.id DESC LIMIT 20", (uid,)
            ).fetchall()
        text = f"👥 <b>Referral</b>\n\n🔗 <code>{esc(link)}</code>\n\n"
        text += f"Total: <code>{get_user(uid)['referral_count']}</code>\n\n"
        for r in refs:
            text += f"• {esc(r['first_name'])} @{esc(r['username'] or '-')}\n"
        await answer_and_delete(q, text[:4090], main_menu(uid))
        return

    if data == "lucky_draw":
        await answer_and_delete(
            q,
            "🏆 <b>Rewards</b>\n\n"
            "📅 Daily Check-in: 10–99 Coins, 1% jackpot 100 Coins\n"
            "📆 Weekly Streak: 7 days streak = 500 Bonus Coins\n"
            "👥 Referral: 25–100 CoinsRandom,1% 999 Coins,0.1% jackpot 5000Coins\n"
            "🏅 Monthly Top Inviter: ၁st ၅၉၉၉၊ ၂nd ၃၉၉၉၊ ၃rd ၁၅၉၉ coin\n"
            "🎰 Lucky Spin: 1000 coins per spin. Win WP, Coins, or Try Again!\n"
            "📌 Daily Mission: Invite 5 friends today -> +500 Coins",
            main_menu(uid),
        )
        return

    if data == "contact":
        await answer_and_delete(
            q,
            f"📞 <b>Admin Contact</b>\n\n"
            f"👤 Admin: <b>@{esc(ADMIN_USERNAME)}</b>\n"
            f"🆔 Admin ID: <code>{OWNER_ID}</code>\n\n"
            f"ပြဿနာ/Order/Recharge ကိစ္စရှိရင် အောက်က <b>💬 Chat Admin</b> ကိုနှိပ်ပြီး တိုက်ရိုက်ဆက်သွယ်နိုင်ပါတယ်။",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Chat Admin", url=f"https://t.me/{ADMIN_USERNAME}")],
                [InlineKeyboardButton("🏠 Home", callback_data="back_main")],
            ]),
        )
        return

    if data == "inviter_dashboard":
        await show_inviter_dashboard(update, context, q, uid)
        return

    if data == "daily_mission":
        progress, target, claimed = check_daily_mission(uid)
        update_mission_progress(uid)
        progress, target, claimed = check_daily_mission(uid)
        status = "✅ Claimed" if claimed else "⏳ Pending"
        text = (
            f"📌 <b>Daily Invite Mission</b>\n\n"
            f"Invite <b>{target}</b> friends today!\n"
            f"Progress: <b>{progress}/{target}</b>\n"
            f"Status: {status}\n\n"
            f"🎁 Reward: <b>500 Coins</b>\n\n"
            f"Use /claimmission to claim when completed."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="daily_mission")],
            [InlineKeyboardButton("🏠 Home", callback_data="back_main")],
        ])
        await answer_and_delete(q, text, keyboard)
        return

    # ---------- LUCKY SPIN ----------
    if data == "spin_open":
        text = (
            "🎰 <b>Lucky Spin</b>\n\n"
            "💫 Pay 1000 Coins per spin!\n"
            "🏆 Prizes:\n"
            "• 🎉 1 Weekly Pass (Very Rare!)\n"
            "• 💰 1000 Coins (Rare)\n"
            "• 💰 500 Coins\n"
            "• 💰 300 Coins\n"
            "• 💰 100 Coins\n"
            "• 😊 Try Again!\n\n"
            f"💎 Your Balance: <code>{balance(uid):,}</code> Coins"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎰 SPIN (1000 Coins)", callback_data="spin_do")],
            [InlineKeyboardButton("📜 History", callback_data="spin_history")],
            [InlineKeyboardButton("🏠 Home", callback_data="back_main")],
        ])
        await answer_and_delete(q, text, keyboard)
        return

    if data == "spin_history":
        history = get_spin_history(uid, limit=20)
        if not history:
            text = "📜 <b>Spin History</b>\n\nYou haven't spun yet!"
        else:
            text = "📜 <b>Your Spin History (Last 20)</b>\n\n"
            for h in history:
                prize_display = h["prize_name"]
                if h["prize_value"].isdigit():
                    prize_display += f" (+{int(h['prize_value']):,} Coins)"
                text += f"• {prize_display} — {esc(h['created_at'])}\n"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Spin", callback_data="spin_open")],
            [InlineKeyboardButton("🏠 Home", callback_data="back_main")],
        ])
        await answer_and_delete(q, text, keyboard)
        return

    if data == "spin_do":
        # One atomic transaction: deduct cost, select prize, credit prize and
        # write history without ever using a closed SQLite connection.
        prizes = [
            {"name": "🎉 Weekly Pass", "value": "WP", "weight": 0.5},
            {"name": "💰 1000 Coins", "value": 1000, "weight": 1.0},
            {"name": "💰 500 Coins", "value": 500, "weight": 5.0},
            {"name": "💰 300 Coins", "value": 300, "weight": 15.0},
            {"name": "💰 100 Coins", "value": 100, "weight": 20.0},
            {"name": "😊 Try Again!", "value": 0, "weight": 58.5},
        ]
        selected = random.choices(prizes, weights=[p["weight"] for p in prizes], k=1)[0]

        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute(
                    "UPDATE users SET coin_balance = coin_balance - 1000 "
                    "WHERE user_id = ? AND coin_balance >= 1000",
                    (uid,),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    await answer_and_delete(
                        q,
                        "❌ သင့်မှာ 1000 Coins မရှိပါ။ ငွေဖြည့်ပါ။",
                        main_menu(uid),
                    )
                    return

                prize_value = selected["value"]
                if prize_value == "WP":
                    credit = 500
                    result_text = (
                        f"🎉 <b>JACKPOT!</b>\n"
                        f"You won a Weekly Pass! (+{credit} Coins added)"
                    )
                elif isinstance(prize_value, int) and prize_value > 0:
                    credit = prize_value
                    result_text = f"🎁 You won <b>{credit:,} Coins</b>!"
                else:
                    credit = 0
                    result_text = "😊 ကျေးဇူးတင်ပါတယ်။ နောက်တစ်ကြိမ် ဆုကြီးပေါက်ပါစေ။"

                if credit:
                    conn.execute(
                        "UPDATE users SET coin_balance = coin_balance + ? WHERE user_id = ?",
                        (credit, uid),
                    )

                conn.execute(
                    "INSERT INTO spin_history(user_id, prize_name, prize_value, cost) "
                    "VALUES(?,?,?,?)",
                    (uid, selected["name"], str(prize_value), 1000),
                )
                conn.commit()

        except Exception:
            log.exception("spin_do")
            await answer_and_delete(
                q,
                "❌ Lucky Spin လုပ်ရာတွင် အမှားဖြစ်သွားပါသည်။ Coin များကို မဖြတ်သွားစေရန် transaction ကို rollback လုပ်ထားပါသည်။",
                main_menu(uid),
            )
            return

        new_bal = balance(uid)
        await answer_and_delete(
            q,
            f"🎰 <b>Lucky Spin Result</b>\n\n"
            f"{result_text}\n\n"
            f"💎 New Balance: <code>{new_bal:,}</code> Coins\n\n"
            f"🔄 Spin again?",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Spin Again (1000 Coins)", callback_data="spin_do")],
                [InlineKeyboardButton("📜 History", callback_data="spin_history")],
                [InlineKeyboardButton("🏠 Home", callback_data="back_main", icon_custom_emoji_id=PREMIUM_EMOJI_IDS["home"])],
            ])
        )
        return

    # ========== SMILE.ONE MLBB AUTO TOP-UP FLOW (from wee.py) ==========
    if data == "smile_refresh" and is_admin(uid):
        if smile:
            smile.market_data = None
            pkgs = smile.get_market(force_refresh=True)
            await answer_and_delete(
                q,
                "💎 ဝယ်ယူရန် နှိပ်ပါ\n"
                "⚡️ စောင့်စရာမလို\n"
                "⚡️ အချိန်မရွေး ဝယ်လို့ရ\n"
                "💎 မြန်ဆန် • လွယ်ကူ • 24/7 Service",
                category_menu()
            )
        else:
            await answer_and_delete(
                q,
                "❌ not available (cloudscraper missing).",
                category_menu()
            )
        return

    if data.startswith("smilebuy|"):
        if smile is None:
            await answer_and_delete(q, "❌  မရှိပါ။", category_menu())
            return
        try:
            idx = int(data.split("|")[1])
        except Exception:
            await answer_and_delete(q, "❌ Invalid package.", category_menu())
            return
        pkgs = smile.get_market()
        if not pkgs or idx >= len(pkgs):
            await answer_and_delete(q, "❌ Package မရှိတော့ပါ။ Refresh လုပ်ပါ။", category_menu())
            return
        product = pkgs[idx]
        context.user_data["smile_product"] = product
        context.user_data["smile_step"] = "uid"
        await answer_and_delete(
            q,
            f"💎 <b>{esc(product['name'])}</b>\n"
            f"💵 စျေးနှုန်း: <code>{product['mmk_price']:,} Coins</code>\n\n"
            f"🎮 Game User ID ကိုအရင် ရိုက်ထည့်ပါ။",
            back_home(),
        )
        return

    if data == "smile_confirm":
        product = context.user_data.get("smile_product")
        uid_game = context.user_data.get("smile_uid")
        zone = context.user_data.get("smile_zone")
        if not product or not uid_game or not zone:
            await answer_and_delete(q, "❌ အချက်အလက် ပျောက်နေပါသည်။ ထပ်စမ်းပါ။", category_menu())
            return
        user_bal = balance(uid)
        price = product["mmk_price"]
        if user_bal < price:
            need = price - user_bal
            pkg_name = product.get("name", "Package")
            text = (
                f"❌ <b>လက်ကျန်ငွေ မလုံလောက်ပါ</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📦 Package: <b>{esc(pkg_name)}</b>\n"
                f"💵 လိုအပ်ငွေ: <code>{price:,} Coins</code>\n"
                f"💰 လက်ကျန်ငွေ: <code>{user_bal:,} Coins</code>\n"
                f"📉 လိုအပ်နေသေး: <code>{need:,} Coins</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💳 ငွေဖြည့်ပြီးမှ ပြန်ဝယ်ယူနိုင်ပါတယ်။\n"
                f"Home မှ <b>💰 ငွေဖြည့်မည်</b> ကို နှိပ်ပါ။"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "💳 ငွေဖြည့်မည်",
                    callback_data="recharge",
                    icon_custom_emoji_id=PREMIUM_EMOJI_IDS.get("buy_now"),
                    style="primary",
                )],
                [InlineKeyboardButton(
                    "🏠 Home",
                    callback_data="back_main",
                    icon_custom_emoji_id=PREMIUM_EMOJI_IDS.get("home"),
                )],
            ])
            # Keep smile session so user can come back after recharge if needed
            await answer_and_delete(q, text, kb)
            return
        # Re-check Weekly Pass limit before charge
        game_key = f"{uid_game}|{zone}"
        if re.search(r"weekly|passe semanal|weeklypass", (product.get("name") or ""), re.I):
            wp_bought = count_wp_bought_for_game(game_key)
            if wp_bought >= 10:
                await answer_and_delete(
                    q,
                    f"❌ ဒီ ML account မှာ Weekly Pass အများဆုံး 10 ခု ထည့်ပြီးပါပြီ။\n"
                    f"လက်ရှိ: <code>{wp_bought}</code> WP",
                    main_menu(uid),
                )
                return
        # Deduct first
        if not change_balance(uid, -price):
            await answer_and_delete(q, "❌ Balance ဖြတ်ရာတွင် အမှားဖြစ်သည်။", main_menu(uid))
            return
        await answer_and_delete(q, "⏳ Diamond ပေးပို့နေသည်... ခဏစောင့်ပါ။", None)
        success, msg = await smile.topup_diamonds(uid_game, zone, product, 1)
        if success:
            # Log as completed order for history
            try:
                oid = create_order(uid, "mlbb", product["name"], price, "smile_auto", f"{uid_game}|{zone}", 1)
                with db() as conn:
                    conn.execute(
                        "UPDATE orders SET status='completed', completed_at=? WHERE id=?",
                        (now_text(), oid),
                    )
            except Exception:
                log.exception("smile order log")
            new_bal = balance(uid)
            await context.bot.send_message(
                uid,
                f"{msg}\n\n💰 ကျန်ငွေ: <code>{new_bal:,} Coins</code>",
                reply_markup=main_menu(uid),
                parse_mode=ParseMode.HTML,
            )
        else:
            # Refund
            change_balance(uid, price)
            await context.bot.send_message(
                uid,
                f"{msg}\n\nငွေပြန်ထည့်ပေးလိုက်ပါပြီ။",
                reply_markup=main_menu(uid),
                parse_mode=ParseMode.HTML,
            )
        context.user_data.clear()
        return
    # ========== END SMILE.ONE FLOW ==========

    # ========== ADMIN PANEL BUTTONS ==========
    if data.startswith("adminpanel|"):
        if not is_admin(uid):
            await q.answer("⛔ Admin only", show_alert=True)
            return
        action = data.split("|", 1)[1]

        if action == "pending":
            with db() as conn:
                rs = conn.execute(
                    "SELECT id,user_id,amount,payment_method,last_5_digits,status,created_at "
                    "FROM recharges WHERE status='pending' ORDER BY id DESC LIMIT 10"
                ).fetchall()
                os_ = conn.execute(
                    "SELECT id,user_id,item_name,amount,payment_method,game_id,status,created_at "
                    "FROM orders WHERE status='pending' ORDER BY id DESC LIMIT 10"
                ).fetchall()
            text = "⏳ <b>PENDING QUEUE</b>\n\n"
            text += "<b>💳 Recharges</b>\n"
            if not rs:
                text += "None\n"
            else:
                for r in rs:
                    text += (
                        f"#{r['id']} • User <code>{r['user_id']}</code>\n"
                        f"   💰 {r['amount']:,} MMK · {esc(r['payment_method'])} · "
                        f"Last5 <code>{esc(r['last_5_digits'])}</code>\n"
                    )
            text += "\n<b>📦 Orders</b>\n"
            if not os_:
                text += "None\n"
            else:
                for r in os_:
                    text += (
                        f"#{r['id']} • User <code>{r['user_id']}</code>\n"
                        f"   {esc(r['item_name'])} · {r['amount']:,} · "
                        f"{esc(r['payment_method'])}\n"
                        f"   🎮 <code>{esc(r['game_id'])}</code>\n"
                    )
            # Inline Approve / Reject buttons (max ~8 items to keep keyboard small)
            kb_rows = []
            for r in rs[:5]:
                kb_rows.append([
                    InlineKeyboardButton(
                        f"✅ R#{r['id']}",
                        callback_data=f"admin|approve|recharge|{r['id']}",
                        style="success",
                    ),
                    InlineKeyboardButton(
                        f"❌ R#{r['id']}",
                        callback_data=f"admin|reject|recharge|{r['id']}",
                        style="danger",
                    ),
                ])
            for r in os_[:5]:
                kb_rows.append([
                    InlineKeyboardButton(
                        f"✅ O#{r['id']}",
                        callback_data=f"admin|approve|order|{r['id']}",
                        style="success",
                    ),
                    InlineKeyboardButton(
                        f"❌ O#{r['id']}",
                        callback_data=f"admin|reject|order|{r['id']}",
                        style="danger",
                    ),
                ])
            kb_rows.append([
                InlineKeyboardButton("🔄 Refresh", callback_data="adminpanel|pending"),
                InlineKeyboardButton("🔙 Panel", callback_data="adminpanel|back"),
            ])
            await answer_and_delete(q, text[:4090], InlineKeyboardMarkup(kb_rows))
            return

        if action == "stats":
            with db() as conn:
                total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
                coins = conn.execute("SELECT COALESCE(SUM(coin_balance),0) c FROM users").fetchone()["c"]
                po = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='pending'").fetchone()["c"]
                pr = conn.execute("SELECT COUNT(*) c FROM recharges WHERE status='pending'").fetchone()["c"]
                stock = conn.execute("SELECT COUNT(*) c FROM voucher_stock WHERE is_used=0").fetchone()["c"]
            text = (
                f"📊 <b>Stats</b>\n\n"
                f"Users: {total:,}\nCoins: {coins:,}\n"
                f"Pending orders: {po:,}\nPending recharges: {pr:,}\n"
                f"Rate: {USD_RATE:,}\nVouchers left: {stock:,}"
            )
            await answer_and_delete(q, text, admin_panel_keyboard())
            return

        if action == "smileauth":
            if smile is None:
                await answer_and_delete(q, "❌ Smile.one not available (cloudscraper/bs4 missing).", admin_panel_keyboard())
                return
            ok, status, profile = smile.check_auth()
            if ok:
                text = (
                    f"✅ <b>Smile.one Authenticated</b>\n\n"
                    f"👤 Name: {esc(profile.get('name', '-'))}\n"
                    f"💰 Smile Coin Balance: <b>{esc(profile.get('saldo', '-'))}</b>\n\n"
                    f"💡 ဒီ balance နဲ့ MLBB Diamond packages ကို auto top-up လုပ်နိုင်ပါတယ်။\n"
                    f"Myanmar / Global server နှစ်မျိုးလုံး UID+Zone ထည့်ပြီး ဝယ်နိုင်သည်။"
                )
            else:
                text = (
                    f"❌ <b>Auth failed</b>: {esc(status)}\n\n"
                    f"🔐 Cookie ပြန်သတ်မှတ်ရန် <b>Set Smile Cookie</b> ခလုပ်ကို နှိပ်ပါ။"
                )
            await answer_and_delete(q, text, admin_panel_keyboard())
            return

        if action == "smile_refresh":
            if smile is None:
                await answer_and_delete(q, "❌ Smile.one not available.", admin_panel_keyboard())
                return
            smile.market_data = None
            pkgs = smile.get_market(force_refresh=True)
            count = len(pkgs) if pkgs else 0
            await answer_and_delete(
                q,
                f"🔄 Smile Market refreshed.\n📦 Packages found: <b>{count}</b>\n\n"
                f"MLBB items ကို Shop → MLBB ကနေ ကြည့်နိုင်ပါတယ် (Myanmar server အပါအဝင် UID+Zone ထည့်ပြီး ဝယ်နိုင်သည်)။",
                admin_panel_keyboard(),
            )
            return

        if action == "smileprices":
            if smile is None:
                await answer_and_delete(q, "❌ Smile.one not available.", admin_panel_keyboard())
                return
            pkgs = smile.get_market(force_refresh=True)
            if not pkgs:
                await answer_and_delete(q, "❌ Market data မရပါ။ Cookie စစ်ပါ။", admin_panel_keyboard())
                return
            text = "💎 <b>Smile.one MLBB Packages (Auto Top-up)</b>\n"
            text += "Myanmar / Global server နှစ်မျိုးလုံး အသုံးပြုနိုင်သည်။\n\n"
            for p in pkgs[:45]:
                text += f"<code>{p['pid']}</code> | {esc(p['name'][:28])} → <b>{p['mmk_price']:,}</b>\n"
            if len(pkgs) > 45:
                text += f"\n... +{len(pkgs)-45} more"
            text += "\n\n💡 Price override လုပ်ရန် <b>Set Smile Price</b> ကို သုံးပါ။"
            await answer_and_delete(q, text[:4090], admin_panel_keyboard())
            return

        if action == "smilerate":
            current = smile.mmk_rate if smile else MMK_EXCHANGE_RATE
            context.user_data["admin_waiting"] = "smilerate"
            await answer_and_delete(
                q,
                f"💵 <b>Set Smile MMK Rate</b>\n\n"
                f"Current: <code>{current}</code>\n"
                f"1 Smile Coin ≈ ? MMK\n\n"
                f"Rate အသစ်ကို ဂဏန်းဖြင့် ရိုက်ပို့ပါ (ဥပမာ <code>85</code>)။",
                admin_panel_keyboard(),
            )
            return

        if action == "cookie":
            context.user_data["admin_waiting"] = "cookie"
            await answer_and_delete(
                q,
                "🔐 <b>Set Smile.one Cookie</b>\n\n"
                "Browser မှ Smile.one cookie အပြည့်အစုံ ကူးပြီး ဒီ chat ထဲ ပို့ပါ။\n"
                "ဥပမာ: <code>_ga=...; session=...; ...</code>\n\n"
                "Cookie သိမ်းပြီးရင် Smile Auth ခလုပ်နဲ့ စစ်ဆေးနိုင်ပါတယ်။",
                admin_panel_keyboard(),
            )
            return

        if action == "setsmileprice":
            context.user_data["admin_waiting"] = "setsmileprice"
            await answer_and_delete(
                q,
                "✏️ <b>Set Smile Package Price</b>\n\n"
                "Format: <code>PID PRICE</code>\n"
                "ဥပမာ: <code>22590 1500</code>\n\n"
                "PID ကို Smile Packages စာရင်းကနေ ကြည့်နိုင်သည်။",
                admin_panel_keyboard(),
            )
            return

        if action == "coins":
            context.user_data["admin_waiting"] = "coins"
            await answer_and_delete(
                q,
                "🪙 <b>Add / Deduct Coins</b>\n\n"
                "Format: <code>USER_ID AMOUNT</code>\n"
                "ဥပမာ: <code>123456789 5000</code> (add)\n"
                "သို့မဟုတ် <code>123456789 -2000</code> (deduct)",
                admin_panel_keyboard(),
            )
            return

        if action == "broadcast":
            context.user_data["admin_waiting"] = "broadcast"
            await answer_and_delete(
                q,
                "📢 <b>Broadcast Message</b>\n\n"
                "ပို့လိုသော စာကို ရိုက်ပို့ပါ။ (HTML မပါရ)\n"
                "ပို့ပြီးရင် အားလုံး user များထံ ပို့ပေးမည်။",
                admin_panel_keyboard(),
            )
            return

        if action == "promos":
            with db() as conn:
                rows = conn.execute(
                    "SELECT code,reward,max_uses,used_count FROM promo_codes ORDER BY code"
                ).fetchall()
            text = "🎟️ <b>PROMO LIST</b>\n\n"
            text += "".join(
                f"• <code>{esc(r['code'])}</code> → +{r['reward']:,} | {r['used_count']}/{r['max_uses'] or '∞'}\n"
                for r in rows
            ) or "No promos.\n"
            text += "\n💡 Create: /createpromo CODE REWARD [MAX]\nDelete: /delpromo CODE"
            await answer_and_delete(q, text[:4090], admin_panel_keyboard())
            return

        if action == "stock":
            with db() as conn:
                rows = conn.execute(
                    "SELECT id, category_key, item_name, code, is_used FROM voucher_stock ORDER BY id DESC LIMIT 40"
                ).fetchall()
            text = "📦 <b>Voucher Stock</b>\n\n"
            if not rows:
                text += "📭 No stock found.\n"
            else:
                for r in rows:
                    status = "✅ Used" if r["is_used"] else "⬜ Available"
                    text += f"#{r['id']} {esc(r['item_name'])} | {status}\n   <code>{esc(r['code'])}</code>\n"
            text += "\n💡 /addstock CATEGORY ITEM CODE\n/delstock ID"
            await answer_and_delete(q, text[:4090], admin_panel_keyboard())
            return

        if action == "distributerewards":
            month_year = datetime.now().strftime("%Y-%m")
            if has_monthly_rewards_been_distributed(month_year):
                await answer_and_delete(
                    q, f"✅ ဤလ ({month_year}) အတွက် ဆုများကို ဖြန့်ပြီးပါပြီ။", admin_panel_keyboard()
                )
                return
            winners = distribute_monthly_rewards()
            if winners is None:
                await answer_and_delete(q, "⚠️ ဆုဖြန့်ရာတွင် အမှားဖြစ်ခဲ့သည်။", admin_panel_keyboard())
                return
            if not winners:
                await answer_and_delete(q, "📭 ဤလတွင် ထိပ်ဆုံးသို့ ရောက်သူမရှိသေးပါ။", admin_panel_keyboard())
                return
            msg = "🏆 <b>Monthly Top Inviter Rewards</b>\n\n"
            for w in winners:
                msg += f"{['🥇','🥈','🥉'][w['rank']-1]} <b>{esc(w['first_name'])}</b> (@{esc(w['username'] or '-')})\n"
                msg += f"   👥 Referrals: {w['referral_count']} | 🎁 +{w['reward']:,} Coins\n"
            msg += "\n✅ ဆုများ အောင်မြင်စွာ ဖြန့်ဝေပြီးပါပြီ။"
            await answer_and_delete(q, msg, admin_panel_keyboard())
            for w in winners:
                try:
                    await context.bot.send_message(
                        w["user_id"],
                        f"🎉 <b>Monthly Top Inviter Reward!</b>\n\n"
                        f"သင်သည် ဤလ၏ ထိပ်ဆုံး #{w['rank']} ဖြစ်ပါသည်။\n"
                        f"ဆုငွေ <code>+{w['reward']:,}</code> Coins ကို သင့် wallet ထဲသို့ ထည့်သွင်းပြီးပါပြီ။\n"
                        f"💎 လက်ကျန်: <code>{balance(w['user_id']):,}</code> Coins",
                        parse_mode=ParseMode.HTML,
                    )
                except TelegramError:
                    pass
            return

        if action == "maintenance":
            current = "ON" if maintenance_mode() else "OFF"
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🟢 Turn ON", callback_data="adminpanel|maint_on"),
                    InlineKeyboardButton("🔴 Turn OFF", callback_data="adminpanel|maint_off"),
                ],
                [InlineKeyboardButton("🔙 Admin Panel", callback_data="adminpanel|back")],
            ])
            await answer_and_delete(
                q,
                f"⚙️ <b>Maintenance Mode</b>\n\nCurrent: <b>{current}</b>\n\nON = users cannot use shop.",
                kb,
            )
            return

        if action == "maint_on":
            set_setting("maintenance", "1")
            await answer_and_delete(q, "✅ Maintenance <b>ON</b>", admin_panel_keyboard())
            return

        if action == "maint_off":
            set_setting("maintenance", "0")
            await answer_and_delete(q, "✅ Maintenance <b>OFF</b>", admin_panel_keyboard())
            return

        if action == "userinfo":
            context.user_data["admin_waiting"] = "userinfo"
            await answer_and_delete(
                q,
                "👤 <b>User Info</b>\n\nUser ID ကို ရိုက်ပို့ပါ။",
                admin_panel_keyboard(),
            )
            return

        if action == "ban":
            context.user_data["admin_waiting"] = "ban"
            await answer_and_delete(
                q,
                "🚫 <b>Ban / Unban</b>\n\n"
                "Format: <code>ban USER_ID</code> သို့မဟုတ် <code>unban USER_ID</code>",
                admin_panel_keyboard(),
            )
            return

        if action == "help":
            text = (
                "🛠️ <b>ADMIN COMMANDS (still available)</b>\n\n"
                "/pending /stats /userinfo /addcoin /deductcoin\n"
                "/createpromo /delpromo /promos /setrate\n"
                "/maintenance on|off /ban /unban /broadcast\n"
                "/promoteadmin /distributerewards\n"
                "/addstock /liststock /delstock /alert\n"
                "/setrechargetiers /setcatemoji /setcatemojiid\n\n"
                "💎 <b>Smile.one</b>\n"
                "/cookie /smileauth /smilerate /smileprices /setsmileprice\n\n"
                "အထက်ပါ ခလုပ်များက အဓိကလုပ်ဆောင်ချက်များကို အဆင်ပြေအောင် ပေးထားသည်။"
            )
            await answer_and_delete(q, text, admin_panel_keyboard())
            return

        if action == "back":
            await answer_and_delete(
                q,
                "🛠️ <b>ADMIN PANEL</b>\n\nခလုပ်များကို ရွေးပါ။",
                admin_panel_keyboard(),
            )
            return

        await answer_and_delete(q, "❌ Unknown admin panel action.", admin_panel_keyboard())
        return
    # ========== END ADMIN PANEL ==========

    if data.startswith("admin|"):
        await admin_callback(update, context)
        return

    if data.startswith("emoji|") and is_admin(uid):
        parts = data.split("|")
        if len(parts) == 3 and parts[1] in PRICES:
            set_cat_emoji(parts[1], parts[2], None)
            await answer_and_delete(q, f"✅ {esc(parts[1])} emoji → {esc(parts[2])}", back_home())
        return

    await answer_and_delete(q, "❌ မသိရှိသော action ဖြစ်နေပါသည်။", main_menu(uid))

async def show_inviter_dashboard(update, context, query, uid):
    referrals = get_user_inviter_dashboard(uid)
    user_info = get_user(uid)
    total_refs = user_info["referral_count"] if user_info else 0

    text = "🏅 <b>Your Inviter Dashboard</b>\n\n"
    text += f"👤 You have invited <b>{total_refs}</b> users.\n"
    text += "📋 <b>Referred Users:</b>\n"

    if not referrals:
        text += "   • (No referrals yet)\n"
    else:
        for idx, r in enumerate(referrals, 1):
            username = f"@{esc(r['username'])}" if r['username'] else f"ID {r['user_id']}"
            text += (
                f"   {idx}. {esc(r['first_name'])} {username}\n"
                f"      💰 Balance: <code>{r['coin_balance']:,}</code> | "
                f"✅ Completed: {r['completed_orders'] + r['completed_recharges']} (orders {r['completed_orders']}, recharges {r['completed_recharges']})\n"
            )

    text += "\n🏆 <b>Monthly Top Inviters</b>\n"
    top = get_top_inviters(limit=3, days=30)
    if top:
        medals = ["🥇", "🥈", "🥉"]
        rewards = ["5,999 Coins", "3,999 Coins", "1,599 Coins"]
        for idx, row in enumerate(top):
            rank = idx + 1
            medal = medals[idx] if idx < len(medals) else f"#{rank}"
            reward_text = rewards[idx] if idx < len(rewards) else "-"
            prefix = "➡️ " if row["user_id"] == uid else "   "
            text += f"{prefix}{medal} <b>{esc(row['first_name'])}</b> (@{esc(row['username'] or '-')}) — {row['referral_count']} active referrals (Prize: {reward_text})\n"
    else:
        text += "   • No active referrers yet this month.\n"

    text += "\n💡 <i>Active referral means the referred user has completed at least one order or recharge.</i>"
    text += "\n📌 <i>Monthly rewards are distributed by admin command.</i>"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="inviter_dashboard")],
        [InlineKeyboardButton("🏠 Home", callback_data="back_main")],
    ])
    await answer_and_delete(query, text, keyboard)

async def notify_admin_order(context, order_id: int):
    row = get_order(order_id)
    if not row:
        return
    for admin_id in list(ADMIN_IDS):
        try:
            await context.bot.send_message(
                admin_id,
                f"📥 <b>New Order #{row['id']}</b>\n\n"
                f"👤 User: <code>{row['user_id']}</code>\n"
                f"📦 {esc(row['item_name'])}\n"
                f"🔢 Quantity: <code>{int(row['quantity'] or 1) if 'quantity' in row.keys() else 1}</code>\n"
                f"🎮 <code>{esc(row['game_id'])}</code>\n"
                f"💰 {row['amount']:,} Coins\n"
                f"💳 {esc(row['payment_method'])}\n",
                reply_markup=admin_action_buttons("order", row["id"]),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            log.exception("notify_admin_order")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if not is_admin(uid):
        await q.answer("⛔ Admin only", show_alert=True)
        return
    parts = (q.data or "").split("|")
    if len(parts) != 4:
        return
    _, action, kind, raw_id = parts
    if action not in ("approve", "reject") or kind not in ("order", "recharge"):
        await q.answer("Invalid admin action.", show_alert=True)
        return
    try:
        item_id = int(raw_id)
    except ValueError:
        return

    if kind == "order":
        row, result = (
            complete_order_once(item_id)
            if action == "approve"
            else reject_order_once(item_id)
        )
        if result == "not_found":
            await q.answer("Order မတွေ့ပါ။", show_alert=True)
            return
        if result == "already_processed":
            await q.answer("ဒီ Order ကို ပြီးသား process လုပ်ထားပါတယ်။", show_alert=True)
            return
        if row:
            status = "Completed" if action == "approve" else "Rejected"
            auto_sent = False
            if action == "approve":
                voucher = get_unused_voucher(row["category"], row["item_name"])
                if voucher:
                    if mark_voucher_used(voucher["id"], row["user_id"]):
                        try:
                            await context.bot.send_message(
                                row["user_id"],
                                f"🎁 <b>Your Voucher Code for {esc(row['item_name'])}</b>\n\n"
                                f"🔐 <code>{esc(voucher['code'])}</code>\n\n"
                                f"Please use it in-game. Thank you!",
                                parse_mode=ParseMode.HTML
                            )
                            auto_sent = True
                        except TelegramError:
                            pass

            try:
                if action == "approve":
                    msg = (
                        f"<b>✅ သင့် Order ကို အတည်ပြုပြီးပါပြီ!</b>\n\n"
                        f"📦 <b>{esc(row['item_name'])}</b>\n"
                        f"🔢 Quantity: <code>{int(row['quantity'] or 1) if 'quantity' in row.keys() else 1}</code>\n"
                        f"💰 <code>{row['amount']:,} Coins</code>\n"
                        f"🎮 <code>{esc(row['game_id'])}</code>\n\n"
                        f"⏳ ၃ မိနစ်အတွင်း ဂိမ်း/account ထဲဝင်စစ်ပေးပါ။\n"
                        f"ဝယ်ယူအားပေးမှုအတွက် ကျေးဇူးတင်ပါသည်။ 🙏"
                    )
                    if auto_sent:
                        msg += "\n\n📩 Code ကို အလိုအလျောက် ပို့ပေးပြီးပါပြီ။"
                else:
                    msg = (
                        f"❌ <b>သင့် Order #{row['id']} ကို ငြင်းပယ်လိုက်ပါပြီ</b>\n\n"
                        f"📦 {esc(row['item_name'])}\n"
                        f"လိုအပ်ပါက Admin @{esc(ADMIN_USERNAME)} ထံ ဆက်သွယ်ပါ။"
                    )
                await context.bot.send_message(
                    row["user_id"],
                    msg,
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
        await safe_edit(q, f"#{item_id} → {status}")
        return

    if kind == "recharge":
        row, result, bonus = (
            complete_recharge_once(item_id)
            if action == "approve"
            else reject_recharge_once(item_id)
        )
        if result == "not_found":
            await q.answer("Recharge မတွေ့ပါ။", show_alert=True)
            return
        if result == "already_processed":
            await q.answer("ဒီ Recharge ကို ပြီးသား process လုပ်ထားပါတယ်။", show_alert=True)
            return
        if row:
            if action == "approve":
                text = (
                    f"<b>✅ သင့် Coin Recharge ကို အတည်ပြုပြီးပါပြီ!</b>\n\n"
                    f"💰 ဖြည့်သွင်းပမာဏ: <code>+{row['amount']:,} Coins</code>\n"
                )
                if bonus > 0:
                    text += f"🎁 Bonus: <code>+{bonus:,} Coins</code>\n"
                text += (
                    f"💎 လက်ကျန်: <code>{balance(row['user_id']):,} Coins</code>\n\n"
                    f"⏳ ၃ မိနစ်အတွင်း Wallet/Account ထဲဝင်စစ်ပေးပါ။\n"
                    f"ဝယ်ယူအားပေးမှုအတွက် ကျေးဇူးတင်ပါသည်။ 🙏"
                )
            else:
                text = (
                    f"❌ <b>Recharge #{row['id']} ငြင်းပယ်လိုက်ပါပြီ</b>\n\n"
                    f"💰 ပမာဏ: <code>{row['amount']:,} MMK</code>\n"
                    f"🔴 Status: <b>REJECTED</b>\n\n"
                    f"လိုအပ်ပါက Admin @{esc(ADMIN_USERNAME)} ထံ ဆက်သွယ်ပါ။"
                )
            try:
                await context.bot.send_message(row["user_id"], text, parse_mode=ParseMode.HTML)
            except TelegramError:
                log.exception("recharge user notification")
            await safe_edit_admin_recharge(q, row)
        return

# ---------------- MESSAGE HANDLER ----------------
def extract_last5(text: str) -> Optional[str]:
    m = re.search(r"(?<!\d)(\d{5})(?!\d)", text or "")
    return m.group(1) if m else None

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    if not msg or not user:
        return
    ensure_user(user)
    if is_banned(user.id):
        await msg.reply_text("🚫 သင့်အကောင့်ကို ပိတ်ထားပါသည်။")
        return

    waiting_order = bool(context.user_data.get("waiting_screenshot"))
    waiting_recharge = bool(context.user_data.get("waiting_recharge_screenshot"))
    if not (waiting_order or waiting_recharge):
        await msg.reply_text("💡 Payment screenshot မဟုတ်ပါက Menu ကို အသုံးပြုပါ။", reply_markup=main_menu(user.id))
        return

    photo = msg.photo[-1]
    try:
        file = await photo.get_file()
        image_bytes = bytes(await file.download_as_bytearray())
    except Exception as e:
        log.error("Failed to download photo: %s", e)
        await msg.reply_text("❌ Screenshot ဒေါင်းလုတ်လုပ်ရာတွင် အမှားဖြစ်သွားပါသည်။ နောက်တစ်ခါ ပြန်ကြိုးစားပါ။")
        return

    caption = msg.caption or ""

    last5 = None
    slip_details = {}
    if TESSERACT_AVAILABLE:
        ocr_text = ocr_image(image_bytes)
        if ocr_text:
            slip_details = parse_slip_text(ocr_text)
            last5 = slip_details.get("last5")
            log.info("Tesseract parsed: %s", slip_details)

    if not last5:
        last5 = extract_last5(caption)
        if not last5:
            last5 = await gemini_extract_last5(image_bytes, "image/jpeg", caption)
            if not last5:
                await msg.reply_text(
                    "❌ Transaction နောက်ဆုံး ၅ လုံး မတွေ့ပါ။\n"
                    "Caption ထဲမှာ နောက်ဆုံး ၅ လုံးကို ထည့်ပြီး Screenshot ပြန်ပို့ပါ။"
                )
                return

    if waiting_recharge:
        amount = int(context.user_data.get("recharge_amount", 0))
        method = context.user_data.get("recharge_method", "kpay")
        if amount < MIN_RECHARGE:
            await msg.reply_text("❌ Recharge amount မမှန်ပါ။ /start မှ ပြန်စပါ။")
            return
        rid = create_recharge(user.id, amount, method, last5, photo.file_id)
        admin_caption = (
            f"💳 <b>New Recharge #{rid}</b>\n\n"
            f"👤 User: <code>{user.id}</code>\n"
            f"💰 {amount:,} MMK\n"
            f"💳 {method.upper()}\n"
            f"🔢 Last 5: <code>{last5}</code>\n"
        )
        if slip_details.get("name"):
            admin_caption += f"🧾 Name: <b>{esc(slip_details['name'])}</b>\n"
        if slip_details.get("transaction_id"):
            admin_caption += f"🔑 Txn ID: <code>{esc(slip_details['transaction_id'])}</code>\n"
        if slip_details.get("date") or slip_details.get("time"):
            admin_caption += f"🕒 Date/Time: {esc(slip_details.get('date',''))} {esc(slip_details.get('time',''))}\n"
        admin_caption += "\n(Parsed by OCR – please verify)"

        for admin_id in list(ADMIN_IDS):
            try:
                await context.bot.send_photo(
                    admin_id,
                    photo=photo.file_id,
                    caption=admin_caption,
                    reply_markup=admin_action_buttons("recharge", rid),
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                log.exception("notify recharge")
        context.user_data.clear()
        await msg.reply_text(
            f"✅ Recharge #{rid} တင်ပြီးပါပြီ။ Admin စစ်ဆေးပြီးပါက +{amount:,} Coins ဝင်ပါမည်။",
            reply_markup=main_menu(user.id),
        )
        return

    oid = context.user_data.get("order_id")
    if not oid:
        await msg.reply_text("❌ Order session မတွေ့ပါ။ Shop မှ ပြန်စပါ။")
        return
    row = get_order(oid)
    if not row or row["user_id"] != user.id:
        await msg.reply_text("❌ Order အချက်အလက် မမှန်ပါ။")
        return

    with db() as conn:
        conn.execute(
            "UPDATE orders SET transaction_last5=?,proof_file_id=? WHERE id=? AND status='pending'",
            (last5, photo.file_id, oid),
        )
    await notify_admin_order(context, oid)
    for admin_id in list(ADMIN_IDS):
        try:
            admin_caption = f"🧾 <b>Payment Proof for Order #{oid}</b>\nLast 5: <code>{last5}</code>\n"
            if slip_details.get("name"):
                admin_caption += f"Name: {esc(slip_details['name'])}\n"
            if slip_details.get("transaction_id"):
                admin_caption += f"Txn ID: <code>{esc(slip_details['transaction_id'])}</code>\n"
            if slip_details.get("date") or slip_details.get("time"):
                admin_caption += f"Date/Time: {esc(slip_details.get('date',''))} {esc(slip_details.get('time',''))}\n"
            await context.bot.send_photo(
                admin_id,
                photo=photo.file_id,
                caption=admin_caption,
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass

    context.user_data.clear()
    await msg.reply_text(
        f"✅ Order #{oid} payment proof တင်ပြီးပါပြီ။ Admin အတည်ပြုပြီးပါက codeautoပေးပို့ပါမည်။",
        reply_markup=main_menu(user.id),
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    if not msg or not user:
        return
    ensure_user(user)
    if is_banned(user.id):
        await msg.reply_text("🚫 သင့်အကောင့်ကို ပိတ်ထားပါသည်။")
        return

    text = (msg.text or "").strip()

    # ========== ADMIN PANEL WAITING INPUTS ==========
    admin_waiting = context.user_data.get("admin_waiting")
    if admin_waiting and is_admin(user.id):
        context.user_data.pop("admin_waiting", None)

        if admin_waiting == "cookie":
            if smile is None:
                await msg.reply_text("❌ Smile.one not available.", reply_markup=admin_panel_keyboard())
                return
            success, msg_txt = smile.save_cookie(text)
            await msg.reply_text(msg_txt, reply_markup=admin_panel_keyboard())
            return

        if admin_waiting == "smilerate":
            try:
                rate = int(text.replace(",", ""))
                if smile:
                    smile.mmk_rate = rate
                    smile.market_data = None
                await msg.reply_text(
                    f"✅ Smile MMK rate = <b>{rate}</b>",
                    reply_markup=admin_panel_keyboard(),
                    parse_mode=ParseMode.HTML,
                )
            except ValueError:
                await msg.reply_text("❌ ဂဏန်းသာ ရိုက်ပါ။", reply_markup=admin_panel_keyboard())
            return

        if admin_waiting == "setsmileprice":
            parts = text.split()
            if len(parts) < 2:
                await msg.reply_text("❌ Format: PID PRICE", reply_markup=admin_panel_keyboard())
                return
            pid = parts[0]
            try:
                price = int(parts[1].replace(",", ""))
            except ValueError:
                await msg.reply_text("❌ Price သည် ဂဏန်းဖြစ်ရမည်။", reply_markup=admin_panel_keyboard())
                return
            prices = load_smile_prices()
            name = prices.get(pid, {}).get("name", pid)
            if smile:
                pkgs = smile.get_market() or []
                for p in pkgs:
                    if p["pid"] == pid:
                        name = p["name"]
                        break
            prices[pid] = {"name": name, "price": price}
            save_smile_prices(prices)
            if smile:
                smile.market_data = None
            await msg.reply_text(
                f"✅ {esc(name)} (<code>{pid}</code>) → <b>{price:,}</b> Coins",
                reply_markup=admin_panel_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            return

        if admin_waiting == "coins":
            parts = text.split()
            if len(parts) < 2:
                await msg.reply_text("❌ Format: USER_ID AMOUNT", reply_markup=admin_panel_keyboard())
                return
            try:
                target = int(parts[0])
                amount = int(parts[1].replace(",", ""))
            except ValueError:
                await msg.reply_text("❌ ဂဏန်းမှန်ကန်စွာ ရိုက်ပါ။", reply_markup=admin_panel_keyboard())
                return
            with db() as conn:
                cur = conn.execute(
                    "UPDATE users SET coin_balance=coin_balance+? WHERE user_id=?",
                    (amount, target),
                )
                if cur.rowcount != 1:
                    await msg.reply_text("❌ User မတွေ့ပါ။", reply_markup=admin_panel_keyboard())
                    return
            await msg.reply_text(
                f"✅ <code>{target}</code> {'+' if amount >= 0 else ''}{amount:,} Coins\n"
                f"Balance: {balance(target):,}",
                reply_markup=admin_panel_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            try:
                await context.bot.send_message(
                    target,
                    f"🪙 Wallet Admin Adjustment\n{'+' if amount >= 0 else ''}{amount:,} Coins\n"
                    f"💎 Balance: {balance(target):,}",
                )
            except TelegramError:
                pass
            return

        if admin_waiting == "broadcast":
            body = text
            with db() as conn:
                users = [r["user_id"] for r in conn.execute("SELECT user_id FROM users WHERE is_banned=0")]
            sent = 0
            for target in users:
                try:
                    await context.bot.send_message(
                        target, f"📢 <b>LEO SHOP</b>\n\n{esc(body)}", parse_mode=ParseMode.HTML
                    )
                    sent += 1
                    await asyncio.sleep(0.05)
                except TelegramError:
                    pass
            await msg.reply_text(
                f"✅ Sent: {sent}/{len(users)}",
                reply_markup=admin_panel_keyboard(),
            )
            return

        if admin_waiting == "userinfo":
            try:
                target = int(text.strip())
            except ValueError:
                await msg.reply_text("❌ User ID ဂဏန်းဖြစ်ရမည်။", reply_markup=admin_panel_keyboard())
                return
            row = get_user(target)
            if not row:
                await msg.reply_text("❌ User မတွေ့ပါ။", reply_markup=admin_panel_keyboard())
                return
            await msg.reply_text(
                f"👤 <b>User</b>\n\n"
                f"ID: <code>{row['user_id']}</code>\n"
                f"Username: @{esc(row['username'] or '-')}\n"
                f"Name: {esc(row['first_name'])} {esc(row['last_name'])}\n"
                f"Balance: <code>{row['coin_balance']:,}</code>\n"
                f"Referrals: <code>{row['referral_count']}</code>\n"
                f"Streak: {row['streak_count']} days\n"
                f"Banned: {'Yes' if row['is_banned'] else 'No'}",
                reply_markup=admin_panel_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            return

        if admin_waiting == "ban":
            parts = text.lower().split()
            if len(parts) < 2 or parts[0] not in ("ban", "unban"):
                await msg.reply_text(
                    "❌ Format: ban USER_ID သို့မဟုတ် unban USER_ID",
                    reply_markup=admin_panel_keyboard(),
                )
                return
            try:
                target = int(parts[1])
            except ValueError:
                await msg.reply_text("❌ User ID ဂဏန်းဖြစ်ရမည်။", reply_markup=admin_panel_keyboard())
                return
            ban_val = 1 if parts[0] == "ban" else 0
            with db() as conn:
                conn.execute(
                    "UPDATE users SET is_banned=? WHERE user_id=?",
                    (ban_val, target),
                )
            await msg.reply_text(
                f"✅ {parts[0]} {target}",
                reply_markup=admin_panel_keyboard(),
            )
            return

    # ========== SMILE.ONE UID / ZONE INPUT ==========
    smile_step = context.user_data.get("smile_step")
    if smile_step == "uid":
        if not text.isdigit():
            await msg.reply_text("❌ User ID မှန်ကန်စွာ ရိုက်ပါ (ဂဏန်းသာ)။")
            return
        context.user_data["smile_uid"] = text
        context.user_data["smile_step"] = "zone"
        await msg.reply_text("🌐 Zone ID / Server ID ကို ရိုက်ထည့်ပါ။")
        return

    if smile_step == "zone":
        if not text.isdigit():
            await msg.reply_text("❌ Zone ID မှန်ကန်စွာ ရိုက်ပါ (ဂဏန်းသာ)။")
            return
        product = context.user_data.get("smile_product")
        uid_game = context.user_data.get("smile_uid")
        zone = text
        if not product or not uid_game:
            context.user_data.clear()
            await msg.reply_text("❌ Session ပျောက်သွားပါသည်။ Shop မှ ပြန်စပါ။", reply_markup=main_menu(user.id))
            return

        # Balance is checked only when user presses "ဝယ်မယ်" (smile_confirm).
        # Here we only verify the MLBB account and show the confirmation screen.
        user_bal = balance(user.id)
        price = product["mmk_price"]

        # ID Check (rich)
        msg_check = await msg.reply_text("🔍 Game ID စစ်ဆေးနေသည်...")
        if not smile:
            await msg_check.edit_text("❌ Smile.one မရနိုင်ပါ။")
            context.user_data.clear()
            return

        ok, info = smile.id_check_full(uid_game, zone, product.get("pid"))
        if not ok:
            await msg_check.edit_text(f"❌ ID မမှန်ကန်ပါ: {esc(info)}")
            context.user_data.clear()
            return

        username = info.get("username", "Unknown")
        region = info.get("region") or guess_mlbb_region(zone)
        game_key = f"{uid_game}|{zone}"
        wp_bought = count_wp_bought_for_game(game_key)
        wp_max = 10
        wp_left = max(0, wp_max - wp_bought)
        double_status = get_2x_diamond_status(game_key)
        double_lines = format_2x_status_line(double_status)

        context.user_data["smile_zone"] = zone
        context.user_data["smile_name"] = username
        context.user_data["smile_region"] = region
        context.user_data["smile_step"] = "confirm"

        is_wp = bool(re.search(r"weekly|passe semanal|weeklypass", (product.get("name") or ""), re.I))
        wp_note = ""
        if is_wp:
            if wp_left <= 0:
                await msg_check.edit_text(
                    f"❌ ဒီ ML account မှာ Weekly Pass အများဆုံး <b>{wp_max}</b> ခု ထည့်ပြီးပါပြီ။\n"
                    f"လက်ရှိ ဝယ်ထား: <code>{wp_bought}</code> WP",
                    parse_mode=ParseMode.HTML,
                    reply_markup=main_menu(user.id),
                )
                context.user_data.clear()
                return
            wp_note = f"\n⚠️ ဒီ account မှာ WP ကျန်: <b>{wp_left}/{wp_max}</b>\n"

        text = (
            f"🌟 <b>MLBB Account Verified</b> 🌟\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 ID: <code>{esc(uid_game)}</code>\n"
            f"🖥 Server: <code>{esc(zone)}</code>\n"
            f"👤 Name: <b>{esc(username)}</b>\n"
            f"🌍 Region: <b>{esc(region)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>ရွေးထားသော Package</b>\n"
            f"• {esc(product['name'])}\n"
            f"💵 စျေးနှုန်း: <code>{price:,} Coins</code>\n"
            f"💰 သင့်လက်ကျန်: <code>{user_bal:,} Coins</code>\n"
            f"{wp_note}"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⭐ Weekly Pass ဝယ်ထား: <code>{wp_bought}</code> / {wp_max}\n"
            f"⭐ ကျန်ဝယ်နိုင်: <code>{wp_left}</code> WP\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💎 <b>2x Diamond Status</b>\n"
            f"{double_lines}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"အတည်ပြုပြီး ဝယ်မည်ဆိုရင် အောက်က ခလုပ်ကို နှိပ်ပါ။"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🛒 ဝယ်မယ်",
                callback_data="smile_confirm",
                icon_custom_emoji_id=PREMIUM_EMOJI_IDS.get("buy_now"),
                style="success",
            )],
            [InlineKeyboardButton(
                "❌ မဝယ်သေးပါ",
                callback_data="back_main",
                icon_custom_emoji_id=PREMIUM_EMOJI_IDS.get("noti_alert"),
                style="danger",
            )],
        ])
        await msg_check.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return
    # ========== END SMILE.ONE INPUT ==========

    if is_admin(user.id) and msg.reply_to_message:
        replied = msg.reply_to_message.text or msg.reply_to_message.caption or ""
        m = re.search(r"(?:Order|အော်ဒါ)\s*#(\d+)|#(\d+)", replied, re.I)
        if m:
            oid = int(m.group(1) or m.group(2))
            row = get_order(oid)
            if row:
                try:
                    await context.bot.send_message(
                        row["user_id"],
                        f"🎁 <b>Order #{oid} Delivery</b>\n\n"
                        f"📦 {esc(row['item_name'])}\n"
                        f"🔐 <code>{esc(text)}</code>",
                        parse_mode=ParseMode.HTML,
                    )
                    await msg.reply_text("✅ Buyer ထံသို့ ပို့ပြီးပါပြီ။")
                except TelegramError as exc:
                    await msg.reply_text(f"❌ ပို့မရပါ: {esc(exc)}")
                return

    if context.user_data.get("waiting_feedback"):
        context.user_data.pop("waiting_feedback", None)
        for admin_id in list(ADMIN_IDS):
            try:
                await context.bot.send_message(
                    admin_id,
                    f"💡 <b>New Feedback</b>\n\n"
                    f"👤 <code>{user.id}</code> {esc(user.first_name)}\n"
                    f"📝 {esc(text)}",
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
        await msg.reply_text("✅ Feedback ကို Admin ထံ ပို့ပြီးပါပြီ။", reply_markup=main_menu(user.id))
        return

    if context.user_data.get("waiting_promo"):
        context.user_data.pop("waiting_promo", None)
        ok, result = use_promo(user.id, text)
        if not ok:
            await msg.reply_text(f"❌ {esc(result)}", reply_markup=main_menu(user.id))
        else:
            await msg.reply_text(
                f"🎉 Promo အောင်မြင်ပါပြီ။ +{result:,} Coins\n"
                f"💎 Balance: {balance(user.id):,}",
                reply_markup=main_menu(user.id),
            )
        return

    if context.user_data.get("waiting_recharge_amt"):
        try:
            amount = int(text.replace(",", ""))
        except ValueError:
            await msg.reply_text("❌ Amount ကို ဂဏန်းဖြင့် ရိုက်ပါ။ ဥပမာ 5000")
            return
        if amount < MIN_RECHARGE:
            await msg.reply_text(f"❌ Minimum {MIN_RECHARGE:,} MMK")
            return
        context.user_data["recharge_amount"] = amount
        context.user_data["waiting_recharge_amt"] = False
        context.user_data["waiting_recharge_screenshot"] = True
        method = context.user_data.get("recharge_method", "kpay")
        name = KPAY_NAME if method == "kpay" else WAVE_NAME
        number = KPAY_NUMBER if method == "kpay" else WAVE_NUMBER
        await msg.reply_text(
            f"💳 <b>{method.upper()}</b>\n\n"
            f"👤 {esc(name)}\n📱 <code>{esc(number)}</code>\n"
            f"💰 <code>{amount:,} MMK</code>\n\n"
            f"ငွေလွှဲပြီး Screenshot ပို့ပါ။ Caption ထဲ Last 5 digits ထည့်ပါ။",
            reply_markup=back_home(),
            parse_mode=ParseMode.HTML,
        )
        return

    if context.user_data.get("waiting_game_id"):
        if not text:
            await msg.reply_text("❌ ID/အချက်အလက် ထည့်ပါ။")
            return
        context.user_data["game_id"] = text
        context.user_data["waiting_game_id"] = False
        key = context.user_data["category_key"]
        item = context.user_data["selected_item"]
        raw = context.user_data["selected_price"]
        if "weeklypass" in item.lower():
            context.user_data["waiting_quantity"] = True
            await msg.reply_text(
                f"⭐ <b>Weekly Pass အရေအတွက်</b>\n\n"
                f"ဒီ ML account အတွက် <b>အများဆုံး 10 Weekly Pass</b> ထည့်နိုင်ပါတယ်။\n"
                f"ဝယ်ယူလိုသော အရေအတွက်ကို <code>1 - 10</code> အတွင်း ရိုက်ပို့ပါ။\n\n"
                f"တစ်ခုလျှင်: <code>{price_display(raw)}</code>",
                reply_markup=back_home(),
                parse_mode=ParseMode.HTML,
            )
            return
        await msg.reply_text(
            f"📋 <b>Order Confirmation</b>\n\n"
            f"📦 {esc(item)}\n"
            f"💰 <code>{esc(price_display(raw))}</code>\n"
            f"🎮 {esc(PRICES[key]['id_label'])}: <code>{esc(text)}</code>\n\n"
            f"Payment method ရွေးပါ။",
            reply_markup=payment_menu(),
            parse_mode=ParseMode.HTML,
        )
        return

    if context.user_data.get("waiting_quantity"):
        key = context.user_data.get("category_key")
        item = context.user_data.get("selected_item")
        raw = context.user_data.get("selected_price")
        game_id = context.user_data.get("game_id")
        if not key or not item or raw is None or not game_id:
            context.user_data.clear()
            await msg.reply_text("❌ Order session မပြည့်စုံတော့ပါ။ Shop မှ ပြန်စပါ။", reply_markup=main_menu(user.id))
            return
        try:
            quantity = int(text.replace(",", "").strip())
        except ValueError:
            await msg.reply_text("❌ Weekly Pass အရေအတွက်ကို 1 မှ 10 အတွင်း ဂဏန်းဖြင့် ရိုက်ပါ။")
            return
        if not 1 <= quantity <= 10:
            await msg.reply_text("❌ Weekly Pass အရေအတွက်သည် 1 မှ 10 အတွင်း ဖြစ်ရပါမည်။")
            return
        context.user_data["order_quantity"] = quantity
        context.user_data["waiting_quantity"] = False
        total = price_to_coins(raw) * quantity
        await msg.reply_text(
            f"📋 <b>Order Confirmation</b>\n\n"
            f"📦 {esc(item)} × <b>{quantity}</b> WP\n"
            f"💰 တစ်ခု: <code>{price_to_coins(raw):,} Coins</code>\n"
            f"💵 စုစုပေါင်း: <code>{total:,} Coins</code>\n"
            f"🎮 {esc(PRICES[key]['id_label'])}: <code>{esc(game_id)}</code>\n\n"
            f"Payment method ရွေးပါ။",
            reply_markup=payment_menu(),
            parse_mode=ParseMode.HTML,
        )
        return

    if text and not text.startswith("/"):
        if maintenance_mode() and not is_admin(user.id):
            await msg.reply_text("🛠️ Maintenance mode ဖြစ်နေပါသည်။")
            return
        prompt = (
            "You are LEO X ALL-IN-ONE SHOP customer support. "
            "Reply in natural Myanmar language, concise and useful. "
            "Never claim that a payment is verified or an order is completed. "
            "For prices, ask the user to use the shop menu rather than inventing a price. "
            "If the user asks about an order/payment, explain that an admin must approve it. "
            f"User ID: {user.id}\nUser message: {text}"
        )
        reply = await gemini_text(prompt)
        if reply:
            await msg.reply_text(
                f"🤖 <b>LEO AI Assistant</b>\n\n{esc(reply)}",
                reply_markup=main_menu(user.id),
                parse_mode=ParseMode.HTML,
            )
        else:
            await msg.reply_text(
                "💡 Menu ခလုတ်များကို အသုံးပြုပါ။ Gemini AI ကို configure မလုပ်ရသေးပါ။",
                reply_markup=main_menu(user.id),
            )
        return

    await msg.reply_text("💡 Menu ကို အသုံးပြုပါ။", reply_markup=main_menu(user.id))

# ---------------- USER COMMAND: SET WEB PIN ----------------
async def setwebpin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set PIN for the HTML web shop login. Usage: /setwebpin 1234"""
    user = update.effective_user
    if not update.message or not user:
        return
    ensure_user(user)
    if is_banned(user.id):
        await update.message.reply_text("🚫 သင့်အကောင့်ကို ပိတ်ထားပါသည်။")
        return
    if not context.args or len(context.args[0]) < 4:
        await update.message.reply_text(
            "🔐 <b>Web PIN</b>\n\n"
            "Usage: <code>/setwebpin 1234</code>\n"
            "PIN အနည်းဆုံး ၄ လုံး။ Web shop login မှာ သုံးပါမည်။",
            parse_mode=ParseMode.HTML,
        )
        return
    pin = context.args[0].strip()
    try:
        from werkzeug.security import generate_password_hash
        h = generate_password_hash(pin)
    except ImportError:
        import hashlib
        h = "sha256:" + hashlib.sha256(pin.encode()).hexdigest()
    with db() as conn:
        conn.execute(
            "UPDATE users SET web_pin_hash=? WHERE user_id=?",
            (h, user.id),
        )
    await update.message.reply_text(
        "✅ Web PIN သိမ်းပြီးပါပြီ။\n"
        "Web shop မှာ Telegram User ID + ဤ PIN ဖြင့် login လုပ်ပါ။\n"
        f"🆔 သင့် ID: <code>{user.id}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(user.id),
    )


# ---------------- USER COMMAND: CLAIM DAILY MISSION ----------------
async def claimmission_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not update.message or not user:
        return
    ensure_user(user)
    if is_banned(user.id):
        await update.message.reply_text("🚫 သင့်အကောင့်ကို ပိတ်ထားပါသည်။")
        return
    if maintenance_mode() and not is_admin(user.id):
        await update.message.reply_text("🛠️ Maintenance mode ဖြစ်နေပါသည်။")
        return

    try:
        # Ensure today's mission exists and calculate progress from actual referrals.
        check_daily_mission(user.id)
        update_mission_progress(user.id)
        ok, result = claim_mission(user.id)
        if ok:
            await update.message.reply_text(
                f"🎉 Mission completed! You received +{result:,} Coins!\n"
                f"💎 Balance: {balance(user.id):,}",
                reply_markup=main_menu(user.id),
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(
                f"❌ {esc(result)}",
                reply_markup=main_menu(user.id),
            )
    except Exception:
        log.exception("claimmission_cmd")
        await update.message.reply_text(
            "❌ Daily Mission claim လုပ်ရာတွင် အမှားဖြစ်သွားပါသည်။",
            reply_markup=main_menu(user.id),
        )

# ---------------- ADMIN COMMANDS ----------------
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USD_RATE
    user = update.effective_user
    if not update.message or not user:
        return
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    cmd = update.message.text.split()[0].lower()
    args = context.args

    try:
        if cmd == "/promoteadmin":
            target = int(args[0])
            with db() as conn:
                conn.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (target,))
            ADMIN_IDS.add(target)
            await update.message.reply_text(f"✅ {target} ကို Admin အဖြစ် ထည့်ပြီးပါပြီ။")
            return

        if cmd == "/setrate":
            if not args:
                await update.message.reply_text(f"Current: {USD_RATE:,}\nUsage: /setrate 4800")
                return
            USD_RATE = int(args[0])
            set_setting("usd_rate", str(USD_RATE))
            await update.message.reply_text(f"✅ USD rate = {USD_RATE:,}")
            return

        if cmd == "/maintenance":
            if not args:
                await update.message.reply_text(
                    f"Maintenance: {'ON' if maintenance_mode() else 'OFF'}"
                )
                return
            action = args[0].lower()
            if action not in ("on", "off"):
                await update.message.reply_text("Usage: /maintenance on|off")
                return
            set_setting("maintenance", "1" if action == "on" else "0")
            await update.message.reply_text(f"✅ Maintenance {action.upper()}")
            return

        if cmd == "/createpromo":
            if len(args) < 2:
                await update.message.reply_text("Usage: /createpromo CODE REWARD [MAX_USES]")
                return
            code = args[0].upper()
            reward = int(args[1])
            max_uses = int(args[2]) if len(args) > 2 else 0
            if reward <= 0 or max_uses < 0:
                raise ValueError("invalid reward/max uses")
            with db() as conn:
                conn.execute(
                    "INSERT INTO promo_codes(code,reward,max_uses,used_count) VALUES(?,?,?,0) "
                    "ON CONFLICT(code) DO UPDATE SET reward=excluded.reward,max_uses=excluded.max_uses,used_count=0",
                    (code, reward, max_uses),
                )
            await update.message.reply_text(f"✅ Promo {code}: +{reward:,} Coins")
            return

        if cmd == "/userinfo":
            target = int(args[0])
            row = get_user(target)
            if not row:
                await update.message.reply_text("❌ User မတွေ့ပါ။")
                return
            await update.message.reply_text(
                f"👤 <b>User</b>\n\n"
                f"ID: <code>{row['user_id']}</code>\n"
                f"Username: @{esc(row['username'] or '-')}\n"
                f"Name: {esc(row['first_name'])} {esc(row['last_name'])}\n"
                f"Balance: <code>{row['coin_balance']:,}</code>\n"
                f"Referrals: <code>{row['referral_count']}</code>\n"
                f"Streak: {row['streak_count']} days\n"
                f"Banned: {'Yes' if row['is_banned'] else 'No'}",
                parse_mode=ParseMode.HTML,
            )
            return

        if cmd == "/changecategoryemoji":
            rows = []
            for key, item in PRICES.items():
                emoji_text, _ = get_cat_emoji_info(key)
                rows.append([InlineKeyboardButton(
                    f"{emoji_text} {item['name']}",
                    callback_data=f"emoji|{key}|✨",
                )])
            await update.message.reply_text(
                "🎨 Category ကိုရွေးပြီး default ✨ ကိုပြောင်းပါ။\n"
                "သို့မဟုတ် /setcatemoji ကို သုံး၍ custom emoji (Premium အပါအဝင်) ထည့်နိုင်သည်။",
                reply_markup=InlineKeyboardMarkup(rows),
            )
            return

        if cmd == "/setcatemoji" or cmd == "/setcatemojiid":
            if len(args) < 2:
                await update.message.reply_text(
                    "Usage:\n"
                    "/setcatemoji CATEGORY <tg-emoji emoji-id='...'>💎</tg-emoji>\n"
                    "/setcatemoji CATEGORY 💎\n"
                    "/setcatemojiid CATEGORY 12345\n"
                    "Get the custom emoji ID from @EmojiIDbot or by sending the emoji as a reply."
                )
                return
            category = args[0]
            if category not in PRICES:
                await update.message.reply_text("❌ Invalid category.")
                return

            if cmd == "/setcatemojiid":
                emoji_id = int(args[1])
                set_cat_emoji(category, "✨", emoji_id)
                await update.message.reply_text(f"✅ Emoji ID set for {esc(category)}: {emoji_id}")
                return

            emoji_input = " ".join(args[1:])
            emoji_id = extract_custom_emoji_id(emoji_input)
            if emoji_id:
                inner_match = re.search(r">(.*?)<", emoji_input)
                emoji_text = inner_match.group(1) if inner_match else "✨"
            else:
                emoji_text = emoji_input
            set_cat_emoji(category, emoji_text, emoji_id)
            await update.message.reply_text(f"✅ Emoji updated for {esc(category)} to: {emoji_text}")
            return

        if cmd == "/users":
            with db() as conn:
                rows = conn.execute(
                    "SELECT user_id, username, coin_balance FROM users ORDER BY created_at DESC LIMIT 50"
                ).fetchall()
            if not rows:
                await update.message.reply_text("No users found.")
                return
            text = "👥 <b>Users</b>\n\n"
            for r in rows:
                text += f"• <code>{r['user_id']}</code> | @{esc(r['username'] or '-')} — {r['coin_balance']:,}\n"
            for i in range(0, len(text), 3900):
                await update.message.reply_text(text[i:i+3900], parse_mode=ParseMode.HTML)
            return

        if cmd in ("/ban", "/unban"):
            target = int(args[0])
            with db() as conn:
                conn.execute(
                    "UPDATE users SET is_banned=? WHERE user_id=?",
                    (1 if cmd == "/ban" else 0, target),
                )
            await update.message.reply_text(f"✅ {cmd} {target}")
            return

        if cmd == "/coinrecharge":
            target, amount = int(args[0]), int(args[1])
            if amount == 0:
                raise ValueError("amount cannot be zero")
            with db() as conn:
                cur = conn.execute(
                    "UPDATE users SET coin_balance=coin_balance+? WHERE user_id=?",
                    (amount, target),
                )
                if cur.rowcount != 1:
                    raise ValueError("user not found")
            await update.message.reply_text(f"✅ {target} {'+' if amount > 0 else ''}{amount:,} Coins")
            try:
                await context.bot.send_message(
                    target,
                    f"🪙 Wallet update: {'+' if amount > 0 else ''}{amount:,} Coins\n"
                    f"Balance: {balance(target):,}",
                )
            except TelegramError:
                pass
            return

        if cmd == "/stats":
            with db() as conn:
                total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
                coins = conn.execute("SELECT COALESCE(SUM(coin_balance),0) c FROM users").fetchone()["c"]
                po = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='pending'").fetchone()["c"]
                pr = conn.execute("SELECT COUNT(*) c FROM recharges WHERE status='pending'").fetchone()["c"]
                stock = conn.execute("SELECT COUNT(*) c FROM voucher_stock WHERE is_used=0").fetchone()["c"]
            await update.message.reply_text(
                f"📊 <b>Stats</b>\n\nUsers: {total:,}\nCoins: {coins:,}\nPending orders: {po:,}\nPending recharges: {pr:,}\nRate: {USD_RATE:,}\nVouchers left: {stock:,}",
                parse_mode=ParseMode.HTML,
            )
            return

        if cmd == "/pending":
            with db() as conn:
                rs = conn.execute("SELECT id,user_id,amount,payment_method,status,created_at FROM recharges WHERE status='pending' ORDER BY id DESC LIMIT 20").fetchall()
                os_ = conn.execute("SELECT id,user_id,item_name,amount,payment_method,status,created_at FROM orders WHERE status='pending' ORDER BY id DESC LIMIT 20").fetchall()
            text = "⏳ <b>PENDING QUEUE</b>\n\n<b>Recharge</b>\n"
            text += "".join(f"#{r['id']} • {r['user_id']} • {r['amount']:,} MMK • {esc(r['payment_method'])}\n" for r in rs) or "None\n"
            text += "\n<b>Orders</b>\n"
            text += "".join(f"#{r['id']} • {r['user_id']} • {esc(r['item_name'])} • {r['amount']:,} Coins • {esc(r['payment_method'])}\n" for r in os_) or "None\n"
            await update.message.reply_text(text[:4090], parse_mode=ParseMode.HTML)
            return

        if cmd in ("/addcoin", "/deductcoin"):
            if len(args) < 2:
                await update.message.reply_text(f"Usage: {cmd} USER_ID AMOUNT")
                return
            target, amount = int(args[0]), int(args[1])
            amount = abs(amount) if cmd == "/addcoin" else -abs(amount)
            with db() as conn:
                cur = conn.execute("UPDATE users SET coin_balance=coin_balance+? WHERE user_id=?", (amount, target))
                if cur.rowcount != 1:
                    raise ValueError("user not found")
            await update.message.reply_text(f"✅ <code>{target}</code> {'+' if amount >= 0 else ''}{amount:,} Coins\nBalance: {balance(target):,}", parse_mode=ParseMode.HTML)
            try:
                await context.bot.send_message(target, f"🪙 Wallet Admin Adjustment\n{'+' if amount >= 0 else ''}{amount:,} Coins\n💎 Balance: {balance(target):,}")
            except TelegramError:
                pass
            return

        if cmd == "/rechargeinfo":
            if not args:
                await update.message.reply_text("Usage: /rechargeinfo RECHARGE_ID")
                return
            row = get_recharge(int(args[0]))
            if not row:
                await update.message.reply_text("❌ Recharge မတွေ့ပါ။")
                return
            await update.message.reply_text(
                f"💳 <b>Recharge #{row['id']}</b>\n\nUser: <code>{row['user_id']}</code>\nAmount: <code>{row['amount']:,} MMK</code>\nMethod: {esc(row['payment_method'])}\nLast 5: <code>{esc(row['last_5_digits'])}</code>\nStatus: {status_icon(row['status'])} {row['status']}",
                parse_mode=ParseMode.HTML,
            )
            return

        if cmd == "/orderinfo":
            if not args:
                await update.message.reply_text("Usage: /orderinfo ORDER_ID")
                return
            row = get_order(int(args[0]))
            if not row:
                await update.message.reply_text("❌ Order မတွေ့ပါ။")
                return
            await update.message.reply_text(
                f"📦 <b>Order #{row['id']}</b>\n\nUser: <code>{row['user_id']}</code>\nItem: {esc(row['item_name'])}\nAmount: <code>{row['amount']:,} Coins</code>\nMethod: {esc(row['payment_method'])}\nGame ID: <code>{esc(row['game_id'])}</code>\nStatus: {status_icon(row['status'])} {row['status']}",
                parse_mode=ParseMode.HTML,
            )
            return

        if cmd == "/delpromo":
            if not args:
                await update.message.reply_text("Usage: /delpromo CODE")
                return
            code = args[0].upper()
            with db() as conn:
                cur = conn.execute("DELETE FROM promo_codes WHERE code=?", (code,))
            await update.message.reply_text("✅ Promo deleted." if cur.rowcount else "❌ Promo မတွေ့ပါ။")
            return

        if cmd == "/promos":
            with db() as conn:
                rows = conn.execute("SELECT code,reward,max_uses,used_count FROM promo_codes ORDER BY code").fetchall()
            text = "🎟️ <b>PROMO LIST</b>\n\n" + "".join(f"• <code>{esc(r['code'])}</code> → +{r['reward']:,} | {r['used_count']}/{r['max_uses'] or '∞'}\n" for r in rows)
            await update.message.reply_text(text[:4090], parse_mode=ParseMode.HTML)
            return

        if cmd == "/distributerewards":
            month_year = datetime.now().strftime("%Y-%m")
            if has_monthly_rewards_been_distributed(month_year):
                await update.message.reply_text(f"✅ ဤလ ({month_year}) အတွက် ဆုများကို ဖြန့်ပြီးပါပြီ။")
                return
            winners = distribute_monthly_rewards()
            if winners is None:
                await update.message.reply_text("⚠️ ဆုဖြန့်ရာတွင် အမှားဖြစ်ခဲ့သည်။")
                return
            if not winners:
                await update.message.reply_text("📭 ဤလတွင် ထိပ်ဆုံးသို့ ရောက်သူမရှိသေးပါ။")
                return
            msg = "🏆 <b>Monthly Top Inviter Rewards</b>\n\n"
            for w in winners:
                msg += f"{['🥇','🥈','🥉'][w['rank']-1]} <b>{esc(w['first_name'])}</b> (@{esc(w['username'] or '-')})\n"
                msg += f"   👥 Referrals: {w['referral_count']} | 🎁 +{w['reward']:,} Coins\n"
            msg += "\n✅ ဆုများ အောင်မြင်စွာ ဖြန့်ဝေပြီးပါပြီ။"
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            for w in winners:
                try:
                    await context.bot.send_message(
                        w["user_id"],
                        f"🎉 <b>Monthly Top Inviter Reward!</b>\n\n"
                        f"သင်သည် ဤလ၏ ထိပ်ဆုံး #{w['rank']} ဖြစ်ပါသည်။\n"
                        f"ဆုငွေ <code>+{w['reward']:,}</code> Coins ကို သင့် wallet ထဲသို့ ထည့်သွင်းပြီးပါပြီ။\n"
                        f"💎 လက်ကျန်: <code>{balance(w['user_id']):,}</code> Coins",
                        parse_mode=ParseMode.HTML,
                    )
                except TelegramError:
                    pass
            return

        if cmd == "/addstock":
            if len(args) < 3:
                await update.message.reply_text("Usage: /addstock CATEGORY_KEY ITEM_NAME CODE")
                return
            category = args[0]
            item_name = " ".join(args[1:-1])
            code = args[-1]
            if category not in PRICES:
                await update.message.reply_text("❌ Invalid category.")
                return
            if add_voucher_stock(category, item_name, code):
                await update.message.reply_text(f"✅ Stock added for {esc(item_name)}")
            else:
                await update.message.reply_text("❌ Failed to add stock.")
            return

        if cmd == "/liststock":
            with db() as conn:
                rows = conn.execute("SELECT id, category_key, item_name, code, is_used FROM voucher_stock ORDER BY id DESC LIMIT 50").fetchall()
            if not rows:
                await update.message.reply_text("📭 No stock found.")
                return
            text = "📦 <b>Voucher Stock</b>\n\n"
            for r in rows:
                status = "✅ Used" if r["is_used"] else "⬜ Available"
                text += f"#{r['id']} {esc(r['item_name'])} | {status}\n"
                text += f"   <code>{esc(r['code'])}</code>\n"
            await update.message.reply_text(text[:4090], parse_mode=ParseMode.HTML)
            return

        if cmd == "/delstock":
            if not args:
                await update.message.reply_text("Usage: /delstock ID")
                return
            sid = int(args[0])
            with db() as conn:
                cur = conn.execute("DELETE FROM voucher_stock WHERE id=?", (sid,))
            await update.message.reply_text("✅ Deleted." if cur.rowcount else "❌ Not found.")
            return

        if cmd == "/alert":
            if len(args) < 3:
                await update.message.reply_text("Usage: /alert CATEGORY ITEM_NAME NEW_PRICE")
                return
            category = args[0]
            item_name = " ".join(args[1:-1])
            new_price = args[-1]
            followers = get_followers(category, item_name)
            if not followers:
                await update.message.reply_text("📭 No followers for this item.")
                return
            sent = 0
            for f in followers:
                try:
                    await context.bot.send_message(
                        f["user_id"],
                        f"🔔 <b>Price Alert!</b>\n\n"
                        f"📦 {esc(item_name)}\n"
                        f"💲 New Price: <code>{esc(new_price)}</code>\n\n"
                        f"Visit the shop to order now!",
                        parse_mode=ParseMode.HTML
                    )
                    sent += 1
                    await asyncio.sleep(0.05)
                except:
                    pass
            await update.message.reply_text(f"✅ Alert sent to {sent} followers.")
            return

        if cmd == "/setrechargetiers":
            if not args:
                tiers = get_recharge_tiers()
                text = "📊 <b>Current Recharge Tiers</b>\n\n"
                for k, v in sorted(tiers.items(), key=lambda x: int(x[0])):
                    text += f"• {int(k):,} MMK → {v}% Bonus\n"
                await update.message.reply_text(text, parse_mode=ParseMode.HTML)
                return
            try:
                new_tiers = {}
                for arg in args:
                    if ":" not in arg:
                        continue
                    k, v = arg.split(":")
                    new_tiers[k] = float(v)
                set_setting("recharge_tiers", json.dumps(new_tiers))
                await update.message.reply_text("✅ Recharge tiers updated!")
            except:
                await update.message.reply_text("❌ Invalid format. Use: 10000:2.0 50000:2.5")
            return

        if cmd == "/admin":
            await update.message.reply_text(
                "🛠️ <b>ADMIN PANEL v18.7 + Smile.one MLBB</b>\n\n"
                "အောက်က ခလုပ်များကို သုံးပါ။\n"
                "Smile Coin / MLBB Auto Top-up ကို ဒီနေရာကနေ စီမံနိုင်ပါတယ်။\n"
                "Cookie, Rate, Package Price စသည်တို့ကို ခလုပ်ဖြင့် သတ်မှတ်နိုင်သည်။",
                reply_markup=admin_panel_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            return

        # ===== Smile.one Admin Commands (from wee.py) =====
        if cmd == "/cookie":
            if not args:
                await update.message.reply_text(
                    "🔐 Usage: /cookie _ga=...; session=...\n"
                    "Browser မှ Smile.one cookie အပြည့်အစုံ ကူးပြီး ပို့ပါ။"
                )
                return
            if smile is None:
                await update.message.reply_text("❌ cloudscraper / bs4 မရှိပါ။ pip install cloudscraper beautifulsoup4")
                return
            success, msg_txt = smile.save_cookie(" ".join(args))
            await update.message.reply_text(msg_txt)
            return

        if cmd == "/smileauth":
            if smile is None:
                await update.message.reply_text("❌ Smile.one not available.")
                return
            ok, status, profile = smile.check_auth()
            if ok:
                await update.message.reply_text(
                    f"✅ <b>Authenticated</b>\n"
                    f"Name: {esc(profile.get('name','-'))}\n"
                    f"Balance: {esc(profile.get('saldo','-'))}",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await update.message.reply_text(f"❌ Auth failed: {esc(status)}")
            return

        if cmd == "/smilerate":
            current = smile.mmk_rate if smile else MMK_EXCHANGE_RATE
            if not args:
                await update.message.reply_text(f"Current Smile MMK rate: {current}")
                return
            try:
                rate = int(args[0])
                if smile:
                    smile.mmk_rate = rate
                    smile.market_data = None
                await update.message.reply_text(f"✅ Smile MMK rate = {rate}")
            except ValueError:
                await update.message.reply_text("❌ Number only.")
            return

        if cmd == "/smileprices":
            if smile is None:
                await update.message.reply_text("❌ Smile.one not available.")
                return
            pkgs = smile.get_market(force_refresh=True)
            if not pkgs:
                await update.message.reply_text("❌ Market data မရပါ။ Cookie စစ်ပါ။")
                return
            text = "💎 <b>Smile.one Packages</b>\n\n"
            for p in pkgs[:40]:
                text += f"<code>{p['pid']}</code> | {esc(p['name'][:25])} → {p['mmk_price']:,}\n"
            if len(pkgs) > 40:
                text += f"\n... +{len(pkgs)-40} more"
            await update.message.reply_text(text[:4090], parse_mode=ParseMode.HTML)
            return

        if cmd == "/setsmileprice":
            if len(args) < 2:
                await update.message.reply_text("Usage: /setsmileprice PID PRICE\nExample: /setsmileprice 22590 1500")
                return
            pid = args[0]
            try:
                price = int(args[1].replace(",", ""))
            except ValueError:
                await update.message.reply_text("❌ Price သည် ဂဏန်းဖြစ်ရမည်။")
                return
            prices = load_smile_prices()
            name = prices.get(pid, {}).get("name", pid)
            # try get name from market
            if smile:
                pkgs = smile.get_market() or []
                for p in pkgs:
                    if p["pid"] == pid:
                        name = p["name"]
                        break
            prices[pid] = {"name": name, "price": price}
            save_smile_prices(prices)
            if smile:
                smile.market_data = None
            await update.message.reply_text(f"✅ {esc(name)} ({pid}) → {price:,} Coins")
            return
        # ===== End Smile.one Admin =====

        if cmd == "/broadcast":
            if not args:
                await update.message.reply_text("Usage: /broadcast message")
                return
            body = " ".join(args)
            with db() as conn:
                users = [r["user_id"] for r in conn.execute("SELECT user_id FROM users WHERE is_banned=0")]
            sent = 0
            for target in users:
                try:
                    await context.bot.send_message(target, f"📢 <b>LEO SHOP</b>\n\n{esc(body)}", parse_mode=ParseMode.HTML)
                    sent += 1
                    await asyncio.sleep(0.05)
                except TelegramError:
                    pass
            await update.message.reply_text(f"✅ Sent: {sent}/{len(users)}")
            return

        await update.message.reply_text("❌ Unknown admin command. Use /admin for help.")
    except (ValueError, IndexError) as exc:
        await update.message.reply_text(f"❌ Input error: {esc(exc)}")
    except Exception:
        log.exception("admin_cmd")
        await update.message.reply_text("❌ Admin command error ဖြစ်သွားပါသည်။")

# ---------------- ERROR HANDLER ----------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled update error: %s", context.error, exc_info=context.error)
    try:
        if update and hasattr(update, "effective_chat"):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ စနစ်တွင် အမှားတစ်ခုဖြစ်ပွားခဲ့သည်။ ကျေးဇူးပြု၍ နောက်မှ ပြန်ကြိုးစားပါ။",
            )
    except Exception:
        pass

# ---------------- MAIN ----------------
def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable မသတ်မှတ်ရသေးပါ။ "
            "Security အတွက် token ကို source code ထဲ hard-code မလုပ်ပါနှင့်။"
        )
    init_db()
    missing_ids = [k for k, v in PREMIUM_EMOJI_IDS.items() if not str(v).isdigit()]
    if missing_ids:
        log.warning("Premium Emoji registry contains invalid IDs: %s", missing_ids)
    missing_categories = [k for k in PRICES if k not in CUSTOM_EMOJI_MAP]
    if missing_categories:
        log.warning("Categories without canonical Premium Emoji mapping: %s", missing_categories)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setwebpin", setwebpin_cmd))
    app.add_handler(CommandHandler("claimmission", claimmission_cmd))
    for command in (
        "promoteadmin", "setrate", "maintenance", "createpromo", "userinfo",
        "changecategoryemoji", "setcatemoji", "setcatemojiid",
        "users", "ban", "unban", "broadcast",
        "coinrecharge", "stats", "pending", "addcoin", "deductcoin",
        "rechargeinfo", "orderinfo", "delpromo", "promos", "admin",
        "distributerewards", "addstock", "liststock", "delstock",
        "alert", "setrechargetiers",
        # Smile.one MLBB
        "cookie", "smileauth", "smilerate", "smileprices", "setsmileprice",
    ):
        app.add_handler(CommandHandler(command, admin_cmd))

    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    log.info(
        "LEO SHOP v18.6 started | Gemini=%s | model=%s | Tesseract=%s",
        bool(gemini_model), GEMINI_CHAT_MODEL, TESSERACT_AVAILABLE,
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
