#!/usr/bin/env python3
"""
Ki Ki Shop – Web Frontend
Shares the same SQLite DB + Smile.one logic as bot.py.
Users must log in (Telegram User ID + PIN).
Diamond purchase requires wallet coins.
Recharge requests notify admin via Telegram bot.
"""
from __future__ import annotations

import asyncio
import hashlib
import html as html_lib
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

# Optional Smile.one deps
try:
    import cloudscraper
    from bs4 import BeautifulSoup

    SMILE_AVAILABLE = True
except ImportError:
    SMILE_AVAILABLE = False
    cloudscraper = None
    BeautifulSoup = None

try:
    import requests
except ImportError:
    requests = None

# ---------------- CONFIG (same defaults as bot.py) ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8275446095:AAHUYrowbdPI0Q9fk0edmEKkaXnKnUoFzlE")
OWNER_ID = int(os.getenv("OWNER_ID", "7308292609"))
ADMIN_IDS = {OWNER_ID}
KPAY_NUMBER = os.getenv("KPAY_NUMBER", "09687512062")
KPAY_NAME = os.getenv("KPAY_NAME", "Ma Chit Su")
WAVE_NUMBER = os.getenv("WAVE_NUMBER", "09687512062")
WAVE_NAME = os.getenv("WAVE_NAME", "Ye Htet Aung")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "kiki20251").lstrip("@")
MIN_RECHARGE = int(os.getenv("MIN_RECHARGE", "5000"))
USD_RATE = int(os.getenv("USD_RATE", "4700"))
DB_PATH = os.getenv("LEO_DB_PATH", "kiki_shop.db")
COOKIE_FILE = os.getenv("COOKIE_FILE", "cookies.json")
SMILE_PRICES_FILE = os.getenv("SMILE_PRICES_FILE", "smile_prices.json")
MMK_EXCHANGE_RATE = int(os.getenv("MMK_EXCHANGE_RATE", "85"))
SECRET_KEY = os.getenv("WEB_SECRET_KEY", secrets.token_hex(32))
HOST = os.getenv("WEB_HOST", "0.0.0.0")
# Render sets PORT; local default 8080
PORT = int(os.getenv("PORT") or os.getenv("WEB_PORT") or "8080")
DEBUG = os.getenv("WEB_DEBUG", "0") == "1"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("web-shop")

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.permanent_session_lifetime = timedelta(days=14)

# ---------------- DB ----------------
def db():
    conn = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""))


def init_web_db():
    """Ensure tables exist (compatible with bot.py schema) + web_pin column."""
    with db() as conn:
        conn.executescript(
            """
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
            completed_at TEXT,
            quantity INTEGER NOT NULL DEFAULT 1
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
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admins(
            user_id INTEGER PRIMARY KEY
        );
        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_recharges_user ON recharges(user_id, id DESC);
        """
        )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "web_pin_hash" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN web_pin_hash TEXT DEFAULT ''")
        if "is_banned" not in cols:
            conn.execute(
                "ALTER TABLE users ADD COLUMN is_banned INTEGER NOT NULL DEFAULT 0"
            )
        for row in conn.execute("SELECT user_id FROM admins").fetchall():
            ADMIN_IDS.add(row["user_id"])
        ADMIN_IDS.add(OWNER_ID)


def get_user(user_id: int):
    try:
        with db() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
    except Exception:
        log.exception("get_user")
        return None


