# Ki Ki Shop – Telegram Bot + HTML Web Shop

`bot.py` နဲ့ `web_app.py` က **တူညီတဲ့ SQLite DB** (`kiki_shop.db`) ကို သုံးပါတယ်။  
Smile.one MLBB packages၊ wallet coins၊ recharge → admin Telegram notify အားလုံး ချိတ်ဆက်ထားပါတယ်။

## Features (Web)

| Feature | အသေးစိတ် |
|--------|-----------|
| Login | Telegram User ID + Web PIN |
| Packages | Smile.one live market (admin cookie) |
| Buy Diamond | **Coin ရှိမှ** ဝယ်နိုင် · auto top-up |
| ငွေဖြည့် | K-Pay / Wave · last 5 digits · **Admin bot ထံ အကြောင်းကြား** |
| History | Orders + Recharges |

## Setup

```bash
cd /path/to/this/folder
pip install -r requirements.txt

# Env (recommended – token ကို code ထဲ hard-code မလုပ်ပါနှင့်)
export BOT_TOKEN="your_bot_token"
export OWNER_ID="7308292609"
export LEO_DB_PATH="kiki_shop.db"   # bot နဲ့ web တူညီရမည်
export COOKIE_FILE="cookies.json"   # Smile cookie (bot /cookie နဲ့ သိမ်း)
export WEB_SECRET_KEY="random-long-string"
export WEB_PORT="8080"
```

### 1) Telegram Bot

```bash
python bot.py
```

- Smile cookie: bot ထဲ `/cookie ...` သို့မဟုတ် Admin Panel → Set Smile Cookie  
- User များ `/start` လုပ်ရမည်  
- Web PIN: `/setwebpin 1234`

### 2) Web Shop

```bash
python web_app.py
# → http://0.0.0.0:8080
```

## User flow

1. Telegram bot မှာ `/start`
2. `/setwebpin 1234` (သို့မဟုတ် web မှာ ပထမအကြိမ် PIN သတ်မှတ်)
3. Browser → Login (User ID + PIN)
4. Shop → package ရွေး → UID + Zone → Coin ဖြင့် ဝယ်
5. Coin မလောက်ရင် **ငွေဖြည့်** → Admin bot ထံ pending recharge ရောက်မည် → Approve

## Files

```
bot.py              # Telegram bot (မူရင်း + /setwebpin)
web_app.py          # Flask web API + pages
templates/          # login.html, shop.html
static/             # style.css, app.js
requirements.txt
kiki_shop.db        # runtime (shared)
cookies.json        # Smile session (runtime)
smile_prices.json   # optional price overrides
```

## Security notes

- `BOT_TOKEN` / API keys ကို source ထဲ မထားဘဲ environment variable သုံးပါ။
- Web ကို HTTPS (reverse proxy) နောက်မှာ run ပါ။
- `WEB_SECRET_KEY` ကို production မှာ ပြောင်းပါ။

## Admin approve (web recharge)

Web ကနေ တင်တဲ့ recharge က `recharges` table ထဲ `pending` ဖြစ်ပြီး bot Admin Panel / `/pending` မှာ ပေါ်ပါတယ်။  
Approve လုပ်ရင် user wallet သို့ coins ဝင်ပါမည် (bot logic အတိုင်း)။
