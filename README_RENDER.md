# Ki Ki Shop – Deploy on Render

## Files needed

```
bot.py
web_app.py
requirements.txt
runtime.txt
Procfile
render.yaml
templates/
static/
```

## Option A – Dashboard (manual, recommended)

### 1) Upload code
- GitHub repo တစ်ခုဖန်တီးပြီး အထက်ပါ ဖိုင်အားလုံး push
- သို့မဟုတ် Render → **New** → **Web Service** → upload / connect repo

### 2) Web Service (HTML shop)
| Setting | Value |
|---------|--------|
| Name | `kiki-shop-web` |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python web_app.py` |
| Instance | Free |

**Environment Variables:**
```
BOT_TOKEN=your_telegram_bot_token
OWNER_ID=7308292609
LEO_DB_PATH=/var/data/kiki_shop.db
COOKIE_FILE=/var/data/cookies.json
SMILE_PRICES_FILE=/var/data/smile_prices.json
WEB_SECRET_KEY=any-long-random-string
KPAY_NUMBER=09687512062
KPAY_NAME=Ma Chit Su
WAVE_NUMBER=09687512062
WAVE_NAME=Ye Htet Aung
ADMIN_USERNAME=kiki20251
```

**Disk (Persistent):** Mount path `/var/data`, size 1 GB  
(DB + Smile cookie မပျောက်အောင်)

### 3) Background Worker (Telegram bot)
- **New** → **Background Worker**
- Same repo
- Build: `pip install -r requirements.txt`
- Start: `python bot.py`
- **Same env vars** + **same disk** `/var/data`

### 4) Open
Web URL: `https://kiki-shop-web.onrender.com`  
Bot: Telegram မှာ `/start`

---

## Option B – Blueprint (`render.yaml`)
1. Repo ထဲ `render.yaml` ပါအောင် push
2. Render → **New** → **Blueprint**
3. Repo ရွေး → env values ဖြည့် → Apply

---

## Important notes

1. **Free tier** – Web service အိပ်သွားနိုင် (15 min idle)။ Bot worker က အမြဲ run နေရမယ်။
2. **Disk** – Web နဲ့ Worker **တူညီတဲ့ disk** သုံးမှ wallet/order data တူမယ်။
3. **BOT_TOKEN** – bot.py ထဲ hard-code ရှိရင်တောင် Render မှာ env ထည့်ထားပါ။
4. **Smile cookie** – Bot online ဖြစ်ပြီး `/cookie ...` နဲ့ သိမ်းပါ (disk ပေါ်မှာ ရှိရမယ်)။
5. Local VPS မဟုတ်ဘဲ Render သုံးရင် `python bot.py` ကို laptop မှာ မလိုတော့ပါ။

## After deploy
```
Telegram → /start
/setwebpin 1234
Browser → https://YOUR-APP.onrender.com/login
Admin → /admin  or 🛠️ ADMIN PANEL
```