def ensure_user(user_id: int, username: str = "", first_name: str = "") -> bool:
    try:
        with db() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, username, first_name, last_name)
                VALUES(?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=CASE WHEN excluded.username!='' THEN excluded.username ELSE users.username END,
                    first_name=CASE WHEN excluded.first_name!='' THEN excluded.first_name ELSE users.first_name END
                """,
                (user_id, username or "", first_name or "", ""),
            )
        return True
    except Exception:
        log.exception("ensure_user")
        return False


def balance(user_id: int) -> int:
    row = get_user(user_id)
    return int(row["coin_balance"]) if row else 0


def change_balance(user_id: int, amount: int) -> bool:
    try:
        with db() as conn:
            cur = conn.execute(
                "UPDATE users SET coin_balance=coin_balance+? WHERE user_id=?",
                (int(amount), user_id),
            )
            return cur.rowcount == 1
    except Exception:
        log.exception("change_balance")
        return False


def is_banned(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["is_banned"])


def maintenance_mode() -> bool:
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='maintenance'"
            ).fetchone()
            return bool(row and row["value"] == "1")
    except Exception:
        return False


def set_web_pin(user_id: int, pin: str) -> bool:
    if len(pin) < 4:
        return False
    h = generate_password_hash(pin)
    with db() as conn:
        cur = conn.execute(
            "UPDATE users SET web_pin_hash=? WHERE user_id=?", (h, user_id)
        )
        return cur.rowcount == 1


def verify_web_pin(user_id: int, pin: str) -> bool:
    row = get_user(user_id)
    if not row:
        return False
    stored = row["web_pin_hash"] if "web_pin_hash" in row.keys() else ""
    if not stored:
        # First-time: if no PIN set, accept any pin of length >= 4 and save it.
        if len(pin) >= 4:
            set_web_pin(user_id, pin)
            return True
        return False
    if stored.startswith("sha256:"):
        import hashlib
        return stored == "sha256:" + hashlib.sha256(pin.encode()).hexdigest()
    return check_password_hash(stored, pin)


def create_order(
    user_id, category, item_name, amount, payment_method, game_id, quantity=1
):
    quantity = max(1, int(quantity or 1))
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO orders(user_id,category,item_name,amount,payment_method,game_id,quantity,status,completed_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                user_id,
                category,
                item_name,
                int(amount),
                payment_method,
                game_id,
                quantity,
                "pending",
                None,
            ),
        )
        return cur.lastrowid


def create_recharge(user_id, amount, method, last5, proof_note=""):
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO recharges(user_id,amount,payment_method,last_5_digits,proof_file_id,status)
            VALUES(?,?,?,?,?,?)
            """,
            (user_id, int(amount), method, last5, proof_note or "web", "pending"),
        )
        return cur.lastrowid


def user_orders(user_id, limit=20):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()


def user_recharges(user_id, limit=20):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM recharges WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()


def count_wp_bought_for_game(game_id: str) -> int:
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
        return 0


# ---------------- SMILE.ONE (aligned with bot.py) ----------------
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
    "Saldo insuficiente": "Insufficient Balance",
}


def load_smile_prices():
    if os.path.exists(SMILE_PRICES_FILE):
        try:
            with open(SMILE_PRICES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


class SmileOneBot:
    def __init__(self):
        self.base_url = "https://www.smile.one"
        self.user_agent = (
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        )
        if SMILE_AVAILABLE:
            self.scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "android", "mobile": True}
            )
        else:
            self.scraper = None
        self.headers = {
            "User-Agent": self.user_agent,
            "Referer": f"{self.base_url}/br/customer/order",
            "X-Requested-With": "XMLHttpRequest",
        }
        self.market_data = None
        self.last_market_update = None
        self.mmk_rate = MMK_EXCHANGE_RATE

    def translate(self, text):
        for pt, en in TRANSLATIONS.items():
            if pt in text:
                text = text.replace(pt, en)
        return text

    def check_auth(self):
        if not SMILE_AVAILABLE or not self.scraper:
            return False, "cloudscraper not installed", None
        if not os.path.exists(COOKIE_FILE):
            return False, "NO_SESSION", None
        try:
            with open(COOKIE_FILE, "r") as f:
                cookies = json.load(f).get("parsed_dict", {})
            res = self.scraper.get(
                f"{self.base_url}/br/customer/order",
                cookies=cookies,
                headers=self.headers,
            )
            soup = BeautifulSoup(res.text, "html.parser")
            det = soup.find("div", class_="user-details")
            if det:
                name = det.find("div", class_="user-name").get_text().strip()
                bal_elem = soup.find("div", class_="balance-coins")
                if bal_elem:
                    bal_parts = bal_elem.find_all("p")
                    if len(bal_parts) > 1:
                        bal = bal_parts[1].get_text().strip()
                        return True, "AUTH_SUCCESS", {
                            "name": name,
                            "saldo": f"{bal} coin",
                        }
            return False, "DENIED", None
        except Exception as e:
            return False, f"ERROR: {str(e)}", None

    def id_check_full(self, u_id, z_id, product_pid=None):
        if not os.path.exists(COOKIE_FILE):
            return False, "Auth Required"
        with open(COOKIE_FILE, "r") as f:
            cookies = json.load(f).get("parsed_dict", {})
        try:
            pid = product_pid or "22590"
            payload = {
                "user_id": u_id,
                "zone_id": z_id,
                "pid": str(pid),
                "checkrole": "1",
                "pay_methond": "smilecoin",
                "channel_method": "smilecoin",
            }
            res = self.scraper.post(
                f"{self.base_url}/merchant/mobilelegends/checkrole",
                data=payload,
                cookies=cookies,
                headers=self.headers,
            )
            data = res.json() if res is not None else {}
            if data.get("code") != 200:
                return False, data.get("info", "Invalid ID")
            username = (
                data.get("username")
                or data.get("role")
                or data.get("name")
                or "Unknown"
            )
            region = (
                data.get("region")
                or data.get("country")
                or data.get("server_name")
                or data.get("zone_name")
                or "Myanmar / Global"
            )
            return True, {
                "username": str(username),
                "region": str(region) if region else "Myanmar / Global",
                "raw": data,
            }
        except Exception as e:
            return False, f"Connection Error: {str(e)}"

    def get_market(self, force_refresh=False):
        if (
            not force_refresh
            and self.market_data
            and self.last_market_update
        ):
            if (datetime.now() - self.last_market_update).seconds < 300:
                return self.market_data
        try:
            if not os.path.exists(COOKIE_FILE):
                return None
            with open(COOKIE_FILE, "r") as f:
                cookies = json.load(f).get("parsed_dict", {})
            res = self.scraper.get(
                f"{self.base_url}/br/merchant/mobilelegends",
                cookies=cookies,
                headers=self.headers,
            )
            match = re.search(
                r"info\s*=\s*JSON\.parse\('(.*?)'\);", res.text, re.DOTALL
            )
            data = json.loads(match.group(1)) if match else {}
            soup = BeautifulSoup(res.text, "html.parser")
            pkgs = []
            custom_prices = load_smile_prices()

            for item in soup.find_all("li", class_="fr fs", id=True):
                pid = item.get("id")
                raw_name = (
                    item.find("h3").get_text(strip=True) if item.find("h3") else "Unknown"
                )
                name = self.translate(raw_name)

                coin_price = 0
                if (
                    pid in data
                    and "smilecoin" in data[pid]
                    and "total_amount" in data[pid]["smilecoin"]
                ):
                    try:
                        coin_price = float(data[pid]["smilecoin"]["total_amount"])
                    except Exception:
                        coin_price = 0

                if pid in custom_prices:
                    mmk_price = custom_prices[pid].get(
                        "price", int(coin_price * self.mmk_rate)
                    )
                    display_name = custom_prices[pid].get("name", name)
                else:
                    mmk_price = int(coin_price * self.mmk_rate)
                    display_name = name

                pkgs.append(
                    {
                        "pid": pid,
                        "name": display_name,
                        "coin_value": coin_price,
                        "mmk_price": int(mmk_price),
                        "raw_name": name,
                    }
                )
            self.market_data = pkgs
            self.last_market_update = datetime.now()
            return pkgs
        except Exception as e:
            log.error("[SmileOne] Market Error: %s", e)
            return None

    def topup_diamonds_sync(self, uid, zone_id, product, quantity=1):
        """Synchronous top-up (for web thread)."""
        auth, status, profile = self.check_auth()
        if not auth:
            return False, "❌ Authentication failed. Cookie စစ်ပါ။"
        try:
            with open(COOKIE_FILE, "r") as f:
                cookies = json.load(f).get("parsed_dict", {})

            res_init = self.scraper.get(
                f"{self.base_url}/br/merchant/mobilelegends", cookies=cookies
            )
            soup = BeautifulSoup(res_init.text, "html.parser")
            csrf_input = soup.find("input", {"name": "_csrf"})
            if not csrf_input:
                return False, "❌ CSRF token မရပါ။ Cookie expire ဖြစ်နေနိုင်သည်။"
            csrf_token = csrf_input["value"]

            query_payload = {
                "user_id": uid,
                "zone_id": zone_id,
                "pid": product["pid"],
                "checkrole": "",
                "pay_methond": "smilecoin",
                "channel_method": "smilecoin",
            }
            res_query = self.scraper.post(
                f"{self.base_url}/merchant/mobilelegends/query",
                data=query_payload,
                cookies=cookies,
                headers=self.headers,
            )
            query_data = res_query.json()
            if query_data.get("code") != 200:
                return False, f"❌ User check failed: {query_data.get('info', 'Unknown')}"

            username = query_data.get("username", "Unknown")
            flowid = query_data.get("flowid")

            success_count = 0
            import time

            for i in range(quantity):
                pay_payload = {
                    "_csrf": csrf_token,
                    "user_id": uid,
                    "zone_id": zone_id,
                    "pay_methond": "smilecoin",
                    "product_id": product["pid"],
                    "channel_method": "smilecoin",
                    "flowid": flowid,
                    "email": "",
                    "coupon_id": "",
                }
                res_pay = self.scraper.post(
                    f"{self.base_url}/merchant/mobilelegends/pay",
                    data=pay_payload,
                    cookies=cookies,
                    headers=self.headers,
                    allow_redirects=False,
                )
                redirect_url = res_pay.headers.get("Location") or res_pay.headers.get(
                    "x-redirect"
                )
                if redirect_url:
                    if not redirect_url.startswith("http"):
                        redirect_url = f"{self.base_url}{redirect_url}"
                    res_final = self.scraper.get(redirect_url, cookies=cookies)
                    if "sucesso" in res_final.text.lower():
                        success_count += 1
                if i < quantity - 1:
                    time.sleep(1.5)

            if success_count > 0:
                return (
                    True,
                    f"✅ {success_count}/{quantity} အောင်မြင်ပါသည်!\n👤 Username: {username}",
                )
            return False, "❌ Topup မအောင်မြင်ပါ။ Balance သို့မဟုတ် Cookie စစ်ပါ။"
        except Exception as e:
            return False, f"❌ Error: {str(e)}"


smile = SmileOneBot() if SMILE_AVAILABLE else None

# ---------------- TELEGRAM NOTIFY ----------------
def notify_telegram_admins(text: str) -> int:
    """Send plain text to all admins via Bot API. Returns success count."""
    if not BOT_TOKEN or not requests:
        log.warning("BOT_TOKEN missing or requests not installed – skip notify")
        return 0
    sent = 0
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for admin_id in list(ADMIN_IDS):
        try:
            r = requests.post(
                url,
                json={
                    "chat_id": admin_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if r.ok:
                sent += 1
            else:
                log.warning("Telegram notify failed %s: %s", admin_id, r.text[:200])
        except Exception:
            log.exception("notify admin %s", admin_id)
    return sent


# ---------------- AUTH HELPERS ----------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "login_required"}), 401
            return redirect(url_for("login_page"))
        uid = int(session["user_id"])
        if is_banned(uid):
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "banned"}), 403
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)

    return decorated


def current_user_id() -> Optional[int]:
    uid = session.get("user_id")
    return int(uid) if uid else None


# ---------------- PAGES ----------------
@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("shop_page"))
    return redirect(url_for("login_page"))


@app.route("/login")
def login_page():
    if session.get("user_id"):
        return redirect(url_for("shop_page"))
    return render_template(
        "login.html",
        admin_username=ADMIN_USERNAME,
        min_recharge=MIN_RECHARGE,
    )


@app.route("/shop")
@login_required
def shop_page():
    uid = current_user_id()
    user = get_user(uid)
    return render_template(
        "shop.html",
        user_id=uid,
        balance=balance(uid),
        first_name=(user["first_name"] if user else "") or "User",
        username=(user["username"] if user else "") or "",
        admin_username=ADMIN_USERNAME,
        kpay_number=KPAY_NUMBER,
        kpay_name=KPAY_NAME,
        wave_number=WAVE_NUMBER,
        wave_name=WAVE_NAME,
        min_recharge=MIN_RECHARGE,
        maintenance=maintenance_mode(),
    )


# ---------------- API ----------------
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    try:
        user_id = int(str(data.get("user_id", "")).strip())
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Telegram User ID ဂဏန်းဖြစ်ရမည်။"}), 400
    pin = str(data.get("pin", "")).strip()
    if len(pin) < 4:
        return jsonify({"ok": False, "error": "PIN အနည်းဆုံး ၄ လုံး လိုအပ်သည်။"}), 400

    if maintenance_mode() and user_id not in ADMIN_IDS:
        return jsonify({"ok": False, "error": "ဆိုင် Maintenance mode ဖြစ်နေပါသည်။"}), 503

    # User must already exist in bot DB (started the Telegram bot at least once)
    row = get_user(user_id)
    if not row:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": (
                        "User မတွေ့ပါ။ အရင် Telegram Bot မှာ /start နှိပ်ပြီး "
                        "မှ ဒီမှာ PIN သတ်မှတ်/login လုပ်ပါ။"
                    ),
                }
            ),
            404,
        )
    if row["is_banned"]:
        return jsonify({"ok": False, "error": "အကောင့်ပိတ်ထားပါသည်။"}), 403

    if not verify_web_pin(user_id, pin):
        return jsonify({"ok": False, "error": "PIN မမှန်ပါ။"}), 401

    session.permanent = True
    session["user_id"] = user_id
    return jsonify(
        {
            "ok": True,
            "user_id": user_id,
            "balance": balance(user_id),
            "first_name": row["first_name"] or "",
        }
    )


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
@login_required
def api_me():
    uid = current_user_id()
    user = get_user(uid)
    return jsonify(
        {
            "ok": True,
            "user_id": uid,
            "balance": balance(uid),
            "first_name": (user["first_name"] if user else "") or "",
            "username": (user["username"] if user else "") or "",
            "referral_count": int(user["referral_count"]) if user else 0,
        }
    )


@app.route("/api/set_pin", methods=["POST"])
@login_required
def api_set_pin():
    data = request.get_json(silent=True) or {}
    pin = str(data.get("pin", "")).strip()
    if len(pin) < 4:
        return jsonify({"ok": False, "error": "PIN အနည်းဆုံး ၄ လုံး"}), 400
    if set_web_pin(current_user_id(), pin):
        return jsonify({"ok": True, "message": "PIN သိမ်းပြီးပါပြီ။"})
    return jsonify({"ok": False, "error": "မအောင်မြင်ပါ"}), 500


@app.route("/api/packages")
@login_required
def api_packages():
    if smile is None:
        return jsonify({"ok": False, "error": "Smile.one မရနိုင်ပါ (cloudscraper)"}), 503
    force = request.args.get("refresh") == "1"
    pkgs = smile.get_market(force_refresh=force)
    if not pkgs:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Market data မရပါ။ Admin မှ Smile Cookie စစ်ပါ။",
                }
            ),
            503,
        )
    return jsonify({"ok": True, "packages": pkgs, "count": len(pkgs)})


@app.route("/api/check_id", methods=["POST"])
@login_required
def api_check_id():
    data = request.get_json(silent=True) or {}
    uid_game = str(data.get("game_uid", "")).strip()
    zone = str(data.get("zone_id", "")).strip()
    pid = data.get("pid")
    if not uid_game.isdigit() or not zone.isdigit():
        return jsonify({"ok": False, "error": "UID / Zone ဂဏန်းဖြစ်ရမည်။"}), 400
    if smile is None:
        return jsonify({"ok": False, "error": "Smile.one မရနိုင်ပါ"}), 503
    ok, info = smile.id_check_full(uid_game, zone, pid)
    if not ok:
        return jsonify({"ok": False, "error": str(info)}), 400
    game_key = f"{uid_game}|{zone}"
    wp = count_wp_bought_for_game(game_key)
    return jsonify(
        {
            "ok": True,
            "username": info.get("username", "Unknown"),
            "region": info.get("region", "Myanmar / Global"),
            "wp_bought": wp,
            "wp_left": max(0, 10 - wp),
        }
    )


@app.route("/api/buy", methods=["POST"])
@login_required
def api_buy():
    """Buy MLBB package with wallet coins → Smile auto top-up."""
    uid = current_user_id()
    if maintenance_mode() and uid not in ADMIN_IDS:
        return jsonify({"ok": False, "error": "Maintenance mode"}), 503

    data = request.get_json(silent=True) or {}
    try:
        idx = int(data.get("package_index"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "package_index မမှန်ပါ"}), 400
    uid_game = str(data.get("game_uid", "")).strip()
    zone = str(data.get("zone_id", "")).strip()
    if not uid_game.isdigit() or not zone.isdigit():
        return jsonify({"ok": False, "error": "UID / Zone ဂဏန်းဖြစ်ရမည်။"}), 400

    if smile is None:
        return jsonify({"ok": False, "error": "Smile.one မရနိုင်ပါ"}), 503

    pkgs = smile.get_market()
    if not pkgs or idx < 0 or idx >= len(pkgs):
        return jsonify({"ok": False, "error": "Package မရှိတော့ပါ။ Refresh လုပ်ပါ။"}), 400
    product = pkgs[idx]
    price = int(product["mmk_price"])
    user_bal = balance(uid)
    if user_bal < price:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "insufficient_balance",
                    "need": price - user_bal,
                    "price": price,
                    "balance": user_bal,
                    "message": f"လက်ကျန် မလုံလောက်ပါ။ လိုအပ်: {price:,} | ရှိ: {user_bal:,}",
                }
            ),
            400,
        )

    game_key = f"{uid_game}|{zone}"
    is_wp = bool(
        re.search(
            r"weekly|passe semanal|weeklypass",
            (product.get("name") or ""),
            re.I,
        )
    )
    if is_wp:
        wp_bought = count_wp_bought_for_game(game_key)
        if wp_bought >= 10:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": f"Weekly Pass အများဆုံး 10 ခု ထည့်ပြီးပါပြီ (လက်ရှိ {wp_bought})",
                    }
                ),
                400,
            )

    # ID check
    ok, info = smile.id_check_full(uid_game, zone, product.get("pid"))
    if not ok:
        return jsonify({"ok": False, "error": f"ID မမှန်: {info}"}), 400

    # Deduct coins first
    if not change_balance(uid, -price):
        return jsonify({"ok": False, "error": "Balance ဖြတ်မရပါ"}), 500

    success, msg = smile.topup_diamonds_sync(uid_game, zone, product, 1)
    if success:
        try:
            oid = create_order(
                uid,
                "mlbb",
                product["name"],
                price,
                "smile_auto_web",
                game_key,
                1,
            )
            with db() as conn:
                conn.execute(
                    "UPDATE orders SET status='completed', completed_at=? WHERE id=?",
                    (now_text(), oid),
                )
        except Exception:
            log.exception("web order log")
            oid = None
        new_bal = balance(uid)
        notify_telegram_admins(
            f"🌐 <b>Web Auto Top-up OK</b>\n"
            f"👤 User: <code>{uid}</code>\n"
            f"📦 {esc(product['name'])}\n"
            f"🎮 {esc(uid_game)} | {esc(zone)}\n"
            f"💰 {price:,} Coins\n"
            f"#{oid or '-'}"
        )
        return jsonify(
            {
                "ok": True,
                "message": msg,
                "balance": new_bal,
                "order_id": oid,
                "username": info.get("username") if isinstance(info, dict) else None,
            }
        )
    # Refund
    change_balance(uid, price)
    return jsonify({"ok": False, "error": msg, "balance": balance(uid)}), 502


@app.route("/api/recharge", methods=["POST"])
@login_required
def api_recharge():
    """Create pending recharge; notify admin on Telegram bot."""
    uid = current_user_id()
    data = request.get_json(silent=True) or {}
    try:
        amount = int(str(data.get("amount", "0")).replace(",", ""))
    except ValueError:
        return jsonify({"ok": False, "error": "Amount ဂဏန်းဖြစ်ရမည်"}), 400
    method = str(data.get("method", "")).lower()
    last5 = str(data.get("last5", "")).strip()
    note = str(data.get("note", "")).strip()[:200]

    if method not in ("kpay", "wave"):
        return jsonify({"ok": False, "error": "method = kpay | wave"}), 400
    if amount < MIN_RECHARGE:
        return (
            jsonify({"ok": False, "error": f"Minimum {MIN_RECHARGE:,} MMK"}),
            400,
        )
    if not re.fullmatch(r"\d{5}", last5):
        return jsonify({"ok": False, "error": "Last 5 digits မမှန်ပါ"}), 400

    rid = create_recharge(uid, amount, method, last5, note or "web")
    pay_name = KPAY_NAME if method == "kpay" else WAVE_NAME
    pay_num = KPAY_NUMBER if method == "kpay" else WAVE_NUMBER

    notify_text = (
        f"🌐 <b>Web Recharge #{rid}</b>\n\n"
        f"👤 User: <code>{uid}</code>\n"
        f"💰 Amount: <code>{amount:,} MMK</code>\n"
        f"💳 Method: <b>{method.upper()}</b>\n"
        f"🔢 Last 5: <code>{last5}</code>\n"
        f"📝 Note: {esc(note) or '—'}\n"
        f"📱 Account: {esc(pay_name)} / <code>{esc(pay_num)}</code>\n\n"
        f"Bot မှာ /pending သို့မဟုတ် Admin Panel မှ Approve လုပ်ပါ။"
    )
    sent = notify_telegram_admins(notify_text)

    return jsonify(
        {
            "ok": True,
            "recharge_id": rid,
            "amount": amount,
            "method": method,
            "admin_notified": sent > 0,
            "message": (
                f"Recharge #{rid} တင်ပြီးပါပြီ။ Admin စစ်ဆေးပြီးပါက "
                f"+{amount:,} Coins ဝင်ပါမည်။"
            ),
        }
    )


@app.route("/api/history")
@login_required
def api_history():
    uid = current_user_id()
    orders = [
        {
            "id": r["id"],
            "item_name": r["item_name"],
            "amount": r["amount"],
            "status": r["status"],
            "game_id": r["game_id"],
            "payment_method": r["payment_method"],
            "created_at": r["created_at"],
        }
        for r in user_orders(uid, 30)
    ]
    recharges = [
        {
            "id": r["id"],
            "amount": r["amount"],
            "status": r["status"],
            "payment_method": r["payment_method"],
            "last_5_digits": r["last_5_digits"],
            "created_at": r["created_at"],
        }
        for r in user_recharges(uid, 30)
    ]
    return jsonify({"ok": True, "orders": orders, "recharges": recharges})


@app.route("/api/payment_info")
@login_required
def api_payment_info():
    return jsonify(
        {
            "ok": True,
            "min_recharge": MIN_RECHARGE,
            "kpay": {"name": KPAY_NAME, "number": KPAY_NUMBER},
            "wave": {"name": WAVE_NAME, "number": WAVE_NUMBER},
            "admin_username": ADMIN_USERNAME,
        }
    )


# ---------------- BOT COMMAND HELPER NOTE ----------------
# Add to bot.py (optional): /setwebpin PIN  so users can set web PIN from Telegram.


def main():
    init_web_db()
    log.info(
        "Web Shop starting on %s:%s | DB=%s | Smile=%s | BotToken=%s",
        HOST,
        PORT,
        DB_PATH,
        SMILE_AVAILABLE and smile is not None,
        bool(BOT_TOKEN),
    )
    app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True)


if __name__ == "__main__":
    main()
