#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Elite Bot v5.0 — Quotex M1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ صفقة واحدة فقط — الأقوى
✅ Groq AI (سريع جداً) + Claude + محلي
✅ أقوى استراتيجية M1 Scalping
✅ إشارة قبل نهاية الدقيقة بـ 23 ثانية
✅ واجهة عربية سليمة
"""

import asyncio, aiohttp, json, math, os, logging, time, uuid, contextlib, sqlite3, re
from datetime import datetime, timedelta
from pathlib import Path
from html import unescape
from aiohttp import web
from zoneinfo import ZoneInfo
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

def _load_dotenv_file():
    """Load simple KEY=VALUE pairs from .env if present."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    try:
        preexisting = set(os.environ.keys())
        file_vars = {}
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                # Keep last value in .env when duplicated keys exist.
                file_vars[key] = value
        for key, value in file_vars.items():
            # Respect externally provided environment variables.
            if key not in preexisting:
                os.environ[key] = value
    except Exception:
        pass

_load_dotenv_file()

TR_TZ = ZoneInfo("Europe/Istanbul")
TRADING_START_HOUR = 11  # 11:00 Turkey time
TRADING_END_HOUR = 22    # 22:00 Turkey time

def turkey_now():
    return datetime.now(TR_TZ)

def is_trading_window_open():
    now_tr = turkey_now()
    # Saturday/Sunday full holiday.
    if now_tr.weekday() in (5, 6):
        return False
    hour = now_tr.hour
    return TRADING_START_HOUR <= hour < TRADING_END_HOUR

def market_closed_message():
    now_tr = turkey_now()
    if now_tr.weekday() == 5:
        return "⛔ يوم السبت السوق مقفل"
    if now_tr.weekday() == 6:
        return "⛔ يوم الأحد السوق مقفل"
    return "⛔ السوق مقفل حاليا (وقت التشغيل من 11:00 إلى 22:00 بتوقيت تركيا)"

# ══════════════════════════════════════════
#  ⚙️  الإعدادات
# ══════════════════════════════════════════
CONFIG = {
    # تيليغرام
    "tg_token"  : os.environ.get("TG_BOT_TOKEN", ""),
    "tg_channel": os.environ.get("TG_CHANNEL_ID", ""),
    "access_tg_token": os.environ.get("ACCESS_REQUEST_TG_BOT_TOKEN", ""),
    "access_tg_channel": os.environ.get("ACCESS_REQUEST_TG_CHANNEL_ID", ""),
    "signal_channel_url": os.environ.get("TG_CHANNEL_URL", "").strip(),

    # OANDA
    "oanda_key" : os.environ.get("OANDA_API_KEY", ""),
    "oanda_url" : os.environ.get("OANDA_URL", "https://api-fxpractice.oanda.com/v3"),

    # AI Keys (do not hard-code secrets here)
    "groq_key"  : os.environ.get("GROQ_API_KEY", ""),
    "claude_key": os.environ.get("ANTHROPIC_API_KEY", ""),

    # AI Validator
    "ai_provider"      : os.environ.get("AI_PROVIDER", "auto"),  # auto | groq | claude
    "ai_confirmation"  : os.environ.get("AI_CONFIRMATION", "true").lower() not in ("0", "false", "no", "off"),
    "ai_review_enabled": os.environ.get("AI_REVIEW_ENABLED", "true").lower() not in ("0", "false", "no", "off"),
    "minimum_ai_confidence": int(os.environ.get("MINIMUM_AI_CONFIDENCE", "75")),
    "ai_failure_mode": os.environ.get("AI_FAILURE_MODE", "reject").strip().lower(),  # reject | strong_only
    "show_ai_reason": os.environ.get("SHOW_AI_REASON", "false").lower() in ("1", "true", "yes", "on"),
    "news_filter_before_min": int(os.environ.get("NEWS_FILTER_BEFORE_MIN", "30")),
    "news_filter_after_min": int(os.environ.get("NEWS_FILTER_AFTER_MIN", "15")),

    # إعدادات
    "admin_pass"    : os.environ.get("ADMIN_PASSWORD", "admin123"),
    "port"          : 8080,
    "min_confidence": 72,
    "auto_telegram" : False,
    "bot_running"   : False,
    "strategy"      : "smart_auto",

    # الأزواج النشطة
    "active_pairs": [
        "EUR_JPY","EUR_AUD","EUR_GBP","EUR_USD","EUR_CHF","EUR_CAD","EUR_NZD",
        "GBP_USD","USD_JPY","USD_CHF","USD_CAD","AUD_USD","NZD_USD",
        "AUD_JPY","GBP_JPY","CAD_JPY","NZD_JPY","CHF_JPY","AUD_CHF","AUD_NZD"
    ],
}

PAIR_NAMES = {
    "EUR_JPY":"EUR/JPY","AUD_JPY":"AUD/JPY","GBP_USD":"GBP/USD",
    "USD_JPY":"USD/JPY","EUR_AUD":"EUR/AUD","AUD_CHF":"AUD/CHF",
    "EUR_GBP":"EUR/GBP","EUR_USD":"EUR/USD","GBP_JPY":"GBP/JPY",
    "USD_CHF":"USD/CHF","USD_CAD":"USD/CAD","AUD_USD":"AUD/USD",
    "NZD_USD":"NZD/USD","CAD_JPY":"CAD/JPY","NZD_JPY":"NZD/JPY",
}
ALL_PAIRS = {
    "EUR": ["EUR_JPY","EUR_AUD","EUR_GBP","EUR_USD","EUR_CHF","EUR_CAD","EUR_NZD"],
    "USD": ["GBP_USD","USD_JPY","USD_CHF","USD_CAD","AUD_USD","NZD_USD"],
    "JPY": ["AUD_JPY","GBP_JPY","CAD_JPY","NZD_JPY","CHF_JPY"],
    "AUD": ["AUD_CHF","AUD_NZD"],
}

CURRENCY_FLAGS = {
    "EUR": "🇪🇺", "USD": "🇺🇸", "GBP": "🇬🇧", "JPY": "🇯🇵",
    "AUD": "🇦🇺", "CHF": "🇨🇭", "CAD": "🇨🇦", "NZD": "🇳🇿",
    "BRL": "🇧🇷", "BDT": "🇧🇩", "EGP": "🇪🇬",
}

STRATEGY_META = {
    "smart_auto": {
        "icon": "🤖",
        "ar": "الوضع الذكي",
        "en": "Smart Auto",
        "desc_ar": "يفحص جميع الاستراتيجيات ويختار الأقوى تلقائياً.",
        "desc_en": "Runs all strategies and automatically picks the strongest setup.",
        "indicators": "RSI • MACD • EMA • BB • ADX",
    },
    "confluence": {
        "icon": "🧠",
        "ar": "التوافق الذكي",
        "en": "Confluence",
        "desc_ar": "توافق شامل بين الاتجاه والمومنتوم والشموع و Price Action.",
        "desc_en": "Full confluence between trend, momentum, candles, and price action.",
        "indicators": "EMA • MACD • ADX • PA",
    },
    "rsi_reversal": {
        "icon": "📉",
        "ar": "انعكاس RSI",
        "en": "RSI Reversal",
        "desc_ar": "يركز على التشبع الشرائي/البيعي مع شمعة انعكاسية قوية.",
        "desc_en": "Focuses on overbought/oversold zones with a strong reversal candle.",
        "indicators": "RSI • Stoch • BB",
    },
    "macd_trend": {
        "icon": "📈",
        "ar": "اتجاه MACD",
        "en": "MACD Trend",
        "desc_ar": "استراتيجية تتبع اتجاه مبنية على MACD و EMA وقوة الاتجاه ADX.",
        "desc_en": "Trend-following setup based on MACD, EMA, and ADX trend strength.",
        "indicators": "MACD • EMA • ADX",
    },
    "bollinger_reversal": {
        "icon": "🎯",
        "ar": "ارتداد بولنجر",
        "en": "Bollinger Bounce",
        "desc_ar": "يعتمد على ارتداد السعر من حدود بولنجر مع تأكيد RSI والشموع.",
        "desc_en": "Uses price reaction at Bollinger edges with RSI and candle confirmation.",
        "indicators": "BB • RSI • PA",
    },
    "stochastic_reversal": {
        "icon": "⚡",
        "ar": "انعكاس ستوكاستك",
        "en": "Stochastic Reversal",
        "desc_ar": "يلتقط الانعكاس السريع من تشبع Stochastic مع تأكيد RSI.",
        "desc_en": "Captures fast reversals from Stochastic extremes with RSI confirmation.",
        "indicators": "Stoch • RSI • PA",
    },
    "ema_cross": {
        "icon": "🔀",
        "ar": "تقاطع EMA",
        "en": "EMA Cross",
        "desc_ar": "يعتمد على تقاطع EMA السريع والبطيء مع زخم السعر.",
        "desc_en": "Uses fast/slow EMA crossover with price momentum confirmation.",
        "indicators": "EMA 5/20 • MACD • Momentum",
    },
    "adx_breakout": {
        "icon": "🚀",
        "ar": "اختراق ADX",
        "en": "ADX Breakout",
        "desc_ar": "يركز على اختراقات قوية عندما يؤكد ADX قوة الاتجاه.",
        "desc_en": "Focuses on breakouts confirmed by ADX trend strength.",
        "indicators": "ADX • DI • ATR • Breakout",
    },
}

HISTORY      = []   # آخر 30 إشارة
STATS        = {"total":0,"sent_tg":0,"cycles":0,"ai":"—","last":"—"}
bot_task     = None
cd_val       = -1
UPLOAD_DIR   = Path(__file__).parent / "uploads"
DB_PATH      = Path(__file__).parent / "bot_data.db"
JOIN_REQUESTS = []
APPROVED_USERS = []
LOGIN_REQUESTS = []
ACTIVE_USERS = []
TG_UPDATE_OFFSET = 0
tg_updates_task = None
# تتبع آخر إشارة لمنع التكرار
LAST_SIGNAL  = {"pair": None, "direction": None, "count": 0}
LAST_SIGNAL_MINUTE = None
LAST_SIGNAL_ENTRY  = None
LAST_SIGNAL_TS     = 0.0

ECONOMIC_CALENDAR_PROVIDER = os.environ.get("ECONOMIC_CALENDAR_PROVIDER", "auto").strip().lower()
ECONOMIC_CALENDAR_URL = os.environ.get("ECONOMIC_CALENDAR_URL", "").strip()
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
RAPIDAPI_HOST = os.environ.get("RAPIDAPI_HOST", "economic-calendar-api.p.rapidapi.com").strip()
RAPIDAPI_PATH = os.environ.get("RAPIDAPI_PATH", "/calendar").strip() or "/calendar"
if not RAPIDAPI_PATH.startswith("/"):
    RAPIDAPI_PATH = "/" + RAPIDAPI_PATH
RAPIDAPI_CALENDAR_URL = f"https://{RAPIDAPI_HOST}{RAPIDAPI_PATH}"
TRADING_ECONOMICS_KEY = os.environ.get("TRADING_ECONOMICS_KEY", "").strip()
TRADING_ECONOMICS_URL = "https://api.tradingeconomics.com/calendar"
INVESTING_CALENDAR_URL = "https://www.investing.com/economic-calendar/"
INVESTING_SCRAPER_PROXY_URL = os.environ.get("INVESTING_SCRAPER_PROXY_URL", "").strip()
INVESTING_WIDGET_SCRAPER_URL = "https://sslecal2.investing.com"
INVESTING_WIDGET_SCRAPER_PARAMS = {
    "columns": "exc_flags,exc_currency,exc_importance,exc_actual,exc_forecast,exc_previous",
    "features": "datepicker,timezone",
    "countries": "25,32,6,37,72,22,17,39,14,10,35,43,56,36,110,11,26,12,4,5",
    "calType": "week",
    "timeZone": "71",
    "lang": "1",
}
CALENDAR_TIMEZONE = os.environ.get("ECONOMIC_CALENDAR_TIMEZONE", "GMT+3").strip() or "GMT+3"
CALENDAR_API_FEEDS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]
CALENDAR_MAJOR_ONLY = os.environ.get("CALENDAR_MAJOR_ONLY", "true").strip().lower() not in {"0", "false", "no", "off"}
MAJOR_EVENT_KEYWORDS = [
    "interest rate decision",
    "interest rate",
    "rate decision",
    "central bank statement",
    "central bank",
    "press conference",
    "fomc",
    "central bank press conference",
    "cpi",
    "core cpi",
    "pce",
    "core pce",
    "non farm payrolls",
    "nonfarm payrolls",
    "unemployment rate",
    "average hourly earnings",
    "gdp",
    "manufacturing pmi",
    "services pmi",
    "ism manufacturing pmi",
    "ism services pmi",
    # Arabic aliases for internally translated titles
    "قرار الفائدة",
    "بيان البنك المركزي",
    "المؤتمر الصحفي للبنك المركزي",
    "مؤشر أسعار المستهلك",
    "الوظائف غير الزراعية",
    "معدل البطالة",
    "متوسط الأجور",
    "الناتج المحلي الإجمالي",
    "مؤشر مديري المشتريات",
]
TRADING_ECONOMICS_COUNTRY_CURRENCY = {
    "United States": "USD",
    "Euro Area": "EUR",
    "Germany": "EUR",
    "France": "EUR",
    "Italy": "EUR",
    "Spain": "EUR",
    "United Kingdom": "GBP",
    "Japan": "JPY",
    "Canada": "CAD",
    "Australia": "AUD",
    "New Zealand": "NZD",
    "Switzerland": "CHF",
    "China": "CNY",
    "Sweden": "SEK",
    "Mexico": "MXN",
}
CALENDAR_CACHE = {"ts": 0, "items": [], "source": "mock"}

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
L = logging.getLogger("Elite")

def db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db_connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS join_requests (
                id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                email TEXT NOT NULL,
                image_url TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                tg_message_id INTEGER
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS approved_users (
                account_id TEXT PRIMARY KEY,
                join_request_id TEXT,
                email TEXT NOT NULL,
                image_url TEXT NOT NULL,
                approved_at TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS access_requests (
                id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                email TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS active_users (
                account_id TEXT PRIMARY KEY,
                access_request_id TEXT,
                email TEXT NOT NULL,
                activated_at TEXT NOT NULL
            )
        """)

# ══════════════════════════════════════════
#  أدوات مساعدة
# ══════════════════════════════════════════
def is_jpy(ins): return "JPY" in ins
def dp(ins):     return 3 if is_jpy(ins) else 5
def pip(ins):    return 0.01 if is_jpy(ins) else 0.0001
def pname(ins):  return PAIR_NAMES.get(ins, ins.replace("_","/"))
def pair_flags(ins):
    txt = str(ins or "").upper().replace("/", "_")
    txt = re.sub(r"\s*\(OTC\)", "", txt)
    parts = re.findall(r"[A-Z]{3}", txt)
    return " ".join(CURRENCY_FLAGS.get(p, "🏳️") for p in parts[:2])


# ══════════════════════════════════════════
#  المؤشرات الفنية
# ══════════════════════════════════════════
def ema(pr, p):
    if len(pr) < p: return None
    k = 2/(p+1); e = sum(pr[:p])/p
    for x in pr[p:]: e = x*k + e*(1-k)
    return e

def rsi(pr, p=14):
    if len(pr) < p+1: return None
    d = [pr[i+1]-pr[i] for i in range(len(pr)-1)]
    g = sum(max(x,0) for x in d[:p])/p
    l = sum(max(-x,0) for x in d[:p])/p
    for x in d[p:]:
        g=(g*(p-1)+max(x,0))/p; l=(l*(p-1)+max(-x,0))/p
    return 100 if l==0 else 100-(100/(1+g/l))

def macd_full(pr):
    """MACD line + Signal + Histogram"""
    e12,e26 = ema(pr,12),ema(pr,26)
    if not e12 or not e26: return None,None,None
    macd_line = e12-e26
    macd_vals=[]
    for i in range(26,len(pr)+1):
        a=ema(pr[:i],12); b=ema(pr[:i],26)
        if a and b: macd_vals.append(a-b)
    signal = ema(macd_vals,9) if len(macd_vals)>=9 else None
    hist   = (macd_line-signal) if signal else None
    return macd_line, signal, hist

def macd(pr):
    ml,_,_ = macd_full(pr)
    return ml

def bollinger(pr, p=20):
    if len(pr)<p: return None
    s=pr[-p:]; m=sum(s)/p
    std=math.sqrt(sum((x-m)**2 for x in s)/p)
    return {"u":m+2*std,"m":m,"l":m-2*std,"std":std}

def atr(cn, p=14):
    if len(cn)<p+1: return None
    tr=[max(c["h"]-c["l"],abs(c["h"]-cn[i]["c"]),abs(c["l"]-cn[i]["c"]))
        for i,c in enumerate(cn[1:])]
    return sum(tr[-p:])/p

def stoch(cn, p=14):
    if len(cn)<p: return None
    s=cn[-p:]; hh=max(c["h"] for c in s); ll=min(c["l"] for c in s)
    return 50.0 if hh==ll else ((cn[-1]["c"]-ll)/(hh-ll))*100

def cci(cn, p=14):
    if len(cn)<p: return None
    tp=[( c["h"]+c["l"]+c["c"])/3 for c in cn[-p:]]
    m=sum(tp)/p; md=sum(abs(x-m) for x in tp)/p
    return 0 if md==0 else (tp[-1]-m)/(0.015*md)

def momentum(pr, p=10):
    if len(pr)<p+1: return None
    return pr[-1]-pr[-p-1]

def adx_calc(cn, p=14):
    """
    ADX — يقيس قوة الاتجاه (ثانوي)
    ADX < 20  = سوق عرضي هادئ  ⚠️
    ADX 20-25 = بداية اتجاه
    ADX > 25  = اتجاه واضح    ✅
    ADX > 40  = اتجاه قوي جداً ⭐
    """
    if len(cn) < p * 2 + 1: return None, None, None
    try:
        plus_dm_list, minus_dm_list, tr_list = [], [], []
        for i in range(1, len(cn)):
            h,l,c   = cn[i]["h"], cn[i]["l"], cn[i]["c"]
            ph,pl,pc= cn[i-1]["h"], cn[i-1]["l"], cn[i-1]["c"]
            tr      = max(h-l, abs(h-pc), abs(l-pc))
            up_move = h - ph; dn_move = pl - l
            pdm = up_move   if up_move>dn_move and up_move>0   else 0
            mdm = dn_move   if dn_move>up_move and dn_move>0   else 0
            tr_list.append(tr); plus_dm_list.append(pdm); minus_dm_list.append(mdm)
        def ws(data, p):
            s=sum(data[:p]); res=[s]
            for x in data[p:]: s=s-s/p+x; res.append(s)
            return res
        atr_s=ws(tr_list,p); pdm_s=ws(plus_dm_list,p); mdm_s=ws(minus_dm_list,p)
        pdi=[100*pdm_s[i]/atr_s[i] if atr_s[i]>0 else 0 for i in range(len(atr_s))]
        mdi=[100*mdm_s[i]/atr_s[i] if atr_s[i]>0 else 0 for i in range(len(atr_s))]
        dx_list=[]
        for i in range(len(pdi)):
            dn=pdi[i]+mdi[i]; dx=100*abs(pdi[i]-mdi[i])/dn if dn>0 else 0; dx_list.append(dx)
        adx_v=sum(dx_list[:p])/p
        for dx in dx_list[p:]: adx_v=(adx_v*(p-1)+dx)/p
        return round(adx_v,1), round(pdi[-1],1) if pdi else None, round(mdi[-1],1) if mdi else None
    except: return None, None, None

# ══════════════════════════════════════════
#  Price Action — 14 نمط
# ══════════════════════════════════════════
def pa_patterns(cn):
    if len(cn)<5: return []
    L,P,P2,P3 = cn[-1],cn[-2],cn[-3],cn[-4]
    body  = lambda c: abs(c["c"]-c["o"])
    uw    = lambda c: c["h"]-max(c["c"],c["o"])
    dw    = lambda c: min(c["c"],c["o"])-c["l"]
    rng   = lambda c: c["h"]-c["l"]
    bull  = lambda c: c["c"]>c["o"]
    bear  = lambda c: c["c"]<c["o"]
    pa=[]

    # نمط 1: Pin Bar صاعد (ذيل سفلي طويل)
    if dw(L)>body(L)*2.5 and uw(L)<body(L)*0.4:
        pa.append(("📌 بار دبوس صاعد","UP",35))
    # نمط 2: Pin Bar هابط (ذيل علوي طويل)
    if uw(L)>body(L)*2.5 and dw(L)<body(L)*0.4:
        pa.append(("📌 بار دبوس هابط","DOWN",35))
    # نمط 3: ابتلاع صاعد
    if bear(P) and bull(L) and L["o"]<P["c"] and L["c"]>P["o"] and body(L)>body(P)*1.2:
        pa.append(("🕯 ابتلاع صاعد","UP",42))
    # نمط 4: ابتلاع هابط
    if bull(P) and bear(L) and L["o"]>P["c"] and L["c"]<P["o"] and body(L)>body(P)*1.2:
        pa.append(("🕯 ابتلاع هابط","DOWN",42))
    # نمط 5: نجمة الصباح
    if bear(P2) and body(P)<body(P2)*0.3 and bull(L) and L["c"]>(P2["o"]+P2["c"])/2:
        pa.append(("🌅 نجمة الصباح","UP",48))
    # نمط 6: نجمة المساء
    if bull(P2) and body(P)<body(P2)*0.3 and bear(L) and L["c"]<(P2["o"]+P2["c"])/2:
        pa.append(("🌆 نجمة المساء","DOWN",48))
    # نمط 7: ثلاثة جنود صاعدين
    if all(bull(c) and (i==0 or c["c"]>[P2,P,L][i-1]["c"]) for i,c in enumerate([P2,P,L])):
        pa.append(("💪 ثلاثة جنود","UP",40))
    # نمط 8: ثلاثة غربان هابطة
    if all(bear(c) and (i==0 or c["c"]<[P2,P,L][i-1]["c"]) for i,c in enumerate([P2,P,L])):
        pa.append(("🦅 ثلاثة غربان","DOWN",40))
    # نمط 9: Marubozu صاعد (شمعة قوية بلا ظلال)
    if bull(L) and body(L)>rng(L)*0.85:
        pa.append(("⚡ ماروبوزو صاعد","UP",32))
    # نمط 10: Marubozu هابط
    if bear(L) and body(L)>rng(L)*0.85:
        pa.append(("⚡ ماروبوزو هابط","DOWN",32))
    # نمط 11: Doji (تردد)
    if body(L)<rng(L)*0.1 and rng(L)>0:
        pa.append(("⚖️ دوجي تردد","NEUTRAL",5))
    # نمط 12: Inside Bar (انكسار)
    if L["h"]<P["h"] and L["l"]>P["l"]:
        pa.append(("📦 شمعة داخلية","NEUTRAL",8))
    # نمط 13: Tweezer Bottom
    if abs(P["l"]-L["l"])<pip("EUR_USD")*2 and bull(L) and bear(P):
        pa.append(("🔄 قاع مزدوج","UP",30))
    # نمط 14: Tweezer Top
    if abs(P["h"]-L["h"])<pip("EUR_USD")*2 and bear(L) and bull(P):
        pa.append(("🔄 قمة مزدوجة","DOWN",30))

    return pa
# ══════════════════════════════════════════
#  OANDA
# ══════════════════════════════════════════
async def get_candles(session, ins, count=200):
    try:
        async with session.get(
            f"{CONFIG['oanda_url']}/instruments/{ins}/candles",
            params={"count":count,"granularity":"M1","price":"M"},
            headers={"Authorization":f"Bearer {CONFIG['oanda_key']}"},
            timeout=aiohttp.ClientTimeout(total=12)
        ) as r:
            if r.status != 200: return None
            d = await r.json()
            return [{"o":float(c["mid"]["o"]),"h":float(c["mid"]["h"]),
                     "l":float(c["mid"]["l"]),"c":float(c["mid"]["c"])}
                    for c in d["candles"] if c.get("complete")]
    except: return None

def fake_candles(ins):
    """بيانات للتجربة عند انقطاع OANDA"""
    bases = {
        "EUR_JPY":162.5,"AUD_JPY":98.5,"GBP_USD":1.265,
        "USD_JPY":149.5,"EUR_AUD":1.660,"AUD_CHF":0.575,
        "EUR_GBP":0.857,"EUR_USD":1.085,"GBP_JPY":189.0,
        "USD_CHF":0.892,"USD_CAD":1.368,"AUD_USD":0.654,
    }
    import random; b=bases.get(ins,1.0); p_=pip(ins); price=b; cn=[]
    for _ in range(100):
        mv=(random.random()-.48)*p_*15
        o=price; c=o+mv; h=max(o,c)+random.random()*p_*6
        l=min(o,c)-random.random()*p_*6
        cn.append({"o":o,"h":h,"l":l,"c":c}); price=c
    return cn

def market_is_moving(ins, cn):
    """Basic movement guard: block signals on flat/stale market."""
    if not cn or len(cn) < 20:
        return False
    highs = [c["h"] for c in cn[-20:]]
    lows = [c["l"] for c in cn[-20:]]
    closes = [c["c"] for c in cn[-20:]]
    total_range = max(highs) - min(lows)
    net_move = abs(closes[-1] - closes[0])
    p = pip(ins)
    # More permissive gate to increase signal frequency while avoiding dead-flat candles.
    return total_range >= (p * 3) and net_move >= (p * 0.4)

def _day_start(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)

def clean_html_text(value):
    if value is None:
        return ""
    value = str(value)
    value = re.sub(r"<[^>]+>", "", value)
    return unescape(value).strip()

def _importance_from_impact(impact):
    s = clean_html_text(impact).lower()
    if "high" in s or "مرتفع" in s or s in {"3", "***"}:
        return 3
    if "medium" in s or "متوسط" in s or s in {"2", "**"}:
        return 2
    return 1

def currency_to_flag(currency):
    return CURRENCY_FLAGS.get(str(currency).upper(), "🌐")

def _calendar_country_from_currency(currency):
    mapping = {
        "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP",
        "CAD": "CA", "AUD": "AU", "CHF": "CH", "NZD": "NZ",
        "CNY": "CN", "BRL": "BR", "EGP": "EG",
    }
    return mapping.get(currency, currency[:2] if currency else "")

def _parse_calendar_dt(raw):
    s = clean_html_text(raw)
    if not s:
        return "", ""
    s = s.replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
        except Exception:
            continue
    if " " in s:
        p = s.split()
        return p[0], p[1][:5]
    return s[:10], ""

def _calendar_mock_items():
    today = _day_start(datetime.now())
    mk = lambda d, t, cur, country, event, imp, actual, forecast, previous: {
        "date": (today + timedelta(days=d)).strftime("%Y-%m-%d"),
        "time": t,
        "currency": cur,
        "country": country,
        "flag": CURRENCY_FLAGS.get(cur, "🏳️"),
        "event": event,
        "importance": int(imp),
        "actual": actual,
        "forecast": forecast,
        "previous": previous,
    }
    return [
        mk(0, "06:00", "JPY", "JP", "قرار الفائدة الصادر عن البنك المركزي الياباني", 3, "", "0.75%", "0.75%"),
        mk(0, "17:00", "USD", "US", "مؤشر ثقة المستهلك CB (أبريل)", 3, "", "89.4", "91.8"),
        mk(0, "15:00", "EUR", "DE", "مؤشر أسعار المستهلك الألماني (سنوي)", 3, "", "2.1%", "2.0%"),
        mk(1, "11:00", "EUR", "DE", "مؤشر أسعار المستهلك (شهري)", 2, "", "0.1%", "0.2%"),
        mk(1, "16:45", "CAD", "CA", "قرار الفائدة الصادر عن البنك المركزي الكندي", 3, "", "2.25%", "2.25%"),
        mk(2, "09:30", "GBP", "GB", "الناتج المحلي الإجمالي (ربع سنوي)", 3, "", "0.3%", "0.2%"),
        mk(3, "03:30", "AUD", "AU", "مؤشر مديري المشتريات الصناعي", 2, "", "49.8", "49.2"),
        mk(7, "21:00", "USD", "US", "محضر اجتماع الفيدرالي الأمريكي", 2, "", "", ""),
    ]

def map_github_calendar_event(item):
    dt = clean_html_text(item.get("data") or item.get("date") or "")
    date, time_str = _parse_calendar_dt(dt)
    currency = clean_html_text(item.get("economy") or item.get("currency") or "").upper()
    return {
        "date": date,
        "time": time_str or "--:--",
        "currency": currency,
        "country": _calendar_country_from_currency(currency),
        "flag": currency_to_flag(currency),
        "event": clean_html_text(item.get("name") or item.get("event") or ""),
        "importance": _importance_from_impact(item.get("impact") or item.get("importance")),
        "actual": clean_html_text(item.get("actual")),
        "forecast": clean_html_text(item.get("forecast")),
        "previous": clean_html_text(item.get("previous")),
    }

async def fetch_calendar_from_github_api(session):
    if not ECONOMIC_CALENDAR_URL:
        return []
    async with session.get(
        ECONOMIC_CALENDAR_URL,
        headers={"User-Agent": "NEXO-TRADE/1.0", "Accept": "application/json"},
        timeout=aiohttp.ClientTimeout(total=12),
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"GitHub calendar API status {r.status}")
        data = await r.json(content_type=None)
    if isinstance(data, dict):
        raw_items = data.get("data") or data.get("items") or data.get("events") or []
    else:
        raw_items = data if isinstance(data, list) else []
    mapped = []
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        ev = map_github_calendar_event(row)
        if ev["date"] and ev["event"] and ev["currency"]:
            mapped.append(ev)
    return mapped

async def fetch_calendar_from_nfs_api(session):
    items = []
    for url in CALENDAR_API_FEEDS:
        try:
            async with session.get(
                url,
                headers={"User-Agent": "NEXO-TRADE/1.0", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=12),
            ) as r:
                if r.status != 200:
                    continue
                data = await r.json(content_type=None)
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for row in data:
            if not isinstance(row, dict):
                continue
            dt = clean_html_text(row.get("date"))
            date, time_str = _parse_calendar_dt(dt)
            currency = clean_html_text(row.get("country") or row.get("currency")).upper()
            event = clean_html_text(row.get("title") or row.get("event"))
            if not date or not event or not currency:
                continue
            items.append({
                "date": date,
                "time": time_str or "--:--",
                "currency": currency,
                "country": _calendar_country_from_currency(currency),
                "flag": currency_to_flag(currency),
                "event": event,
                "importance": _importance_from_impact(row.get("impact")),
                "actual": clean_html_text(row.get("actual")),
                "forecast": clean_html_text(row.get("forecast")),
                "previous": clean_html_text(row.get("previous")),
            })
    dedup = {}
    for e in items:
        key = f"{e['date']}|{e['time']}|{e['currency']}|{e['event']}"
        dedup[key] = e
    return list(dedup.values())

def _calendar_range_dates(range_key):
    today = _day_start(datetime.now())
    if range_key == "yesterday":
        d = today - timedelta(days=1)
        return d, d
    if range_key == "today":
        return today, today
    if range_key == "tomorrow":
        d = today + timedelta(days=1)
        return d, d
    weekday = today.weekday()
    start_week = today - timedelta(days=weekday)
    if range_key == "week":
        return start_week, start_week + timedelta(days=6)
    if range_key == "next_week":
        n = start_week + timedelta(days=7)
        return n, n + timedelta(days=6)
    return today, today + timedelta(days=7)

def map_rapidapi_calendar_event(item):
    volatility = clean_html_text(item.get("volatility")).upper()
    importance_map = {"NONE": 1, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
    date_utc = clean_html_text(item.get("dateUtc") or item.get("date") or "")
    date, time_str = _parse_calendar_dt(date_utc)
    currency = clean_html_text(item.get("currencyCode") or item.get("currency") or "").upper()
    country = clean_html_text(item.get("countryCode") or item.get("country") or "").upper()
    country = country or _calendar_country_from_currency(currency)
    return {
        "date": date,
        "time": time_str or "--:--",
        "currency": currency,
        "country": country,
        "flag": currency_to_flag(currency),
        "event": clean_html_text(item.get("name") or item.get("event") or ""),
        "importance": importance_map.get(volatility, 1),
        "actual": clean_html_text(item.get("actual")),
        "forecast": clean_html_text(item.get("consensus") or item.get("forecast")),
        "previous": clean_html_text(item.get("previous")),
    }

async def fetch_calendar_from_rapidapi(session, range_key="today", currency="ALL", importance="all"):
    country_map = {
        "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP",
        "CAD": "CA", "AUD": "AU", "CHF": "CH", "NZD": "NZ",
    }
    volatility_map = {"1": "LOW", "2": "MEDIUM", "3": "HIGH"}
    start_dt, end_dt = _calendar_range_dates(range_key)
    params = {
        "limit": "200",
        "timezone": CALENDAR_TIMEZONE,
        "startDate": start_dt.strftime("%Y-%m-%d"),
        "endDate": end_dt.strftime("%Y-%m-%d"),
    }
    if currency != "ALL" and currency in country_map:
        params["countryCode"] = country_map[currency]
    if importance != "all":
        params["volatility"] = volatility_map.get(str(importance), "HIGH")

    async with session.get(
        RAPIDAPI_CALENDAR_URL,
        params=params,
        headers={
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": RAPIDAPI_HOST,
            "Accept": "application/json",
            "User-Agent": "NEXO-TRADE/1.0",
        },
        timeout=aiohttp.ClientTimeout(total=12),
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"RapidAPI calendar status {r.status}")
        data = await r.json(content_type=None)
    if isinstance(data, dict):
        raw_items = data.get("data") or data.get("events") or data.get("items") or []
    else:
        raw_items = data if isinstance(data, list) else []

    mapped = []
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        ev = map_rapidapi_calendar_event(row)
        if ev["date"] and ev["event"] and ev["currency"]:
            mapped.append(ev)
    return mapped

def map_tradingeconomics_calendar_event(item):
    date_raw = clean_html_text(item.get("Date") or item.get("date") or item.get("DateSpan") or "")
    date, time_str = _parse_calendar_dt(date_raw)
    if not date and "T" in date_raw:
        date = date_raw[:10]
    country = clean_html_text(item.get("Country") or item.get("country") or "")
    currency = clean_html_text(item.get("Currency") or item.get("currency") or "").upper()
    if not currency:
        currency = TRADING_ECONOMICS_COUNTRY_CURRENCY.get(country, "")
    country = clean_html_text(item.get("Country") or item.get("country") or "")
    event = clean_html_text(item.get("Event") or item.get("event") or item.get("Category") or "")
    if not event:
        event = clean_html_text(item.get("Title") or item.get("title") or "")
    importance = item.get("Importance", item.get("importance", 1))
    try:
        importance = max(1, min(3, int(importance)))
    except Exception:
        importance = _importance_from_impact(importance)
    return {
        "date": date,
        "time": time_str or "--:--",
        "currency": currency,
        "country": country or _calendar_country_from_currency(currency),
        "flag": currency_to_flag(currency),
        "event": event,
        "importance": importance,
        "actual": clean_html_text(item.get("Actual") or item.get("actual")) or "—",
        "forecast": clean_html_text(item.get("Forecast") or item.get("TEForecast") or item.get("forecast")) or "—",
        "previous": clean_html_text(item.get("Previous") or item.get("previous")) or "—",
    }

async def fetch_calendar_from_tradingeconomics(session):
    if not TRADING_ECONOMICS_KEY:
        return []
    params = {
        "c": TRADING_ECONOMICS_KEY,
        "f": "json",
    }
    async with session.get(
        TRADING_ECONOMICS_URL,
        params=params,
        headers={"Accept": "application/json", "User-Agent": "NEXO-TRADE/1.0"},
        ssl=False,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"TradingEconomics status {r.status}")
        data = await r.json(content_type=None)
    raw_items = data if isinstance(data, list) else []
    mapped = []
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        ev = map_tradingeconomics_calendar_event(row)
        if ev["date"] and ev["event"] and ev["currency"]:
            mapped.append(ev)
    dedup = {}
    for e in mapped:
        key = f"{e['date']}|{e['time']}|{e['currency']}|{e['event']}"
        dedup[key] = e
    return list(dedup.values())

async def fetch_investing_calendar_html(session):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Referer": "https://www.investing.com/",
    }
    async with session.get(
        INVESTING_WIDGET_SCRAPER_URL,
        params=INVESTING_WIDGET_SCRAPER_PARAMS,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"Investing calendar status {r.status}")
        return await r.text()

def _parse_investing_day_label(raw):
    s = clean_html_text(raw)
    if not s:
        return ""
    s = s.replace(",", "")
    for fmt in ("%A %B %d %Y", "%A %d %B %Y", "%B %d %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return ""

def _date_from_event_attr(value):
    s = clean_html_text(value)
    if not s:
        return ""
    if s.isdigit():
        try:
            ts = int(s)
            if ts > 10_000_000_000:
                ts = ts // 1000
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            pass
    d, _ = _parse_calendar_dt(s)
    return d

def parse_investing_calendar(html):
    if not BeautifulSoup:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = []
    current_date = ""
    rows = soup.select("tr")
    for row in rows:
        day_cell = row.select_one("td.theDay")
        if day_cell:
            maybe_day = _parse_investing_day_label(day_cell.get_text(" ", strip=True))
            if maybe_day:
                current_date = maybe_day
            continue

        row_text = " ".join(row.get_text(" ", strip=True).split())
        if not row_text:
            continue
        if re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),", row_text, re.I):
            maybe_day = _parse_investing_day_label(row_text)
            if maybe_day:
                current_date = maybe_day
            continue

        row_id = row.get("id", "")
        if not row_id.startswith("eventRow_") and not row.get("data-event-datetime"):
            continue

        time_value = clean_html_text(
            (row.select_one("td.first.left.time") or row.select_one("td[data-column-name='time']")).get_text(" ", strip=True)
            if (row.select_one("td.first.left.time") or row.select_one("td[data-column-name='time']")) else ""
        )
        currency_cell = row.select_one("td.left.flagCur.noWrap, td[data-column-name='currency']")
        currency_text = clean_html_text(currency_cell.get_text(" ", strip=True) if currency_cell else "")
        m = re.search(r"\b[A-Z]{3}\b", currency_text)
        currency = m.group(0) if m else ""
        if not currency:
            for td in row.find_all("td"):
                m = re.search(r"\b[A-Z]{3}\b", clean_html_text(td.get_text(" ", strip=True)))
                if m:
                    currency = m.group(0)
                    break
        if not currency:
            continue

        event_cell = row.select_one("td.left.event, td[data-column-name='event']")
        event_name = clean_html_text(event_cell.get_text(" ", strip=True) if event_cell else "")
        if not event_name:
            continue

        actual_cell = row.select_one("td.act, td[data-column-name='actual']")
        forecast_cell = row.select_one("td.fore, td[data-column-name='forecast']")
        previous_cell = row.select_one("td.prev, td[data-column-name='previous']")
        actual = clean_html_text(actual_cell.get_text(" ", strip=True) if actual_cell else "")
        forecast = clean_html_text(forecast_cell.get_text(" ", strip=True) if forecast_cell else "")
        previous = clean_html_text(previous_cell.get_text(" ", strip=True) if previous_cell else "")

        importance = 1
        imp_cell = row.select_one("td.sentiment, td[data-column-name='importance']")
        if imp_cell:
            bull_icons = len(imp_cell.select(".grayFullBullishIcon, .redFullBullishIcon, .bullishIcon"))
            if bull_icons:
                importance = min(3, bull_icons)
            else:
                imp_text = clean_html_text(imp_cell.get_text(" ", strip=True)).lower()
                if "high" in imp_text:
                    importance = 3
                elif "medium" in imp_text:
                    importance = 2

        date_val = _date_from_event_attr(row.get("data-event-datetime")) or current_date
        if not date_val:
            date_val = _day_start(datetime.now()).strftime("%Y-%m-%d")
        items.append({
            "date": date_val,
            "time": time_value or "--:--",
            "currency": currency,
            "country": _calendar_country_from_currency(currency),
            "flag": currency_to_flag(currency),
            "event": event_name,
            "importance": importance,
            "actual": actual or "—",
            "forecast": forecast or "—",
            "previous": previous or "—",
        })
    dedup = {}
    for e in items:
        key = f"{e['date']}|{e['time']}|{e['currency']}|{e['event']}"
        dedup[key] = e
    return list(dedup.values())

def normalize_calendar_item(row):
    if not isinstance(row, dict):
        return None
    date = clean_html_text(row.get("date"))
    time_str = clean_html_text(row.get("time"))
    if not date:
        date, parsed_time = _parse_calendar_dt(row.get("dateUtc") or row.get("datetime") or row.get("timestamp") or "")
        if not time_str:
            time_str = parsed_time
    currency = clean_html_text(row.get("currency") or row.get("currencyCode") or row.get("economy") or "").upper()
    if not currency:
        return None
    event = clean_html_text(row.get("event") or row.get("name") or row.get("title") or "")
    if not event:
        return None
    importance = row.get("importance", row.get("impact", 1))
    try:
        importance = max(1, min(3, int(importance)))
    except Exception:
        importance = _importance_from_impact(importance)
    return {
        "date": date or _day_start(datetime.now()).strftime("%Y-%m-%d"),
        "time": time_str or "--:--",
        "currency": currency,
        "country": clean_html_text(row.get("country") or row.get("countryCode") or _calendar_country_from_currency(currency)),
        "flag": clean_html_text(row.get("flag")) or currency_to_flag(currency),
        "event": event,
        "importance": importance,
        "actual": clean_html_text(row.get("actual")) or "—",
        "forecast": clean_html_text(row.get("forecast") or row.get("consensus")) or "—",
        "previous": clean_html_text(row.get("previous")) or "—",
    }

async def fetch_investing_calendar_from_proxy(session):
    if not INVESTING_SCRAPER_PROXY_URL:
        return []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Referer": "https://www.investing.com/",
    }
    async with session.get(
        INVESTING_WIDGET_SCRAPER_URL,
        params=INVESTING_WIDGET_SCRAPER_PARAMS,
        headers=headers,
        proxy=INVESTING_SCRAPER_PROXY_URL,
        ssl=False,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"Investing proxy status {r.status}")
        html = await r.text()
        return parse_investing_calendar(html)

def filter_calendar_items(items, range_key="today", currency="ALL", importance="all"):
    out = [x for x in items if _in_range(x.get("date", ""), range_key)]
    if currency != "ALL":
        out = [x for x in out if str(x.get("currency", "")).upper() == currency]
    if importance != "all":
        imp = int(importance)
        out = [x for x in out if int(x.get("importance") or 1) == imp]
    out.sort(key=lambda x: (x.get("date", ""), x.get("time", "")))
    return out

def _in_range(item_date, range_key):
    try:
        d = datetime.strptime(item_date, "%Y-%m-%d")
    except Exception:
        return False
    d = _day_start(d)
    today = _day_start(datetime.now())
    weekday = today.weekday()
    start_week = today - timedelta(days=weekday)
    end_week = start_week + timedelta(days=6)
    next_start = start_week + timedelta(days=7)
    next_end = next_start + timedelta(days=6)
    if range_key == "yesterday":
        return d == today - timedelta(days=1)
    if range_key == "today":
        return d == today
    if range_key == "tomorrow":
        return d == today + timedelta(days=1)
    if range_key == "week":
        return start_week <= d <= end_week
    if range_key == "next_week":
        return next_start <= d <= next_end
    return True

def _is_major_calendar_event(event_name):
    s = clean_html_text(event_name).lower()
    if not s:
        return False
    return any(k in s for k in MAJOR_EVENT_KEYWORDS)


# ══════════════════════════════════════════
#  الاستراتيجية الجديدة الصارمة
#  الشروط الإجبارية للإشارة:
#  1. الاتجاه (EMA5 > EMA20 > EMA50)
#  2. المومنتوم (في نفس اتجاه EMA)
#  3. هيستوغرام MACD (في نفس الاتجاه)
#  4. Price Action (نمط يؤكد الاتجاه)
#  5. شمعة M5 (آخر 5 شموع في نفس الاتجاه)
# ══════════════════════════════════════════
def check_5candle_trend(cn, direction):
    """
    التحقق من أن آخر 5 شموع تسير في نفس اتجاه الإشارة.
    UP  = أغلب الشموع الخمس صاعدة (close > open)
    DOWN= أغلب الشموع الخمس هابطة
    يشترط على الأقل 3 من 5 في نفس الاتجاه.
    """
    if len(cn) < 5: return False, 0
    last5 = cn[-5:]
    bull_count = sum(1 for c in last5 if c["c"] > c["o"])
    bear_count = 5 - bull_count
    if direction == "UP":
        return bull_count >= 3, bull_count
    else:
        return bear_count >= 3, bear_count

def analyze_confluence(ins, cn):
    if not cn or len(cn) < 55: return None
    pr  = [c["c"] for c in cn]
    cur = pr[-1]

    # ── حساب جميع المؤشرات ──
    e5  = ema(pr, 5)
    e20 = ema(pr, 20)
    e50 = ema(pr, 50)
    r14 = rsi(pr, 14)
    r7  = rsi(pr, 7)
    macd_line, macd_sig, macd_hist = macd_full(pr)
    bb  = bollinger(pr, 20)
    at  = atr(cn, 14)
    sk  = stoch(cn, 14)
    cc  = cci(cn, 14)

    # ADX — قوة الاتجاه (ثانوي)
    adx_val, plus_di, minus_di = adx_calc(cn, 14)

    # المومنتوم: مقارنة متعددة الأطر
    mom3  = pr[-1] - pr[-4]   # 3 شموع
    mom5  = pr[-1] - pr[-6]   # 5 شموع
    mom10 = pr[-1] - pr[-11]  # 10 شموع

    # الأنماط
    pa = pa_patterns(cn)

    # دعم ومقاومة
    rec20 = cn[-20:]
    RES   = max(c["h"] for c in rec20)
    SUP   = min(c["l"] for c in rec20)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  الشرط 1: تحديد الاتجاه من EMA (مخفف)
    #  يكفي: EMA5 > EMA20 (UP)
    #  أو:   EMA5 < EMA20 (DOWN)
    #  EMA50 تضيف نقاطاً إضافية فقط (ليست شرطاً)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if not (e5 and e20):
        return None

    trend_up   = e5 > e20
    trend_down = e5 < e20
    # اتجاه غير واضح (متساوي تقريباً) — لا إشارة
    diff_ema = abs(e5 - e20)
    min_diff  = pip(ins) * 3   # فرق لا يقل عن 3 نقاط
    if diff_ema < min_diff:
        return None

    trend_dir = "UP" if trend_up else "DOWN"
    # EMA50 تحقق الاتجاه الكبير (نقاط إضافية فقط)
    ema50_confirms = (e50 and trend_up and e20 > e50) or \
                     (e50 and trend_down and e20 < e50)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  الشرط 2: المومنتوم في نفس الاتجاه
    #  يجب أن يكون المومنتوم موافقاً للاتجاه
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    mom_ok = False
    if trend_dir == "UP"   and mom3 > 0 and mom5 > 0: mom_ok = True
    if trend_dir == "DOWN" and mom3 < 0 and mom5 < 0: mom_ok = True
    # المومنتوم مخالف للاتجاه — لا إشارة
    if not mom_ok:
        return None

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  الشرط 3: هيستوغرام MACD في نفس الاتجاه
    #  UP  = هيستوغرام موجب (+)
    #  DOWN= هيستوغرام سالب (-)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    hist_ok = False
    if macd_hist is not None:
        if trend_dir == "UP"   and macd_hist > 0: hist_ok = True
        if trend_dir == "DOWN" and macd_hist < 0: hist_ok = True
    # هيستوغرام مخالف — لا إشارة
    if not hist_ok:
        return None

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  الشرط 4: شمعة آخر 5 في نفس الاتجاه
    #  على الأقل 3 من 5 شموع موافقة
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    c5_ok, c5_count = check_5candle_trend(cn, trend_dir)
    if not c5_ok:
        return None

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  الشرط 5: Price Action يؤكد الاتجاه
    #  يجب وجود نمط واحد على الأقل موافق
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    pa_confirms = [p for p in pa if p[1] == trend_dir]
    pa_neutral  = [p for p in pa if p[1] == "NEUTRAL"]
    # إذا كان هناك نمط معاكس قوي — لا إشارة
    pa_opposite = [p for p in pa if p[1] != trend_dir and p[1] != "NEUTRAL" and p[2] >= 35]
    if pa_opposite:
        return None
    # يجب وجود نمط PA مؤكد
    if not pa_confirms:
        return None

    best_pa = max(pa_confirms, key=lambda x: x[2])

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  حساب نقاط القوة (بعد تجاوز كل الشروط)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    score = 0; reasons = []; badges = []

    # EMA (اتجاه محقق)
    score += 25
    ema_label = "EMA✓↑" if trend_up else "EMA✓↓"
    badges.append((ema_label, "bull" if trend_up else "bear"))
    reasons.append(f"EMA5{'>'if trend_up else '<'}EMA20")
    # EMA50 تؤكد الاتجاه الكبير — نقاط إضافية
    if ema50_confirms:
        score += 15
        badges.append(("EMA50✓", "bull" if trend_up else "bear"))
        reasons.append("EMA50 تؤكد الاتجاه")

    # مومنتوم (محقق)
    score += 20
    mom_str = f"+{mom5:.{dp(ins)}f}" if mom5>0 else f"{mom5:.{dp(ins)}f}"
    badges.append((f"زخم{mom_str}", "bull" if trend_up else "bear"))

    # MACD هيستوغرام (محقق)
    hist_abs = abs(macd_hist) if macd_hist else 0
    hist_strength = min(int(hist_abs / pip(ins) * 10), 25)
    score += 15 + hist_strength
    badges.append((f"HIST{'+' if macd_hist>0 else ''}{macd_hist:.5f}", "bull" if macd_hist>0 else "bear"))
    reasons.append(f"هيستوغرام MACD {'↑' if macd_hist>0 else '↓'}")

    # شمعة 5 (محققة)
    score += 10 + c5_count * 3
    badges.append((f"شمعة5:{c5_count}/5", "bull" if trend_up else "bear"))

    # Price Action (محقق + أعلى وزن)
    score += int(best_pa[2] * 1.5)
    badges.append((best_pa[0], "bull" if trend_up else "bear"))
    reasons.insert(0, f"نمط: {best_pa[0]}")

    # RSI (مكمّل — ليس شرطاً)
    if r14 is not None:
        badges.append((f"RSI{r14:.0f}", "bull" if r14<50 else "bear"))
        if trend_up:
            if   r14 < 35: score += 20; reasons.append(f"RSI={r14:.0f} ذروة بيع")
            elif r14 < 50: score += 10
            elif r14 > 70: score -= 10  # ضعف في الصعود إذا كان RSI مرتفعاً جداً
        else:
            if   r14 > 65: score += 20; reasons.append(f"RSI={r14:.0f} ذروة شراء")
            elif r14 > 50: score += 10
            elif r14 < 30: score -= 10

    # Stoch (مكمّل)
    if sk is not None:
        badges.append((f"Stch{sk:.0f}", "bull" if sk<50 else "bear"))
        if trend_up   and sk < 30: score += 15; reasons.append("Stoch ذروة بيع")
        if trend_down and sk > 70: score += 15; reasons.append("Stoch ذروة شراء")

    # BB (مكمّل)
    if bb and bb["u"] != bb["l"]:
        pos = (cur - bb["l"]) / (bb["u"] - bb["l"])
        badges.append((f"BB{pos*100:.0f}%", "bull" if pos<0.4 else "bear" if pos>0.6 else "neu"))
        if trend_up   and pos < 0.3: score += 12; reasons.append("عند بولنجر السفلي")
        if trend_down and pos > 0.7: score += 12; reasons.append("عند بولنجر العلوي")

    # دعم/مقاومة (مكمّل)
    if at:
        if trend_up   and cur - SUP < at * 0.4: score += 12; reasons.append("قرب دعم قوي")
        if trend_down and RES - cur < at * 0.4: score += 12; reasons.append("قرب مقاومة قوية")

    # ADX — ثانوي (يضيف/يخصم نقاطاً فقط — ليس شرطاً)
    adx_label = None
    if adx_val is not None:
        if adx_val > 40:
            # اتجاه قوي جداً → +20 نقطة
            score += 20
            adx_label = f"ADX{adx_val:.0f}⭐"
            badges.append((adx_label, "bull" if trend_up else "bear"))
            reasons.append(f"ADX={adx_val:.0f} اتجاه قوي جداً")
        elif adx_val > 25:
            # اتجاه واضح → +12 نقطة
            score += 12
            adx_label = f"ADX{adx_val:.0f}✅"
            badges.append((adx_label, "bull" if trend_up else "bear"))
            reasons.append(f"ADX={adx_val:.0f} اتجاه واضح")
        elif adx_val > 20:
            # بداية اتجاه → +5 نقاط
            score += 5
            adx_label = f"ADX{adx_val:.0f}"
            badges.append((adx_label, "neu"))
        else:
            # سوق عرضي → -15 نقطة (تحذير)
            score -= 15
            adx_label = f"ADX{adx_val:.0f}⚠️"
            badges.append((adx_label, "neu"))
            # إذا ADX أقل من 15 جداً = سوق عرضي حاد → لا إشارة
            if adx_val < 15:
                return None

    # حساب الثقة
    # <span id="minConfLabel">الحد الأدنى للثقة</span> بعد تحقق كل الشروط = 65%
    conf = min(65 + int(score / 12), 95)

    res = {
        "ins"       : ins,
        "pair"      : pname(ins),
        "pair_flags": pair_flags(ins),
        "dir"       : trend_dir,
        "price"     : cur,
        "conf"      : conf,
        "bs"        : score if trend_dir=="UP"   else 0,
        "ss"        : score if trend_dir=="DOWN" else 0,
        "rsi"       : round(r14,1) if r14 else None,
        "pa"        : best_pa[0],
        "ema_trend" : "صاعد" if trend_up else "هابط",
        "reasons"   : reasons[:4],
        "badges"    : badges[:8],
        "atr"       : at,
        "adx"       : adx_val,
        "plus_di"   : plus_di,
        "minus_di"  : minus_di,
        # معلومات إضافية للـ AI
        "macd_hist" : round(macd_hist,6) if macd_hist else None,
        "c5_count"  : c5_count,
        "mom3"      : round(mom3,dp(ins)+1),
        "mom5"      : round(mom5,dp(ins)+1),
    }
    meta = STRATEGY_META["confluence"]
    res.update({
        "strategy": "confluence",
        "strategy_icon": meta["icon"],
        "strategy_name": meta["en"],
        "strategy_name_ar": meta["ar"],
        "strategy_name_en": meta["en"],
    })
    return res


def build_analysis_result(ins, direction, price, score, reasons, badges, strategy_id, rsi_value=None, pa_label=None, ema_trend=None, atr_value=None, adx_value=None, plus_di=None, minus_di=None, macd_hist=None, c5_count=0, mom3=None, mom5=None):
    meta = STRATEGY_META.get(strategy_id, STRATEGY_META["confluence"])
    conf = max(66, min(95, 64 + int(score / 5)))
    return {
        "ins": ins,
        "pair": pname(ins),
        "pair_flags": pair_flags(ins),
        "dir": direction,
        "price": price,
        "conf": conf,
        "bs": score if direction == "UP" else 0,
        "ss": score if direction == "DOWN" else 0,
        "rsi": round(rsi_value, 1) if rsi_value is not None else None,
        "pa": pa_label,
        "ema_trend": ema_trend or ("صاعد" if direction == "UP" else "هابط"),
        "reasons": reasons[:4],
        "badges": badges[:8],
        "atr": atr_value,
        "adx": adx_value,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "macd_hist": round(macd_hist, 6) if macd_hist is not None else None,
        "c5_count": c5_count,
        "mom3": mom3,
        "mom5": mom5,
        "strategy": strategy_id,
        "strategy_icon": meta["icon"],
        "strategy_name": meta["en"],
        "strategy_name_ar": meta["ar"],
        "strategy_name_en": meta["en"],
    }

def analyze_rsi_reversal(ins, cn):
    if not cn or len(cn) < 25: return None
    pr = [c["c"] for c in cn]
    cur = pr[-1]
    e20 = ema(pr, 20)
    r14 = rsi(pr, 14)
    sk = stoch(cn, 14)
    bb = bollinger(pr, 20)
    at = atr(cn, 14)
    adx_val, plus_di, minus_di = adx_calc(cn, 14)
    pa = pa_patterns(cn)
    L = cn[-1]
    body = abs(L["c"] - L["o"]) or pip(ins)
    lower_wick = min(L["c"], L["o"]) - L["l"]
    upper_wick = L["h"] - max(L["c"], L["o"])
    bull_reject = L["c"] > L["o"] and lower_wick > body * 1.3
    bear_reject = L["c"] < L["o"] and upper_wick > body * 1.3
    bb_pos = None
    if bb and bb["u"] != bb["l"]:
        bb_pos = (cur - bb["l"]) / (bb["u"] - bb["l"])
    mom3 = round(pr[-1] - pr[-4], dp(ins) + 1)
    mom5 = round(pr[-1] - pr[-6], dp(ins) + 1)

    direction = None
    reasons, badges = [], []
    pa_label = None
    score = 0

    if r14 is not None and r14 <= 36 and (sk is None or sk <= 28) and (bb_pos is None or bb_pos <= 0.28) and bull_reject:
        direction = "UP"
        score = 76
        reasons = ["RSI في تشبع بيعي مع ارتداد", "شمعة رفض صاعدة واضحة", "السعر قريب من الحد السفلي لبولنجر"]
        badges = [(f"RSI {r14:.0f}", "bull"), (f"Stoch {sk:.0f}" if sk is not None else "Stoch", "bull"), ("BB Lower", "bull"), ("Reversal", "bull")]
        if e20 and cur > e20: score += 6; reasons.append("السعر عاد فوق EMA20")
        pa_match = next((x[0] for x in pa if x[1] == "UP"), None)
        if pa_match: pa_label = pa_match; score += 8
    elif r14 is not None and r14 >= 64 and (sk is None or sk >= 72) and (bb_pos is None or bb_pos >= 0.72) and bear_reject:
        direction = "DOWN"
        score = 76
        reasons = ["RSI في تشبع شرائي مع انعكاس", "شمعة رفض هابطة واضحة", "السعر قريب من الحد العلوي لبولنجر"]
        badges = [(f"RSI {r14:.0f}", "bear"), (f"Stoch {sk:.0f}" if sk is not None else "Stoch", "bear"), ("BB Upper", "bear"), ("Reversal", "bear")]
        if e20 and cur < e20: score += 6; reasons.append("السعر عاد تحت EMA20")
        pa_match = next((x[0] for x in pa if x[1] == "DOWN"), None)
        if pa_match: pa_label = pa_match; score += 8
    else:
        return None

    if adx_val is not None and adx_val > 18: score += 4
    return build_analysis_result(ins, direction, cur, score, reasons, badges, "rsi_reversal", rsi_value=r14, pa_label=pa_label, ema_trend="صاعد" if direction == "UP" else "هابط", atr_value=at, adx_value=adx_val, plus_di=plus_di, minus_di=minus_di, c5_count=0, mom3=mom3, mom5=mom5)

def analyze_macd_trend(ins, cn):
    if not cn or len(cn) < 35: return None
    pr = [c["c"] for c in cn]
    cur = pr[-1]
    e9 = ema(pr, 9)
    e21 = ema(pr, 21)
    r14 = rsi(pr, 14)
    macd_line, macd_sig, macd_hist = macd_full(pr)
    at = atr(cn, 14)
    adx_val, plus_di, minus_di = adx_calc(cn, 14)
    pa = pa_patterns(cn)
    mom3 = pr[-1] - pr[-4]
    mom5 = pr[-1] - pr[-6]
    if None in (e9, e21, macd_hist, r14): return None

    direction = None
    reasons, badges = [], []
    pa_label = None
    score = 0
    if e9 > e21 and macd_hist > 0 and mom3 > 0 and mom5 > 0 and 45 <= r14 <= 72 and (adx_val is None or adx_val >= 18):
        direction = "UP"
        score = 78
        reasons = ["اتجاه EMA صاعد", "هيستوغرام MACD موجب", "المومنتوم يدعم الاستمرار"]
        badges = [("EMA 9/21", "bull"), (f"MACD {macd_hist:.4f}", "bull"), (f"ADX {adx_val:.0f}" if adx_val is not None else "ADX", "bull")]
        pa_label = next((x[0] for x in pa if x[1] == "UP"), None)
        if pa_label: score += 6
        if adx_val and adx_val > 25: score += 6; reasons.append("قوة اتجاه جيدة عبر ADX")
    elif e9 < e21 and macd_hist < 0 and mom3 < 0 and mom5 < 0 and 28 <= r14 <= 55 and (adx_val is None or adx_val >= 18):
        direction = "DOWN"
        score = 78
        reasons = ["اتجاه EMA هابط", "هيستوغرام MACD سالب", "المومنتوم يؤكد الهبوط"]
        badges = [("EMA 9/21", "bear"), (f"MACD {macd_hist:.4f}", "bear"), (f"ADX {adx_val:.0f}" if adx_val is not None else "ADX", "bear")]
        pa_label = next((x[0] for x in pa if x[1] == "DOWN"), None)
        if pa_label: score += 6
        if adx_val and adx_val > 25: score += 6; reasons.append("قوة اتجاه جيدة عبر ADX")
    else:
        return None

    return build_analysis_result(ins, direction, cur, score, reasons, badges, "macd_trend", rsi_value=r14, pa_label=pa_label, ema_trend="صاعد" if direction == "UP" else "هابط", atr_value=at, adx_value=adx_val, plus_di=plus_di, minus_di=minus_di, macd_hist=macd_hist, c5_count=0, mom3=round(mom3, dp(ins)+1), mom5=round(mom5, dp(ins)+1))

def analyze_bollinger_reversal(ins, cn):
    if not cn or len(cn) < 25: return None
    pr = [c["c"] for c in cn]
    cur = pr[-1]
    bb = bollinger(pr, 20)
    r14 = rsi(pr, 14)
    at = atr(cn, 14)
    adx_val, plus_di, minus_di = adx_calc(cn, 14)
    pa = pa_patterns(cn)
    if not bb or bb["u"] == bb["l"] or r14 is None: return None
    pos = (cur - bb["l"]) / (bb["u"] - bb["l"])
    L = cn[-1]
    body = abs(L["c"] - L["o"]) or pip(ins)
    lower_wick = min(L["c"], L["o"]) - L["l"]
    upper_wick = L["h"] - max(L["c"], L["o"])
    bull_reject = lower_wick > body * 1.2 and L["c"] >= L["o"]
    bear_reject = upper_wick > body * 1.2 and L["c"] <= L["o"]
    mom3 = round(pr[-1] - pr[-4], dp(ins) + 1)
    mom5 = round(pr[-1] - pr[-6], dp(ins) + 1)

    if pos <= 0.16 and r14 <= 40 and bull_reject:
        pa_label = next((x[0] for x in pa if x[1] == "UP"), None)
        score = 74 + (8 if pa_label else 0)
        reasons = ["السعر يلامس الحد السفلي لبولنجر", "RSI يدعم الارتداد", "شمعة رفض صاعدة من منطقة دعم"]
        badges = [(f"BB {pos*100:.0f}%", "bull"), (f"RSI {r14:.0f}", "bull"), ("Bounce", "bull")]
        return build_analysis_result(ins, "UP", cur, score, reasons, badges, "bollinger_reversal", rsi_value=r14, pa_label=pa_label, ema_trend="صاعد", atr_value=at, adx_value=adx_val, plus_di=plus_di, minus_di=minus_di, c5_count=0, mom3=mom3, mom5=mom5)
    if pos >= 0.84 and r14 >= 60 and bear_reject:
        pa_label = next((x[0] for x in pa if x[1] == "DOWN"), None)
        score = 74 + (8 if pa_label else 0)
        reasons = ["السعر يلامس الحد العلوي لبولنجر", "RSI يدعم الانعكاس الهابط", "شمعة رفض هابطة من منطقة مقاومة"]
        badges = [(f"BB {pos*100:.0f}%", "bear"), (f"RSI {r14:.0f}", "bear"), ("Bounce", "bear")]
        return build_analysis_result(ins, "DOWN", cur, score, reasons, badges, "bollinger_reversal", rsi_value=r14, pa_label=pa_label, ema_trend="هابط", atr_value=at, adx_value=adx_val, plus_di=plus_di, minus_di=minus_di, c5_count=0, mom3=mom3, mom5=mom5)
    return None

def analyze_stochastic_reversal(ins, cn):
    if not cn or len(cn) < 25: return None
    pr = [c["c"] for c in cn]
    cur = pr[-1]
    sk = stoch(cn, 14)
    r14 = rsi(pr, 14)
    bb = bollinger(pr, 20)
    at = atr(cn, 14)
    adx_val, plus_di, minus_di = adx_calc(cn, 14)
    pa = pa_patterns(cn)
    if sk is None or r14 is None: return None
    L, P = cn[-1], cn[-2]
    bull_turn = sk < 25 and r14 < 45 and L["c"] > L["o"] and L["c"] > P["c"]
    bear_turn = sk > 75 and r14 > 55 and L["c"] < L["o"] and L["c"] < P["c"]
    pos = None
    if bb and bb["u"] != bb["l"]:
        pos = (cur - bb["l"]) / (bb["u"] - bb["l"])
    if bull_turn and (pos is None or pos < 0.45):
        pa_label = next((x[0] for x in pa if x[1] == "UP"), None)
        score = 72 + (10 if pa_label else 0) + (6 if sk < 18 else 0)
        reasons = ["Stochastic في تشبع بيعي", "RSI يدعم انعكاس صاعد", "شمعة صاعدة تؤكد بداية الارتداد"]
        badges = [(f"Stoch {sk:.0f}", "bull"), (f"RSI {r14:.0f}", "bull"), ("Fast Reversal", "bull")]
        return build_analysis_result(ins, "UP", cur, score, reasons, badges, "stochastic_reversal", rsi_value=r14, pa_label=pa_label, ema_trend="صاعد", atr_value=at, adx_value=adx_val, plus_di=plus_di, minus_di=minus_di, mom3=round(pr[-1]-pr[-4], dp(ins)+1), mom5=round(pr[-1]-pr[-6], dp(ins)+1))
    if bear_turn and (pos is None or pos > 0.55):
        pa_label = next((x[0] for x in pa if x[1] == "DOWN"), None)
        score = 72 + (10 if pa_label else 0) + (6 if sk > 82 else 0)
        reasons = ["Stochastic في تشبع شرائي", "RSI يدعم انعكاس هابط", "شمعة هابطة تؤكد بداية النزول"]
        badges = [(f"Stoch {sk:.0f}", "bear"), (f"RSI {r14:.0f}", "bear"), ("Fast Reversal", "bear")]
        return build_analysis_result(ins, "DOWN", cur, score, reasons, badges, "stochastic_reversal", rsi_value=r14, pa_label=pa_label, ema_trend="هابط", atr_value=at, adx_value=adx_val, plus_di=plus_di, minus_di=minus_di, mom3=round(pr[-1]-pr[-4], dp(ins)+1), mom5=round(pr[-1]-pr[-6], dp(ins)+1))
    return None

def analyze_ema_cross(ins, cn):
    if not cn or len(cn) < 35: return None
    pr = [c["c"] for c in cn]
    cur = pr[-1]
    e5 = ema(pr, 5); e20 = ema(pr, 20); e50 = ema(pr, 50)
    prev_e5 = ema(pr[:-1], 5); prev_e20 = ema(pr[:-1], 20)
    r14 = rsi(pr, 14)
    ml, ms, mh = macd_full(pr)
    at = atr(cn, 14)
    adx_val, plus_di, minus_di = adx_calc(cn, 14)
    if not all(x is not None for x in (e5, e20, prev_e5, prev_e20, mh, r14)): return None
    mom3 = pr[-1] - pr[-4]; mom5 = pr[-1] - pr[-6]
    pa = pa_patterns(cn)
    crossed_up = prev_e5 <= prev_e20 and e5 > e20
    crossed_dn = prev_e5 >= prev_e20 and e5 < e20
    aligned_up = e5 > e20 and mom3 > 0 and mom5 > 0 and mh > 0
    aligned_dn = e5 < e20 and mom3 < 0 and mom5 < 0 and mh < 0
    if (crossed_up or aligned_up) and 40 <= r14 <= 72:
        pa_label = next((x[0] for x in pa if x[1] == "UP"), None)
        score = 74 + (10 if crossed_up else 4) + (6 if e50 and e20 > e50 else 0) + (5 if adx_val and adx_val > 20 else 0)
        reasons = ["EMA5 أعلى من EMA20", "MACD يؤكد الاتجاه الصاعد", "المومنتوم إيجابي"]
        badges = [("EMA Cross", "bull"), (f"MACD {mh:.4f}", "bull"), (f"RSI {r14:.0f}", "bull")]
        return build_analysis_result(ins, "UP", cur, score, reasons, badges, "ema_cross", rsi_value=r14, pa_label=pa_label, ema_trend="صاعد", atr_value=at, adx_value=adx_val, plus_di=plus_di, minus_di=minus_di, macd_hist=mh, mom3=round(mom3, dp(ins)+1), mom5=round(mom5, dp(ins)+1))
    if (crossed_dn or aligned_dn) and 28 <= r14 <= 60:
        pa_label = next((x[0] for x in pa if x[1] == "DOWN"), None)
        score = 74 + (10 if crossed_dn else 4) + (6 if e50 and e20 < e50 else 0) + (5 if adx_val and adx_val > 20 else 0)
        reasons = ["EMA5 أسفل EMA20", "MACD يؤكد الاتجاه الهابط", "المومنتوم سلبي"]
        badges = [("EMA Cross", "bear"), (f"MACD {mh:.4f}", "bear"), (f"RSI {r14:.0f}", "bear")]
        return build_analysis_result(ins, "DOWN", cur, score, reasons, badges, "ema_cross", rsi_value=r14, pa_label=pa_label, ema_trend="هابط", atr_value=at, adx_value=adx_val, plus_di=plus_di, minus_di=minus_di, macd_hist=mh, mom3=round(mom3, dp(ins)+1), mom5=round(mom5, dp(ins)+1))
    return None

def analyze_adx_breakout(ins, cn):
    if not cn or len(cn) < 45: return None
    pr = [c["c"] for c in cn]
    cur = pr[-1]
    r14 = rsi(pr, 14)
    at = atr(cn, 14)
    adx_val, plus_di, minus_di = adx_calc(cn, 14)
    ml, ms, mh = macd_full(pr)
    if adx_val is None or plus_di is None or minus_di is None or at is None or mh is None or r14 is None: return None
    rec = cn[-18:-1]
    recent_high = max(c["h"] for c in rec)
    recent_low = min(c["l"] for c in rec)
    buffer = at * 0.10
    pa = pa_patterns(cn)
    mom3 = pr[-1] - pr[-4]; mom5 = pr[-1] - pr[-6]
    if adx_val >= 22 and plus_di > minus_di and cur > recent_high - buffer and mh > 0 and mom3 > 0:
        pa_label = next((x[0] for x in pa if x[1] == "UP"), None)
        score = 78 + (10 if adx_val > 30 else 0) + (6 if cur > recent_high else 0)
        reasons = ["ADX يؤكد قوة اتجاه صاعد", "DI+ أقوى من DI-", "اختراق قريب من قمة حديثة"]
        badges = [(f"ADX {adx_val:.0f}", "bull"), ("DI+", "bull"), ("Breakout", "bull")]
        return build_analysis_result(ins, "UP", cur, score, reasons, badges, "adx_breakout", rsi_value=r14, pa_label=pa_label, ema_trend="صاعد", atr_value=at, adx_value=adx_val, plus_di=plus_di, minus_di=minus_di, macd_hist=mh, mom3=round(mom3, dp(ins)+1), mom5=round(mom5, dp(ins)+1))
    if adx_val >= 22 and minus_di > plus_di and cur < recent_low + buffer and mh < 0 and mom3 < 0:
        pa_label = next((x[0] for x in pa if x[1] == "DOWN"), None)
        score = 78 + (10 if adx_val > 30 else 0) + (6 if cur < recent_low else 0)
        reasons = ["ADX يؤكد قوة اتجاه هابط", "DI- أقوى من DI+", "اختراق قريب من قاع حديث"]
        badges = [(f"ADX {adx_val:.0f}", "bear"), ("DI-", "bear"), ("Breakout", "bear")]
        return build_analysis_result(ins, "DOWN", cur, score, reasons, badges, "adx_breakout", rsi_value=r14, pa_label=pa_label, ema_trend="هابط", atr_value=at, adx_value=adx_val, plus_di=plus_di, minus_di=minus_di, macd_hist=mh, mom3=round(mom3, dp(ins)+1), mom5=round(mom5, dp(ins)+1))
    return None

def analyze_local(ins, cn, strategy_id=None):
    mode = strategy_id or CONFIG.get("strategy", "smart_auto")
    analyzers = {
        "confluence": analyze_confluence,
        "rsi_reversal": analyze_rsi_reversal,
        "macd_trend": analyze_macd_trend,
        "bollinger_reversal": analyze_bollinger_reversal,
        "stochastic_reversal": analyze_stochastic_reversal,
        "ema_cross": analyze_ema_cross,
        "adx_breakout": analyze_adx_breakout,
    }
    if mode == "smart_auto":
        results = [fn(ins, cn) for fn in analyzers.values()]
        results = [r for r in results if r]
        if not results:
            return None
        return sorted(results, key=lambda x: (x["conf"], x.get("adx") or 0, len(x.get("reasons") or [])), reverse=True)[0]
    fn = analyzers.get(mode, analyze_confluence)
    return fn(ins, cn)


# ══════════════════════════════════════════
#  AI — Groq → Claude → محلي
# ══════════════════════════════════════════
def normalize_ai_json(raw):
    """Extract and parse the first JSON object returned by an AI provider."""
    if not raw:
        return None
    raw = str(raw).replace("```json", "").replace("```", "").strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        return None

AI_REVIEWER_SYSTEM_PROMPT = """أنت AI Trading Reviewer داخل تطبيق NEXO TRADE.

مهمتك ليست إنشاء إشارات جديدة.
مهمتك فقط مراجعة الإشارة القادمة من الاستراتيجية وتحديد هل يتم إرسالها أم رفضها.

راجع الإشارة بناءً على:
1. توافق الاتجاه العام
2. توافق المؤشرات
3. حالة السوق هل هو واضح أم متذبذب
4. قرب السعر من الدعم أو المقاومة
5. الأخبار الاقتصادية القوية على عملات الزوج
6. جودة التوقيت وسرعة حركة السعر
7. مستوى المخاطرة العام

لا توافق على الإشارة إذا:
- السوق متذبذب أو غير واضح
- الإشارة عكس الاتجاه بدون سبب قوي
- السعر قريب من دعم أو مقاومة ضد اتجاه الصفقة
- يوجد خبر اقتصادي قوي خلال 30 دقيقة قبل أو 15 دقيقة بعد الخبر
- السعر تحرك بعيدًا عن نقطة الإشارة
- المؤشرات متعارضة
- الثقة أقل من 75

أعد النتيجة بصيغة JSON فقط بدون أي شرح خارج JSON:
{
  "decision": "APPROVE | REJECT | WAIT",
  "confidence": 0,
  "risk_level": "low | medium | high",
  "reason_ar": "سبب القرار بالعربية",
  "reason_en": "reason in English",
  "filters": {
    "trend": "pass | fail | mixed",
    "indicators": "pass | fail | mixed",
    "market_condition": "pass | fail | mixed",
    "support_resistance": "pass | fail | mixed",
    "news": "pass | fail | mixed",
    "timing": "pass | fail | mixed"
  }
}
"""

def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default

def _parse_event_dt(date_s, time_s):
    if not date_s:
        return None
    time_s = (time_s or "").strip()
    if not time_s or time_s == "--:--":
        time_s = "00:00"
    raw = f"{date_s} {time_s}"
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=TR_TZ)
        except Exception:
            continue
    return None

def _extract_pair_currencies(pair):
    parts = str(pair or "").upper().replace("/", "_").split("_")
    return [p for p in parts if len(p) == 3][:2]

def _calc_sr_distances(candles, current_price, direction, ins):
    if not candles:
        return None, None, False
    recent = candles[-20:] if len(candles) >= 20 else candles
    highs = [c.get("h") for c in recent if c.get("h") is not None]
    lows = [c.get("l") for c in recent if c.get("l") is not None]
    if not highs or not lows:
        return None, None, False
    resistance = max(highs)
    support = min(lows)
    p = pip(ins)
    if p <= 0:
        p = max(abs(current_price) * 0.0001, 0.00001)
    support_distance = abs(current_price - support) / p
    resistance_distance = abs(resistance - current_price) / p
    # Balanced SR tuning: make rejection near SR less aggressive.
    near_threshold = 5.5
    near_against = (direction == "UP" and resistance_distance <= near_threshold) or (direction == "DOWN" and support_distance <= near_threshold)
    return support_distance, resistance_distance, near_against

def _wick_noise_level(candles):
    if not candles or len(candles) < 5:
        return "unknown"
    recent = candles[-5:]
    noisy = 0
    for c in recent:
        o, h, l, cl = c.get("o"), c.get("h"), c.get("l"), c.get("c")
        if None in (o, h, l, cl):
            continue
        body = abs(cl - o)
        rng = max(h - l, 1e-9)
        wick = rng - body
        if wick / rng >= 0.62:
            noisy += 1
    if noisy >= 3:
        return "high"
    if noisy == 2:
        return "medium"
    return "low"

def _candle_overlap_is_high(candles):
    if not candles or len(candles) < 5:
        return False
    recent = candles[-5:]
    overlap = 0
    for i in range(1, len(recent)):
        a = recent[i - 1]
        b = recent[i]
        if None in (a.get("h"), a.get("l"), b.get("h"), b.get("l")):
            continue
        low = max(a["l"], b["l"])
        high = min(a["h"], b["h"])
        if high > low:
            overlap += 1
    # Balanced overlap tuning: require stronger overlap before rejecting.
    return overlap >= 4

def _detect_news_risk(pair, now_dt):
    currencies = _extract_pair_currencies(pair)
    before_min = int(CONFIG.get("news_filter_before_min", 30) or 30)
    after_min = int(CONFIG.get("news_filter_after_min", 15) or 15)
    nearest = None
    for ev in CALENDAR_CACHE.get("items", []) or []:
        cur = str(ev.get("currency", "")).upper()
        if cur not in currencies:
            continue
        try:
            imp = int(ev.get("importance") or 1)
        except Exception:
            imp = 1
        if imp < 3:
            continue
        ev_dt = _parse_event_dt(ev.get("date"), ev.get("time"))
        if not ev_dt:
            continue
        diff_min = (ev_dt - now_dt).total_seconds() / 60.0
        if -after_min <= diff_min <= before_min:
            if nearest is None or abs(diff_min) < abs(nearest["minutes_to_news"]):
                nearest = {
                    "has_high_impact_news": True,
                    "minutes_to_news": int(round(diff_min)),
                    "affected_currency": cur,
                    "event_name": str(ev.get("event") or ""),
                }
    if nearest:
        return nearest
    return {
        "has_high_impact_news": False,
        "minutes_to_news": None,
        "affected_currency": None,
        "event_name": None,
    }

def build_ai_review_payload(signal, candles=None):
    direction = "CALL" if signal.get("dir") == "UP" else "PUT"
    pair = signal.get("pair") or pname(signal.get("ins"))
    now_dt = turkey_now()
    current_price = _safe_float(signal.get("price"))
    signal_price = _safe_float(signal.get("price"))
    p = pip(signal.get("ins"))
    if p <= 0:
        p = max(abs(current_price) * 0.0001, 0.00001)

    support_distance, resistance_distance, near_against = _calc_sr_distances(candles or [], current_price, signal.get("dir"), signal.get("ins"))
    wick_noise = _wick_noise_level(candles or [])
    news = _detect_news_risk(pair, now_dt)

    adx_val = _safe_float(signal.get("adx"), default=0.0)
    bb_width_pips = None
    if candles and len(candles) >= 20:
        closes = [c.get("c") for c in candles if c.get("c") is not None]
        if len(closes) >= 20:
            bb = bollinger(closes, 20)
            if bb:
                bb_width_pips = abs(bb["u"] - bb["l"]) / p

    payload = {
        "pair": pair,
        "direction": direction,
        "timeframe": "M1",
        "entry_time": next_minute(),
        "entry_price": signal_price,
        "current_price": current_price,
        "strategy": signal.get("strategy_name_en") or signal.get("strategy_name") or signal.get("strategy") or "unknown",
        "local_confidence": int(_safe_float(signal.get("conf"), 0)),
        "indicators": {
            "rsi": signal.get("rsi"),
            "macd": "bullish" if _safe_float(signal.get("macd_hist")) > 0 else ("bearish" if _safe_float(signal.get("macd_hist")) < 0 else "unknown"),
            "ema20": None,
            "ema50": None,
            "adx": signal.get("adx"),
            # Balanced Bollinger tuning: treat only very narrow bands as tight/choppy.
            "bollinger_width": "tight" if (bb_width_pips is not None and bb_width_pips < 4.5) else ("normal" if bb_width_pips is not None else "unknown"),
            "plus_di": signal.get("plus_di"),
            "minus_di": signal.get("minus_di"),
            "mom3": signal.get("mom3"),
            "mom5": signal.get("mom5"),
        },
        "market_structure": {
            "trend": "up" if signal.get("dir") == "UP" else "down",
            "support_distance": round(support_distance, 2) if support_distance is not None else None,
            "resistance_distance": round(resistance_distance, 2) if resistance_distance is not None else None,
            "last_5_candles": "overlap_high" if _candle_overlap_is_high(candles or []) else "clean",
            "wick_noise": wick_noise,
        },
        "news": news,
        "timing": {
            "seconds_before_entry": 23,
            "price_moved_from_signal": abs(current_price - signal_price),
            "price_moved_pips": round(abs(current_price - signal_price) / p, 2),
        },
        "meta": {
            "ins": signal.get("ins"),
            "pair_flags": signal.get("pair_flags"),
            "near_sr_against": near_against,
            "bb_width_pips": round(bb_width_pips, 2) if bb_width_pips is not None else None,
        },
    }
    return payload

def run_hard_filters(payload):
    reasons = []
    hard_block = False
    soft_flags = 0
    adx_val = _safe_float(payload["indicators"].get("adx"), 0)
    # News proximity hard block disabled by request.
    if adx_val and adx_val < 18:
        soft_flags += 1
        reasons.append("ADX أقل من 18 (سوق متذبذب)")
    if payload["indicators"].get("bollinger_width") == "tight":
        soft_flags += 1
        reasons.append("Bollinger Bands ضيقة جدًا")
    if payload["market_structure"].get("last_5_candles") == "overlap_high":
        soft_flags += 1
        reasons.append("الشموع الأخيرة متداخلة بشدة")
    if payload["market_structure"].get("wick_noise") == "high":
        soft_flags += 1
        reasons.append("wick noise مرتفع")
    if payload.get("meta", {}).get("near_sr_against"):
        soft_flags += 1
        reasons.append("السعر قريب من دعم/مقاومة عكس الاتجاه")

    max_allowed_move_pips = max(2.0, _safe_float(payload["meta"].get("bb_width_pips"), 8.0) * 0.35)
    # Post-signal price move hard block disabled by request.

    # Indicator contradiction checks.
    direction = payload.get("direction")
    macd = payload["indicators"].get("macd")
    trend = payload["market_structure"].get("trend")
    rsi_v = _safe_float(payload["indicators"].get("rsi"), 50)
    ema_trend_ok = (direction == "CALL" and trend == "up") or (direction == "PUT" and trend == "down")
    macd_ok = (direction == "CALL" and macd == "bullish") or (direction == "PUT" and macd == "bearish")
    rsi_ok = (direction == "CALL" and rsi_v <= 72) or (direction == "PUT" and rsi_v >= 28)
    plus_di = _safe_float(payload["indicators"].get("plus_di"), 0)
    minus_di = _safe_float(payload["indicators"].get("minus_di"), 0)
    di_ok = (direction == "CALL" and plus_di >= minus_di) or (direction == "PUT" and minus_di >= plus_di)

    contradictions = sum(1 for ok in (ema_trend_ok, macd_ok, rsi_ok, di_ok) if not ok)
    if contradictions >= 2:
        soft_flags += 2
        reasons.append("تعارض قوي بين المؤشرات")
    # Balanced mode:
    # - hard blocks always reject (news / excessive move)
    # - softer choppy/SR conditions require accumulation before rejecting
    passes = (not hard_block) and (soft_flags < 3)
    return {
        "pass": passes,
        "reasons": reasons,
        "max_allowed_move_pips": round(max_allowed_move_pips, 2),
        "soft_flags": soft_flags,
        "hard_block": hard_block,
    }

def _build_ai_review_user_prompt(payload):
    return "راجع الإشارة التالية وأعد JSON فقط:\n" + json.dumps(payload, ensure_ascii=False, indent=2)

async def groq_validate_signal(session, best):
    if not CONFIG.get("groq_key"):
        return None
    try:
        async with session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {CONFIG['groq_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                "messages": [
                    {"role": "system", "content": AI_REVIEWER_SYSTEM_PROMPT},
                    {"role": "user", "content": _build_ai_review_user_prompt(best)},
                ],
                "temperature": 0.05,
                "max_tokens": 420,
            },
            timeout=aiohttp.ClientTimeout(total=12),
        ) as r:
            if r.status != 200:
                L.warning(f"Groq validator HTTP {r.status}")
                return None
            d = await r.json()
            raw = d["choices"][0]["message"]["content"].strip()
            result = normalize_ai_json(raw)
            if result:
                result["provider"] = "Groq"
            return result
    except Exception as e:
        L.warning(f"Groq validator error: {e}")
        return None

async def claude_validate_signal(session, best):
    if not CONFIG.get("claude_key"):
        return None
    try:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": CONFIG["claude_key"],
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
                "max_tokens": 420,
                "temperature": 0.05,
                "system": AI_REVIEWER_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": _build_ai_review_user_prompt(best)}],
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            if r.status != 200:
                L.warning(f"Claude validator HTTP {r.status}")
                return None
            d = await r.json()
            raw = "".join(x.get("text", "") for x in d.get("content", []) if x.get("type") == "text")
            result = normalize_ai_json(raw)
            if result:
                result["provider"] = "Claude"
            return result
    except Exception as e:
        L.warning(f"Claude validator error: {e}")
        return None

def parse_ai_review_response(res, local_confidence):
    if not res:
        return None
    decision = str(res.get("decision", "")).upper()
    if decision not in ("APPROVE", "REJECT", "WAIT"):
        return None
    try:
        confidence = int(float(res.get("confidence", local_confidence)))
    except Exception:
        confidence = int(local_confidence)
    confidence = max(0, min(100, confidence))
    risk_level = str(res.get("risk_level") or res.get("risk") or "medium").lower()
    if risk_level not in ("low", "medium", "high"):
        risk_level = "medium"
    filters = res.get("filters") if isinstance(res.get("filters"), dict) else {}
    return {
        "decision": decision,
        "confidence": confidence,
        "risk_level": risk_level,
        "reason_ar": str(res.get("reason_ar") or res.get("reason") or "")[:260],
        "reason_en": str(res.get("reason_en") or "")[:260],
        "filters": filters,
        "provider": str(res.get("provider") or "AI"),
    }

async def call_ai_reviewer(session, payload):
    if not CONFIG.get("ai_review_enabled", True):
        return {
            "decision": "APPROVE",
            "confidence": int(_safe_float(payload.get("local_confidence"), 0)),
            "risk_level": "medium",
            "reason_ar": "مراجعة AI معطلة",
            "reason_en": "AI review disabled",
            "filters": {},
            "provider": "Local",
            "error": None,
        }
    provider = str(CONFIG.get("ai_provider", "auto")).lower()
    attempts = []
    if provider == "groq":
        attempts = [groq_validate_signal]
    elif provider == "claude":
        attempts = [claude_validate_signal]
    else:
        attempts = [groq_validate_signal, claude_validate_signal]

    for fn in attempts:
        res = await fn(session, payload)
        if not res:
            continue
        parsed = parse_ai_review_response(res, payload.get("local_confidence", 0))
        if not parsed:
            continue
        provider_name = parsed.get("provider", "AI")
        STATS["ai"] = f"🤖 {provider_name} Reviewer"
        L.info(f"  🤖 {provider_name}: {parsed['decision']} {parsed['confidence']}%")
        parsed["error"] = None
        return parsed

    STATS["ai"] = "📊 Local Fallback"
    return {
        "decision": "REJECT",
        "confidence": int(_safe_float(payload.get("local_confidence"), 0)),
        "reason_ar": "AI unavailable",
        "reason_en": "AI unavailable",
        "risk_level": "high",
        "filters": {},
        "provider": "Local",
        "error": "ai_unavailable",
    }

def finalize_ai_decision(hard_filter_result, ai_result, settings, local_confidence):
    min_ai_conf = int(settings.get("minimum_ai_confidence", 75) or 75)
    failure_mode = str(settings.get("ai_failure_mode", "reject")).lower()
    if not hard_filter_result.get("pass", False):
        return {
            "decision": "REJECT",
            "confidence": int(local_confidence),
            "reason_ar": "Hard filters failed: " + " | ".join(hard_filter_result.get("reasons", [])),
            "reason_en": "Hard filters failed",
            "risk_level": "high",
            "source": "hard_filters",
        }
    if not ai_result or ai_result.get("error"):
        if failure_mode == "strong_only" and int(local_confidence) >= 90:
            return {
                "decision": "APPROVE",
                "confidence": int(local_confidence),
                "reason_ar": "AI failed, strong strategy fallback approved",
                "reason_en": "AI failed, strong strategy fallback approved",
                "risk_level": "medium",
                "source": "fallback_strong",
            }
        return {
            "decision": "REJECT",
            "confidence": int(local_confidence),
            "reason_ar": "AI unavailable",
            "reason_en": "AI unavailable",
            "risk_level": "high",
            "source": "ai_error",
        }

    decision = str(ai_result.get("decision", "REJECT")).upper()
    conf = int(_safe_float(ai_result.get("confidence"), local_confidence))
    if decision == "APPROVE" and conf < min_ai_conf:
        decision = "WAIT" if conf >= 60 else "REJECT"
    if decision == "APPROVE" and conf >= 85:
        decision = "APPROVE_STRONG"
    return {
        "decision": decision,
        "confidence": conf,
        "reason_ar": ai_result.get("reason_ar") or ai_result.get("reason_en") or "",
        "reason_en": ai_result.get("reason_en") or "",
        "risk_level": ai_result.get("risk_level", "medium"),
        "source": ai_result.get("provider", "AI"),
    }

def should_send_signal(final_decision):
    return str(final_decision.get("decision", "")).upper() in ("APPROVE", "APPROVE_STRONG")

# ══════════════════════════════════════════
#  بناء الإشارة النهائية (واحدة فقط)
# ══════════════════════════════════════════
async def build_signal(session, pairs_data, market_data=None):
    """
    اختيار أفضل زوج وإرسال صفقة واحدة فقط
    مع منع تكرار نفس الإشارة أكثر من مرتين متتاليتين
    """
    global LAST_SIGNAL
    if not pairs_data: return None

    # ترتيب حسب: conf + pa_score + confluence
    def score_pair(a):
        pa_bonus = 25 if a["pa"] else 0
        confluence = abs(a["bs"]-a["ss"]) / (a["bs"]+a["ss"]+1)
        # خصم طفيف إذا كانت نفس الإشارة السابقة (لتحفيز التنوع)
        repeat_penalty = 0
        if (LAST_SIGNAL["pair"] == a["ins"] and
            LAST_SIGNAL["direction"] == a["dir"] and
            LAST_SIGNAL["count"] >= 2):
            repeat_penalty = 15  # خصم 15 نقطة لتفضيل زوج آخر
        return a["conf"] + pa_bonus + confluence*20 - repeat_penalty

    # ترتيب كل الأزواج
    sorted_pairs = sorted(pairs_data, key=score_pair, reverse=True)

    # اختيار أفضل زوج
    # قاعدة إضافية: لا نكرر نفس الزوج إذا كان هناك زوج آخر بثقة أعلى.
    best = sorted_pairs[0]
    if LAST_SIGNAL["pair"] == best["ins"]:
        better_alternatives = [
            x for x in pairs_data
            if x.get("ins") != best["ins"] and float(x.get("conf", 0)) > float(best.get("conf", 0))
        ]
        if better_alternatives:
            alt_best = max(better_alternatives, key=lambda x: float(x.get("conf", 0)))
            L.info(
                f"  🔁 منع تكرار الزوج: اختيار {alt_best['pair']} ({alt_best['conf']}%) "
                f"بدلاً من {best['pair']} ({best['conf']}%)"
            )
            best = alt_best

    # إذا كان الأفضل هو نفس الإشارة السابقة 3 مرات أو أكثر
    # وهناك بديل مقبول — اختر البديل
    if (len(sorted_pairs) > 1 and
        LAST_SIGNAL["pair"] == best["ins"] and
        LAST_SIGNAL["direction"] == best["dir"] and
        LAST_SIGNAL["count"] >= 3):
        # هل البديل قريب في القوة (فرق أقل من 10 نقاط)؟
        alt = sorted_pairs[1]
        if best["conf"] - alt["conf"] <= 10:
            best = alt
            L.info(f"  🔄 تبديل لمنع التكرار: {alt['pair']} بدلاً من {sorted_pairs[0]['pair']}")
        else:
            L.info(f"  ♻️ نفس الإشارة (لا يوجد بديل أقوى): {best['pair']}")

    L.info(f"  ⭐ أفضل زوج: {best['pair']} {best['dir']} {best['conf']}%")

    # تحديث عداد التكرار
    if LAST_SIGNAL["pair"] == best["ins"] and LAST_SIGNAL["direction"] == best["dir"]:
        LAST_SIGNAL["count"] += 1
    else:
        LAST_SIGNAL = {"pair": best["ins"], "direction": best["dir"], "count": 1}

    # Strategy Signal -> Hard Filters -> AI Review -> Final Decision.
    candles = (market_data or {}).get(best.get("ins")) if isinstance(market_data, dict) else None
    payload = build_ai_review_payload(best, candles=candles)
    hard_result = run_hard_filters(payload)
    call_put = "CALL" if best["dir"] == "UP" else "PUT"
    if not hard_result.get("pass"):
        L.info(f"  ❌ HARD FILTER REJECTED {best['pair']} {call_put} reason: {' | '.join(hard_result.get('reasons', []))}")
        return None
    ai_result = await call_ai_reviewer(session, payload)
    final_decision = finalize_ai_decision(hard_result, ai_result, CONFIG, best["conf"])
    ai_decision = str(final_decision.get("decision", "REJECT")).upper()
    final_conf = int(final_decision.get("confidence", best["conf"]))
    ai_reason = final_decision.get("reason_ar") or final_decision.get("reason_en") or ""
    if not should_send_signal(final_decision):
        if ai_decision == "WAIT":
            L.info(f"  ⏳ AI WAIT {best['pair']} {call_put} confidence {final_conf} reason: {ai_reason}")
        elif final_decision.get("source") == "ai_error":
            L.warning("  ⚠️ AI ERROR: invalid response / timeout")
            L.info(f"  ❌ AI REJECTED {best['pair']} {call_put} confidence {final_conf} reason: AI unavailable")
        else:
            L.info(f"  ❌ AI REJECTED {best['pair']} {call_put} confidence {final_conf} reason: {ai_reason}")
        return None

    final_dir = best["dir"]
    source = final_decision.get("source", "ai")
    L.info(f"  ✅ AI APPROVED {best['pair']} {call_put} confidence {final_conf}")

    # بناء الأسباب
    reasons = []
    if best["pa"]:  reasons.append(f"نمط: {best['pa']}")
    if ai_reason:   reasons.append(f"AI: {ai_reason}")
    reasons += [r for r in best["reasons"] if r not in reasons]

    now = datetime.now()
    next_min = (now.replace(second=0,microsecond=0)+timedelta(minutes=1)).strftime("%H:%M:00")

    signal = {
        "ins"       : best["ins"],
        "pair"      : best["pair"],
        "direction" : final_dir,
        "confidence": final_conf,
        "rsi"       : best["rsi"],
        "pa"        : best["pa"],
        "ema"       : best["ema_trend"],
        "reasons"   : reasons[:3],
        "badges"    : best["badges"],
        "time"      : now.strftime("%H:%M:%S"),
        "next_min"  : next_min,
        "ai_source" : STATS["ai"],
        "source"    : source,
        "ai_decision": ai_decision,
        "ai_reason" : ai_reason,
        "ai_risk"   : final_decision.get("risk_level", "medium"),
        "price"     : best["price"],
        "pair_flags": best.get("pair_flags", ""),
        "strategy"  : best.get("strategy", CONFIG.get("strategy", "confluence")),
        "strategy_icon": best.get("strategy_icon", "🧠"),
        "strategy_name": best.get("strategy_name", "Confluence"),
        "strategy_name_ar": best.get("strategy_name_ar", "التوافق الذكي"),
        "strategy_name_en": best.get("strategy_name_en", "Confluence"),
    }
    return signal

# ══════════════════════════════════════════
#  تيليغرام
# ══════════════════════════════════════════
def build_tg(sig):
    arr = "🟢⬆️" if sig["direction"]=="UP" else "🔴⬇️"
    act_ar = "صعود" if sig["direction"]=="UP" else "هبوط"
    act_en = "UP" if sig["direction"]=="UP" else "DOWN"
    pair_text = f"{sig.get('pair_flags','')} {sig['pair']}".strip()
    lines = [
        "📈 NEXO TRADE",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{arr}  الاتجاه : {act_ar}",
        f"💱  الزوج : {pair_text}",
        f"⏰  وقت الدخول : {sig['next_min']}",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "⚠️  المسؤولية على المتداول / Trade at your own risk",
        "📌  ادخل مضاعفة في حال الخسارة / Use martingale after loss",
        f"Direction : {act_en}",
        f"Pair : {pair_text}",
        f"Entry Time : {sig['next_min']}",
    ]
    if CONFIG.get("show_ai_reason"):
        lines += [
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "مراجعة AI:",
            f"الثقة: {sig.get('confidence', 0)}%",
            f"السبب: {sig.get('ai_reason') or 'المؤشرات متوافقة'}",
        ]
    return "\n".join(lines)

async def send_tg(session, msg):
    tok=CONFIG["tg_token"]; ch=CONFIG["tg_channel"]
    if not tok or not ch: return False,"Token/Channel غير مضبوط"
    try:
        async with session.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={"chat_id":ch,"text":msg},
            timeout=aiohttp.ClientTimeout(total=12)
        ) as r:
            d=await r.json()
            return (True,"تم") if d.get("ok") else (False,d.get("description","خطأ"))
    except Exception as e:
        return False,str(e)

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def request_preview(req):
    return (
        "📥 طلب انضمام جديد\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Account ID: {req['account_id']}\n"
        f"📧 Email: {req['email']}\n"
        f"🕒 الوقت: {req['created_at']}\n"
        f"🔖 الطلب: {req['id']}\n"
        "🖼 الصورة: مرفقة في الرسالة\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

def access_request_preview(req):
    return (
        "🔐 طلب دخول جديد\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Account ID: {req['account_id']}\n"
        f"📧 Email: {req['email']}\n"
        f"🕒 الوقت: {req['created_at']}\n"
        f"🔖 الطلب: {req['id']}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

async def send_join_request_to_tg(session, req, image_bytes=None, image_filename="profile.jpg"):
    tok = CONFIG.get("access_tg_token") or CONFIG.get("tg_token")
    ch = CONFIG.get("access_tg_channel") or CONFIG.get("tg_channel")
    if not tok or not ch:
        return False, "TG_BOT_TOKEN / TG_CHANNEL_ID غير مضبوطين", None
    L.info(f"Join request target chat: {ch}")
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ قبول", "callback_data": f"join:approve:{req['id']}"},
                {"text": "❌ رفض", "callback_data": f"join:reject:{req['id']}"},
            ],
            [
                {"text": "📋 نسخ Account ID", "copy_text": {"text": req["account_id"]}}
            ],
        ]
    }
    try:
        if image_bytes:
            fd = aiohttp.FormData()
            fd.add_field("chat_id", str(ch))
            fd.add_field("caption", request_preview(req))
            fd.add_field("reply_markup", json.dumps(reply_markup, ensure_ascii=False))
            fd.add_field("photo", image_bytes, filename=image_filename, content_type="application/octet-stream")
            async with session.post(
                f"https://api.telegram.org/bot{tok}/sendPhoto",
                data=fd,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as r:
                d = await r.json()
                if not d.get("ok"):
                    return False, d.get("description", "فشل إرسال الصورة"), None
                msg_id = d.get("result", {}).get("message_id")
                return True, "تم", msg_id
        payload = {"chat_id": ch, "text": request_preview(req), "reply_markup": reply_markup}
        async with session.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=12)
        ) as r:
            d = await r.json()
            if not d.get("ok"):
                return False, d.get("description", "فشل إرسال الطلب"), None
            msg_id = d.get("result", {}).get("message_id")
            return True, "تم", msg_id
    except Exception as e:
        return False, str(e), None

async def send_access_request_to_tg(session, req):
    tok = CONFIG.get("access_tg_token")
    ch = CONFIG.get("access_tg_channel")
    if not tok or not ch:
        return False, "ACCESS_REQUEST_TG_BOT_TOKEN / ACCESS_REQUEST_TG_CHANNEL_ID غير مضبوطين", None
    L.info(f"Access request target chat: {ch}")
    payload = {"chat_id": ch, "text": access_request_preview(req)}
    try:
        async with session.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=12)
        ) as r:
            d = await r.json()
            if not d.get("ok"):
                return False, d.get("description", "فشل إرسال طلب الدخول"), None
            msg_id = d.get("result", {}).get("message_id")
            return True, "تم", msg_id
    except Exception as e:
        return False, str(e), None

def find_request(req_id):
    with db_connect() as con:
        row = con.execute("SELECT * FROM join_requests WHERE id = ?", (req_id,)).fetchone()
    if row:
        return dict(row)
    return next((x for x in JOIN_REQUESTS if x["id"] == req_id), None)

def set_request_status(req, new_status, actor="admin"):
    if not req:
        return None
    updated_at = now_iso()
    req["status"] = new_status
    req["updated_at"] = updated_at
    req["updated_by"] = actor
    with db_connect() as con:
        con.execute(
            "UPDATE join_requests SET status = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (new_status, updated_at, actor, req["id"]),
        )
        if new_status == "approved":
            con.execute(
                """
                INSERT OR REPLACE INTO approved_users(account_id, join_request_id, email, image_url, approved_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (req["account_id"], req["id"], req["email"], req["image_url"], updated_at),
            )
    return req

async def answer_callback(session, callback_id, text, tok):
    if not tok:
        return
    try:
        await session.post(
            f"https://api.telegram.org/bot{tok}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text, "show_alert": False},
            timeout=aiohttp.ClientTimeout(total=10),
        )
    except Exception:
        pass

async def clear_join_request_buttons(session, req):
    tok = CONFIG.get("access_tg_token") or CONFIG.get("tg_token")
    ch = CONFIG.get("access_tg_channel") or CONFIG.get("tg_channel")
    msg_id = (req or {}).get("tg_message_id")
    if not tok or not ch or not msg_id:
        return
    try:
        await session.post(
            f"https://api.telegram.org/bot{tok}/editMessageReplyMarkup",
            json={"chat_id": ch, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}},
            timeout=aiohttp.ClientTimeout(total=12),
        )
    except Exception as e:
        L.warning(f"Failed to clear join request buttons: {e}")

async def process_tg_updates():
    global TG_UPDATE_OFFSET
    # Callback buttons for join/access requests are sent via ACCESS TG bot (when configured).
    tok = CONFIG.get("access_tg_token") or CONFIG.get("tg_token")
    if not tok:
        return
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(
                    f"https://api.telegram.org/bot{tok}/getUpdates",
                    params={"timeout": 20, "offset": TG_UPDATE_OFFSET, "allowed_updates": json.dumps(["callback_query"])},
                    timeout=aiohttp.ClientTimeout(total=25),
                ) as r:
                    data = await r.json()
                    if not data.get("ok"):
                        await asyncio.sleep(2)
                        continue
                    for upd in data.get("result", []):
                        TG_UPDATE_OFFSET = upd["update_id"] + 1
                        cb = upd.get("callback_query")
                        if not cb:
                            continue
                        cb_data = cb.get("data", "")
                        parts = cb_data.split(":")
                        if len(parts) != 3 or parts[0] != "join":
                            await answer_callback(session, cb["id"], "إجراء غير معروف", tok)
                            continue
                        action, req_id = parts[1], parts[2]
                        req = find_request(req_id)
                        if not req:
                            await answer_callback(session, cb["id"], "الطلب غير موجود", tok)
                            continue
                        if req["status"] != "pending":
                            await answer_callback(session, cb["id"], f"تمت المعالجة سابقاً: {req['status']}", tok)
                            continue
                        if action == "approve":
                            set_request_status(req, "approved", actor=f"tg:{cb.get('from',{}).get('id','?')}")
                            await clear_join_request_buttons(session, req)
                            await answer_callback(session, cb["id"], "تم قبول المستخدم ✅", tok)
                        elif action == "reject":
                            set_request_status(req, "rejected", actor=f"tg:{cb.get('from',{}).get('id','?')}")
                            await clear_join_request_buttons(session, req)
                            await answer_callback(session, cb["id"], "تم رفض الطلب ❌", tok)
                        else:
                            await answer_callback(session, cb["id"], "إجراء غير معروف", tok)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                L.warning(f"Telegram updates error: {e}")
                await asyncio.sleep(2)

# ══════════════════════════════════════════
#  التوقيت — الثانية :37 (قبل نهاية الدقيقة بـ 23 ثانية)
# ══════════════════════════════════════════
def secs_until_37():
    now = datetime.now()
    s   = now.second
    return (37-s) if s<37 else (60-s+37)

def next_minute():
    now = datetime.now()
    return (now.replace(second=0,microsecond=0)+timedelta(minutes=1)).strftime("%H:%M:00")

def can_emit_signal(sig):
    """Prevent sending two signals in the same minute."""
    global LAST_SIGNAL_MINUTE, LAST_SIGNAL_ENTRY, LAST_SIGNAL_TS
    now_min = datetime.now().strftime("%Y-%m-%d %H:%M")
    now_ts = time.time()
    entry_min = (sig or {}).get("next_min")
    # Enforce a strict cooldown of 2 minutes between trades.
    if LAST_SIGNAL_TS and (now_ts - LAST_SIGNAL_TS) < 120:
        return False
    if LAST_SIGNAL_MINUTE == now_min:
        return False
    if entry_min and LAST_SIGNAL_ENTRY == entry_min:
        return False
    LAST_SIGNAL_TS = now_ts
    LAST_SIGNAL_MINUTE = now_min
    LAST_SIGNAL_ENTRY = entry_min
    return True

# ══════════════════════════════════════════
#  حلقة البوت الرئيسية
# ══════════════════════════════════════════
async def bot_loop():
    global cd_val
    L.info("▶ البوت بدأ — ينتظر الثانية :37 من كل دقيقة")

    async with aiohttp.ClientSession() as session:
        # رسالة بدء
        if CONFIG["auto_telegram"]:
            start_msg = (
                "📈 إشارات التداول\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "✅  تم تشغيل البوت\n"
                f"📊  {len(CONFIG['active_pairs'])} أزواج نشطة\n"
                "⏰  المهلة بين كل صفقة دقيقتان\n"
                "🔬  Groq AI + Claude + محلي\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💱  الأزواج: " + " | ".join(pname(p) for p in CONFIG["active_pairs"])
            )
            await send_tg(session, start_msg)

        while CONFIG["bot_running"]:
            if not is_trading_window_open():
                CONFIG["bot_running"] = False
                cd_val = -1
                L.warning(market_closed_message())
                break
            # انتظر حتى الثانية 37
            wait = secs_until_37()
            L.info(f"⏳ انتظار {wait} ثانية...")
            for i in range(wait, 0, -1):
                if not CONFIG["bot_running"]: return
                cd_val = i
                await asyncio.sleep(1)

            if not CONFIG["bot_running"]: return
            cd_val = 0
            STATS["cycles"] += 1
            now_s = datetime.now().strftime("%H:%M:%S")
            nm    = next_minute()
            L.info(f"🔔 [{now_s}] وقت الإشارة! الدخول في {nm}")

            # ── جلب البيانات وتحليل كل الأزواج ──
            pairs_data = []
            market_data = {}
            for ins in CONFIG["active_pairs"]:
                cn = await get_candles(session, ins)
                if not cn:
                    L.warning(f"  ⚠️ {ins}: لا توجد بيانات حقيقية من OANDA (السوق مغلق/لا اتصال)")
                    continue
                if not market_is_moving(ins, cn):
                    L.info(f"  💤 {ins}: السوق شبه ثابت — لا إشارة")
                    continue
                res = analyze_local(ins, cn, CONFIG.get("strategy"))
                if res:
                    market_data[ins] = cn
                    pairs_data.append(res)
                    L.info(f"  {res['pair']}: {res['dir']} {res['conf']}% [{res.get('strategy_name','Confluence')}] (PA:{res['pa'] or '—'})")

            if not pairs_data:
                L.warning("  ❌ لا بيانات")
                await asyncio.sleep(5)
                continue

            # ── صفقة واحدة — الأقوى ──
            sig = await build_signal(session, pairs_data, market_data=market_data)
            if not sig or sig["confidence"] < CONFIG["min_confidence"]:
                L.info(f"  ⏳ أعلى ثقة {sig['confidence'] if sig else 0}% < {CONFIG['min_confidence']}% — لا إشارة")
                await asyncio.sleep(5)
                continue
            if not can_emit_signal(sig):
                L.info("  ⛔ تم منع إشارة مكررة داخل نفس الدقيقة")
                await asyncio.sleep(5)
                continue

            # حفظ الإشارة
            HISTORY.insert(0, sig)
            STATS["total"]  += 1
            STATS["last"]    = now_s
            while len(HISTORY)>30: HISTORY.pop()

            L.info(f"  🎯 إشارة: {sig['pair']} {sig['direction']} {sig['confidence']}% [{STATS['ai']}]")

            # إرسال تيليغرام
            if CONFIG["auto_telegram"]:
                msg    = build_tg(sig)
                ok,err = await send_tg(session, msg)
                if ok:  STATS["sent_tg"]+=1; L.info("  ✅ تيليغرام أُرسل")
                else:   L.error(f"  ❌ تيليغرام: {err}")

            # انتظر 5 ثواني لتجنب التكرار
            await asyncio.sleep(5)

# ══════════════════════════════════════════
#  لوحة الإدمن HTML
# ══════════════════════════════════════════
HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXO TRADE | Trading Signals</title>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#050B16;--s1:#0D1322;--s2:#101827;--bd:rgba(255,255,255,0.08);
  --gold:#1565FF;--g2:#1D7CFF;--g3:#3B82F6;
  --up:#22C55E;--dn:#EF4444;--ac:#1565FF;
  --tx:#F8FAFC;--mt:#94A3B8;--pur:#1565FF;
  --page-gradient:linear-gradient(180deg,#050B16 0%,#0D1322 52%,#050B16 100%);
  --btn-primary:linear-gradient(to right,#6C4AF2 0%,#6B49F7 50%,#6A47EE 100%);
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--page-gradient) fixed;color:var(--tx);font-family:'Cairo','Inter','Segoe UI',Tahoma,sans-serif;min-height:100vh;direction:rtl;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
body::before,body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:0}
body::before{background:radial-gradient(40% 35% at 92% 6%, rgba(21,101,255,.18), transparent 70%),radial-gradient(36% 30% at 6% 94%, rgba(21,101,255,.14), transparent 72%),radial-gradient(60% 52% at 50% 30%, rgba(100,116,139,.08), transparent 80%)}
body::after{background:repeating-linear-gradient(135deg, rgba(21,101,255,.08) 0 1px, transparent 1px 22px),radial-gradient(circle at 1px 1px, rgba(148,163,184,.2) 1px, transparent 1px);background-size:auto,16px 16px;mask-image:linear-gradient(to top, transparent, black 25%, black 72%, transparent);opacity:.25}

/* ── شاشة الدخول: NEXO TRADE Identity ── */
#LS{
  position:fixed;inset:0;z-index:99;
  background:
    radial-gradient(58% 44% at 9% 88%, rgba(21,101,255,.20) 0%, rgba(21,101,255,0) 78%),
    radial-gradient(52% 40% at 88% 10%, rgba(21,101,255,.17) 0%, rgba(21,101,255,0) 74%),
    radial-gradient(65% 55% at 50% 0%, rgba(100,116,139,.13) 0%, rgba(100,116,139,0) 70%),
    var(--page-gradient);
  display:flex;align-items:flex-start;justify-content:center;
  padding:max(18px, env(safe-area-inset-top)) 18px max(28px, env(safe-area-inset-bottom));
  overflow-y:auto;-webkit-overflow-scrolling:touch;
  isolation:isolate;
}
.lbox{
  width:100%;max-width:440px;margin:0 auto;
  background:rgba(13,19,34,.75);
  border:1px solid rgba(255,255,255,.08);
  border-radius:24px;
  backdrop-filter:blur(10px);
  -webkit-backdrop-filter:blur(10px);
  padding:26px 20px 18px;
  box-shadow:
    0 20px 60px rgba(4,9,20,.55),
    0 0 0 1px rgba(21,101,255,.10) inset,
    0 0 36px rgba(21,101,255,.16);
  position:relative;overflow:hidden;
  z-index:1;
}
.ls-decor{position:absolute;inset:0;pointer-events:none;z-index:0;overflow:hidden}
.ls-glow-t,.ls-glow-b{position:absolute;border-radius:50%;filter:blur(28px)}
.ls-glow-t{width:260px;height:260px;top:-130px;right:-70px;background:rgba(21,101,255,.20)}
.ls-glow-b{width:260px;height:260px;bottom:-140px;left:-80px;background:rgba(21,101,255,.15)}
.ls-x{
  position:absolute;left:50%;top:44%;
  transform:translate(-50%,-50%) rotate(-10deg);
  font-size:clamp(210px,44vw,370px);font-weight:700;
  line-height:1;color:rgba(21,101,255,.10);
  letter-spacing:.03em;
}
.ls-candles{
  position:absolute;top:110px;right:24px;width:86px;height:112px;opacity:.34;
  background:
    linear-gradient(rgba(21,101,255,.85),rgba(21,101,255,.85)) 8px 58px/2px 38px no-repeat,
    linear-gradient(rgba(21,101,255,.85),rgba(21,101,255,.85)) 18px 36px/9px 54px no-repeat,
    linear-gradient(rgba(21,101,255,.85),rgba(21,101,255,.85)) 31px 48px/2px 30px no-repeat,
    linear-gradient(rgba(21,101,255,.85),rgba(21,101,255,.85)) 40px 26px/10px 58px no-repeat,
    linear-gradient(rgba(21,101,255,.85),rgba(21,101,255,.85)) 56px 45px/2px 34px no-repeat,
    linear-gradient(rgba(21,101,255,.85),rgba(21,101,255,.85)) 62px 34px/9px 45px no-repeat,
    linear-gradient(rgba(21,101,255,.85),rgba(21,101,255,.85)) 75px 52px/8px 30px no-repeat;
}
.ls-grid{
  position:absolute;left:-8%;right:-8%;bottom:-44px;height:190px;opacity:.23;
  background-image:radial-gradient(circle at 1px 1px, rgba(100,116,139,.72) 1.2px, transparent 1.2px);
  background-size:14px 14px;
  mask-image:linear-gradient(to top, black 14%, transparent 90%);
}
.ls-lines{
  position:absolute;inset:-24%;opacity:.11;
  background:repeating-linear-gradient(135deg, rgba(21,101,255,.72) 0 2px, transparent 2px 24px);
}
.ls-content{position:relative;z-index:1}
.ltit{text-align:center;margin-bottom:8px}
.lang-switch{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-bottom:10px}
.lang-switch label{font-size:11px;color:#9fb3d1;font-weight:700}
.lang-switch select{background:rgba(13,19,34,.86);color:#e2e8f0;border:1px solid rgba(255,255,255,.1);border-radius:10px;padding:8px 10px;font-family:'Cairo','Inter','Segoe UI',Tahoma,sans-serif;font-size:12px;outline:none}
.logo-main{
  font-size:clamp(40px,9vw,58px);
  line-height:1.03;font-weight:600;letter-spacing:.12em;
  color:#edf1ff;text-transform:uppercase;text-shadow:0 0 26px rgba(21,101,255,.20);
}
.logo-main .x{color:#1565FF;text-shadow:0 0 24px rgba(21,101,255,.62)}
.logo-sub-wrap{margin-top:10px;display:flex;align-items:center;justify-content:center;gap:12px}
.logo-sub-wrap .line{height:1px;width:52px;background:linear-gradient(90deg,transparent,#64748B,transparent)}
.logo-sub{color:#1565FF;letter-spacing:.55em;font-size:12px;font-weight:600;padding-inline-start:.55em}
.ltit p{font-size:11px;color:#8fa2c0;margin-top:12px}
.lsep{height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.14),transparent);margin:18px 0}
.lf{margin-bottom:14px}
.lf label{display:block;font-size:11px;color:#9db7dd;font-weight:700;margin-bottom:5px}
.lf input{width:100%;padding:13px 14px;background:rgba(9,15,27,.78);border:1px solid rgba(100,116,139,.33);border-radius:10px;color:var(--tx);font-size:15px;font-family:'Cairo','Inter','Segoe UI',Tahoma,sans-serif;outline:none;transition:border-color .2s, box-shadow .2s}
.lf input:focus{border-color:#1565FF;box-shadow:0 0 0 3px rgba(21,101,255,.17)}
.lbtn{width:100%;padding:15px;margin-top:6px;background:var(--btn-primary);border:none;border-radius:11px;color:#f6f2ff;font-family:'Cairo','Inter','Segoe UI',Tahoma,sans-serif;font-size:16px;font-weight:900;cursor:pointer;letter-spacing:.5px;box-shadow:0 10px 28px rgba(108,74,242,.35);transition:all .22s}
.lbtn:hover{transform:translateY(-2px);box-shadow:0 14px 36px rgba(21,101,255,.46);filter:brightness(1.07)}
.lerr{color:var(--dn);font-size:12px;text-align:center;margin-top:8px;display:none}

#LS{display:none !important}

/* ── Premium motion polish ── */
.topbar,.stat,.card,.bottom-nav{animation:dashIn .45s ease both}.stat:nth-child(2){animation-delay:.06s}.stat:nth-child(3){animation-delay:.1s}.stat:nth-child(4){animation-delay:.14s}.brand-logo{animation:logoGlow 3.4s ease-in-out infinite}@keyframes dashIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}@keyframes logoGlow{0%,100%{filter:drop-shadow(0 6px 18px rgba(21,101,255,.14))}50%{filter:drop-shadow(0 8px 26px rgba(21,101,255,.34))}}
/* ── التطبيق ── */
#APP{display:block;max-width:1360px;margin:0 auto;padding:14px 16px 96px;position:relative;z-index:1}

/* ── الشريط العلوي ── */
.topbar{background:linear-gradient(140deg,rgba(16,24,39,.88),rgba(13,19,34,.82));border:1px solid rgba(255,255,255,.08);border-radius:28px;padding:20px 24px;margin-bottom:18px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);box-shadow:0 16px 42px rgba(2,8,20,.42),0 0 0 1px rgba(21,101,255,.08) inset}
.tb-inner{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:14px}
.brand{display:flex;flex-direction:column;gap:7px}.brand-logo{display:block;width:min(240px,42vw);max-width:100%;height:auto;object-fit:contain;filter:drop-shadow(0 6px 18px rgba(21,101,255,.14))}.brand .b2{font-size:12px;color:#94A3B8;font-weight:600;letter-spacing:.02em}
.tb-right{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.sbadge{display:flex;align-items:center;gap:8px;padding:8px 14px;border-radius:999px;font-size:12px;font-weight:700;border:1px solid rgba(239,68,68,.38);color:#FCA5A5;background:rgba(239,68,68,.08);transition:all .25s}
.sbadge.on{border-color:rgba(34,197,94,.45);color:#86EFAC;background:rgba(34,197,94,.12)}
.sdot{width:8px;height:8px;border-radius:50%;background:#EF4444;transition:all .3s;flex-shrink:0}
.sdot.on{background:var(--up);animation:dp 1.2s infinite}
@keyframes dp{0%,100%{box-shadow:0 0 0 0 rgba(0,230,118,.5)}70%{box-shadow:0 0 0 7px rgba(0,230,118,0)}}
.cdbox{background:rgba(9,15,27,.78);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:7px 16px;text-align:center;box-shadow:inset 0 0 0 1px rgba(21,101,255,.1)}
.cdlbl{font-size:10px;color:var(--mt);letter-spacing:.4px}
.cd{font-family:'IBM Plex Mono',monospace;font-size:22px;font-weight:700;color:#1565FF;text-shadow:0 0 14px rgba(21,101,255,.4)}
.cd.urg{color:var(--dn);animation:up .5s ease-in-out infinite}
@keyframes up{0%,100%{opacity:1}50%{opacity:.5}}
.xbtn{padding:9px 14px;border-radius:12px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.04);color:#e2e8f0;font-family:'Cairo','Inter','Segoe UI',Tahoma,sans-serif;font-size:12px;font-weight:600;cursor:pointer;transition:all .2s}
.xbtn:hover{border-color:rgba(21,101,255,.46);background:rgba(21,101,255,.12);color:#fff}

/* ── الإحصاءات ── */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px}
.stat{background:rgba(16,24,39,.8);border:1px solid rgba(255,255,255,.1);border-radius:22px;padding:15px 16px;position:relative;overflow:hidden;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);min-height:108px;transition:all .2s}
.stat:hover{border-color:rgba(21,101,255,.34);background:rgba(19,30,49,.88)}
.stat::after{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.stat.g::after{background:linear-gradient(90deg,var(--gold),transparent)}
.stat.v::after{background:linear-gradient(90deg,var(--up),transparent)}
.stat.b::after{background:linear-gradient(90deg,var(--ac),transparent)}
.stat.p::after{background:linear-gradient(90deg,var(--pur),transparent)}
.st-l{font-size:11px;color:var(--mt);margin-bottom:8px;letter-spacing:.2px}
.st-v{font-size:30px;font-weight:800;font-family:'IBM Plex Mono',monospace;line-height:1}
.st-v.g{color:var(--gold)}.st-v.v{color:var(--up)}.st-v.b{color:var(--ac)}.st-v.p{color:var(--pur)}
.st-s{font-size:11px;color:var(--mt);margin-top:8px}

/* ── الشبكة ── */
.grid{display:grid;grid-template-columns:290px minmax(0,1fr);gap:14px}

/* ── البطاقات ── */
.card{background:rgba(16,24,39,.8);border:1px solid rgba(255,255,255,.1);border-radius:24px;overflow:hidden;margin-bottom:14px;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);box-shadow:0 14px 34px rgba(2,8,20,.36);transition:all .2s}
.card:hover{border-color:rgba(21,101,255,.4);box-shadow:0 18px 40px rgba(21,101,255,.12)}
.chd{padding:13px 16px;border-bottom:1px solid rgba(255,255,255,.08);display:flex;align-items:center;justify-content:space-between;background:linear-gradient(120deg,rgba(13,19,34,.9),rgba(16,24,39,.45))}
.ctit{font-size:14px;font-weight:700;color:#E2E8F0;letter-spacing:.01em}
.cbody{padding:14px 16px}

/* ── أزرار التحكم الرئيسية ── */
.start-btn{width:100%;padding:14px;background:#1565FF;border:none;border-radius:16px;color:#fff;font-family:'Cairo','Inter','Segoe UI',Tahoma,sans-serif;font-size:15px;font-weight:900;cursor:pointer;box-shadow:0 10px 24px rgba(21,101,255,.28);transition:all .22s;margin-bottom:8px;display:flex;align-items:center;justify-content:center;gap:7px}
.start-btn:hover{transform:translateY(-2px);background:#1D7CFF;box-shadow:0 14px 32px rgba(21,101,255,.4)}
.start-btn:disabled{opacity:.4;cursor:not-allowed;transform:none;box-shadow:none}
.pr{width:11px;height:11px;border-radius:50%;background:var(--up);animation:pr_ 1.4s infinite}
@keyframes pr_{0%{box-shadow:0 0 0 0 rgba(0,230,118,.7)}70%{box-shadow:0 0 0 9px rgba(0,230,118,0)}}
.stop-btn{width:100%;padding:11px;background:rgba(239,68,68,.9);border:none;border-radius:14px;color:#fff;font-family:'Cairo','Inter','Segoe UI',Tahoma,sans-serif;font-size:14px;font-weight:900;cursor:pointer;box-shadow:0 8px 20px rgba(239,68,68,.25);transition:all .22s;margin-bottom:8px}
.stop-btn:hover{transform:translateY(-2px);box-shadow:0 8px 22px rgba(255,61,87,.5)}
.stop-btn:disabled{opacity:.35;cursor:not-allowed;transform:none}
.act-btn{width:100%;padding:10px;border-radius:14px;border:none;cursor:pointer;font-family:'Cairo','Inter','Segoe UI',Tahoma,sans-serif;font-size:12px;font-weight:700;transition:all .2s;margin-bottom:7px;display:flex;align-items:center;justify-content:center;gap:6px}
.act-btn:hover{transform:translateY(-1px)}
.btn-b{background:rgba(255,255,255,.03);color:#BFDBFE;border:1px solid rgba(255,255,255,.14)}
.btn-b:hover{border-color:rgba(21,101,255,.45);background:rgba(21,101,255,.12)}
.btn-v{background:rgba(255,255,255,.03);color:#93C5FD;border:1px solid rgba(255,255,255,.14)}
.btn-v:hover{border-color:rgba(21,101,255,.45);background:rgba(21,101,255,.12)}
.btn-ch{background:linear-gradient(135deg,#1565FF,#38A8FF);color:#fff;border:1px solid rgba(56,168,255,.55);box-shadow:0 10px 24px rgba(21,101,255,.28)}
.btn-ch:hover{background:linear-gradient(135deg,#1D7CFF,#38A8FF);box-shadow:0 12px 28px rgba(21,101,255,.38)}
.btn-join{background:var(--btn-primary);color:#f6f2ff;border:1px solid rgba(108,74,242,.45);box-shadow:0 8px 22px rgba(108,74,242,.28)}
.btn-join:hover{background:var(--btn-primary);filter:brightness(1.06);box-shadow:0 10px 28px rgba(108,74,242,.42)}
.btn-g{background:rgba(255,255,255,.03);color:#BFDBFE;border:1px solid rgba(255,255,255,.16);padding:5px 11px;font-size:11px;border-radius:999px}
.btn-g:hover{background:rgba(232,184,75,.08)}
.btn-sm{padding:4px 9px;font-size:10px;border-radius:999px}

/* ── معلومة التوقيت ── */
.timing-info{background:rgba(21,101,255,.08);border:1px solid rgba(21,101,255,.24);border-radius:14px;padding:10px 12px;margin-bottom:11px;font-size:11px;color:#BFDBFE;line-height:1.9}
.timing-info b{color:var(--gold)}

/* ── الأزواج ── */
.pg{font-size:9px;color:var(--g3);font-weight:700;letter-spacing:1px;padding:6px 2px 2px;text-transform:uppercase}
.pi{display:flex;align-items:center;justify-content:space-between;padding:6px 7px;border-radius:7px;cursor:pointer;border:1px solid transparent;margin-bottom:2px;transition:background .15s}
.pi:hover{background:rgba(255,255,255,.04)}
.pi.on{background:rgba(21,101,255,.12);border-color:rgba(21,101,255,.42)}
.pn{font-weight:700;font-size:12px;font-family:'IBM Plex Mono',monospace;color:var(--tx)}
.pflags{display:inline-flex;align-items:center;gap:5px;min-width:46px;filter:drop-shadow(0 0 6px rgba(21,101,255,.16))}.flag-badge{width:18px;height:18px;border-radius:999px;object-fit:cover;border:1px solid rgba(255,255,255,.22);box-shadow:0 0 8px rgba(21,101,255,.16);background:rgba(255,255,255,.05)}
.pair-filter{background:rgba(9,15,27,.82);border:1px solid rgba(21,101,255,.22);color:#dbeafe;border-radius:10px;padding:6px 9px;font-family:'IBM Plex Mono',monospace;font-size:10px;outline:none}.pair-filter option{background:#050c15}.strategy-box{margin-top:10px;padding:12px;border-radius:16px;border:1px solid rgba(21,101,255,.18);background:linear-gradient(180deg,rgba(10,18,34,.85),rgba(5,12,21,.92));box-shadow:0 10px 30px rgba(5,11,22,.28)}
.strategy-head{display:flex;align-items:center;gap:10px;margin-bottom:6px}.strategy-ic{width:42px;height:42px;border-radius:14px;display:grid;place-items:center;background:radial-gradient(circle at 30% 20%,rgba(56,189,248,.34),rgba(21,101,255,.10) 55%,rgba(15,23,42,.85));border:1px solid rgba(21,101,255,.36);font-size:20px;box-shadow:0 0 22px rgba(21,101,255,.18)}.strategy-title{font-weight:800;color:#e8f1ff;font-size:13px}.strategy-desc{font-size:11px;color:var(--mt);line-height:1.7}.strategy-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.strategy-tag{padding:4px 8px;border-radius:999px;font-size:10px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.03);color:#9cc2ff}.s-strategy{display:inline-flex;align-items:center;gap:6px;padding:4px 8px;border-radius:999px;background:rgba(21,101,255,.10);border:1px solid rgba(21,101,255,.22);color:#dbeafe;font-size:10px;font-weight:700}.pair-line{display:flex;align-items:center;gap:8px}
.ppr{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--ac)}
.pchk{width:14px;height:14px;accent-color:var(--gold);cursor:pointer}

/* ── المدخلات ── */
.ig{margin-bottom:9px}
.ig label{display:block;font-size:11px;color:var(--gold);font-weight:700;margin-bottom:4px}
.ig input,.ig select{width:100%;padding:9px 10px;background:rgba(9,15,27,.82);border:1px solid rgba(255,255,255,.12);border-radius:12px;color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:11px;outline:none;transition:border-color .2s, box-shadow .2s}
.ig input:focus,.ig select:focus{border-color:#1565FF;box-shadow:0 0 0 3px rgba(21,101,255,.16)}
.ig select option{background:#050c15}
.togrow{display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.togrow:last-child{border-bottom:none}
.toglbl{font-size:11px;color:var(--tx)}
.tog{width:35px;height:17px;background:#162236;border-radius:9px;cursor:pointer;position:relative;transition:background .25s;flex-shrink:0}
.tog.on{background:var(--gold)}
.tog::after{content:'';position:absolute;top:2px;left:2px;width:13px;height:13px;background:#fff;border-radius:50%;transition:left .25s}
.tog.on::after{left:20px}

/* ── بطاقات الإشارات ── */
.slist{max-height:500px;overflow-y:auto}
.slist::-webkit-scrollbar{width:3px}
.slist::-webkit-scrollbar-thumb{background:var(--bd)}
.sc{border-radius:12px;overflow:hidden;margin-bottom:9px;border:1px solid;animation:si .35s ease}
@keyframes si{from{opacity:0;transform:translateY(-12px)}to{opacity:1;transform:translateY(0)}}
.sc:hover{transform:translateY(-2px);transition:transform .2s}
.sc.UP{border-color:rgba(34,197,94,.32);background:linear-gradient(145deg,rgba(21,101,255,.10),rgba(34,197,94,.06));box-shadow:0 8px 26px rgba(21,101,255,.12)}
.sc.DOWN{border-color:rgba(239,68,68,.32);background:linear-gradient(145deg,rgba(239,68,68,.08),rgba(16,24,39,.72));box-shadow:0 8px 26px rgba(239,68,68,.12)}
.s-head{display:flex;align-items:center;justify-content:space-between;padding:9px 13px;border-bottom:1px solid rgba(255,255,255,.04)}
.s-pair{font-family:'IBM Plex Mono',monospace;font-size:17px;font-weight:700;color:var(--tx)}
.s-dir{padding:5px 16px;border-radius:20px;font-size:12px;font-weight:900;letter-spacing:.5px}
.s-dir.UP{background:rgba(0,230,118,.15);color:var(--up);border:1px solid rgba(0,230,118,.3)}
.s-dir.DOWN{background:rgba(255,61,87,.15);color:var(--dn);border:1px solid rgba(255,61,87,.3)}
.s-time{font-size:9px;color:var(--mt);font-family:'IBM Plex Mono',monospace;text-align:left}
.s-body{padding:10px 13px}
.s-entry{background:rgba(21,101,255,.10);border:1px solid rgba(21,101,255,.24);border-radius:12px;padding:8px 11px;margin-bottom:8px;font-size:11px;color:#BFDBFE;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.s-entry b{color:var(--g2)}
.s-badges{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:7px}
.ib{padding:2px 7px;border-radius:4px;font-size:9px;font-weight:700;font-family:'IBM Plex Mono',monospace}
.ib.bull{color:var(--up);background:rgba(0,230,118,.07);border:1px solid rgba(0,230,118,.2)}
.ib.bear{color:var(--dn);background:rgba(255,61,87,.07);border:1px solid rgba(255,61,87,.2)}
.ib.neu{color:var(--gold);background:rgba(232,184,75,.07);border:1px solid rgba(232,184,75,.2)}
.s-reason{background:rgba(0,0,0,.2);border:1px solid rgba(255,255,255,.05);border-radius:6px;padding:6px 10px;font-size:11px;color:#9ab8cc;line-height:1.7;margin-bottom:8px}
.s-bar{height:4px;background:var(--bd);border-radius:2px;overflow:hidden;margin-bottom:4px}
.s-fill{height:100%;border-radius:2px;transition:width 1.2s}
.s-fill.hi{background:linear-gradient(90deg,var(--up),#00bb44)}
.s-fill.md{background:linear-gradient(90deg,var(--gold),#cc8800)}
.s-fill.lo{background:linear-gradient(90deg,var(--dn),#aa1130)}
.s-foot{display:flex;justify-content:space-between;align-items:center;font-size:10px}
.s-conf{color:var(--mt)}
.s-ai{color:var(--pur);font-size:9px}

/* ── صندوق تيليغرام ── */
.tg-box{background:linear-gradient(180deg,rgba(13,19,34,.86),rgba(16,24,39,.92));border-radius:14px;padding:12px;font-family:'IBM Plex Mono',monospace;font-size:10px;line-height:2;border:1px solid rgba(255,255,255,.1);white-space:pre-wrap;color:#dbeafe;max-height:220px;overflow-y:auto;box-shadow:inset 0 0 0 1px rgba(21,101,255,.12)}

/* ── السجل ── */
.logbox{max-height:160px;overflow-y:auto}
#sigHistoryList{max-height:none;overflow:visible}
.logbox::-webkit-scrollbar{width:3px}
.logbox::-webkit-scrollbar-thumb{background:var(--bd)}
.le{display:flex;gap:10px;align-items:flex-start;padding:9px 2px;border-bottom:1px solid rgba(255,255,255,.06);font-size:12px;transition:all .2s}
.le:hover{background:rgba(255,255,255,.03)}
.lt{font-family:'IBM Plex Mono',monospace;color:var(--mt);min-width:44px;flex-shrink:0;font-size:10px}
.lm{line-height:1.7}
.lm.ok{color:var(--up)}.lm.err{color:var(--dn)}.lm.info{color:var(--ac)}.lm.warn{color:var(--gold)}

/* ── فارغ ── */
.empty{text-align:center;padding:44px 32px;color:var(--mt)}
.empty .ei{font-size:40px;margin-bottom:10px}

/* ── لودر ── */
.ld{display:inline-flex;gap:3px;align-items:center}
.ld span{width:4px;height:4px;background:var(--gold);border-radius:50%;animation:la 1s infinite}
.ld span:nth-child(2){animation-delay:.2s}.ld span:nth-child(3){animation-delay:.4s}
@keyframes la{0%,80%,100%{transform:scale(.55)}40%{transform:scale(1)}}

/* ── إشعار ── */
.notif{position:fixed;top:16px;left:50%;transform:translateX(-50%);padding:9px 22px;border-radius:10px;font-size:13px;font-weight:700;z-index:999;opacity:0;transition:opacity .3s;pointer-events:none}
.notif.ok{background:rgba(34,197,94,.16);border:1px solid rgba(34,197,94,.42);color:var(--up)}
.notif.err{background:rgba(239,68,68,.16);border:1px solid rgba(239,68,68,.42);color:var(--dn)}

/* ── التبويبات الداخلية ── */
.tabs-wrap{display:none!important}
.tab-btn{
  border:1px solid rgba(255,255,255,.12);
  background:rgba(255,255,255,.03);
  color:var(--mt);
  padding:8px 14px;
  border-radius:999px;
  font-size:12px;
  font-weight:700;
  cursor:pointer;
  transition:all .2s;
}
.tab-btn:hover{border-color:rgba(21,101,255,.42);color:#dbeafe}
.tab-btn.active{
  color:#fff;
  border-color:rgba(21,101,255,.7);
  background:rgba(21,101,255,.20);
  box-shadow:0 8px 18px rgba(21,101,255,.18);
}
.tab-pane{display:none;min-height:calc(100vh - 250px);animation:tabFade .24s ease}
.tab-pane.active{display:block}
@keyframes tabFade{from{opacity:.4;transform:translateY(4px)}to{opacity:1;transform:none}}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.three-col{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.users-list{max-height:230px;overflow-y:auto}
.user-row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.07)}
.user-row:last-child{border-bottom:none}
.u-id{font-family:'IBM Plex Mono',monospace;color:#dbeafe}
.u-email{color:var(--mt);font-size:10px}
.logs-head{background:linear-gradient(140deg,rgba(16,24,39,.82),rgba(13,19,34,.75));border:1px solid rgba(255,255,255,.08);border-radius:22px;padding:16px 18px;margin-bottom:14px}
.logs-head h3{margin:4px 0 6px;font-size:24px;color:#f8fafc;font-weight:800}
.logs-head p{margin:0;color:#94A3B8;font-size:12px;line-height:1.8}
.logs-badge{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;border-radius:999px;border:1px solid rgba(21,101,255,.36);background:rgba(21,101,255,.12);color:#bfdbfe;font-size:10px;font-weight:700}
.badge-pill{display:inline-flex;align-items:center;justify-content:center;min-width:24px;height:20px;padding:0 8px;border-radius:999px;background:rgba(21,101,255,.15);border:1px solid rgba(21,101,255,.35);color:#dbeafe;font-size:10px;font-weight:700}
.danger-btn{background:rgba(239,68,68,.10);border:1px solid rgba(239,68,68,.34);color:#fecaca}
.danger-btn:hover{background:rgba(239,68,68,.18);border-color:rgba(239,68,68,.48)}
.success-btn{background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.34);color:#86efac}
.success-btn:hover{background:rgba(34,197,94,.2);border-color:rgba(34,197,94,.5)}
.empty-state{border:1px dashed rgba(255,255,255,.12);border-radius:14px;padding:18px 14px;text-align:center;background:rgba(255,255,255,.02);color:#94A3B8}
.empty-state .e-ic{width:34px;height:34px;border-radius:10px;margin:0 auto 8px;background:rgba(21,101,255,.12);color:#93c5fd;display:flex;align-items:center;justify-content:center;font-size:16px}
.empty-state .e-tt{font-size:13px;color:#e2e8f0;font-weight:700;margin-bottom:4px}
.req-row{border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:10px 11px;margin-bottom:8px;background:rgba(255,255,255,.02);transition:all .2s}
.req-row:hover{border-color:rgba(21,101,255,.35);background:rgba(19,30,49,.45)}
.req-meta{display:grid;gap:2px;margin-bottom:8px}
.req-k{font-size:10px;color:#94A3B8}
.req-v{font-size:12px;color:#e2e8f0;font-weight:600}
.req-v.ltr{direction:ltr;text-align:left;font-family:'IBM Plex Mono',monospace}
.logs-two-col{display:grid;grid-template-columns:1fr 1fr;gap:12px}
#sigHistoryList .sc{margin-bottom:10px}
#sigHistoryList .s-pair{font-size:14px}
#sigHistoryList .s-entry{font-size:10px}
.bottom-nav{
  position:fixed;left:50%;transform:translateX(-50%);bottom:10px;
  width:min(760px,calc(100vw - 18px));z-index:99;
  display:grid;grid-template-columns:repeat(4,1fr);gap:6px;
  background:rgba(16,24,39,.88);border:1px solid rgba(255,255,255,.11);
  border-radius:18px;padding:8px;backdrop-filter:blur(12px);
  box-shadow:0 14px 30px rgba(0,0,0,.35),0 0 16px rgba(21,101,255,.2);
}
.bnav-btn{
  border:1px solid transparent;background:rgba(255,255,255,.02);color:#94A3B8;
  border-radius:13px;padding:8px 8px 7px;font-size:11px;font-weight:700;cursor:pointer;transition:all .2s;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;min-height:58px;
}
.bnav-btn:hover{border-color:rgba(21,101,255,.36);color:#dbeafe}
.bnav-btn.active{background:rgba(21,101,255,.24);border-color:rgba(21,101,255,.75);color:#fff;box-shadow:0 8px 18px rgba(21,101,255,.22)}
.bnav-ic{width:18px;height:18px;display:inline-flex;align-items:center;justify-content:center;opacity:.96}
.bnav-ic svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
.bnav-tx{font-size:11px;line-height:1}

.news-filters{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
.news-list{display:grid;gap:12px}
.news-card{position:relative;overflow:hidden;border:1px solid rgba(255,255,255,.08);background:radial-gradient(circle at top right, rgba(21,101,255,.12), transparent 30%), rgba(10,18,33,.82);border-radius:18px;padding:16px;box-shadow:0 16px 34px rgba(0,0,0,.22)}
.news-card::before{content:"";position:absolute;inset-inline-start:0;top:0;bottom:0;width:3px;background:linear-gradient(180deg,#1565FF,#38A8FF)}
.news-meta{display:flex;justify-content:space-between;gap:10px;color:#8fa7c7;font-size:12px;margin-bottom:8px}
.news-title{color:#f8fbff;font-size:15px;font-weight:800;line-height:1.6}
.news-desc{color:#a9b9d1;font-size:13px;line-height:1.7;margin-top:8px}
.news-open{display:inline-flex;margin-top:12px;color:#72b7ff;text-decoration:none;font-size:13px;font-weight:800}
.cal-filters{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.cal-chip{border:1px solid rgba(21,101,255,.25);background:rgba(21,101,255,.08);color:#cfe5ff;border-radius:999px;padding:8px 12px;cursor:pointer;font-weight:700}
.cal-chip.active{background:linear-gradient(135deg,#1565FF,#38A8FF);color:#fff;box-shadow:0 10px 22px rgba(21,101,255,.24)}
.calendar-list{display:grid;gap:12px}
.calendar-event-card{
  border:1px solid rgba(21,101,255,.22);
  background:
    radial-gradient(circle at top right, rgba(21,101,255,.12), transparent 30%),
    rgba(8,16,29,.86);
  border-radius:18px;
  padding:16px;
  box-shadow:0 14px 32px rgba(0,0,0,.24);
}
.calendar-event-top{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  margin-bottom:10px;
}
.calendar-top-left{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.calendar-time{
  color:#DCEBFF;
  font-weight:800;
  font-size:14px;
}
.calendar-currency-badge{
  display:inline-flex;
  align-items:center;
  gap:7px;
  padding:7px 11px;
  border-radius:999px;
  background:rgba(21,101,255,.14);
  border:1px solid rgba(21,101,255,.35);
  color:#EAF3FF;
  font-weight:900;
  font-size:13px;
  letter-spacing:.04em;
}
.calendar-currency-badge .flag{font-size:17px}
.calendar-event-title{
  color:#FFFFFF;
  font-weight:900;
  font-size:15px;
  line-height:1.7;
  margin-bottom:12px;
}
.calendar-values{
  display:grid;
  grid-template-columns:repeat(3, 1fr);
  gap:8px;
}
.calendar-value{
  border-radius:12px;
  padding:9px;
  background:rgba(255,255,255,.035);
  border:1px solid rgba(255,255,255,.06);
}
.calendar-value-label{
  color:#8FA7C7;
  font-size:11px;
  margin-bottom:4px;
}
.calendar-value-number{
  color:#EAF3FF;
  font-size:13px;
  font-weight:800;
}
.calendar-stars{
  color:#FACC15;
  font-size:13px;
  letter-spacing:2px;
}
.plan-head{
  border:1px solid rgba(21,101,255,.22);
  border-radius:18px;
  padding:14px 15px;
  margin-bottom:12px;
  background:linear-gradient(140deg,rgba(12,24,46,.84),rgba(9,17,31,.78));
  box-shadow:0 12px 28px rgba(0,0,0,.24);
}
.plan-title{margin:0 0 5px;font-size:24px;color:#f8fbff;font-weight:900}
.plan-desc{margin:0;color:#9eb0cc;font-size:12px;line-height:1.8}
.plan-grid{display:grid;grid-template-columns:1.1fr 1fr;gap:12px}
.plan-form{display:grid;gap:10px}
.plan-input{
  width:100%;
  border:1px solid rgba(255,255,255,.1);
  background:rgba(255,255,255,.03);
  color:#e2e8f0;
  border-radius:12px;
  padding:10px 11px;
  font-size:13px;
  font-family:'IBM Plex Mono',monospace;
  direction:ltr;
  text-align:left;
  unicode-bidi:plaintext;
  outline:none;
  transition:all .2s ease;
}
.plan-input:focus{
  border-color:rgba(56,168,255,.62);
  box-shadow:0 0 0 3px rgba(56,168,255,.18);
}
.plan-input[type="number"]{
  -moz-appearance:textfield;
  appearance:textfield;
}
.plan-input[type="number"]::-webkit-outer-spin-button,
.plan-input[type="number"]::-webkit-inner-spin-button{
  -webkit-appearance:none;
  margin:0;
}
.plan-stepper{
  display:grid;
  grid-template-columns:40px 1fr 40px;
  gap:8px;
  align-items:center;
}
.plan-step-btn{
  height:38px;
  border-radius:10px;
  border:1px solid rgba(56,168,255,.38);
  background:rgba(21,101,255,.14);
  color:#dbeafe;
  font-size:18px;
  font-weight:900;
  cursor:pointer;
  transition:all .2s ease;
}
.plan-step-btn:hover{
  border-color:rgba(56,168,255,.64);
  background:rgba(21,101,255,.24);
}
.plan-step-btn:active{transform:translateY(1px)}
.plan-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
.plan-results{display:grid;gap:10px}
.plan-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.plan-out{
  border:1px solid rgba(255,255,255,.08);
  border-radius:14px;
  padding:11px 12px;
  background:rgba(255,255,255,.03);
}
.plan-k{font-size:11px;color:#9cb0cc;margin-bottom:4px}
.plan-v{font-size:18px;font-weight:900;color:#f8fbff}
.plan-v.loss{color:#fca5a5}
.plan-v.win{color:#86efac}
.plan-stop{
  border:1px solid rgba(255,255,255,.1);
  border-radius:14px;
  padding:11px 12px;
  background:rgba(255,255,255,.025);
  color:#dbeafe;
  font-size:12px;
  line-height:1.75;
}
.plan-state{
  border:1px solid transparent;
  border-radius:14px;
  padding:10px 12px;
  font-size:12px;
  font-weight:700;
}
.plan-state.safe{color:#86efac;background:rgba(34,197,94,.14);border-color:rgba(34,197,94,.36)}
.plan-state.balanced{color:#fde68a;background:rgba(250,204,21,.12);border-color:rgba(250,204,21,.34)}
.plan-state.high{color:#fecaca;background:rgba(239,68,68,.14);border-color:rgba(239,68,68,.34)}
.plan-warnings{display:grid;gap:8px}
.plan-warn{
  border:1px solid rgba(239,68,68,.35);
  border-radius:12px;
  background:rgba(239,68,68,.12);
  color:#fecaca;
  padding:9px 10px;
  font-size:12px;
}
.plan-block{margin-top:12px}
.plan-subtitle{
  margin:0 0 6px;
  font-size:20px;
  color:#f8fbff;
  font-weight:900;
}
.plan-subdesc{
  margin:0;
  color:#9eb0cc;
  font-size:12px;
  line-height:1.8;
}
.plan-state.caution{color:#fdba74;background:rgba(251,146,60,.12);border-color:rgba(251,146,60,.36)}

@media(max-width:960px){
  .topbar{padding:16px 14px;border-radius:22px}
  .brand-logo{width:min(210px,62vw)}
  .brand .b2{font-size:10px}
  .grid{grid-template-columns:1fr}
  .stats{grid-template-columns:repeat(2,1fr)}
  #APP{padding:10px 10px 92px;font-variant-numeric:lining-nums tabular-nums}
  .bottom-nav{
    left:10px;
    right:10px;
    width:auto;
    transform:none;
    bottom:max(8px, env(safe-area-inset-bottom));
  }
  .two-col,.three-col,.logs-two-col{grid-template-columns:1fr}
  .plan-grid,.plan-cards{grid-template-columns:1fr}
  .lbox{padding:22px 14px 16px}
  .logo-sub{letter-spacing:.42em}
  .logo-sub-wrap .line{width:34px}
  .ls-candles{right:8px;top:102px;opacity:.22;transform:scale(.88);transform-origin:top right}
}
@media(min-width:900px){
  #LS{align-items:center;padding:32px 24px}
  .lbox{padding:30px 24px 20px}
}
</style>
</head>
<body>
<div class="notif" id="notif"></div>

<!-- شاشة الدخول -->
<div id="LS">
<div class="lbox">
  <div class="ls-decor">
    <div class="ls-glow-t"></div>
    <div class="ls-glow-b"></div>
    <div class="ls-x">X</div>
    <div class="ls-candles"></div>
    <div class="ls-grid"></div>
    <div class="ls-lines"></div>
  </div>
  <div class="ls-content">
  <div class="lang-switch">
    <label id="langLabel" for="langSelect">اللغة</label>
    <select id="langSelect" onchange="setLang(this.value)">
      <option value="ar">العربية</option>
      <option value="en">English</option>
    </select>
  </div>
  <div class="ltit">
    <div class="logo-main">NE<span class="x">X</span>O</div>
    <div class="logo-sub-wrap">
      <div class="line"></div><span class="logo-sub">TRADE</span><div class="line"></div>
    </div>
    <p>Smart Signals. Better Trades.</p>
  </div>
  <div class="lsep"></div>
  <div id="idLoginBox">
    <div class="lf">
      <label id="loginAccountLabel">🆔 Account ID</label>
      <input id="userLoginId" placeholder="ادخل ID الحساب"
        onkeydown="if(event.key==='Enter')userIdLogin()">
    </div>
    <button class="lbtn" id="loginBtn" onclick="userIdLogin()">دخول</button>
    <div class="lerr" id="userLoginMsg" style="display:block"></div>
    <div class="lsep"></div>
  </div>
  <div id="joinBox" style="display:none">
    <div class="lf">
      <label id="joinAccountLabel">🆔 Account ID</label>
      <input id="pubJoinId" placeholder="ادخل ID الحساب">
    </div>
    <div class="lf">
      <label id="joinEmailLabel">📧 Email</label>
      <input id="pubJoinEmail" type="email" placeholder="ادخل البريد الإلكتروني">
    </div>
    <div class="lf">
      <label id="joinImageLabel">🖼 صورة الملف الشخصي</label>
      <div id="joinHint" style="font-size:10px;color:var(--mt);line-height:1.6;margin:-2px 0 6px">
        يجب أن تظهر في الصورة بيانات الحساب كما في المنصة: <b>Account ID</b> و<b>Email</b> بوضوح.
      </div>
      <input id="pubJoinImg" type="file" accept="image/*">
    </div>
    <button class="lbtn" id="joinSubmitBtn" style="margin-top:2px" onclick="submitJoinPublic()">إرسال طلب الانضمام</button>
    <div class="lerr" id="pubJoinMsg" style="display:block"></div>
    <button class="xbtn" id="backLoginBtn" style="width:100%;margin-top:8px" onclick="showIdLogin()">تسجيل الدخول</button>
  </div>
  </div>
</div>
</div>

<!-- التطبيق -->
<div id="APP">
  <!-- الشريط العلوي -->
  <div class="topbar">
    <div class="tb-inner">
      <div class="brand">
        <img class="brand-logo" src="/uploads/nexo_logo_transparent.png" alt="NEXO TRADE">
        <div class="b2" id="brandSub">Smart Signals • AI Assistant • Quotex M1</div>
      </div>
      <div class="tb-right">
        <div class="sbadge" id="sbadge">
          <div class="sdot" id="sdot"></div>
          <span id="stxt">متوقف</span>
        </div>
        <div class="cdbox">
          <div class="cdlbl" id="cdlbl">الإشارة في</div>
          <div class="cd" id="cd">--:--</div>
        </div>
        <button class="xbtn" id="logoutBtn" onclick="doLogout()">خروج ↩</button>
      </div>
    </div>
  </div>

  <div class="tabs-wrap">
    <button class="tab-btn active" id="tabBtnLive" onclick="switchTab('live')"><span id="tabBtnLiveLabel">الإشارات الحية</span></button>
    <button class="tab-btn" id="tabBtnControl" onclick="switchTab('control')"><span id="tabBtnControlLabel">مركز التحكم</span></button>
    <button class="tab-btn" id="tabBtnLogs" onclick="switchTab('logs')"><span id="tabBtnLogsLabel">السجل والمستخدمين</span></button>
    <button class="tab-btn" id="tabBtnPlan" onclick="switchTab('plan')"><span id="tabBtnPlanLabel">الخطة اليومية</span></button>
  </div>

  <!-- تبويب الإشارات الحية -->
  <div class="tab-pane active" id="tabLive">
    <div class="stats">
      <div class="stat g">
        <div class="st-l" id="statSignalsLabel">Today Signals</div>
        <div class="st-v g" id="sTot">0</div>
        <div class="st-s" id="statSignalsSub">One trade / minute</div>
      </div>
      <div class="stat v">
        <div class="st-l" id="statTelegramLabel">Telegram Sent</div>
        <div class="st-v v" id="sTG">0</div>
        <div class="st-s" id="statTelegramSub">To channel</div>
      </div>
      <div class="stat b">
        <div class="st-l" id="statPairsLabel">Active Pairs</div>
        <div class="st-v b" id="sPrs">0</div>
        <div class="st-s" id="statPairsSub">Scanned every minute</div>
      </div>
      <div class="stat p">
        <div class="st-l" id="statSourceLabel">Analysis Source</div>
        <div class="st-v p" id="sAI" style="font-size:10px">—</div>
        <div class="st-s" id="statSourceSub">Latest signal</div>
      </div>
    </div>

    <div class="card" style="margin-bottom:11px">
      <div class="chd">
        <div class="ctit" id="signalsCardTitle">🎯 NEXO TRADE Signals — Quotex M1</div>
        <div style="display:flex;align-items:center;gap:7px">
          <div id="aiSrc" style="font-size:9px;color:var(--pur);font-family:'IBM Plex Mono',monospace">—</div>
        </div>
      </div>
      <div class="cbody">
        <div class="slist" id="sigList">
          <div class="empty">
            <div class="ei">📈</div>
            <div id="liveEmptyTitle" style="color:#BFDBFE;font-weight:700;margin-bottom:4px">Ready to analyze</div>
            <div id="liveEmptyDesc" style="font-size:11px">The bot is watching the market for a high-quality setup</div>
            <div style="font-size:10px;color:var(--mt);margin-top:5px">
              Smart Signals • Better Trades
            </div>
          </div>
        </div>
      </div>
    </div>


  </div>

  <!-- تبويب مركز التحكم -->
  <div class="tab-pane" id="tabControl">
    <div class="grid">
      <div>
        <div class="card">
          <div class="chd">
            <div class="ctit"><span id="controlTitle">🎮 مركز التحكم</span></div>
            <div class="ld" id="loader" style="display:none">
              <span></span><span></span><span></span>
            </div>
          </div>
          <div class="cbody">
            <div class="timing-info">
              <div id="timingInfoHtml">⏰ <b>توقيت الإشارة</b><br>
              تُرسل قبل نهاية الدقيقة بـ <b>23 ثانية</b><br>
              ادخل الصفقة في <b>بداية الدقيقة التالية</b><br>
              <b>صفقة واحدة فقط — الأقوى</b>
              </div>
            </div>
            <button class="start-btn" id="btnStart" onclick="startBot()">
              <div class="pr"></div>
              <span id="btnStartLabel">▶ تشغيل البوت</span>
            </button>
            <button class="stop-btn" id="btnStop" onclick="stopBot()" disabled>
              <span id="btnStopLabel">⏹ إيقاف البوت</span>
            </button>
          </div>
        </div>

        <div class="card">
          <div class="chd"><div class="ctit"><span id="settingsTitle">⚙️ الإعدادات</span></div></div>
          <div class="cbody">
            <div class="ig">
              <label><span id="strategyLabel">الاستراتيجية</span></label>
              <select id="strategySelect" onchange="saveStrategy()"></select>
              <div class="strategy-box" id="strategyInfo"></div>
            </div>
            <div class="ig">
              <label><span id="minConfLabel">الحد الأدنى للثقة</span></label>
              <select id="minConf" onchange="saveConf()">
                <option value="65">65%+</option>
                <option value="70" selected>70%+</option>
                <option value="75">75%+</option>
                <option value="80">80%+</option>
              </select>
            </div>
            <div class="togrow">
              <span class="toglbl"><span id="aiConfirmLabel">🤖 AI Confirmation</span></span>
              <div class="tog on" id="togAI" onclick="toggleAIConfirm()"></div>
            </div>
            <div class="togrow">
              <span class="toglbl"><span id="aiReviewLabel">🧠 مراجعة الذكاء الاصطناعي</span></span>
              <div class="tog on" id="togAIReview" onclick="toggleAIReview()"></div>
            </div>
            <div class="ig">
              <label><span id="minAIConfLabel">🎯 الحد الأدنى لثقة AI</span></label>
              <select id="minAIConf" onchange="saveMinAIConf()">
                <option value="60">60%</option>
                <option value="65">65%</option>
                <option value="70">70%</option>
                <option value="75" selected>75%</option>
                <option value="80">80%</option>
                <option value="85">85%</option>
                <option value="90">90%</option>
              </select>
            </div>
            <div class="ig">
              <label><span id="aiFailureModeLabel">⚠️ عند فشل AI</span></label>
              <select id="aiFailureMode" onchange="saveAIFailureMode()">
                <option value="reject" id="aiFailRejectOpt">Reject Signal</option>
                <option value="strong_only" id="aiFailStrongOpt">Allow Only Strong Strategy Signals</option>
              </select>
            </div>
            <div class="togrow">
              <span class="toglbl"><span id="showAIReasonLabel">📝 إظهار سبب AI في تلغرام</span></span>
              <div class="tog" id="togShowAIReason" onclick="toggleShowAIReason()"></div>
            </div>
            <div class="ig">
              <label><span id="newsWindowLabel">🗞 فلتر الأخبار</span></label>
              <div id="newsWindowValue" style="font-size:12px;color:var(--mt)">30 دقيقة قبل الخبر / 15 دقيقة بعد الخبر</div>
            </div>
            <button class="act-btn btn-ch" id="joinChannelBtn" onclick="joinSignalChannel()">
              <span id="joinChannelLabel">🔵 انضمام للقناة</span>
            </button>
          </div>
        </div>
      </div>

      <div>
        <div class="card">
          <div class="chd">
            <div class="ctit"><span id="pairsTitle">📊 الأزواج</span></div>
            <div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap">
              <select id="pairFilter" onchange="renderPairs()" class="pair-filter">
                <option value="all">All Markets</option>
                <option value="majors">Majors</option>
                <option value="jpy">JPY</option>
                <option value="high_vol">High Volatility</option>
                <option value="eur">EUR</option>
                <option value="usd">USD</option>
                <option value="aud">AUD</option>
              </select>
              <button class="btn-g btn-sm" onclick="selAll()"><span id="allPairsLabel">الكل</span></button>
              <button class="btn-g btn-sm" onclick="selNone()"><span id="clearPairsLabel">مسح</span></button>
            </div>
          </div>
          <div class="cbody" id="pList" style="padding:7px 9px;max-height:300px;overflow-y:auto"></div>
        </div>


      </div>
    </div>
  </div>

  <!-- تبويب السجل والمستخدمين -->
  <div class="tab-pane" id="tabLogs">
    <div class="logs-head">
      <span class="logs-badge"><span id="activityBadgeLabel">Activity Center</span></span>
      <h3 id="logsTitle">السجل</h3>
      <p id="logsDesc">مراجعة نشاط البوت وسجل الإشارات فقط.</p>
    </div>
    <div class="card">
      <div class="chd"><div class="ctit"><span id="signalHistoryTitle">🧠 سجل الإشارات</span> <span class="badge-pill" id="signalCountBadge">0</span></div></div>
      <div class="cbody logbox" id="sigHistoryList">
        <div class="empty-state">
          <div class="e-ic">📈</div>
          <div class="e-tt" id="signalHistoryEmptyTitle">No signals yet</div>
          <div id="signalHistoryEmptyDesc">Generated signals will appear here</div>
        </div>
      </div>
    </div>
  </div>

  <div class="tab-pane" id="tabPlan">
    <div class="plan-block">
      <div class="plan-head">
        <h3 class="plan-subtitle" id="atTitle">🎯 تارغت الحساب</h3>
        <p class="plan-subdesc" id="atDesc">احسب كم ربح وصفقات تحتاج للوصول إلى هدف حسابك.</p>
      </div>
      <div class="plan-grid">
        <div class="card">
          <div class="chd"><div class="ctit" id="atInputsTitle">🧮 مدخلات التارغت</div></div>
          <div class="cbody plan-form">
            <div class="ig">
              <label id="atCurrentBalanceLabel">الرصيد الحالي</label>
              <div class="plan-stepper">
                <button type="button" class="plan-step-btn" onclick="adjustPlanField('atCurrentBalance',-1,1,1)">-</button>
                <input class="plan-input" id="atCurrentBalance" type="number" min="1" step="1" value="100" lang="en" dir="ltr" inputmode="numeric" oninput="updateAccountTarget()">
                <button type="button" class="plan-step-btn" onclick="adjustPlanField('atCurrentBalance',1,1,1)">+</button>
              </div>
            </div>
            <div class="ig">
              <label id="atTargetBalanceLabel">الهدف المطلوب</label>
              <div class="plan-stepper">
                <button type="button" class="plan-step-btn" onclick="adjustPlanField('atTargetBalance',-1,1,1)">-</button>
                <input class="plan-input" id="atTargetBalance" type="number" min="1" step="1" value="150" lang="en" dir="ltr" inputmode="numeric" oninput="updateAccountTarget()">
                <button type="button" class="plan-step-btn" onclick="adjustPlanField('atTargetBalance',1,1,1)">+</button>
              </div>
            </div>
            <div class="ig">
              <label id="atStakeAmountLabel">مبلغ الدخول</label>
              <div class="plan-stepper">
                <button type="button" class="plan-step-btn" onclick="adjustPlanField('atStakeAmount',-1,1,1)">-</button>
                <input class="plan-input" id="atStakeAmount" type="number" min="1" step="1" value="5" lang="en" dir="ltr" inputmode="numeric" oninput="updateAccountTarget()">
                <button type="button" class="plan-step-btn" onclick="adjustPlanField('atStakeAmount',1,1,1)">+</button>
              </div>
            </div>
            <div class="ig">
              <label id="atPayoutPercentLabel">نسبة الربح Payout %</label>
              <div class="plan-stepper">
                <button type="button" class="plan-step-btn" onclick="adjustPlanField('atPayoutPercent',-1,1,1)">-</button>
                <input class="plan-input" id="atPayoutPercent" type="number" min="1" step="1" value="85" lang="en" dir="ltr" inputmode="numeric" oninput="updateAccountTarget()">
                <button type="button" class="plan-step-btn" onclick="adjustPlanField('atPayoutPercent',1,1,1)">+</button>
              </div>
            </div>
            <div class="ig">
              <label id="atDaysCountLabel">عدد الأيام للوصول للهدف</label>
              <div class="plan-stepper">
                <button type="button" class="plan-step-btn" onclick="adjustPlanField('atDaysCount',-1,1,1)">-</button>
                <input class="plan-input" id="atDaysCount" type="number" min="1" step="1" value="5" lang="en" dir="ltr" inputmode="numeric" oninput="updateAccountTarget()">
                <button type="button" class="plan-step-btn" onclick="adjustPlanField('atDaysCount',1,1,1)">+</button>
              </div>
            </div>
            <div class="plan-actions">
              <button class="btn-g btn-sm" onclick="resetAccountTarget()" id="atResetBtn">Reset</button>
              <button class="btn-g btn-sm" onclick="copyAccountTargetPlan()" id="atCopyBtn">Copy Target Plan</button>
            </div>
          </div>
        </div>
        <div class="plan-results">
          <div class="card">
            <div class="chd"><div class="ctit" id="atResultsTitle">📊 نتائج التارغت</div></div>
            <div class="cbody plan-cards">
              <div class="plan-out"><div class="plan-k" id="atNeededProfitLabel">الربح المطلوب</div><div class="plan-v win" id="atNeededProfit">0.00$</div></div>
              <div class="plan-out"><div class="plan-k" id="atProfitPerWinLabel">ربح الصفقة الواحدة</div><div class="plan-v" id="atProfitPerWin">0.00$</div></div>
              <div class="plan-out"><div class="plan-k" id="atWinsNeededLabel">الصفقات الرابحة المطلوبة</div><div class="plan-v" id="atWinsNeeded">0</div></div>
              <div class="plan-out"><div class="plan-k" id="atGrowthPercentLabel">نسبة نمو الحساب المطلوبة</div><div class="plan-v" id="atGrowthPercent">0.00%</div></div>
              <div class="plan-out"><div class="plan-k" id="atDailyProfitNeededLabel">الربح اليومي المطلوب</div><div class="plan-v" id="atDailyProfitNeeded">0.00$</div></div>
              <div class="plan-out"><div class="plan-k" id="atDailyWinsNeededLabel">الصفقات المطلوبة يوميًا</div><div class="plan-v" id="atDailyWinsNeeded">0</div></div>
            </div>
          </div>
          <div id="atEvaluation" class="plan-state balanced">هدف متوسط، يفضل تقسيمه على عدة جلسات</div>
          <div class="plan-warnings" id="atWarnings"></div>
        </div>
      </div>
    </div>
  </div>

  <div class="bottom-nav">
    <button class="bnav-btn active" id="bnavLive" onclick="switchTab('live')">
      <span class="bnav-ic" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 18h16"></path><path d="M6 16l3-4 3 2 4-6 2 3"></path><path d="M6 7v9"></path></svg></span>
      <span class="bnav-tx" id="bnavLiveLabel">الإشارات</span>
    </button>
    <button class="bnav-btn" id="bnavControl" onclick="switchTab('control')">
      <span class="bnav-ic" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v4"></path><path d="M12 17v4"></path><path d="M4.9 4.9l2.8 2.8"></path><path d="M16.3 16.3l2.8 2.8"></path><path d="M3 12h4"></path><path d="M17 12h4"></path><path d="M4.9 19.1l2.8-2.8"></path><path d="M16.3 7.7l2.8-2.8"></path><circle cx="12" cy="12" r="3.2"></circle></svg></span>
      <span class="bnav-tx" id="bnavControlLabel">التحكم</span>
    </button>
    <button class="bnav-btn" id="bnavLogs" onclick="switchTab('logs')">
      <span class="bnav-ic" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 6h10"></path><path d="M8 12h10"></path><path d="M8 18h10"></path><path d="M4 6h.01"></path><path d="M4 12h.01"></path><path d="M4 18h.01"></path></svg></span>
      <span class="bnav-tx" id="bnavLogsLabel">السجل</span>
    </button>
    <button class="bnav-btn" id="bnavPlan" onclick="switchTab('plan')">
      <span class="bnav-ic" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"></circle><path d="M12 8v4"></path><path d="M12 16h.01"></path><path d="M16.5 7.5l-3 3"></path></svg></span>
      <span class="bnav-tx" id="bnavPlanLabel">الخطة</span>
    </button>
  </div>
</div><!-- /APP -->

<script>
const I18N = {
  ar: {
    langLabel:"اللغة", loginAccountPlaceholder:"ادخل ID الحساب", loginBtn:"دخول", logoutBtn:"خروج ↩", cdlbl:"الإشارة في", active:"نشط", stopped:"متوقف",
    tabLive:"الإشارات الحية", tabControl:"مركز التحكم", tabLogs:"السجل", tabPlan:"تارغت الحساب", bnavLive:"الإشارات", bnavControl:"التحكم", bnavLogs:"السجل", bnavPlan:"التارغت",
    statSignalsLabel:"إشارات اليوم", statSignalsSub:"صفقة واحدة / دقيقة", statTelegramLabel:"أُرسل تيليغرام", statTelegramSub:"إلى القناة", statPairsLabel:"أزواج نشطة", statPairsSub:"يتم فحصها كل دقيقة", statSourceLabel:"مصدر التحليل", statSourceSub:"آخر إشارة",
    signalsCardTitle:"🎯 إشارات NEXO TRADE — Quotex M1", liveEmptyTitle:"جاهز للتحليل", liveEmptyDesc:"البوت يراقب السوق وينتظر فرصة عالية الجودة",
    tgPreviewTitle:"✈️ معاينة رسالة تيليغرام", sendMini:"إرسال", tgWaiting:`📈 إشارات التداول

في انتظار الإشارة الأولى...`, miniLogTitle:"📋 آخر نشاط",
    controlTitle:"🎮 مركز التحكم", settingsTitle:"⚙️ الإعدادات", pairsTitle:"📊 الأزواج", strategyLabel:"🧠 الاستراتيجية", aiProviderLabel:"🤖 مزود الذكاء الاصطناعي", aiConfirmLabel:"🤖 تأكيد AI", aiReview:"🧠 مراجعة الذكاء الاصطناعي", minAIConf:"🎯 الحد الأدنى لثقة AI", aiFailureMode:"⚠️ عند فشل AI", aiFailReject:"رفض الإشارة", aiFailStrong:"السماح فقط للإشارات القوية", showAIReason:"📝 إظهار سبب AI في تلغرام", newsWindow:"🗞 فلتر الأخبار", newsWindowValue:"30 دقيقة قبل الخبر / 15 دقيقة بعد الخبر", all:"الكل", clear:"مسح", minConf:"الحد الأدنى للثقة", autoTG:"✈️ إرسال تيليغرام تلقائي", joinChannel:"🔵 انضمام للقناة",
    btnStart:"▶ تشغيل البوت", btnStop:"⏹ إيقاف البوت", analyzeNow:"🔍 تحليل فوري الآن", sendTG:"✈️ إرسال آخر إشارة لتيليغرام",
    logsTitle:"السجل", logsDesc:"مراجعة نشاط البوت وسجل الإشارات فقط.", activityTitle:"📋 سجل النشاط الكامل", signalHistoryTitle:"🧠 سجل الإشارات", activityCenter:"Activity Center",
    emptySignalsTitle:"لا توجد إشارات بعد", emptySignalsDesc:"ستظهر هنا الإشارات التي يولدها البوت", waitingStart:"في انتظار البدء...",
    loginEnterId:"ادخل ID الحساب", checking:"جارٍ التحقق...", pending:"جاري معالجة طلبك، حاول خلال 30 دقيقة", notFound:"حسابك غير موجود، قدم طلب انضمام", loginFailed:"تعذر تسجيل الدخول", connectionError:"خطأ في الاتصال",
    joinEmailPlaceholder:"ادخل البريد الإلكتروني", joinImageLabel:"🖼 صورة الملف الشخصي", joinHint:"يجب أن تظهر في الصورة بيانات الحساب كما في المنصة: <b>Account ID</b> و<b>Email</b> بوضوح.", joinSubmit:"إرسال طلب الانضمام", backToLogin:"تسجيل الدخول", joinMissing:"املأ Account ID و Email وارفق الصورة", joinSending:"جارٍ إرسال الطلب...", joinSuccess:"تم تقديم طلبك، يتم الموافقة خلال 30 دقيقة ✅", joinSubmitError:"تعذر إرسال الطلب",
    signal:"إشارة", entry:"دخول", enterTrade:"ادخل الصفقة في", durationOneMin:"المدة: دقيقة واحدة", price:"السعر", confidence:"الثقة", strategyText:"الاستراتيجية", up:"صعود", down:"هبوط",
    tgTitle:"📈 إشارات التداول", tgPair:"💱  الزوج", tgEntry:"⏰  وقت الدخول", tgPrice:"💰  السعر", tgConf:"📊  الثقة", tgPattern:"🕯  النمط", tgRsi:"📉  RSI", tgTrend:"📈  الاتجاه", tgAnalysis:"📝  التحليل", tgSource:"🔬  المصدر", tgRisk:"⚠️  المسؤولية على المتداول", tgDuration:"      Quotex  —  مدة دقيقة",
    groupEUR:"🇪🇺 أزواج اليورو", groupUSD:"💵 أزواج الدولار", groupJPY:"🇯🇵 أزواج الين", groupAUD:"🦘 أزواج الأسترالي",
    welcomeLog:"✅ أهلاً في لوحة التداول", startLog:"▶ تم تشغيل البوت — صفقة واحدة كل دقيقة", stopLog:"⏹ تم إيقاف البوت", analyzingLog:"🔍 تحليل فوري...", noSignalLog:"⏳ لا إشارة كافية الآن", errorLog:"❌ خطأ", noLastSignal:"لا توجد إشارة", sentTelegram:"✅ تم الإرسال لتيليغرام", sentShort:"✅ أُرسل", genericError:"خطأ",
    timingInfo:"⏰ <b>توقيت الإشارة</b><br>تُرسل قبل نهاية الدقيقة بـ <b>23 ثانية</b><br>ادخل الصفقة في <b>بداية الدقيقة التالية</b><br><b>صفقة واحدة فقط — الأقوى</b>",
    dailyPlanTitle:"🎯 الخطة اليومية", dailyPlanDesc:"حدد هدفك وحد خسارتك قبل بدء التداول.", dailyPlanInputsTitle:"🧮 إعدادات الخطة", dailyPlanResultsTitle:"📊 النتائج",
    dpAccountBalance:"رصيد الحساب", dpDailyTargetPercent:"هدف اليوم %", dpDailyLossLimitPercent:"حد الخسارة اليومي %", dpMaxTrades:"أقصى عدد صفقات", dpPayoutPercent:"نسبة الربح Payout %", dpRiskMode:"نمط الخطة",
    dpRiskConservative:"محافظ", dpRiskBalanced:"متوازن", dpRiskAggressive:"هجومي", dpReset:"إعادة ضبط", dpCopy:"نسخ الخطة",
    dpTargetAmount:"هدف اليوم", dpLossAmount:"حد الخسارة اليومي", dpStake:"مبلغ الدخول المقترح", dpProfitPerWin:"الربح المتوقع من صفقة رابحة", dpWinsNeeded:"الصفقات الرابحة المطلوبة", dpMode:"وضع الخطة",
    dpStopRule:"توقف عند ربح {target}$ أو خسارة {loss}$ أو بعد {maxTrades} صفقات.", dpStatusSafe:"الخطة محافظة وآمنة نسبيًا", dpStatusBalanced:"الخطة متوازنة", dpStatusHigh:"الخطة عالية المخاطرة",
    dpWarnWins:"هدف اليوم يحتاج صفقات رابحة أكثر من الحد الأقصى للصفقات. قلّل الهدف أو زد عدد الصفقات.", dpWarnStake:"مبلغ الدخول أعلى من 5% من رصيد الحساب، وهذا يعتبر مخاطرة مرتفعة.",
    dpCopyTemplate:"خطة NEXO اليومية:\nرصيد الحساب: {balance}$\nهدف اليوم: {targetPct}% = {target}$\nحد الخسارة: {lossPct}% = {loss}$\nأقصى عدد صفقات: {maxTrades}\nمبلغ الدخول المقترح: {stake}$\nالربح المتوقع للصفقة الرابحة: {profit}$\nقاعدة التوقف: توقف عند تحقيق الهدف أو الوصول لحد الخسارة أو انتهاء عدد الصفقات.",
    atTitle:"🎯 تارغت الحساب", atDesc:"احسب كم ربح وصفقات تحتاج للوصول إلى هدف حسابك.", atInputsTitle:"🧮 مدخلات التارغت", atResultsTitle:"📊 نتائج التارغت",
    atCurrentBalance:"الرصيد الحالي", atTargetBalance:"الهدف المطلوب", atStakeAmount:"مبلغ الدخول", atPayoutPercent:"نسبة الربح Payout %", atDaysCount:"عدد الأيام للوصول للهدف",
    atReset:"إعادة ضبط", atCopy:"نسخ خطة التارغت", atNeededProfit:"الربح المطلوب", atProfitPerWin:"ربح الصفقة الواحدة", atWinsNeeded:"عدد الصفقات الرابحة المطلوبة", atGrowthPercent:"نسبة نمو الحساب المطلوبة",
    atDailyProfitNeeded:"الربح اليومي المطلوب", atDailyWinsNeeded:"الصفقات الرابحة المطلوبة يوميًا",
    atEvalLow:"هدف منطقي ومنخفض المخاطرة", atEvalMedium:"هدف متوسط، يفضل تقسيمه على عدة جلسات", atEvalHigh:"هدف مرتفع، يحتاج انضباط قوي", atEvalVeryHigh:"هدف عالي المخاطرة، يفضل تقليله أو تقسيمه على عدة أيام",
    atWarnTarget:"الهدف يجب أن يكون أكبر من الرصيد الحالي.", atWarnStake:"مبلغ الدخول أعلى من 5% من الرصيد الحالي.", atWarnWins:"عدد الصفقات الرابحة المطلوبة كبير، حاول تقسيم الهدف.",
    atCopyTemplate:"خطة تارغت NEXO:\nالرصيد الحالي: {current}$\nالهدف المطلوب: {target}$\nالربح المطلوب: {needed}$\nمبلغ الدخول: {stake}$\nربح الصفقة الواحدة: {profitPerWin}$\nعدد الصفقات الرابحة المطلوبة: {wins}\nعدد الأيام: {days}\nالربح اليومي المطلوب: {dailyProfit}$\nالصفقات المطلوبة يوميًا: {dailyWins}\nتنبيه: لا ترفع المخاطرة للوصول للهدف بسرعة."
  },
  en: {
    langLabel:"Language", loginAccountPlaceholder:"Enter account ID", loginBtn:"Login", logoutBtn:"Logout ↩", cdlbl:"Next signal", active:"Active", stopped:"Stopped",
    tabLive:"Live Signals", tabControl:"Control", tabLogs:"Logs", tabPlan:"Account Target", bnavLive:"Signals", bnavControl:"Control", bnavLogs:"Logs", bnavPlan:"Target",
    statSignalsLabel:"Today Signals", statSignalsSub:"One trade / minute", statTelegramLabel:"Telegram Sent", statTelegramSub:"To channel", statPairsLabel:"Active Pairs", statPairsSub:"Scanned every minute", statSourceLabel:"Analysis Source", statSourceSub:"Latest signal",
    signalsCardTitle:"🎯 NEXO TRADE Signals — Quotex M1", liveEmptyTitle:"Ready to analyze", liveEmptyDesc:"The bot is watching the market for a high-quality setup",
    tgPreviewTitle:"✈️ Telegram Preview", sendMini:"Send", tgWaiting:`📈 Trading Signals

Waiting for the first signal...`, miniLogTitle:"📋 Latest Activity",
    controlTitle:"🎮 Control Center", settingsTitle:"⚙️ Settings", pairsTitle:"📊 Pairs", strategyLabel:"🧠 Strategy", aiProviderLabel:"🤖 AI Provider", aiConfirmLabel:"🤖 AI Confirmation", aiReview:"🧠 AI Review", minAIConf:"🎯 Minimum AI Confidence", aiFailureMode:"⚠️ On AI Failure", aiFailReject:"Reject Signal", aiFailStrong:"Allow Only Strong Strategy Signals", showAIReason:"📝 Show AI reason in Telegram", newsWindow:"🗞 News Filter", newsWindowValue:"30 minutes before / 15 minutes after", all:"All", clear:"Clear", minConf:"Minimum confidence", autoTG:"✈️ Auto Telegram", joinChannel:"🔵 Join Channel",
    btnStart:"▶ Start Bot", btnStop:"⏹ Stop Bot", analyzeNow:"🔍 Analyze Now", sendTG:"✈️ Send Last Signal",
    logsTitle:"Logs", logsDesc:"Review bot activity and signal history only.", activityTitle:"📋 Full Activity Log", signalHistoryTitle:"🧠 Signal History", activityCenter:"Activity Center",
    emptySignalsTitle:"No signals yet", emptySignalsDesc:"Generated signals will appear here", waitingStart:"Waiting to start...",
    loginEnterId:"Enter account ID", checking:"Checking...", pending:"Your request is being reviewed. Try again within 30 minutes", notFound:"Account not found. Submit a join request", loginFailed:"Login failed", connectionError:"Connection error",
    joinEmailPlaceholder:"Enter email address", joinImageLabel:"🖼 Profile image", joinHint:"The image must clearly show your platform details: <b>Account ID</b> and <b>Email</b>.", joinSubmit:"Submit Join Request", backToLogin:"Back to Login", joinMissing:"Fill Account ID, Email, and attach the image", joinSending:"Sending request...", joinSuccess:"Request submitted. Approval usually takes up to 30 minutes ✅", joinSubmitError:"Unable to submit request",
    signal:"Signal", entry:"Entry", enterTrade:"Enter trade at", durationOneMin:"Duration: 1 minute", price:"Price", confidence:"Confidence", strategyText:"Strategy", up:"UP", down:"DOWN",
    tgTitle:"📈 Trading Signals", tgPair:"💱  Pair", tgEntry:"⏰  Entry time", tgPrice:"💰  Price", tgConf:"📊  Confidence", tgPattern:"🕯  Pattern", tgRsi:"📉  RSI", tgTrend:"📈  Trend", tgAnalysis:"📝  Analysis", tgSource:"🔬  Source", tgRisk:"⚠️  Trade at your own risk", tgDuration:"      Quotex  —  1 minute",
    groupEUR:"🇪🇺 EUR Pairs", groupUSD:"💵 USD Pairs", groupJPY:"🇯🇵 JPY Pairs", groupAUD:"🦘 AUD Pairs",
    welcomeLog:"✅ Welcome to the trading dashboard", startLog:"▶ Bot started — one trade every minute", stopLog:"⏹ Bot stopped", analyzingLog:"🔍 Instant analysis...", noSignalLog:"⏳ No strong signal right now", errorLog:"❌ Error", noLastSignal:"No signal available", sentTelegram:"✅ Sent to Telegram", sentShort:"✅ Sent", genericError:"Error",
    timingInfo:"⏰ <b>Signal timing</b><br>Sent <b>23 seconds</b> before the candle closes<br>Enter the trade at the <b>start of the next minute</b><br><b>Only one trade — the strongest setup</b>",
    dailyPlanTitle:"🎯 Daily Plan", dailyPlanDesc:"Set your target and loss limits before you trade.", dailyPlanInputsTitle:"🧮 Plan Inputs", dailyPlanResultsTitle:"📊 Results",
    dpAccountBalance:"Account Balance", dpDailyTargetPercent:"Daily Target %", dpDailyLossLimitPercent:"Daily Loss Limit %", dpMaxTrades:"Max Trades", dpPayoutPercent:"Payout %", dpRiskMode:"Plan Mode",
    dpRiskConservative:"Conservative", dpRiskBalanced:"Balanced", dpRiskAggressive:"Aggressive", dpReset:"Reset", dpCopy:"Copy Plan",
    dpTargetAmount:"Daily target", dpLossAmount:"Daily loss limit", dpStake:"Suggested stake", dpProfitPerWin:"Expected profit per win", dpWinsNeeded:"Wins needed for target", dpMode:"Plan mode",
    dpStopRule:"Stop at profit {target}$, loss {loss}$, or after {maxTrades} trades.", dpStatusSafe:"Conservative and relatively safe plan", dpStatusBalanced:"Balanced plan", dpStatusHigh:"High-risk plan",
    dpWarnWins:"Daily target needs more winning trades than your max trades. Lower the target or increase max trades.", dpWarnStake:"Suggested stake is above 5% of account balance, which is high risk.",
    dpCopyTemplate:"NEXO Daily Plan:\nAccount Balance: {balance}$\nDaily Target: {targetPct}% = {target}$\nDaily Loss Limit: {lossPct}% = {loss}$\nMax Trades: {maxTrades}\nSuggested Stake: {stake}$\nExpected Profit Per Win: {profit}$\nStop Rule: Stop at target, loss limit, or max trades.",
    atTitle:"🎯 Account Target", atDesc:"Estimate profit and winning trades required to reach your account target.", atInputsTitle:"🧮 Target Inputs", atResultsTitle:"📊 Target Results",
    atCurrentBalance:"Current Balance", atTargetBalance:"Target Balance", atStakeAmount:"Stake Amount", atPayoutPercent:"Payout %", atDaysCount:"Days to Target",
    atReset:"Reset", atCopy:"Copy Target Plan", atNeededProfit:"Needed Profit", atProfitPerWin:"Profit per Win", atWinsNeeded:"Winning Trades Needed", atGrowthPercent:"Required Account Growth",
    atDailyProfitNeeded:"Daily Profit Needed", atDailyWinsNeeded:"Daily Wins Needed",
    atEvalLow:"Logical low-risk target", atEvalMedium:"Moderate target, better split across sessions", atEvalHigh:"High target, requires strong discipline", atEvalVeryHigh:"Very high-risk target, better reduce or split over more days",
    atWarnTarget:"Target balance must be greater than current balance.", atWarnStake:"Stake amount is above 5% of current balance.", atWarnWins:"Required winning trades are high; consider splitting the target.",
    atCopyTemplate:"NEXO Target Plan:\nCurrent Balance: {current}$\nTarget Balance: {target}$\nNeeded Profit: {needed}$\nStake Amount: {stake}$\nProfit per Win: {profitPerWin}$\nWinning Trades Needed: {wins}\nDays Count: {days}\nDaily Profit Needed: {dailyProfit}$\nDaily Wins Needed: {dailyWins}\nNote: Do not increase risk just to reach the target faster."
  }
};
let appLang = localStorage.getItem("appLang") || localStorage.getItem("publicLang") || "ar";
let signalChannelUrl = "";
const t = (k) => (I18N[appLang] && I18N[appLang][k]) || (I18N.ar[k] || k);
function setLang(lang){
  appLang = lang === "en" ? "en" : "ar";
  localStorage.setItem("appLang", appLang);
  localStorage.setItem("publicLang", appLang);
  applyLanguage();
}
function applyLanguage(){
  const setText=(id,val)=>{ const el=document.getElementById(id); if(el) el.textContent=val; };
  const setHTML=(id,val)=>{ const el=document.getElementById(id); if(el) el.innerHTML=val; };
  document.documentElement.lang = appLang;
  document.documentElement.dir = appLang === 'ar' ? 'rtl' : 'ltr';
  if (document.body) document.body.dir = document.documentElement.dir;
  const ls=document.getElementById('langSelect'); if(ls) ls.value=appLang;
  setText('langLabel', t('langLabel'));
  const loginInput=document.getElementById('userLoginId'); if(loginInput) loginInput.placeholder=t('loginEnterId');
  const joinId=document.getElementById('pubJoinId'); if(joinId) joinId.placeholder=t('loginEnterId');
  const joinEmail=document.getElementById('pubJoinEmail'); if(joinEmail) joinEmail.placeholder=t('joinEmailPlaceholder');
  setText('loginBtn', t('loginBtn')); setText('logoutBtn', t('logoutBtn')); setText('cdlbl', t('cdlbl'));
  setText('joinImageLabel', t('joinImageLabel')); setHTML('joinHint', t('joinHint')); setText('joinSubmitBtn', t('joinSubmit')); setText('backLoginBtn', t('backToLogin'));
  setText('tabBtnLiveLabel', t('tabLive')); setText('tabBtnControlLabel', t('tabControl')); setText('tabBtnLogsLabel', t('tabLogs')); setText('tabBtnPlanLabel', t('tabPlan'));
  setText('bnavLiveLabel', t('bnavLive')); setText('bnavControlLabel', t('bnavControl')); setText('bnavLogsLabel', t('bnavLogs')); setText('bnavPlanLabel', t('bnavPlan'));
  setText('statSignalsLabel', t('statSignalsLabel')); setText('statSignalsSub', t('statSignalsSub')); setText('statTelegramLabel', t('statTelegramLabel')); setText('statTelegramSub', t('statTelegramSub'));
  setText('statPairsLabel', t('statPairsLabel')); setText('statPairsSub', t('statPairsSub')); setText('statSourceLabel', t('statSourceLabel')); setText('statSourceSub', t('statSourceSub'));
  setText('signalsCardTitle', t('signalsCardTitle')); setText('liveEmptyTitle', t('liveEmptyTitle')); setText('liveEmptyDesc', t('liveEmptyDesc'));
  setText('tgPreviewTitle', t('tgPreviewTitle')); setText('sendMiniLabel', t('sendMini')); setText('miniLogTitle', t('miniLogTitle'));
  const tgPrev=document.getElementById('tgPrev'); if(tgPrev && !lastSig) tgPrev.textContent=t('tgWaiting');
  setText('controlTitle', t('controlTitle')); setText('settingsTitle', t('settingsTitle')); setText('pairsTitle', t('pairsTitle')); setHTML('timingInfoHtml', t('timingInfo'));
  setText('strategyLabel', t('strategyLabel')); setText('aiConfirmLabel', t('aiConfirmLabel'));
  setText('aiReviewLabel', t('aiReview')); setText('minAIConfLabel', t('minAIConf')); setText('aiFailureModeLabel', t('aiFailureMode')); setText('showAIReasonLabel', t('showAIReason'));
  setText('aiFailRejectOpt', t('aiFailReject')); setText('aiFailStrongOpt', t('aiFailStrong')); setText('newsWindowLabel', t('newsWindow')); setText('newsWindowValue', t('newsWindowValue'));
  setText('allPairsLabel', t('all')); setText('clearPairsLabel', t('clear')); setText('minConfLabel', t('minConf')); setText('autoTGLabel', t('autoTG'));
  setText('joinChannelLabel', t('joinChannel'));
  setText('btnStartLabel', t('btnStart')); setText('btnStopLabel', t('btnStop')); setText('analyzeBtnLabel', t('analyzeNow')); setText('sendTGLabel', t('sendTG'));
  setText('logsTitle', t('logsTitle')); setText('logsDesc', t('logsDesc')); setText('activityTitle', t('activityTitle')); setText('signalHistoryTitle', t('signalHistoryTitle')); setText('activityBadgeLabel', t('activityCenter')); setText('clearLogsLabel', t('clear'));
  setText('dailyPlanTitle', t('dailyPlanTitle')); setText('dailyPlanDesc', t('dailyPlanDesc')); setText('dailyPlanInputsTitle', t('dailyPlanInputsTitle')); setText('dailyPlanResultsTitle', t('dailyPlanResultsTitle'));
  setText('dpAccountBalanceLabel', t('dpAccountBalance')); setText('dpDailyTargetPercentLabel', t('dpDailyTargetPercent')); setText('dpDailyLossLimitPercentLabel', t('dpDailyLossLimitPercent')); setText('dpMaxTradesLabel', t('dpMaxTrades'));
  setText('dpPayoutPercentLabel', t('dpPayoutPercent')); setText('dpRiskModeLabel', t('dpRiskMode')); setText('dpRiskModeConservative', t('dpRiskConservative')); setText('dpRiskModeBalanced', t('dpRiskBalanced')); setText('dpRiskModeAggressive', t('dpRiskAggressive'));
  setText('dpResetBtn', t('dpReset')); setText('dpCopyBtn', t('dpCopy')); setText('dpTargetAmountLabel', t('dpTargetAmount')); setText('dpLossAmountLabel', t('dpLossAmount'));
  setText('dpStakeLabel', t('dpStake')); setText('dpProfitPerWinLabel', t('dpProfitPerWin')); setText('dpWinsNeededLabel', t('dpWinsNeeded')); setText('dpModeLabel', t('dpMode'));
  setText('atTitle', t('atTitle')); setText('atDesc', t('atDesc')); setText('atInputsTitle', t('atInputsTitle')); setText('atResultsTitle', t('atResultsTitle'));
  setText('atCurrentBalanceLabel', t('atCurrentBalance')); setText('atTargetBalanceLabel', t('atTargetBalance')); setText('atStakeAmountLabel', t('atStakeAmount')); setText('atPayoutPercentLabel', t('atPayoutPercent')); setText('atDaysCountLabel', t('atDaysCount'));
  setText('atResetBtn', t('atReset')); setText('atCopyBtn', t('atCopy')); setText('atNeededProfitLabel', t('atNeededProfit')); setText('atProfitPerWinLabel', t('atProfitPerWin'));
  setText('atWinsNeededLabel', t('atWinsNeeded')); setText('atGrowthPercentLabel', t('atGrowthPercent')); setText('atDailyProfitNeededLabel', t('atDailyProfitNeeded')); setText('atDailyWinsNeededLabel', t('atDailyWinsNeeded'));
  setText('signalHistoryEmptyTitle', t('emptySignalsTitle')); setText('signalHistoryEmptyDesc', t('emptySignalsDesc'));
  const aLog=document.getElementById('aLog'); if(aLog && !aLog.children.length){ aLog.innerHTML=`<div class="le"><div class="lt">--:--</div><div class="lm info">${t('waitingStart')}</div></div>`; }
  const initialMini=document.getElementById('initialMiniLog'); if(initialMini) initialMini.textContent=t('waitingStart');
  if (typeof renderStrategyOptions === 'function') renderStrategyOptions();
  if (typeof updateDailyPlan === 'function') updateDailyPlan();
  if (typeof updateAccountTarget === 'function') updateAccountTarget();
  if (typeof renderPairs === 'function') renderPairs();
  if (typeof updateJoinChannelButton === 'function') updateJoinChannelButton();
  syncSignalHistory(); syncMiniLogs(); setStatus(document.getElementById('sdot')?.classList.contains('on'));
}
// ══ بيانات الأزواج ══
const ALL = {
  EUR: ["EUR_JPY","EUR_AUD","EUR_GBP","EUR_USD","EUR_CHF","EUR_CAD","EUR_NZD"],
  USD: ["GBP_USD","USD_JPY","USD_CHF","USD_CAD","AUD_USD","NZD_USD"],
  JPY: ["AUD_JPY","GBP_JPY","CAD_JPY","NZD_JPY","CHF_JPY"],
  AUD: ["AUD_CHF","AUD_NZD"],
};
const GROUPS = ["EUR","USD","JPY","AUD"];
function groupLabel(g){ return t(`group${g}`); }
const NAMES = {EUR_JPY:"EUR/JPY",AUD_JPY:"AUD/JPY",GBP_USD:"GBP/USD",USD_JPY:"USD/JPY",EUR_AUD:"EUR/AUD",AUD_CHF:"AUD/CHF",EUR_GBP:"EUR/GBP",EUR_USD:"EUR/USD",GBP_JPY:"GBP/JPY",USD_CHF:"USD/CHF",USD_CAD:"USD/CAD",AUD_USD:"AUD/USD",NZD_USD:"NZD/USD",CAD_JPY:"CAD/JPY",NZD_JPY:"NZD/JPY",EUR_CHF:"EUR/CHF"};
const pname = id => NAMES[id] || String(id || "").replace("_","/");
const FLAG_MAP = {EUR:"🇪🇺", USD:"🇺🇸", GBP:"🇬🇧", JPY:"🇯🇵", AUD:"🇦🇺", CHF:"🇨🇭", CAD:"🇨🇦", NZD:"🇳🇿", BRL:"🇧🇷", BDT:"🇧🇩", EGP:"🇪🇬"};
const FLAG_COUNTRY_CODES = {EUR:"eu", USD:"us", GBP:"gb", JPY:"jp", AUD:"au", CHF:"ch", CAD:"ca", NZD:"nz", BRL:"br", BDT:"bd", EGP:"eg"};
const normalizePairId = (id) => String(id || "").toUpperCase().replace(/\s*\(OTC\)/g, "").replace(/\//g, "_");
const pairFlags = (id) => {
  const parts = normalizePairId(id).match(/[A-Z]{3}/g) || [];
  return parts.slice(0,2).map(p => FLAG_MAP[p] || "🏳️").join(" ");
};
const flagImg = (code, label) => {
  const cc = FLAG_COUNTRY_CODES[code];
  if (!cc) return `<span>${FLAG_MAP[code] || "🏳️"}</span>`;
  return `<img class="flag-badge" src="https://flagcdn.com/24x18/${cc}.png" alt="${label || code}" loading="lazy" referrerpolicy="no-referrer" onerror="this.outerHTML='${FLAG_MAP[code] || "🏳️"}'">`;
};
const pairFlagBadges = (id) => {
  const parts = normalizePairId(id).match(/[A-Z]{3}/g) || [];
  return parts.slice(0,2).map(code => flagImg(code, code)).join("");
};
const PAIR_FILTERS = {
  all: () => true,
  majors: id => ["EUR_USD","GBP_USD","USD_JPY","USD_CHF","USD_CAD","AUD_USD","NZD_USD"].includes(id),
  jpy: id => id.includes("JPY"),
  high_vol: id => ["GBP_USD","GBP_JPY","EUR_JPY","AUD_JPY","USD_JPY","EUR_AUD"].includes(id),
  eur: id => id.includes("EUR"),
  usd: id => id.includes("USD"),
  aud: id => id.includes("AUD"),
};
function pairMatchesFilter(id){
  const f = document.getElementById("pairFilter")?.value || "all";
  return (PAIR_FILTERS[f] || PAIR_FILTERS.all)(id);
}
const STRATEGIES = {
  smart_auto:{icon:"🤖", ar:"الوضع الذكي", en:"Smart Auto", desc_ar:"يفحص جميع الاستراتيجيات ويختار أفضل فرصة تلقائياً.", desc_en:"Runs all strategies and automatically picks the strongest setup.", indicators:"RSI • MACD • EMA • BB • ADX"},
  confluence:{icon:"🧠", ar:"التوافق الذكي", en:"Confluence", desc_ar:"يجمع الاتجاه والزخم والشموع و Price Action في قرار واحد.", desc_en:"Combines trend, momentum, candles, and price action into one decision.", indicators:"EMA • MACD • ADX • PA"},
  rsi_reversal:{icon:"📉", ar:"انعكاس RSI", en:"RSI Reversal", desc_ar:"يعتمد على مناطق التشبع مع شمعة انعكاسية قوية.", desc_en:"Uses overbought/oversold zones with a strong reversal candle.", indicators:"RSI • Stoch • BB"},
  macd_trend:{icon:"📈", ar:"اتجاه MACD", en:"MACD Trend", desc_ar:"استراتيجية اتجاه سريعة مع MACD و EMA و ADX.", desc_en:"Fast trend setup using MACD, EMA, and ADX.", indicators:"MACD • EMA • ADX"},
  bollinger_reversal:{icon:"🎯", ar:"ارتداد بولنجر", en:"Bollinger Bounce", desc_ar:"يلتقط الارتداد من حدود بولنجر مع تأكيد RSI.", desc_en:"Captures reversals at Bollinger Band edges with RSI confirmation.", indicators:"BB • RSI • PA"},
  stochastic_reversal:{icon:"⚡", ar:"انعكاس ستوكاستك", en:"Stochastic Reversal", desc_ar:"يلتقط الانعكاس السريع من تشبع Stochastic مع تأكيد RSI.", desc_en:"Captures fast reversals from Stochastic extremes with RSI confirmation.", indicators:"Stoch • RSI • PA"},
  ema_cross:{icon:"🔀", ar:"تقاطع EMA", en:"EMA Cross", desc_ar:"تقاطع EMA سريع/بطيء مع تأكيد الزخم.", desc_en:"Fast/slow EMA crossover with momentum confirmation.", indicators:"EMA 5/20 • MACD • Momentum"},
  adx_breakout:{icon:"🚀", ar:"اختراق ADX", en:"ADX Breakout", desc_ar:"اختراقات قوية عندما يؤكد ADX قوة الاتجاه.", desc_en:"Breakout setups confirmed by ADX trend strength.", indicators:"ADX • DI • ATR"},
};
let currentStrategy = "smart_auto";
function strategyLabel(id){ const s = STRATEGIES[id] || STRATEGIES.smart_auto; return `${s.icon} ${appLang === 'ar' ? s.ar : s.en}`; }
function renderStrategyOptions(){
  const sel = document.getElementById('strategySelect');
  if (!sel) return;
  const selected = currentStrategy || sel.value || 'smart_auto';
  sel.innerHTML = Object.entries(STRATEGIES).map(([id, s]) => `<option value="${id}">${s.icon} ${appLang === 'ar' ? s.ar : s.en}</option>`).join('');
  sel.value = selected in STRATEGIES ? selected : 'smart_auto';
  renderStrategyInfo();
}
function renderStrategyInfo(){
  const id = document.getElementById('strategySelect')?.value || currentStrategy || 'smart_auto';
  currentStrategy = id;
  const box = document.getElementById('strategyInfo');
  if (!box) return;
  const s = STRATEGIES[id] || STRATEGIES.smart_auto;
  const title = appLang === 'ar' ? s.ar : s.en;
  const desc = appLang === 'ar' ? s.desc_ar : s.desc_en;
  box.innerHTML = `<div class="strategy-head"><div class="strategy-ic">${s.icon}</div><div><div class="strategy-title">${title}</div><div class="strategy-desc">${desc}</div></div></div><div class="strategy-tags"><span class="strategy-tag">${s.indicators}</span><span class="strategy-tag">Quotex M1</span></div>`;
}

let active = new Set(["EUR_JPY","AUD_JPY","GBP_USD","USD_JPY","EUR_AUD","AUD_CHF","EUR_GBP"]);
let lastSig = null, pollTimer = null, logged = false, prevCount = 0, joinReqHash = "", lastMarketMsg = "";
let currentTab = "live";
const DAILY_PLAN_DEFAULTS = {
  accountBalance: 100,
  dailyTargetPercent: 5,
  dailyLossLimitPercent: 3,
  maxTrades: 5,
  payoutPercent: 85,
  riskMode: "balanced",
};
const ACCOUNT_TARGET_DEFAULTS = {
  currentBalance: 100,
  targetBalance: 150,
  stakeAmount: 5,
  payoutPercent: 85,
  daysCount: 5,
};
function switchTab(tabId) {
  currentTab = tabId;
  const tabs = [
    {btn:"tabBtnLive", pane:"tabLive", id:"live"},
    {btn:"tabBtnControl", pane:"tabControl", id:"control"},
    {btn:"tabBtnLogs", pane:"tabLogs", id:"logs"},
    {btn:"tabBtnPlan", pane:"tabPlan", id:"plan"},
  ];
  const bottom = [
    {btn:"bnavLive", id:"live"},
    {btn:"bnavControl", id:"control"},
    {btn:"bnavLogs", id:"logs"},
    {btn:"bnavPlan", id:"plan"},
  ];
  tabs.forEach(t => {
    const b = document.getElementById(t.btn);
    const p = document.getElementById(t.pane);
    if (b) b.classList.toggle("active", t.id === tabId);
    if (p) p.classList.toggle("active", t.id === tabId);
  });
  bottom.forEach(t => {
    const b = document.getElementById(t.btn);
    if (b) b.classList.toggle("active", t.id === tabId);
  });
}

function dpNum(id, fallback){
  const el = document.getElementById(id);
  const raw = String(el?.value || "").replace(/[٠-٩]/g, d => "٠١٢٣٤٥٦٧٨٩".indexOf(d)).replace(/[۰-۹]/g, d => "۰۱۲۳۴۵۶۷۸۹".indexOf(d));
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : fallback;
}
function dpInt(id, fallback){
  const el = document.getElementById(id);
  const n = parseInt(el?.value, 10);
  return Number.isFinite(n) ? n : fallback;
}
function dpFmt(v){
  const n = Number.isFinite(v) ? v : 0;
  return n.toFixed(2);
}
function dpTpl(key, values){
  let txt = t(key) || "";
  Object.entries(values || {}).forEach(([k, v]) => {
    txt = txt.replaceAll(`{${k}}`, String(v));
  });
  return txt;
}
function setDpText(id, val){
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}
function adjustPlanField(id, dir, step=1, min=0){
  const el = document.getElementById(id);
  if (!el) return;
  const current = Number.isFinite(parseFloat(el.value)) ? parseFloat(el.value) : parseFloat(el.min || 0) || 0;
  const next = Math.max(min, Math.round(current + (dir * step)));
  el.value = String(next);
  if (id.startsWith("dp")) updateDailyPlan();
  else if (id.startsWith("at")) updateAccountTarget();
}
function adjustRiskMode(dir){
  const modes = ["conservative","balanced","aggressive"];
  const el = document.getElementById("dpRiskMode");
  if (!el) return;
  const current = modes.indexOf(el.value);
  const idx = current < 0 ? 1 : current;
  const next = (idx + (dir > 0 ? 1 : -1) + modes.length) % modes.length;
  el.value = modes[next];
  updateDailyPlan();
}
function normalizeDailyPlanInputs(){
  const clampInt = (id, minVal, fallback) => {
    const el = document.getElementById(id);
    if (!el) return fallback;
    const n = Math.max(minVal, Math.round(dpNum(id, fallback)));
    el.value = String(n);
    return n;
  };
  return {
    accountBalance: clampInt("dpAccountBalance", 1, DAILY_PLAN_DEFAULTS.accountBalance),
    dailyTargetPercent: clampInt("dpDailyTargetPercent", 1, DAILY_PLAN_DEFAULTS.dailyTargetPercent),
    dailyLossLimitPercent: clampInt("dpDailyLossLimitPercent", 1, DAILY_PLAN_DEFAULTS.dailyLossLimitPercent),
    maxTrades: clampInt("dpMaxTrades", 1, DAILY_PLAN_DEFAULTS.maxTrades),
    payoutPercent: clampInt("dpPayoutPercent", 1, DAILY_PLAN_DEFAULTS.payoutPercent),
    riskMode: document.getElementById("dpRiskMode")?.value || DAILY_PLAN_DEFAULTS.riskMode,
  };
}
function updateDailyPlan(){
  const normalized = normalizeDailyPlanInputs();
  const accountBalance = normalized.accountBalance;
  const dailyTargetPercent = normalized.dailyTargetPercent;
  const dailyLossLimitPercent = normalized.dailyLossLimitPercent;
  const maxTrades = normalized.maxTrades;
  const payoutPercent = normalized.payoutPercent;
  const riskMode = normalized.riskMode;
  const mult = riskMode === "conservative" ? 0.75 : (riskMode === "aggressive" ? 1.25 : 1);

  const dailyTargetAmount = (accountBalance * dailyTargetPercent) / 100;
  const dailyLossLimitAmount = (accountBalance * dailyLossLimitPercent) / 100;
  const baseStake = maxTrades > 0 ? (dailyLossLimitAmount / maxTrades) : 0;
  const suggestedStake = baseStake * mult;
  const expectedProfitPerWin = (suggestedStake * payoutPercent) / 100;
  const winsNeededForTarget = expectedProfitPerWin > 0 ? Math.ceil(dailyTargetAmount / expectedProfitPerWin) : 0;

  setDpText("dpTargetAmount", `+${dpFmt(dailyTargetAmount)}$`);
  setDpText("dpLossAmount", `-${dpFmt(dailyLossLimitAmount)}$`);
  setDpText("dpStakeAmount", `${dpFmt(suggestedStake)}$`);
  setDpText("dpProfitPerWin", `${dpFmt(expectedProfitPerWin)}$`);
  setDpText("dpWinsNeeded", `${winsNeededForTarget}`);
  const modeLabel = riskMode === "conservative" ? t("dpRiskConservative") : (riskMode === "aggressive" ? t("dpRiskAggressive") : t("dpRiskBalanced"));
  setDpText("dpMode", modeLabel);
  setDpText("dpStopRule", dpTpl("dpStopRule", {target:dpFmt(dailyTargetAmount), loss:dpFmt(dailyLossLimitAmount), maxTrades}));

  const stateEl = document.getElementById("dpPlanState");
  let stateKey = "dpStatusBalanced";
  let stateCls = "balanced";
  if (dailyTargetPercent <= 3 && dailyLossLimitPercent <= 2) {
    stateKey = "dpStatusSafe"; stateCls = "safe";
  } else if (dailyTargetPercent > 5 || dailyLossLimitPercent > 5) {
    stateKey = "dpStatusHigh"; stateCls = "high";
  }
  if (stateEl) {
    stateEl.className = `plan-state ${stateCls}`;
    stateEl.textContent = t(stateKey);
  }

  const warns = [];
  if (winsNeededForTarget > maxTrades) warns.push(t("dpWarnWins"));
  if (suggestedStake > accountBalance * 0.05) warns.push(t("dpWarnStake"));
  const warnEl = document.getElementById("dpWarnings");
  if (warnEl) warnEl.innerHTML = warns.map(w => `<div class="plan-warn">⚠️ ${w}</div>`).join("");
}
function resetDailyPlan(){
  const d = DAILY_PLAN_DEFAULTS;
  const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = String(val); };
  setVal("dpAccountBalance", d.accountBalance);
  setVal("dpDailyTargetPercent", d.dailyTargetPercent);
  setVal("dpDailyLossLimitPercent", d.dailyLossLimitPercent);
  setVal("dpMaxTrades", d.maxTrades);
  setVal("dpPayoutPercent", d.payoutPercent);
  setVal("dpRiskMode", d.riskMode);
  updateDailyPlan();
}
async function copyDailyPlan(){
  const balance = Math.max(0, dpNum("dpAccountBalance", DAILY_PLAN_DEFAULTS.accountBalance));
  const targetPct = Math.max(0, dpNum("dpDailyTargetPercent", DAILY_PLAN_DEFAULTS.dailyTargetPercent));
  const lossPct = Math.max(0, dpNum("dpDailyLossLimitPercent", DAILY_PLAN_DEFAULTS.dailyLossLimitPercent));
  const maxTrades = Math.max(1, dpInt("dpMaxTrades", DAILY_PLAN_DEFAULTS.maxTrades));
  const payout = Math.max(0, dpNum("dpPayoutPercent", DAILY_PLAN_DEFAULTS.payoutPercent));
  const riskMode = document.getElementById("dpRiskMode")?.value || DAILY_PLAN_DEFAULTS.riskMode;
  const mult = riskMode === "conservative" ? 0.75 : (riskMode === "aggressive" ? 1.25 : 1);
  const target = (balance * targetPct) / 100;
  const loss = (balance * lossPct) / 100;
  const stake = ((loss / maxTrades) * mult);
  const profit = (stake * payout) / 100;
  const txt = dpTpl("dpCopyTemplate", {
    balance: dpFmt(balance), targetPct: dpFmt(targetPct), target: dpFmt(target),
    lossPct: dpFmt(lossPct), loss: dpFmt(loss), maxTrades, stake: dpFmt(stake), profit: dpFmt(profit)
  });
  try {
    await navigator.clipboard.writeText(txt);
    notify("✅ " + t("dpCopy"), "ok");
  } catch {
    notify("❌ " + t("connectionError"), "err");
  }
}
function normalizeAccountTargetInputs(){
  const clampInt = (id, minVal, fallback) => {
    const el = document.getElementById(id);
    if (!el) return fallback;
    const n = Math.max(minVal, Math.round(dpNum(id, fallback)));
    el.value = String(n);
    return n;
  };
  return {
    currentBalance: clampInt("atCurrentBalance", 1, ACCOUNT_TARGET_DEFAULTS.currentBalance),
    targetBalance: clampInt("atTargetBalance", 1, ACCOUNT_TARGET_DEFAULTS.targetBalance),
    stakeAmount: clampInt("atStakeAmount", 1, ACCOUNT_TARGET_DEFAULTS.stakeAmount),
    payoutPercent: clampInt("atPayoutPercent", 1, ACCOUNT_TARGET_DEFAULTS.payoutPercent),
    daysCount: clampInt("atDaysCount", 1, ACCOUNT_TARGET_DEFAULTS.daysCount),
  };
}
function updateAccountTarget(){
  const n = normalizeAccountTargetInputs();
  const neededProfitRaw = n.targetBalance - n.currentBalance;
  const neededProfit = Math.max(0, neededProfitRaw);
  const profitPerWin = (n.stakeAmount * n.payoutPercent) / 100;
  const winsNeeded = neededProfit > 0 && profitPerWin > 0 ? Math.ceil(neededProfit / profitPerWin) : 0;
  const growthPercent = n.currentBalance > 0 ? (neededProfit / n.currentBalance) * 100 : 0;
  const dailyProfitNeeded = n.daysCount > 0 ? (neededProfit / n.daysCount) : 0;
  const dailyWinsNeeded = n.daysCount > 0 ? Math.ceil(winsNeeded / n.daysCount) : 0;

  setDpText("atNeededProfit", `${dpFmt(neededProfit)}$`);
  setDpText("atProfitPerWin", `${dpFmt(profitPerWin)}$`);
  setDpText("atWinsNeeded", `${winsNeeded}`);
  setDpText("atGrowthPercent", `${dpFmt(growthPercent)}%`);
  setDpText("atDailyProfitNeeded", `${dpFmt(dailyProfitNeeded)}$`);
  setDpText("atDailyWinsNeeded", `${dailyWinsNeeded}`);

  const evalEl = document.getElementById("atEvaluation");
  let evalKey = "atEvalMedium";
  let evalCls = "balanced";
  if (growthPercent <= 10) { evalKey = "atEvalLow"; evalCls = "safe"; }
  else if (growthPercent > 10 && growthPercent <= 30) { evalKey = "atEvalMedium"; evalCls = "balanced"; }
  else if (growthPercent > 30 && growthPercent <= 50) { evalKey = "atEvalHigh"; evalCls = "caution"; }
  else if (growthPercent > 50) { evalKey = "atEvalVeryHigh"; evalCls = "high"; }
  if (evalEl) {
    evalEl.className = `plan-state ${evalCls}`;
    evalEl.textContent = t(evalKey);
  }

  const warns = [];
  if (n.targetBalance <= n.currentBalance) warns.push(t("atWarnTarget"));
  if (n.stakeAmount > n.currentBalance * 0.05) warns.push(t("atWarnStake"));
  if (winsNeeded > 15) warns.push(t("atWarnWins"));
  const warnEl = document.getElementById("atWarnings");
  if (warnEl) warnEl.innerHTML = warns.map(w => `<div class="plan-warn">⚠️ ${w}</div>`).join("");
}
function resetAccountTarget(){
  const d = ACCOUNT_TARGET_DEFAULTS;
  const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = String(val); };
  setVal("atCurrentBalance", d.currentBalance);
  setVal("atTargetBalance", d.targetBalance);
  setVal("atStakeAmount", d.stakeAmount);
  setVal("atPayoutPercent", d.payoutPercent);
  setVal("atDaysCount", d.daysCount);
  updateAccountTarget();
}
async function copyAccountTargetPlan(){
  const n = normalizeAccountTargetInputs();
  const neededProfit = Math.max(0, n.targetBalance - n.currentBalance);
  const profitPerWin = (n.stakeAmount * n.payoutPercent) / 100;
  const winsNeeded = neededProfit > 0 && profitPerWin > 0 ? Math.ceil(neededProfit / profitPerWin) : 0;
  const dailyProfitNeeded = n.daysCount > 0 ? (neededProfit / n.daysCount) : 0;
  const dailyWinsNeeded = n.daysCount > 0 ? Math.ceil(winsNeeded / n.daysCount) : 0;
  const txt = dpTpl("atCopyTemplate", {
    current: dpFmt(n.currentBalance),
    target: dpFmt(n.targetBalance),
    needed: dpFmt(neededProfit),
    stake: dpFmt(n.stakeAmount),
    profitPerWin: dpFmt(profitPerWin),
    wins: winsNeeded,
    days: n.daysCount,
    dailyProfit: dpFmt(dailyProfitNeeded),
    dailyWins: dailyWinsNeeded,
  });
  try {
    await navigator.clipboard.writeText(txt);
    notify("✅ " + t("atCopy"), "ok");
  } catch {
    notify("❌ " + t("connectionError"), "err");
  }
}

// ── دخول / خروج ──
function showJoinForm(prefillId="") {
  const loginBox = document.getElementById("idLoginBox");
  const joinBox = document.getElementById("joinBox");
  if (loginBox) loginBox.style.display = "none";
  if (joinBox) joinBox.style.display = "block";
  if (prefillId && document.getElementById("pubJoinId")) {
    document.getElementById("pubJoinId").value = prefillId;
  }
}

function showIdLogin() {
  const loginBox = document.getElementById("idLoginBox");
  const joinBox = document.getElementById("joinBox");
  if (joinBox) joinBox.style.display = "none";
  if (loginBox) loginBox.style.display = "block";
}

async function userIdLogin() {
  const accountId = document.getElementById("userLoginId")?.value.trim();
  const msgEl = document.getElementById("userLoginMsg");
  if (!accountId) {
    if (msgEl) { msgEl.style.display = "block"; msgEl.style.color = "var(--dn)"; msgEl.textContent = t("loginEnterId"); }
    return;
  }
  if (msgEl) { msgEl.style.display = "block"; msgEl.style.color = "var(--ac)"; msgEl.textContent = t("checking"); }
  try {
    const r = await fetch("/api/user/login", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({account_id: accountId}),
    });
    const d = await r.json();
    if (d.ok && d.status === "approved") {
      document.getElementById("LS").style.display="none";
      document.getElementById("APP").style.display="block";
      logged=true; init();
      return;
    }
    if (d.status === "pending") {
      notify("⏳ " + t("pending"), "ok");
      if (msgEl) {
        msgEl.style.color = "var(--gold)";
        msgEl.textContent = t("pending");
      }
      return;
    }
    if (d.status === "not_found") {
      notify("⚠️ " + t("notFound"), "err");
      if (msgEl) {
        msgEl.style.color = "var(--dn)";
        msgEl.textContent = t("notFound");
      }
      showJoinForm(accountId);
      return;
    }
    if (msgEl) { msgEl.style.color = "var(--dn)"; msgEl.textContent = d.msg || t("loginFailed"); }
  } catch {
    if (msgEl) { msgEl.style.color = "var(--dn)"; msgEl.textContent = t("connectionError"); }
  }
}
function doLogout() {
  logged=false; clearInterval(pollTimer);
  location.href = "/";
}

async function submitJoinPublic() {
  const accountId = document.getElementById("pubJoinId")?.value.trim();
  const email = document.getElementById("pubJoinEmail")?.value.trim();
  const file = document.getElementById("pubJoinImg")?.files?.[0];
  const msgEl = document.getElementById("pubJoinMsg");
  if (!accountId || !email || !file) {
    if (msgEl) {
      msgEl.style.display = "block";
      msgEl.style.color = "var(--dn)";
      msgEl.textContent = t("joinMissing");
    }
    return;
  }
  const fd = new FormData();
  fd.append("account_id", accountId);
  fd.append("email", email);
  fd.append("profile_image", file);
  if (msgEl) {
    msgEl.style.display = "block";
    msgEl.style.color = "var(--ac)";
    msgEl.textContent = t("joinSending");
  }
  try {
    const r = await fetch("/api/join-request", {method:"POST", body:fd});
    const d = await r.json();
    if (d.ok) {
      if (msgEl) {
        msgEl.style.color = "var(--up)";
        msgEl.textContent = t("joinSuccess");
      }
      notify("✅ " + t("joinSuccess"), "ok");
      document.getElementById("pubJoinId").value = "";
      document.getElementById("pubJoinEmail").value = "";
      document.getElementById("pubJoinImg").value = "";
    } else if (msgEl) {
      msgEl.style.color = "var(--dn)";
      msgEl.textContent = d.msg || t("joinSubmitError");
      if ((d.msg || "").includes("قيد المراجعة")) {
        notify("⏳ " + t("pending"), "ok");
      }
    }
  } catch {
    if (msgEl) {
      msgEl.style.color = "var(--dn)";
      msgEl.textContent = t("connectionError");
    }
  }
}

function init() {
  switchTab("live");
  applyLanguage();
  fetch("/api/config").then(r=>r.json()).then(d=>{
    active = new Set(d.active_pairs||[]);
    currentStrategy = d.strategy || "smart_auto";
    signalChannelUrl = d.signal_channel_url || "";
    document.getElementById("minConf").value = d.min_confidence||70;
    if ((d.ai_provider || "").toLowerCase() !== "groq") {
      fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ai_provider:"groq"})});
    }
    const togAI = document.getElementById("togAI");
    if (togAI) togAI.classList.toggle("on", d.ai_confirmation !== false);
    const togAIReview = document.getElementById("togAIReview");
    if (togAIReview) togAIReview.classList.toggle("on", d.ai_review_enabled !== false);
    const minAIConf = document.getElementById("minAIConf");
    if (minAIConf) minAIConf.value = String(d.minimum_ai_confidence || 75);
    const aiFailureMode = document.getElementById("aiFailureMode");
    if (aiFailureMode) aiFailureMode.value = (d.ai_failure_mode || "reject");
    const togShowAIReason = document.getElementById("togShowAIReason");
    if (togShowAIReason) togShowAIReason.classList.toggle("on", d.show_ai_reason === true);
    const nw = document.getElementById("newsWindowValue");
    if (nw) nw.textContent = `${d.news_filter_before_min || 30} دقيقة قبل الخبر / ${d.news_filter_after_min || 15} دقيقة بعد الخبر`;
    renderStrategyOptions();
    renderPairs(); updatePC();
  });
  pollTimer = setInterval(poll, 2000);
  poll();
  addLog(t("welcomeLog"),"ok");
  applyLanguage();
}

function renderJoinRequests(list) {
  const el = document.getElementById("joinReqList");
  if (!el) return;
  const pending = (list||[]).filter(x => x.status==="pending");
  const cnt = document.getElementById("joinCountBadge");
  if (cnt) cnt.textContent = pending.length;
  if (!pending.length) {
    el.innerHTML = `<div class="empty-state"><div class="e-ic">📥</div><div class="e-tt">لا توجد طلبات قيد الانتظار</div><div>ستظهر هنا طلبات المستخدمين الجدد</div></div>`;
    return;
  }
  el.innerHTML = pending.slice(0,20).map(r => `
    <div class="req-row">
      <div class="req-meta">
        <span class="req-k">Account ID</span>
        <span class="req-v ltr">${r.account_id}</span>
      </div>
      <div class="req-meta">
        <span class="req-k">Email</span>
        <span class="req-v ltr">${r.email}</span>
      </div>
      <div style="margin:6px 0"><a href="${r.image_url}" target="_blank" style="color:#7dd3fc">عرض الصورة</a></div>
      <div style="display:flex;gap:6px;margin-top:8px">
        <button class="btn-g btn-sm success-btn" onclick="approveReq('${r.id}')">قبول</button>
        <button class="btn-g btn-sm danger-btn" onclick="rejectReq('${r.id}')">رفض</button>
      </div>
    </div>
  `).join("");
}

async function loadJoinRequests() {
  const r = await fetch("/api/join-requests");
  const d = await r.json();
  const hash = JSON.stringify([d.pending_count, d.approved_count, d.requests[0]?.id, d.requests[0]?.status]);
  if (hash !== joinReqHash) {
    renderJoinRequests(d.requests || []);
    joinReqHash = hash;
  }
}

async function loadActiveUsers() {
  const el = document.getElementById("activeUsersList");
  if (!el) return;
  try {
    const r = await fetch("/api/admin/overview");
    const d = await r.json();
    const users = d.active_users || [];
    const cnt = document.getElementById("usersCountBadge");
    if (cnt) cnt.textContent = users.length;
    if (!users.length) {
      el.innerHTML = `<div class="empty-state"><div class="e-ic">👤</div><div class="e-tt">لا يوجد مستخدمون مقبولون</div><div>عند قبول مستخدم جديد سيظهر هنا</div></div>`;
      return;
    }
    el.innerHTML = users.slice(0,50).map(u => `
      <div class="user-row">
        <div>
          <div class="u-id" dir="ltr">${u.account_id}</div>
          <div class="u-email" dir="ltr">${u.email || "—"}</div>
        </div>
        <div style="display:grid;gap:4px;justify-items:end">
          <span class="badge-pill" style="background:rgba(34,197,94,.14);border-color:rgba(34,197,94,.35);color:#86efac">مقبول</span>
          <div style="font-size:10px;color:var(--up)">${(u.activated_at||"").slice(11,16)}</div>
        </div>
      </div>
    `).join("");
  } catch {}
}

async function approveReq(id) {
  const r = await fetch(`/api/join-request/${id}/approve`, {method:"POST"});
  const d = await r.json();
  if (d.ok) { addLog(`✅ تم قبول الطلب ${id}`,"ok"); loadJoinRequests(); }
}
async function rejectReq(id) {
  const r = await fetch(`/api/join-request/${id}/reject`, {method:"POST"});
  const d = await r.json();
  if (d.ok) { addLog(`❌ تم رفض الطلب ${id}`,"warn"); loadJoinRequests(); }
}

// ── رسم الأزواج ──
function renderPairs() {
  let h="";
  for (const g of GROUPS) {
    const ids = (ALL[g]||[]).filter(pairMatchesFilter);
    if (!ids.length) continue;
    h += `<div class="pg">${groupLabel(g)}</div>`;
    ids.forEach(id => {
      const on = active.has(id);
      h += `<div class="pi ${on?"on":""}" id="pi-${id}" onclick="togP('${id}')">
        <div style="display:flex;align-items:center;gap:7px">
          <input type="checkbox" class="pchk" ${on?"checked":""} onclick="event.stopPropagation();togP('${id}')" id="ck-${id}">
          <span class="pflags">${pairFlagBadges(id)}</span><span class="pn" dir="ltr">${pname(id)}</span>
        </div>
        <div class="ppr" id="pp-${id}">---</div>
      </div>`;
    });
  }
  const el = document.getElementById("pList");
  if (el) el.innerHTML = h || `<div class="empty-state"><div class="e-ic">🔎</div><div class="e-tt">No pairs</div><div>Change market filter</div></div>`;
}
function togP(id) {
  active.has(id) ? active.delete(id) : active.add(id);
  const el=document.getElementById(`pi-${id}`);
  if (el) el.className=`pi ${active.has(id)?"on":""}`;
  const ck=document.getElementById(`ck-${id}`);
  if (ck) ck.checked=active.has(id);
  updatePC();
  fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({active_pairs:[...active]})});
}
function selAll()  { Object.values(ALL).flat().filter(pairMatchesFilter).forEach(id=>active.add(id));   renderPairs(); updatePC(); savePairs(); }
function selNone() { Object.values(ALL).flat().filter(pairMatchesFilter).forEach(id=>active.delete(id)); renderPairs(); updatePC(); savePairs(); }
function savePairs(){ fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({active_pairs:[...active]})}); }
function updatePC(){ document.getElementById("sPrs").textContent=active.size; }
function saveStrategy(){
  const sel = document.getElementById("strategySelect");
  currentStrategy = sel ? sel.value : "smart_auto";
  renderStrategyInfo();
  fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({strategy:currentStrategy})});
}
function saveConf(){
  fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({min_confidence:parseInt(document.getElementById("minConf").value)})});
}
function saveAIProvider(){
  const el=document.getElementById("aiProvider");
  fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({ai_provider:el ? el.value : "auto"})});
}
function toggleAIConfirm(){
  const el=document.getElementById("togAI"); el.classList.toggle("on");
  fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({ai_confirmation:el.classList.contains("on")})});
}
function toggleAIReview(){
  const el=document.getElementById("togAIReview"); el.classList.toggle("on");
  fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({ai_review_enabled:el.classList.contains("on")})});
}
function saveMinAIConf(){
  const el=document.getElementById("minAIConf");
  fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({minimum_ai_confidence:parseInt(el ? el.value : "75")})});
}
function saveAIFailureMode(){
  const el=document.getElementById("aiFailureMode");
  fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({ai_failure_mode:(el ? el.value : "reject")})});
}
function toggleShowAIReason(){
  const el=document.getElementById("togShowAIReason"); el.classList.toggle("on");
  fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({show_ai_reason:el.classList.contains("on")})});
}
function joinSignalChannel(){
  if (!signalChannelUrl) {
    notify("❌ TG_CHANNEL_URL not set", "err");
    return;
  }
  window.open(signalChannelUrl, "_blank", "noopener,noreferrer");
}

async function submitJoinMain(){
  const accountId = document.getElementById("joinAccountId")?.value.trim();
  const email = document.getElementById("joinEmail")?.value.trim();
  const file = document.getElementById("joinProfileImage")?.files?.[0];
  const msgEl = document.getElementById("joinMainMsg");
  if (!accountId || !email || !file) {
    if (msgEl) { msgEl.style.color = "var(--dn)"; msgEl.textContent = "املأ ID و Email وارفق صورة"; }
    return;
  }
  const fd = new FormData();
  fd.append("account_id", accountId);
  fd.append("email", email);
  fd.append("profile_image", file);
  if (msgEl) { msgEl.style.color = "var(--mt)"; msgEl.textContent = t("joinSending"); }
  try {
    const r = await fetch("/api/join-request", {method:"POST", body:fd});
    const d = await r.json();
    if (d.ok) {
      if (d.status === "approved") {
        if (msgEl) { msgEl.style.color = "var(--up)"; msgEl.textContent = d.msg || "الحساب مقبول مسبقًا، سيتم تحويلك لتسجيل الدخول..."; }
        setTimeout(()=>{ window.location.href = d.redirect || "/login"; }, 500);
        return;
      }
      if (msgEl) { msgEl.style.color = "var(--up)"; msgEl.textContent = "تم إرسال الطلب بنجاح ✅"; }
      document.getElementById("joinAccountId").value = "";
      document.getElementById("joinEmail").value = "";
      document.getElementById("joinProfileImage").value = "";
    } else {
      if (msgEl) { msgEl.style.color = "var(--dn)"; msgEl.textContent = d.msg || t("joinSubmitError"); }
    }
  } catch {
    if (msgEl) { msgEl.style.color = "var(--dn)"; msgEl.textContent = t("connectionError"); }
  }
}

// ── التحكم بالبوت ──
function startBot() {
  document.getElementById("loader").style.display="flex";
  fetch("/api/bot/start",{method:"POST"}).then(r=>r.json()).then(d=>{
    document.getElementById("loader").style.display="none";
    if (d.ok) {
      setStatus(true);
      addLog(t("startLog"),"ok");
      document.getElementById("btnStart").disabled=true;
      document.getElementById("btnStop").disabled=false;
    } else { notify(d.msg||t("genericError"),"err"); }
  });
}
function stopBot() {
  fetch("/api/bot/stop",{method:"POST"}).then(r=>r.json()).then(d=>{
    if (d.ok) {
      setStatus(false);
      addLog(t("stopLog"),"info");
      document.getElementById("btnStart").disabled=false;
      document.getElementById("btnStop").disabled=true;
      document.getElementById("cd").textContent="--:--";
      document.getElementById("cd").className="cd";
    }
  });
}
function analyzeNow() {
  document.getElementById("loader").style.display="flex";
  addLog(t("analyzingLog"),"info");
  fetch("/api/analyze",{method:"POST"}).then(r=>r.json()).then(d=>{
    document.getElementById("loader").style.display="none";
    if (d.signal) {
      addSigCard(d.signal);
      addLog(`🎯 ${d.signal.pair} ${d.signal.direction} ${d.signal.confidence}% [${d.signal.ai_source}]`,"ok");
    } else {
      addLog(d.msg || t("noSignalLog"),"warn");
    }
  }).catch(()=>{ document.getElementById("loader").style.display="none"; addLog(t("errorLog"),"err"); });
}
function sendLastTG() {
  if (!lastSig) { addLog(t("noLastSignal"),"err"); return; }
  fetch("/api/telegram/send",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({signal:lastSig})})
  .then(r=>r.json()).then(d=>{
    if (d.ok) { notify(t("sentTelegram"),"ok"); addLog(t("sentShort"),"ok"); }
    else { notify("❌ "+d.msg,"err"); addLog("❌ "+d.msg,"err"); }
  });
}

// ── استطلاع الحالة ──
function poll() {
  if (!logged) return;
  fetch("/api/status").then(r=>r.json()).then(d=>{
    document.getElementById("sTot").textContent = d.total||0;
    document.getElementById("sTG").textContent  = d.sent_tg||0;
    const ai = d.ai||"—";
    document.getElementById("sAI").textContent  = ai;
    document.getElementById("aiSrc").textContent = ai;
    setStatus(d.running);
    const marketClosed = d.market_open === false;
    document.getElementById("btnStart").disabled = !!d.running || marketClosed;
    document.getElementById("btnStop").disabled  = !d.running;
    if (marketClosed && d.market_msg) {
      const st = document.getElementById("stxt");
      if (st) st.textContent = d.market_msg;
    }
    if (marketClosed && d.market_msg) {
      if (lastMarketMsg !== d.market_msg) {
        notify(d.market_msg, "err");
        addLog(d.market_msg, "warn");
        lastMarketMsg = d.market_msg;
      }
    } else {
      lastMarketMsg = "";
    }
    if (d.cd>0) setCD(d.cd);
    else if (!d.running) { document.getElementById("cd").textContent="--:--"; document.getElementById("cd").className="cd"; }
    if (d.count > prevCount && d.latest) {
      addSigCard(d.latest); prevCount=d.count;
    }
  }).catch(()=>{});
}

// ── عرض بطاقة الإشارة ──
function addSigCard(s) {
  const cont = document.getElementById("sigList");
  if (cont.querySelector(".empty")) cont.innerHTML="";
  const c=s.confidence, cc=c>=80?"hi":c>=68?"md":"lo";
  const dir=s.direction==="UP"?"UP":"DOWN";
  const exp=s.next_min||"--:--:00";
  const d=s.pair&&s.pair.includes("JPY")?3:5;

  // شارات المؤشرات
  let bh="";
  if (s.badges) {
    bh = s.badges.slice(0,6).map(b=>{
      const cls = b[1]||"neu";
      return `<span class="ib ${cls}">${b[0]}</span>`;
    }).join("");
  }

  // الأسباب
  const reas = Array.isArray(s.reasons) ? s.reasons.join(" | ") : (s.reason||"");

  const el = document.createElement("div");
  el.className = `sc ${dir}`;
  el.innerHTML = `
    <div class="s-head">
      <div class="pair-line">
        <span class="pflags">${pairFlagBadges(s.ins || s.pair)}</span>
        <span class="s-pair" dir="ltr">${s.pair}</span>
        <span class="s-dir ${dir}">${dir==="UP"?`🟢  ${t("up")}  ⬆️`:`🔴  ${t("down")}  ⬇️`}</span>
      </div>
      <div class="s-time">
        ${t("signal")}: ${s.time||"--:--"}<br>
        ${t("entry")}: ${exp}
      </div>
    </div>
    <div class="s-body">
      <div class="s-entry">
        ⏰ <b>${t("enterTrade")}: ${exp}</b>
        &nbsp;|&nbsp; ${t("durationOneMin")}
        &nbsp;|&nbsp; ${t("price")}: ${parseFloat(s.price||0).toFixed(d)}
      </div>
      ${bh ? `<div class="s-badges">${bh}</div>` : ""}
      ${(s.strategy_name || s.strategy) ? `<div class="s-strategy">${s.strategy_icon || "🧠"} ${appLang === "ar" ? (s.strategy_name_ar || s.strategy_name || strategyLabel(s.strategy)) : (s.strategy_name_en || s.strategy_name || strategyLabel(s.strategy))}</div>` : ""}
      ${s.ai_decision ? `<div class="s-strategy">🤖 ${s.ai_decision} • ${s.ai_risk || "medium"} • ${s.source || "AI"}</div>` : ""}
      ${reas ? `<div class="s-reason">${reas}</div>` : ""}
      <div class="s-bar">
        <div class="s-fill ${cc}" style="width:${c}%"></div>
      </div>
      <div class="s-foot">
        <span class="s-conf">${t("confidence")}: <b>${c}%</b></span>
        <span class="s-ai">${s.ai_source||"—"}</span>
      </div>
    </div>`;

  cont.insertBefore(el, cont.firstChild);
  while (cont.children.length > 15) cont.removeChild(cont.lastChild);
  lastSig = s;
  syncSignalHistory();

  // معاينة تيليغرام (إن وُجدت في الواجهة)
  const tgPrevEl = document.getElementById("tgPrev");
  if (tgPrevEl) tgPrevEl.textContent = buildTGPreview(s);
}

function syncSignalHistory() {
  const src = document.getElementById("sigList");
  const dst = document.getElementById("sigHistoryList");
  if (!src || !dst) return;
  const cards = [...src.querySelectorAll(".sc")].slice(0,10);
  const cnt = document.getElementById("signalCountBadge");
  if (cnt) cnt.textContent = cards.length;
  if (!cards.length) {
    dst.innerHTML = `<div class="empty-state"><div class="e-ic">📈</div><div class="e-tt">${t("emptySignalsTitle")}</div><div>${t("emptySignalsDesc")}</div></div>`;
    return;
  }
  dst.innerHTML = cards.map(c => c.outerHTML).join("");
}

function buildTGPreview(s) {
  const d=s.pair&&s.pair.includes("JPY")?3:5;
  const arr=s.direction==="UP"?"🟢⬆️":"🔴⬇️";
  const act=s.direction==="UP"?`${t("up")}  ⬆️`:`${t("down")}  ⬇️`;
  const reas=Array.isArray(s.reasons)?s.reasons.join(" | "):(s.reason||"");
  return [
    t("tgTitle"),
    "━━━━━━━━━━━━━━━━━━━━━━━━",
    `${arr}  ${act}`,
    `${t("tgPair")}      :  ${(s.pair_flags || pairFlags(s.ins || s.pair))} ${s.pair}`,
    `${t("tgEntry")} :  ${s.next_min||"--:--:00"}`,
    `${t("tgPrice")}      :  ${parseFloat(s.price||0).toFixed(d)}`,
    "━━━━━━━━━━━━━━━━━━━━━━━━",
    `${t("tgConf")}      :  ${s.confidence}%`,
    (s.strategy_name || s.strategy) ? `${t("strategyText")} :  ${s.strategy_icon || "🧠"} ${appLang === "ar" ? (s.strategy_name_ar || s.strategy_name) : (s.strategy_name_en || s.strategy_name)}` : "",
    s.ai_decision ? `🤖 AI Validator :  ${s.ai_decision} • ${s.ai_risk || "medium"} • ${s.source || "AI"}` : "",
    s.pa ? `${t("tgPattern")}      :  ${s.pa}` : "",
    s.rsi ? `${t("tgRsi")}        :  ${s.rsi}` : "",
    s.ema ? `${t("tgTrend")}   :  ${s.ema}` : "",
    reas  ? `${t("tgAnalysis")}   :  ${reas}` : "",
    "━━━━━━━━━━━━━━━━━━━━━━━━",
    `${t("tgSource")}     :  ${s.ai_source||"—"}`,
    `🤖  OANDA Live  |  ${s.time||""}`,
    "━━━━━━━━━━━━━━━━━━━━━━━━",
    t("tgRisk"),
    t("tgDuration"),
  ].filter(Boolean).join("\n");
}

// ── مساعدات ──
function setCD(rem) {
  const el=document.getElementById("cd");
  el.textContent=String(Math.floor(rem/60)).padStart(2,"0")+":"+String(rem%60).padStart(2,"0");
  el.className="cd"+(rem<=10?" urg":"");
}
function setStatus(on) {
  const b=document.getElementById("sbadge"),d=document.getElementById("sdot"),st=document.getElementById("stxt");
  b.className="sbadge "+(on?"on":"");
  d.className="sdot "+(on?"on":"");
  st.textContent=on?t("active"):t("stopped");
}
function addLog(msg,type="") {
  const c=document.getElementById("aLog"); if(!c) return;
  const t=new Date().toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit"});
  const e=document.createElement("div"); e.className="le";
  e.innerHTML=`<div class="lt">${t}</div><div class="lm ${type}">${msg}</div>`;
  c.insertBefore(e,c.firstChild);
  while(c.children.length>50) c.removeChild(c.lastChild);
  const badge = document.getElementById("logCountBadge");
  if (badge) badge.textContent = c.children.length;
  syncMiniLogs();
}
function syncMiniLogs() {
  const full = document.getElementById("aLog");
  const mini = document.getElementById("aLogMini");
  if (!full || !mini) return;
  const rows = [...full.children].slice(0,5).map(x => x.outerHTML).join("");
  mini.innerHTML = rows || `<div class="le"><div class="lt">--:--</div><div class="lm info">${t("waitingStart")}</div></div>`;
}
function clearLogs() {
  const full = document.getElementById("aLog");
  if (full) full.innerHTML = "";
  const badge = document.getElementById("logCountBadge");
  if (badge) badge.textContent = "0";
  syncMiniLogs();
}
function notify(msg,type="ok") {
  const el=document.getElementById("notif"); el.textContent=msg;
  el.className="notif "+type; el.style.opacity="1";
  setTimeout(()=>el.style.opacity="0",2500);
}
document.addEventListener("DOMContentLoaded", () => { logged = true; init(); });
</script>
</body>
</html>"""

LANDING_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXO TRADE</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#050B16;--bg2:#0D1322;--blue:#1565FF;--blue2:#38A8FF;--text:#EDF4FF;--muted:#C8D5E7}
*{box-sizing:border-box}html,body{height:100%;margin:0}body{font-family:'IBM Plex Sans Arabic','Outfit','Segoe UI',Tahoma,sans-serif;background:linear-gradient(135deg,var(--bg),var(--bg2));color:var(--text);overflow:hidden}
.page{min-height:100vh;display:block;padding:0}
.stage{position:relative;width:100vw;min-height:100vh;border-radius:0;overflow:hidden;background:#07101d url('/uploads/nexo_landing_bg.png') center center / cover no-repeat;box-shadow:none;isolation:isolate}
.stage::before{content:'';position:absolute;inset:0;background:linear-gradient(90deg,rgba(4,10,20,.78) 0%,rgba(4,10,20,.46) 36%,rgba(4,10,20,.18) 58%,rgba(4,10,20,.14) 100%);z-index:0}
.stage::after{content:'';position:absolute;inset:0;background:radial-gradient(circle at 20% 74%, rgba(21,101,255,.18), transparent 22%),radial-gradient(circle at 85% 10%, rgba(21,101,255,.12), transparent 18%);pointer-events:none;z-index:0}
.lang-ui{position:absolute;top:22px;right:22px;z-index:5;display:flex;gap:8px;padding:6px;border-radius:999px;background:rgba(7,14,27,.5);border:1px solid rgba(255,255,255,.1);backdrop-filter:blur(12px)}
.lang-ui button{padding:9px 14px;border-radius:999px;border:1px solid rgba(255,255,255,.08);background:transparent;color:#d7e5ff;font-size:12px;font-weight:800;cursor:pointer;transition:.2s ease}
.lang-ui button.active{background:linear-gradient(135deg,#1565FF,#38A8FF);color:#fff;box-shadow:0 8px 18px rgba(21,101,255,.25)}
.hero{position:relative;z-index:3;min-height:100vh;width:100%}
.hero-copy{
  position:absolute;
  top:51%;
  left:20%;
  transform:translate(-10%,-50%);
  width:min(620px,46vw);
  text-align:center;
}
.headline{margin:0;font-size:clamp(42px,4.7vw,72px);line-height:1.08;font-weight:700;letter-spacing:-.03em;color:#F5F9FF;text-shadow:0 5px 24px rgba(0,0,0,.44)}
.headline .accent{color:#1565FF}.desc{margin-top:20px;max-width:520px;font-size:22px;line-height:1.85;color:var(--muted);text-shadow:0 2px 12px rgba(0,0,0,.22)}
.desc{max-width:none}
.actions{display:flex;gap:16px;flex-wrap:wrap;justify-content:center;margin-top:34px}.btn{display:inline-flex;align-items:center;justify-content:center;min-width:190px;padding:18px 28px;border-radius:18px;text-decoration:none;font-size:19px;font-weight:800;transition:.2s ease;border:1px solid transparent;backdrop-filter:blur(6px)}.btn:hover{transform:translateY(-2px)}.btn-primary{background:linear-gradient(135deg,#1565FF,#38A8FF);color:#fff;box-shadow:0 18px 32px rgba(21,101,255,.28)}.btn-secondary{background:rgba(255,255,255,.05);color:#fff;border-color:rgba(255,255,255,.16)}
@media (min-width:1101px){
  .stage::before{background:linear-gradient(180deg,rgba(4,10,20,.12) 0%,rgba(4,10,20,.38) 60%,rgba(4,10,20,.64) 100%)}
  .hero{min-height:100vh}
  .hero-copy{top:52%;left:22%;transform:translate(-10%,-50%);width:min(620px,44vw)}
  .headline,.desc{
    max-width:920px;
    text-align:center;
    text-shadow:0 5px 24px rgba(0,0,0,.44);
  }
  .headline{margin-top:28px}
  .actions{justify-content:center;margin-top:40px}
  .btn{
    min-width:230px;
    font-size:20px;
    padding:19px 34px;
    box-shadow:0 12px 30px rgba(0,0,0,.26);
  }
}
@media (max-width:1100px){
  .stage{min-height:100vh;background-position:58% center}
  .hero{min-height:100vh}
  .hero-copy{top:auto;left:50%;bottom:74px;transform:translateX(-50%);width:min(700px,88vw)}
  .headline{font-size:clamp(38px,5vw,58px)}
  .desc{font-size:19px;max-width:none}
  .actions{justify-content:center}
}
@media (max-width:760px){
  .page{padding:0}
  .stage{
    width:100%;
    min-height:100svh;
    border-radius:0;
    background-color:#030916;
    background-image:url('/uploads/nexo_landing_bg.png');
    background-position:center top;
    background-size:contain;
    background-repeat:no-repeat;
  }
  .stage::before{
    background:transparent;
  }
  .lang-ui{top:14px;right:12px}
  .hero{min-height:100vh}
  .hero-copy{
    left:50%;
    top:auto;
    bottom:max(20px, env(safe-area-inset-bottom));
    transform:translateX(-50%);
    width:min(94vw,520px);
    padding:0 8px;
  }
  .headline{font-size:clamp(30px,9vw,44px);line-height:1.16}
  .desc{margin-top:14px;font-size:15px;line-height:1.75;max-width:none}
  .actions{
    width:100%;
    gap:10px;
    justify-content:center;
    margin-top:22px;
  }
  .btn{
    flex:1;
    min-width:0;
    padding:14px 12px;
    font-size:16px;
    border-radius:14px;
  }
}
@media (max-width:480px){
  .stage{
    background-position:center top;
    background-size:contain;
  }
  .hero-copy{
    width:min(96vw,420px);
    bottom:max(14px, env(safe-area-inset-bottom));
  }
  .headline{font-size:clamp(27px,8.8vw,38px)}
  .desc{font-size:14px;line-height:1.65}
  .actions{
    display:grid;
    grid-template-columns:1fr;
    gap:9px;
  }
  .btn{
    width:100%;
    padding:13px 12px;
    font-size:15px;
  }
}
[dir='ltr'] .hero{align-items:flex-start}[dir='ltr'] .headline,[dir='ltr'] .desc{text-align:left}
[dir='rtl'] .headline,[dir='rtl'] .desc{text-align:right}
@keyframes fadeUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}.headline,.desc,.actions{animation:fadeUp .7s ease both}
</style>
</head>
<body>
<div class="page">
  <section class="stage">
    <div class="lang-ui">
      <button type="button" class="active" data-lang-btn="ar">AR</button>
      <button type="button" data-lang-btn="en">EN</button>
    </div>
    <div class="hero">
      <div class="hero-copy">
      <div class="headline" data-ar="منصة تداول احترافية.<br><span class=&quot;accent&quot;>ابدأ الآن.</span>" data-en="A premium trading platform.<br><span class=&quot;accent&quot;>Start now.</span>">منصة تداول احترافية.<br><span class="accent">ابدأ الآن.</span></div>
      <div class="desc" data-ar="اختر الإجراء المناسب للمتابعة: تسجيل الدخول إذا لديك حساب، أو التسجيل لإنشاء طلب جديد." data-en="Choose what you need to continue: login if you already have an account, or register to create a new request.">اختر الإجراء المناسب للمتابعة: تسجيل الدخول إذا لديك حساب، أو التسجيل لإنشاء طلب جديد.</div>
      <div class="actions">
        <a class="btn btn-primary" href="/login" data-ar="تسجيل دخول" data-en="Login">تسجيل دخول</a>
        <a class="btn btn-secondary" href="/join" data-ar="تسجيل" data-en="Register">تسجيل</a>
      </div>
      </div>
    </div>
  </section>
</div>
<script>
function setPublicLang(lang){
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  document.querySelectorAll('[data-lang-btn]').forEach(btn => btn.classList.toggle('active', btn.dataset.langBtn === lang));
  document.querySelectorAll('[data-ar][data-en]').forEach(el => {
    el.innerHTML = el.dataset[lang];
  });
  localStorage.setItem('publicLang', lang);
  localStorage.setItem('appLang', lang);
}
const MOBILE_BG_UPLOAD_PATH = "/uploads/nexo_landing_bg_mobile.png";
function applyMobileLandingBackground(){
  if (window.matchMedia("(max-width: 760px)").matches) {
    const img = new Image();
    img.onload = () => {
      const stage = document.querySelector(".stage");
      if (stage) stage.style.backgroundImage = `url('${MOBILE_BG_UPLOAD_PATH}')`;
    };
    img.src = MOBILE_BG_UPLOAD_PATH + "?v=" + Date.now();
  }
}
const savedLang = localStorage.getItem('publicLang') || 'ar';
setPublicLang(savedLang);
applyMobileLandingBackground();
document.querySelectorAll('[data-lang-btn]').forEach(btn => {
  btn.addEventListener('click', () => setPublicLang(btn.dataset.langBtn));
});
</script>
</body>
</html>"""

JOIN_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>تسجيل | NEXO TRADE</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#050B16;--bg2:#0D1322;--blue:#1565FF;--blue2:#38A8FF;--card:rgba(10,18,33,.78);--stroke:rgba(255,255,255,.08);--text:#EDF4FF;--muted:#9CB0CC}*{box-sizing:border-box}html,body{height:100%;margin:0}body{font-family:'IBM Plex Sans Arabic','Outfit','Segoe UI',Tahoma,sans-serif;background:radial-gradient(circle at 15% 85%, rgba(21,101,255,.18), transparent 18%),radial-gradient(circle at 86% 10%, rgba(21,101,255,.16), transparent 16%),linear-gradient(135deg,var(--bg),#07111f 55%,var(--bg2));color:var(--text);overflow-x:hidden}body::before{content:'';position:fixed;inset:0;background:repeating-linear-gradient(118deg,transparent 0 22px,rgba(56,168,255,.03) 22px 24px);pointer-events:none}.page{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:26px}.shell{width:min(1220px,100%);display:grid;grid-template-columns:.95fr .9fr;gap:26px;align-items:center}.visual{position:relative;min-height:690px;padding:20px 10px}.logo{width:min(380px,80vw);display:block}.headline{margin-top:18px;font-size:clamp(30px,4vw,48px);line-height:1.22;font-weight:700}.headline .acc{color:var(--blue)}.desc{max-width:430px;margin-top:16px;font-size:17px;line-height:1.9;color:var(--muted)}.xmark{position:absolute;left:-10px;bottom:96px;width:min(360px,60vw);opacity:.9}.candles{position:absolute;right:16px;top:170px;display:flex;gap:18px;align-items:flex-end}.candles span{position:relative;display:block;width:18px;border-radius:3px;background:linear-gradient(180deg,#2E9EFF,#1565FF);box-shadow:0 0 16px rgba(21,101,255,.24)}.candles span::before,.candles span::after{content:'';position:absolute;left:50%;transform:translateX(-50%);width:4px;border-radius:99px;background:#2E9EFF}.candles span::before{bottom:100%;height:14px}.candles span::after{top:100%;height:12px}.c1{height:76px}.c2{height:102px}.c3{height:84px}.world{position:absolute;left:0;bottom:0;width:min(560px,94vw)}.card{position:relative;z-index:1;background:var(--card);border:1px solid var(--stroke);border-radius:28px;padding:22px;backdrop-filter:blur(16px);box-shadow:0 28px 60px rgba(0,0,0,.36),0 0 0 1px rgba(21,101,255,.08) inset}.top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}.back{color:#dbe8ff;text-decoration:none;font-size:13px}.title{font-size:30px;font-weight:800;margin:0 0 6px}.sub{font-size:14px;line-height:1.8;color:var(--muted);margin-bottom:12px}label{display:block;margin:14px 0 7px;font-size:13px;color:#D8E6FF}input{width:100%;padding:15px 16px;border-radius:16px;border:1px solid rgba(255,255,255,.1);background:rgba(5,11,22,.92);color:#fff;outline:none;font:500 14px inherit}input:focus{border-color:rgba(56,168,255,.6);box-shadow:0 0 0 4px rgba(21,101,255,.14)}.hint{font-size:11px;color:var(--muted);line-height:1.8;margin:2px 0 8px}.file{padding:13px;background:rgba(5,11,22,.86)}button{margin-top:16px;width:100%;padding:15px;border:none;border-radius:16px;background:linear-gradient(135deg,var(--blue),var(--blue2));color:#fff;font-weight:800;font-size:16px;cursor:pointer;box-shadow:0 14px 30px rgba(21,101,255,.28)}.msg{margin-top:12px;font-size:13px;line-height:1.6}.ok{color:#7ef7b4}.err{color:#ff8080}.foot{text-align:center;color:var(--muted);font-size:12px;margin-top:12px}.foot a{color:#7dbdff;text-decoration:none}@media (max-width:980px){.shell{grid-template-columns:1fr}.visual{min-height:330px;text-align:center}.logo{margin-inline:auto}.desc{margin-inline:auto}.xmark{left:50%;transform:translateX(-50%);bottom:56px;width:260px;opacity:.55}.candles{right:50%;transform:translateX(124px) scale(.84);top:118px}.world{left:50%;transform:translateX(-50%)}.card{max-width:680px;margin:-16px auto 0}}@media (max-width:620px){.page{padding:12px}.visual{min-height:250px;padding:10px 0}.headline{font-size:34px}.card{padding:18px;border-radius:22px;margin-top:-10px}.title{font-size:25px}}
.lang-ui{position:fixed;top:18px;right:18px;z-index:20;display:flex;gap:6px;padding:6px;border-radius:999px;background:rgba(8,14,27,.52);border:1px solid rgba(255,255,255,.10);backdrop-filter:blur(12px)}.lang-ui button{width:auto;margin:0;padding:7px 10px;border-radius:999px;border:1px solid rgba(255,255,255,.08);background:transparent;color:#AFC1DB;font-size:11px;font-weight:800;box-shadow:none}.lang-ui button.active{background:linear-gradient(135deg,#1565FF,#38A8FF);color:#fff}.logo,.phone,.card{animation:fadeUp .75s ease both}.xmark,.candles,.world{display:none !important}@keyframes fadeUp{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:translateY(0)}}@keyframes candlePulse{0%,100%{filter:drop-shadow(0 0 5px rgba(21,101,255,.18));transform:translateY(0)}50%{filter:drop-shadow(0 0 16px rgba(21,101,255,.55));transform:translateY(-4px)}}
</style>
</head>
<body>
<div class="page"><div class="lang-ui"><button type="button" class="active" onclick="setPublicLang('ar')">AR</button><button type="button" onclick="setPublicLang('en')">EN</button></div><div class="shell"><section class="visual"><img class="logo" src="/uploads/nexo_logo_transparent.png" alt="NEXO TRADE"><div class="headline"><span data-ar="انضم إلى تجربة<br><span class=&quot;acc&quot;>NEXO TRADE</span> الاحترافية." data-en="Join the premium<br><span class=&quot;acc&quot;>NEXO TRADE</span> experience.">Join the premium<br><span class="acc">NEXO TRADE</span> experience.</span></div><svg class="xmark" viewBox="0 0 420 420" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M209 204 91 83c-8-8-22-2-22 9v15c0 5 2 10 6 14l103 108c3 3 7 5 12 5h19v-30Z" fill="#1565FF"/><path d="M216 204 333 83c8-8 22-2 22 9v15c0 5-2 10-6 14L246 229c-3 3-7 5-12 5h-18v-30Z" fill="#1565FF"/><path d="M209 217 91 337c-8 8-22 2-22-9v-15c0-5 2-10 6-14l103-108c3-3 7-5 12-5h19v30Z" fill="#4B5B78" opacity=".9"/><path d="M216 217 333 337c8 8 22 2 22-9v-15c0-5-2-10-6-14L246 191c-3-3-7-5-12-5h-18v30Z" fill="#1565FF"/></svg><div class="candles"><span class="c1"></span><span class="c2"></span><span class="c3"></span></div><svg class="world" viewBox="0 0 760 260" xmlns="http://www.w3.org/2000/svg"><defs><pattern id="mapDots" x="0" y="0" width="6" height="6" patternUnits="userSpaceOnUse"><circle cx="1.7" cy="1.7" r="1.2" fill="#66B3FF" opacity=".72"/></pattern><filter id="nodeGlow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter><linearGradient id="lineGlow" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#66B3FF" stop-opacity=".95"/><stop offset="100%" stop-color="#1E82FF" stop-opacity=".28"/></linearGradient></defs><g opacity=".92"><path d="M35 110c10-17 29-29 51-35 15-5 35-7 47-3 8 3 16 2 22-3l17-14c6-5 15-7 24-5l28 8c9 3 16 9 21 17l10 18c4 7 3 15-2 21l-15 17c-4 4-10 7-16 7h-16c-8 0-15 4-19 10l-10 16c-5 8-14 13-23 12l-33-4c-10-2-19-7-24-16l-13-20c-4-7-12-11-20-11H47c-9 0-15-10-12-18Z" fill="url(#mapDots)"/><path d="M180 145c8-7 19-10 30-9l16 2c6 1 10 5 12 11l5 16c2 6 1 12-2 17l-10 14c-4 6-6 13-6 20v23c0 9-10 14-18 9l-13-9c-7-5-11-13-10-21l2-17c1-6-1-12-5-17l-12-14c-8-9-6-22 4-30l7-5Z" fill="url(#mapDots)"/><path d="M318 94c8-10 21-16 35-16h20c8 0 15 4 20 10l8 10c6 7 7 17 3 26l-8 16c-3 7-4 16-2 23l5 17c2 7-1 14-7 18l-18 10c-6 4-13 4-20 2l-18-7c-8-3-14-9-16-17l-4-13c-2-7-7-12-14-15l-13-5c-10-4-14-16-8-25l12-18c1-2 3-4 5-6Z" fill="url(#mapDots)"/><path d="M387 84c8-9 20-14 33-14h35c8 0 16 3 22 8l14 11c5 5 13 7 20 7h42c9 0 18 3 24 9l27 25c8 7 8 20 0 28l-25 25c-7 7-17 11-27 11h-20c-9 0-18 4-24 11l-16 18c-6 7-16 11-25 10l-31-2c-8 0-15-4-21-10l-13-13c-6-6-14-9-22-10l-25-1c-12-1-22-10-24-22l-3-18c-1-7 1-14 5-20l16-23c2-4 4-7 8-10Z" fill="url(#mapDots)"/><path d="M624 182c6-6 14-10 23-10h17c7 0 13 2 18 7l12 11c6 5 8 13 6 20l-4 10c-3 8-10 13-19 14l-21 2c-9 1-17-2-23-8l-10-10c-8-9-8-25 1-34Z" fill="url(#mapDots)"/></g><g stroke="url(#lineGlow)" stroke-width="2.3" stroke-linecap="round" fill="none"><path d="M92 176C140 146 180 136 232 138"/><path d="M92 176C180 152 286 138 364 145"/><path d="M232 138C315 121 397 118 466 126"/><path d="M364 145C442 114 508 114 572 132"/><path d="M466 126C560 137 626 164 660 205"/><path d="M364 145C345 170 336 191 337 213" opacity=".75"/></g><g fill="#78BEFF" filter="url(#nodeGlow)"><circle cx="92" cy="176" r="4.8"/><circle cx="232" cy="138" r="4.2"/><circle cx="364" cy="145" r="5.2"/><circle cx="466" cy="126" r="4.7"/><circle cx="572" cy="132" r="4.3"/><circle cx="660" cy="205" r="5"/><circle cx="337" cy="213" r="4.5"/></g></svg></section><section class="card"><div class="top"><a class="back" href="/">← العودة</a><img src="/uploads/nexo_logo_transparent.png" alt="NEXO" style="width:120px;height:auto"></div><h1 class="title" data-ar="إنشاء طلب انضمام" data-en="Create Join Request">إنشاء طلب انضمام</h1><div class="sub" data-ar="أدخل بياناتك وارفع صورة الحساب، وسيتم إرسال الطلب إلى الإدارة للمراجعة." data-en="Enter your details and upload the account image. The request will be sent to admin review.">أدخل بياناتك وارفع صورة الحساب، وسيتم إرسال الطلب إلى الإدارة للمراجعة.</div><form id="joinForm"><label>Account ID</label><input name="account_id" required placeholder="أدخل رقم الحساب"><label>Email</label><input type="email" name="email" required placeholder="أدخل البريد الإلكتروني"><label>صورة الملف الشخصي للمنصة</label><div class="hint">يجب أن تظهر في الصورة بيانات الحساب كما في المنصة: <b>Account ID</b> و<b>Email</b> بوضوح.</div><input class="file" type="file" name="profile_image" accept="image/*" required><button type="submit" data-ar="إرسال الطلب" data-en="Submit Request">إرسال الطلب</button></form><div class="msg" id="msg"></div><div class="foot">لديك حساب مفعل؟ <a href="/login">تسجيل دخول</a></div></section></div></div>
<script>
function setPublicLang(lang){
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  document.querySelectorAll('.lang-ui button').forEach(btn => {
    const isArBtn = btn.textContent.trim().toUpperCase() === 'AR';
    btn.classList.toggle('active', (lang === 'ar' && isArBtn) || (lang === 'en' && !isArBtn));
  });
  document.querySelectorAll('[data-ar][data-en]').forEach(el => { el.innerHTML = el.dataset[lang]; });
  localStorage.setItem('publicLang', lang);
  localStorage.setItem('appLang', lang);
}
const savedJoinLang = localStorage.getItem('publicLang') || 'ar';
setPublicLang(savedJoinLang);

let joinWatchTimer = null;
let joinWatchAccountId = localStorage.getItem("pendingJoinAccountId") || "";

async function checkJoinApprovalStatus(accountId){
  if (!accountId) return;
  const msg = document.getElementById("msg");
  try {
    const r = await fetch("/api/user/login", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({account_id: accountId})
    });
    const d = await r.json();
    if (d.status === "approved") {
      localStorage.removeItem("pendingJoinAccountId");
      if (joinWatchTimer) { clearInterval(joinWatchTimer); joinWatchTimer = null; }
      msg.textContent = "✅ تم قبول طلبك! سيتم تحويلك إلى صفحة تسجيل الدخول...";
      msg.className = "msg ok";
      setTimeout(() => { location.href = "/login"; }, 900);
      return;
    }
    if (d.status === "pending") {
      msg.textContent = "⏳ طلبك قيد المراجعة. سنقوم بتنبيهك هنا فور القبول.";
      msg.className = "msg ok";
      return;
    }
    msg.textContent = "⚠️ الحساب غير موجود أو غير مفعل بعد.";
    msg.className = "msg err";
  } catch {
    msg.textContent = "خطأ في التحقق من حالة الطلب";
    msg.className = "msg err";
  }
}

function startJoinStatusWatcher(accountId){
  joinWatchAccountId = (accountId || "").trim();
  if (!joinWatchAccountId) return;
  localStorage.setItem("pendingJoinAccountId", joinWatchAccountId);
  if (joinWatchTimer) clearInterval(joinWatchTimer);
  checkJoinApprovalStatus(joinWatchAccountId);
  joinWatchTimer = setInterval(() => checkJoinApprovalStatus(joinWatchAccountId), 10000);
}

if (joinWatchAccountId) {
  startJoinStatusWatcher(joinWatchAccountId);
}

document.getElementById("joinForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("msg");
  msg.textContent = "جارٍ الإرسال...";
  msg.className = "msg";
  const form = e.target;
  const fd = new FormData(form);
  const accountId = String(fd.get("account_id") || "").trim();
  try {
    const r = await fetch("/api/join-request", {method:"POST", body: fd});
    const d = await r.json();
    if (d.ok && d.status === "approved") {
      msg.textContent = "✅ الحساب مقبول مسبقًا. سيتم تحويلك إلى تسجيل الدخول...";
      msg.className = "msg ok";
      localStorage.removeItem("pendingJoinAccountId");
      setTimeout(() => { location.href = "/login"; }, 700);
      return;
    }
    if (d.ok) {
      msg.textContent = "⏳ تم إرسال الطلب. طلبك الآن قيد الانتظار وسنبلغك هنا عند القبول.";
      msg.className = "msg ok";
      form.reset();
      startJoinStatusWatcher(accountId);
      return;
    }
    msg.textContent = d.msg || "تعذر إرسال الطلب";
    msg.className = "msg err";
  } catch {
    msg.textContent = "خطأ في الاتصال";
    msg.className = "msg err";
  }
});
</script>
</body>
</html>"""

LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>تسجيل الدخول | NEXO TRADE</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#050B16;--bg2:#0D1322;--blue:#1565FF;--blue2:#38A8FF;--card:rgba(10,18,33,.78);--stroke:rgba(255,255,255,.08);--text:#EDF4FF;--muted:#9CB0CC}*{box-sizing:border-box}html,body{height:100%;margin:0}body{font-family:'IBM Plex Sans Arabic','Outfit','Segoe UI',Tahoma,sans-serif;background:radial-gradient(circle at 15% 85%, rgba(21,101,255,.18), transparent 18%),radial-gradient(circle at 86% 10%, rgba(21,101,255,.16), transparent 16%),linear-gradient(135deg,var(--bg),#07111f 55%,var(--bg2));color:var(--text);overflow-x:hidden}body::before{content:'';position:fixed;inset:0;background:repeating-linear-gradient(118deg,transparent 0 22px,rgba(56,168,255,.03) 22px 24px);pointer-events:none}.page{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:26px}.shell{width:min(1200px,100%);display:grid;grid-template-columns:.95fr .85fr;gap:26px;align-items:center}.visual{position:relative;min-height:670px;padding:20px 10px}.logo{width:min(380px,80vw);display:block}.headline{margin-top:18px;font-size:clamp(30px,4vw,48px);line-height:1.22;font-weight:700}.headline .acc{color:var(--blue)}.desc{max-width:430px;margin-top:16px;font-size:17px;line-height:1.9;color:var(--muted)}.xmark{position:absolute;left:-10px;bottom:96px;width:min(360px,60vw);opacity:.9}.candles{position:absolute;right:16px;top:170px;display:flex;gap:18px;align-items:flex-end}.candles span{position:relative;display:block;width:18px;border-radius:3px;background:linear-gradient(180deg,#2E9EFF,#1565FF);box-shadow:0 0 16px rgba(21,101,255,.24)}.candles span::before,.candles span::after{content:'';position:absolute;left:50%;transform:translateX(-50%);width:4px;border-radius:99px;background:#2E9EFF}.candles span::before{bottom:100%;height:14px}.candles span::after{top:100%;height:12px}.c1{height:76px}.c2{height:102px}.c3{height:84px}.world{position:absolute;left:0;bottom:0;width:min(560px,94vw)}.card{position:relative;z-index:1;background:var(--card);border:1px solid var(--stroke);border-radius:28px;padding:22px;backdrop-filter:blur(16px);box-shadow:0 28px 60px rgba(0,0,0,.36),0 0 0 1px rgba(21,101,255,.08) inset}.top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}.back{color:#dbe8ff;text-decoration:none;font-size:13px}.title{font-size:30px;font-weight:800;margin:0 0 6px}.sub{font-size:14px;line-height:1.8;color:var(--muted);margin-bottom:12px}label{display:block;margin:14px 0 7px;font-size:13px;color:#D8E6FF}input{width:100%;padding:15px 16px;border-radius:16px;border:1px solid rgba(255,255,255,.1);background:rgba(5,11,22,.92);color:#fff;outline:none;font:500 14px inherit}input:focus{border-color:rgba(56,168,255,.6);box-shadow:0 0 0 4px rgba(21,101,255,.14)}button{margin-top:16px;width:100%;padding:15px;border:none;border-radius:16px;background:linear-gradient(135deg,var(--blue),var(--blue2));color:#fff;font-weight:800;font-size:16px;cursor:pointer;box-shadow:0 14px 30px rgba(21,101,255,.28)}.msg{margin-top:12px;font-size:13px;line-height:1.6}.ok{color:#7ef7b4}.err{color:#ff8080}.warn{color:#f9d36d}.foot{text-align:center;color:var(--muted);font-size:12px;margin-top:12px}.foot a{color:#7dbdff;text-decoration:none}@media (max-width:980px){.shell{grid-template-columns:1fr}.visual{min-height:330px;text-align:center}.logo{margin-inline:auto}.desc{margin-inline:auto}.xmark{left:50%;transform:translateX(-50%);bottom:56px;width:260px;opacity:.55}.candles{right:50%;transform:translateX(124px) scale(.84);top:118px}.world{left:50%;transform:translateX(-50%)}.card{max-width:680px;margin:-16px auto 0}}@media (max-width:620px){.page{padding:12px}.visual{min-height:250px;padding:10px 0}.headline{font-size:34px}.card{padding:18px;border-radius:22px;margin-top:-10px}.title{font-size:25px}}
.lang-ui{position:fixed;top:18px;right:18px;z-index:20;display:flex;gap:6px;padding:6px;border-radius:999px;background:rgba(8,14,27,.52);border:1px solid rgba(255,255,255,.10);backdrop-filter:blur(12px)}.lang-ui button{width:auto;margin:0;padding:7px 10px;border-radius:999px;border:1px solid rgba(255,255,255,.08);background:transparent;color:#AFC1DB;font-size:11px;font-weight:800;box-shadow:none}.lang-ui button.active{background:linear-gradient(135deg,#1565FF,#38A8FF);color:#fff}.logo,.phone,.card{animation:fadeUp .75s ease both}.xmark,.candles,.world{display:none !important}@keyframes fadeUp{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:translateY(0)}}@keyframes candlePulse{0%,100%{filter:drop-shadow(0 0 5px rgba(21,101,255,.18));transform:translateY(0)}50%{filter:drop-shadow(0 0 16px rgba(21,101,255,.55));transform:translateY(-4px)}}
</style>
</head>
<body>
<div class="page"><div class="lang-ui"><button type="button" class="active" onclick="setPublicLang('ar')">AR</button><button type="button" onclick="setPublicLang('en')">EN</button></div><div class="shell"><section class="visual"><img class="logo" src="/uploads/nexo_logo_transparent.png" alt="NEXO TRADE"><div class="headline"><span data-ar="ادخل حسابك وانتقل مباشرة إلى<br><span class=&quot;acc&quot;>NEXO TRADE</span>." data-en="Enter your account and access<br><span class=&quot;acc&quot;>NEXO TRADE</span> instantly.">Enter your account and access<br><span class="acc">NEXO TRADE</span> instantly.</span></div><svg class="xmark" viewBox="0 0 420 420" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M209 204 91 83c-8-8-22-2-22 9v15c0 5 2 10 6 14l103 108c3 3 7 5 12 5h19v-30Z" fill="#1565FF"/><path d="M216 204 333 83c8-8 22-2 22 9v15c0 5-2 10-6 14L246 229c-3 3-7 5-12 5h-18v-30Z" fill="#1565FF"/><path d="M209 217 91 337c-8 8-22 2-22-9v-15c0-5 2-10 6-14l103-108c3-3 7-5 12-5h19v30Z" fill="#4B5B78" opacity=".9"/><path d="M216 217 333 337c8 8 22 2 22-9v-15c0-5-2-10-6-14L246 191c-3-3-7-5-12-5h-18v30Z" fill="#1565FF"/></svg><div class="candles"><span class="c1"></span><span class="c2"></span><span class="c3"></span></div><svg class="world" viewBox="0 0 760 260" xmlns="http://www.w3.org/2000/svg"><defs><pattern id="mapDots" x="0" y="0" width="6" height="6" patternUnits="userSpaceOnUse"><circle cx="1.7" cy="1.7" r="1.2" fill="#66B3FF" opacity=".72"/></pattern><filter id="nodeGlow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter><linearGradient id="lineGlow" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#66B3FF" stop-opacity=".95"/><stop offset="100%" stop-color="#1E82FF" stop-opacity=".28"/></linearGradient></defs><g opacity=".92"><path d="M35 110c10-17 29-29 51-35 15-5 35-7 47-3 8 3 16 2 22-3l17-14c6-5 15-7 24-5l28 8c9 3 16 9 21 17l10 18c4 7 3 15-2 21l-15 17c-4 4-10 7-16 7h-16c-8 0-15 4-19 10l-10 16c-5 8-14 13-23 12l-33-4c-10-2-19-7-24-16l-13-20c-4-7-12-11-20-11H47c-9 0-15-10-12-18Z" fill="url(#mapDots)"/><path d="M180 145c8-7 19-10 30-9l16 2c6 1 10 5 12 11l5 16c2 6 1 12-2 17l-10 14c-4 6-6 13-6 20v23c0 9-10 14-18 9l-13-9c-7-5-11-13-10-21l2-17c1-6-1-12-5-17l-12-14c-8-9-6-22 4-30l7-5Z" fill="url(#mapDots)"/><path d="M318 94c8-10 21-16 35-16h20c8 0 15 4 20 10l8 10c6 7 7 17 3 26l-8 16c-3 7-4 16-2 23l5 17c2 7-1 14-7 18l-18 10c-6 4-13 4-20 2l-18-7c-8-3-14-9-16-17l-4-13c-2-7-7-12-14-15l-13-5c-10-4-14-16-8-25l12-18c1-2 3-4 5-6Z" fill="url(#mapDots)"/><path d="M387 84c8-9 20-14 33-14h35c8 0 16 3 22 8l14 11c5 5 13 7 20 7h42c9 0 18 3 24 9l27 25c8 7 8 20 0 28l-25 25c-7 7-17 11-27 11h-20c-9 0-18 4-24 11l-16 18c-6 7-16 11-25 10l-31-2c-8 0-15-4-21-10l-13-13c-6-6-14-9-22-10l-25-1c-12-1-22-10-24-22l-3-18c-1-7 1-14 5-20l16-23c2-4 4-7 8-10Z" fill="url(#mapDots)"/><path d="M624 182c6-6 14-10 23-10h17c7 0 13 2 18 7l12 11c6 5 8 13 6 20l-4 10c-3 8-10 13-19 14l-21 2c-9 1-17-2-23-8l-10-10c-8-9-8-25 1-34Z" fill="url(#mapDots)"/></g><g stroke="url(#lineGlow)" stroke-width="2.3" stroke-linecap="round" fill="none"><path d="M92 176C140 146 180 136 232 138"/><path d="M92 176C180 152 286 138 364 145"/><path d="M232 138C315 121 397 118 466 126"/><path d="M364 145C442 114 508 114 572 132"/><path d="M466 126C560 137 626 164 660 205"/><path d="M364 145C345 170 336 191 337 213" opacity=".75"/></g><g fill="#78BEFF" filter="url(#nodeGlow)"><circle cx="92" cy="176" r="4.8"/><circle cx="232" cy="138" r="4.2"/><circle cx="364" cy="145" r="5.2"/><circle cx="466" cy="126" r="4.7"/><circle cx="572" cy="132" r="4.3"/><circle cx="660" cy="205" r="5"/><circle cx="337" cy="213" r="4.5"/></g></svg></section><section class="card"><div class="top"><a class="back" href="/">← العودة</a><img src="/uploads/nexo_logo_transparent.png" alt="NEXO" style="width:120px;height:auto"></div><h1 class="title" data-ar="تسجيل الدخول" data-en="Login">تسجيل الدخول</h1><div class="sub" data-ar="أدخل Account ID الخاص بك للوصول إلى لوحة التطبيق إذا كان حسابك مفعّلًا." data-en="Enter your Account ID to access the dashboard if your account is approved.">أدخل Account ID الخاص بك للوصول إلى لوحة التطبيق إذا كان حسابك مفعّلًا.</div><form id="loginForm"><label>Account ID</label><input name="account_id" required placeholder="أدخل رقم الحساب"><button type="submit" data-ar="دخول" data-en="Login">دخول</button></form><div class="msg" id="msg"></div><div class="foot">ليس لديك حساب؟ <a href="/join">قدّم طلب انضمام</a></div></section></div></div>
<script>
function setPublicLang(lang){
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  document.querySelectorAll('.lang-ui button').forEach(btn => {
    const isArBtn = btn.textContent.trim().toUpperCase() === 'AR';
    btn.classList.toggle('active', (lang === 'ar' && isArBtn) || (lang === 'en' && !isArBtn));
  });
  document.querySelectorAll('[data-ar][data-en]').forEach(el => { el.innerHTML = el.dataset[lang]; });
  localStorage.setItem('publicLang', lang);
  localStorage.setItem('appLang', lang);
}
const savedLoginLang = localStorage.getItem('publicLang') || 'ar';
setPublicLang(savedLoginLang);
document.getElementById("loginForm").addEventListener("submit", async (e) => {e.preventDefault();const msg = document.getElementById("msg");msg.textContent = "جارٍ التحقق...";msg.className = "msg";const payload = Object.fromEntries(new FormData(e.target).entries());try {const r = await fetch("/api/user/login", {method:"POST",headers:{"Content-Type":"application/json"},body: JSON.stringify(payload)});const d = await r.json();if (d.status === "approved") {msg.textContent = "تم قبول الحساب، سيتم تحويلك الآن...";msg.className = "msg ok";setTimeout(()=>location.href='/dashboard', 500);} else if (d.status === "pending") {msg.textContent = "طلبك قيد المراجعة حاليًا. يرجى الانتظار حتى التفعيل.";msg.className = "msg warn";} else if (d.status === "not_found") {msg.innerHTML = 'الحساب غير موجود أو غير مفعّل. <a href="/join" style="color:#7dbdff">قدّم طلب انضمام</a>';msg.className = "msg err";} else {msg.textContent = d.msg || "تعذر تسجيل الدخول";msg.className = "msg err";}} catch {msg.textContent = "خطأ في الاتصال";msg.className = "msg err";}});
</script>
</body>
</html>"""

ACCESS_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>طلب دخول</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
body{font-family:'IBM Plex Sans Arabic','Segoe UI',Tahoma,sans-serif;background:#0a1320;color:#e3edf6;display:flex;justify-content:center;padding:30px;direction:rtl;-webkit-font-smoothing:antialiased}
.box{width:450px;max-width:100%;background:#111d2f;border:1px solid #223752;border-radius:14px;padding:22px}
input{width:100%;padding:10px;border-radius:8px;border:1px solid #2a425f;background:#07101c;color:#e3edf6;margin:6px 0 10px}
button{width:100%;padding:12px;border:none;border-radius:8px;background:#f4c95d;color:#111;font-weight:700;cursor:pointer}
.msg{margin-top:12px;font-size:13px}.ok{color:#7ef7b4}.err{color:#ff8080}
</style>
</head>
<body>
<div class="box">
  <h3>طلب دخول للمنصة</h3>
  <form id="f">
    <input name="account_id" placeholder="Account ID" required>
    <input type="email" name="email" placeholder="Email" required>
    <button type="submit">إرسال طلب الدخول</button>
  </form>
  <div class="msg" id="m"></div>
</div>
<script>
document.getElementById("f").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = Object.fromEntries(fd.entries());
  const m = document.getElementById("m");
  m.className = "msg"; m.textContent = "جارٍ الإرسال...";
  try{
    const r = await fetch("/api/access-request", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (d.ok){ m.className="msg ok"; m.textContent="تم إرسال الطلب ✅"; e.target.reset(); }
    else { m.className="msg err"; m.textContent=d.msg || "فشل الإرسال"; }
  }catch{ m.className="msg err"; m.textContent="خطأ في الاتصال"; }
});
</script>
</body>
</html>"""

ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>لوحة الأدمن</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--card:#101b2f;--card2:#0c1628;--bd:#243a5b;--txt:#e8f1fb;--mut:#9fb4cd;--ok:#22c55e;--no:#ef4444}
*{box-sizing:border-box}
body{font-family:'IBM Plex Sans Arabic','Segoe UI',Tahoma,sans-serif;background:radial-gradient(circle at 20% 15%,rgba(45,116,255,.12),transparent 30%),linear-gradient(180deg,#060d18,#091326 45%,#070f1d);color:var(--txt);margin:0;direction:rtl}
.wrap{max-width:1260px;margin:0 auto;padding:22px}
.top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:12px}
#counts{font-size:12px;color:var(--mut);padding:8px 10px;border:1px solid var(--bd);border-radius:999px;background:rgba(16,27,47,.65)}
.toolbar{display:grid;grid-template-columns:1.4fr .8fr;gap:10px;margin-bottom:12px}
.toolbar input,.toolbar select{width:100%;padding:10px;border-radius:9px;border:1px solid #335784;background:#07101c;color:#e3edf6}
.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.card{background:linear-gradient(180deg,var(--card),var(--card2));border:1px solid var(--bd);border-radius:14px;padding:12px;min-height:520px}
.card h3{margin:0 0 10px;font-size:16px}
.card .hd{display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:8px}
.list{max-height:455px;overflow:auto;padding-inline-end:4px}
.item{border:1px solid #2b4670;border-radius:10px;padding:10px;margin-bottom:8px;font-size:13px;background:rgba(12,23,41,.78)}
.item b{font-size:14px;color:#d8e7ff}.meta{color:var(--mut);margin-top:2px}
.actions{display:flex;gap:6px;margin-top:9px}.muted{font-size:12px;color:var(--mut)}
button{border:none;border-radius:8px;padding:7px 11px;cursor:pointer;font-weight:700}
.ok{background:rgba(34,197,94,.15);color:#9ef7be;border:1px solid rgba(34,197,94,.38)}
.no{background:rgba(239,68,68,.14);color:#ffaaaa;border:1px solid rgba(239,68,68,.35)}
.sm{padding:6px 8px;font-size:11px}
.pager{display:flex;align-items:center;justify-content:space-between;gap:6px;margin-top:8px}
.pager .pinfo{font-size:11px;color:var(--mut)}
#lastUpdate{font-size:11px;color:var(--mut);margin-inline-start:8px}
#LS{position:fixed;inset:0;background:rgba(6,12,22,.9);display:flex;align-items:center;justify-content:center;backdrop-filter:blur(5px)}
.box{width:min(430px,92vw);background:linear-gradient(180deg,#10203a,#0b172b);border:1px solid var(--bd);border-radius:14px;padding:18px}
#toast{position:fixed;left:18px;bottom:18px;padding:10px 12px;background:#10223c;border:1px solid #2f4d78;border-radius:10px;color:#dceaff;display:none;z-index:99}
a{color:#8ec5ff;text-decoration:none}
@media (max-width:980px){.cards{grid-template-columns:1fr}.card{min-height:auto}.list{max-height:340px}.toolbar{grid-template-columns:1fr}}
</style>
</head>
<body>
<div id="LS"><div class="box">
  <h3>دخول لوحة الأدمن</h3>
  <input id="p" type="password" placeholder="كلمة المرور">
  <button class="sm" style="margin-top:10px;width:100%;background:#26456d;color:#e2efff" onclick="login()">دخول</button>
  <div id="e" style="color:#ff8080;font-size:12px;margin-top:8px;display:none">كلمة المرور غير صحيحة</div>
</div></div>
<div class="wrap" id="APP" style="display:none">
  <div class="top">
    <h2>لوحة الأدمن</h2>
    <div style="display:flex;align-items:center;gap:6px">
      <button class="sm" style="background:#26456d;color:#e2efff" onclick="load(true)">تحديث</button>
      <span id="lastUpdate">آخر تحديث: --:--:--</span>
      <div id="counts"></div>
    </div>
  </div>
  <div class="toolbar">
    <input id="searchBox" placeholder="بحث بـ Account ID أو Email..." oninput="renderAll()">
    <select id="statusFilter" onchange="renderAll()">
      <option value="pending">Pending فقط</option>
      <option value="all">الكل</option>
    </select>
  </div>
  <div class="cards">
    <div class="card">
      <div class="hd"><h3>طلبات المستخدمين</h3><div><button class="ok sm" onclick="bulkAction('join','approve')">قبول الكل</button> <button class="no sm" onclick="bulkAction('join','reject')">رفض الكل</button></div></div>
      <div id="join" class="list"></div>
      <div class="pager"><span class="pinfo" id="joinPageInfo">--</span><div><button class="sm" onclick="changePage('join',-1)">السابق</button> <button class="sm" onclick="changePage('join',1)">التالي</button></div></div>
    </div>
    <div class="card">
      <div class="hd"><h3>المستخدمون النشطون</h3><span class="muted">قراءة فقط</span></div>
      <div id="active" class="list"></div>
      <div class="pager"><span class="pinfo" id="activePageInfo">--</span><div><button class="sm" onclick="changePage('active',-1)">السابق</button> <button class="sm" onclick="changePage('active',1)">التالي</button></div></div>
    </div>
    <div class="card">
      <div class="hd"><h3>طلبات الدخول</h3><div><button class="ok sm" onclick="bulkAction('access','approve')">قبول الكل</button> <button class="no sm" onclick="bulkAction('access','reject')">رفض الكل</button></div></div>
      <div id="access" class="list"></div>
      <div class="pager"><span class="pinfo" id="accessPageInfo">--</span><div><button class="sm" onclick="changePage('access',-1)">السابق</button> <button class="sm" onclick="changePage('access',1)">التالي</button></div></div>
    </div>
  </div>
</div>
<div id="toast"></div>
<script>
let poll = null;
let state = {join_requests:[], active_users:[], access_requests:[], pending_join:0, pending_access:0, active_count:0};
const PAGE_SIZE = 8;
let pages = {join:1, active:1, access:1};
function saveUiState(){
  const data = {
    q: document.getElementById("searchBox")?.value || "",
    status: document.getElementById("statusFilter")?.value || "pending",
    pages: pages,
  };
  localStorage.setItem("nexoAdminUiState", JSON.stringify(data));
}
function loadUiState(){
  try{
    const raw = localStorage.getItem("nexoAdminUiState");
    if(!raw) return;
    const s = JSON.parse(raw);
    if (s && typeof s === "object"){
      const qEl = document.getElementById("searchBox");
      const stEl = document.getElementById("statusFilter");
      if (qEl && typeof s.q === "string") qEl.value = s.q;
      if (stEl && (s.status === "pending" || s.status === "all")) stEl.value = s.status;
      if (s.pages && typeof s.pages === "object"){
        pages.join = parseInt(s.pages.join || 1, 10) || 1;
        pages.active = parseInt(s.pages.active || 1, 10) || 1;
        pages.access = parseInt(s.pages.access || 1, 10) || 1;
      }
    }
  }catch(_){}
}
function toast(msg){
  const el=document.getElementById("toast");
  el.textContent=msg; el.style.display="block";
  clearTimeout(window.__tst); window.__tst=setTimeout(()=>el.style.display="none",2200);
}
function q(){ return (document.getElementById("searchBox")?.value || "").trim().toLowerCase(); }
function statusMode(){ return document.getElementById("statusFilter")?.value || "pending"; }
function isMatch(x){
  const s=q(); if(!s) return true;
  return String(x.account_id||"").toLowerCase().includes(s) || String(x.email||"").toLowerCase().includes(s);
}
function byStatus(list){
  if(statusMode()==="all") return list;
  return (list||[]).filter(x=>x.status==="pending");
}
async function login(){
  const p=document.getElementById("p").value.trim();
  const r=await fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({pass:p})});
  const d=await r.json();
  if(!d.ok){document.getElementById("e").style.display="block";return;}
  document.getElementById("LS").style.display="none";
  document.getElementById("APP").style.display="block";
  loadUiState();
  await load(); poll=setInterval(load,2000);
}
function rowJoin(x){
  return `<div class="item"><b>${x.account_id}</b><div class="meta">${x.email||""}</div><div class="meta">${String(x.image_url||"").startsWith("/uploads/")?`<a href="${x.image_url}" target="_blank">عرض الصورة</a>`:`الصورة مرسلة على تيليغرام`}</div><div class="actions"><button class="ok" onclick="approveJoin('${x.id}')">قبول</button><button class="no" onclick="rejectJoin('${x.id}')">رفض</button></div></div>`;
}
function rowAccess(x){
  return `<div class="item"><b>${x.account_id}</b><div class="meta">${x.email||""}</div><div class="meta">${x.created_at||""}</div><div class="actions"><button class="ok" onclick="approveAccess('${x.id}')">قبول</button><button class="no" onclick="rejectAccess('${x.id}')">رفض</button></div></div>`;
}
function rowActive(x){
  return `<div class='item'><b>${x.account_id}</b><div class="meta">${x.email||""}</div><div class="meta">${x.activated_at||""}</div></div>`;
}
async function approveJoin(id){await fetch(`/api/join-request/${id}/approve`,{method:"POST"});toast("تم قبول الطلب");load();}
async function rejectJoin(id){await fetch(`/api/join-request/${id}/reject`,{method:"POST"});toast("تم رفض الطلب");load();}
async function approveAccess(id){await fetch(`/api/access-request/${id}/approve`,{method:"POST"});toast("تم قبول طلب الدخول");load();}
async function rejectAccess(id){await fetch(`/api/access-request/${id}/reject`,{method:"POST"});toast("تم رفض طلب الدخول");load();}
async function bulkAction(kind, action){
  const ok = confirm(action==="approve" ? "تأكيد تنفيذ القبول الجماعي؟" : "تأكيد تنفيذ الرفض الجماعي؟");
  if(!ok) return;
  const list = kind==="join" ? byStatus(state.join_requests).filter(isMatch) : byStatus(state.access_requests).filter(isMatch);
  if(!list.length){ toast("لا توجد عناصر مطابقة"); return; }
  const endpoint = kind==="join" ? "/api/join-request" : "/api/access-request";
  for(const x of list){ await fetch(`${endpoint}/${x.id}/${action}`,{method:"POST"}); }
  toast(`تم تنفيذ العملية على ${list.length} عنصر`);
  load();
}
function paginate(list, key){
  const total = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
  if (pages[key] > total) pages[key] = total;
  if (pages[key] < 1) pages[key] = 1;
  const start = (pages[key]-1) * PAGE_SIZE;
  const part = list.slice(start, start + PAGE_SIZE);
  const infoEl = document.getElementById(`${key}PageInfo`);
  if (infoEl) infoEl.textContent = `${pages[key]} / ${total} • ${list.length} عنصر`;
  return part;
}
function changePage(key, step){
  pages[key] = (pages[key] || 1) + step;
  saveUiState();
  renderAll();
}
function renderAll(){
  const joins = byStatus(state.join_requests).filter(isMatch);
  const access = byStatus(state.access_requests).filter(isMatch);
  const active = (state.active_users||[]).filter(isMatch);
  const joinsPage = paginate(joins, "join");
  const accessPage = paginate(access, "access");
  const activePage = paginate(active, "active");
  document.getElementById("join").innerHTML = joinsPage.map(rowJoin).join("") || "<div class='muted'>لا يوجد</div>";
  document.getElementById("access").innerHTML = accessPage.map(rowAccess).join("") || "<div class='muted'>لا يوجد</div>";
  document.getElementById("active").innerHTML = activePage.map(rowActive).join("") || "<div class='muted'>لا يوجد</div>";
  document.getElementById("counts").textContent = `طلبات الانضمام: ${state.pending_join} | النشطون: ${state.active_count} | طلبات الدخول: ${state.pending_access} | نتائج الفلترة: ${joins.length + access.length + active.length}`;
  saveUiState();
}
async function load(showToast){
  const r=await fetch("/api/admin/overview");
  const d=await r.json();
  state = d || state;
  const now = new Date();
  const t = now.toLocaleTimeString("en-GB");
  const lu = document.getElementById("lastUpdate");
  if (lu) lu.textContent = `آخر تحديث: ${t}`;
  if (showToast) toast("تم تحديث البيانات");
  renderAll();
}
</script>
</body>
</html>"""

# ══════════════════════════════════════════
#  API ROUTES
# ══════════════════════════════════════════
async def route_login(req):
    d=await req.json()
    return web.json_response({"ok": d.get("pass")==CONFIG["admin_pass"]})

async def route_user_login(req):
    d = await req.json()
    account_id = (d.get("account_id") or "").strip()
    if not account_id:
        return web.json_response({"ok": False, "status": "invalid", "msg": "Account ID مطلوب"}, status=400)

    with db_connect() as con:
        approved = con.execute("SELECT 1 FROM approved_users WHERE account_id = ? LIMIT 1", (account_id,)).fetchone()
        pending = con.execute(
            "SELECT 1 FROM join_requests WHERE account_id = ? AND status = 'pending' LIMIT 1",
            (account_id,),
        ).fetchone()
    if approved:
        return web.json_response({"ok": True, "status": "approved"})
    if pending:
        return web.json_response({"ok": True, "status": "pending"})

    return web.json_response({"ok": True, "status": "not_found"})

async def route_landing(req):
    return web.Response(text=LANDING_HTML, content_type="text/html")

async def route_dash(req):
    return web.Response(text=HTML, content_type="text/html")

async def route_login_page(req):
    return web.Response(text=LOGIN_HTML, content_type="text/html")

async def route_join_page(req):
    return web.Response(text=JOIN_HTML, content_type="text/html")

async def route_access_page(req):
    return web.Response(text=ACCESS_HTML, content_type="text/html")

async def route_admin_page(req):
    return web.Response(text=ADMIN_HTML, content_type="text/html")

async def route_join_submit(req):
    try:
        reader = await req.multipart()
        account_id = ""
        email = ""
        image_name = None
        image_bytes = b""
        image_filename = "profile.jpg"
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "account_id":
                account_id = (await part.text()).strip()
            elif part.name == "email":
                email = (await part.text()).strip().lower()
            elif part.name == "profile_image":
                fname = part.filename or "profile.jpg"
                ext = os.path.splitext(fname)[1].lower() or ".jpg"
                safe_ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
                image_name = f"{uuid.uuid4().hex}{safe_ext}"
                image_filename = f"profile{safe_ext}"
                chunks = bytearray()
                while True:
                    chunk = await part.read_chunk()
                    if not chunk:
                        break
                    chunks.extend(chunk)
                    if len(chunks) > 8 * 1024 * 1024:
                        return web.json_response({"ok": False, "msg": "حجم الصورة كبير جداً (الحد 8MB)"}, status=400)
                image_bytes = bytes(chunks)
        if not account_id or not email or not image_name:
            return web.json_response({"ok": False, "msg": "كل الحقول مطلوبة"}, status=400)
        with db_connect() as con:
            approved = con.execute(
                "SELECT 1 FROM approved_users WHERE account_id = ? OR email = ? LIMIT 1",
                (account_id, email),
            ).fetchone()
        if approved:
            return web.json_response({
                "ok": True,
                "status": "approved",
                "redirect": "/login",
                "msg": "الحساب مقبول مسبقًا، يمكنك تسجيل الدخول مباشرة",
            })
        with db_connect() as con:
            pending = con.execute(
                "SELECT 1 FROM join_requests WHERE account_id = ? AND status = 'pending' LIMIT 1",
                (account_id,),
            ).fetchone()
        if pending:
            return web.json_response({"ok": False, "msg": "لديك طلب قيد المراجعة بالفعل"}, status=400)
        new_req = {
            "id": uuid.uuid4().hex[:10],
            "account_id": account_id,
            "email": email,
            "image_url": "telegram://attached",
            "status": "pending",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "updated_by": "self",
            "tg_message_id": None,
        }
        with db_connect() as con:
            con.execute(
                """
                INSERT INTO join_requests(id, account_id, email, image_url, status, created_at, updated_at, updated_by, tg_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_req["id"], new_req["account_id"], new_req["email"], new_req["image_url"],
                    new_req["status"], new_req["created_at"], new_req["updated_at"], new_req["updated_by"], None
                ),
            )
        async with aiohttp.ClientSession() as session:
            ok, msg, tg_msg_id = await send_join_request_to_tg(
                session,
                new_req,
                image_bytes=image_bytes,
                image_filename=image_filename,
            )
            if tg_msg_id:
                new_req["tg_message_id"] = tg_msg_id
                with db_connect() as con:
                    con.execute("UPDATE join_requests SET tg_message_id = ? WHERE id = ?", (tg_msg_id, new_req["id"]))
            if not ok:
                L.warning(f"Join request telegram not sent: {msg}")
        return web.json_response({"ok": True, "request_id": new_req["id"]})
    except Exception as e:
        return web.json_response({"ok": False, "msg": str(e)}, status=500)

async def route_join_requests(req):
    with db_connect() as con:
        requests = [dict(r) for r in con.execute("SELECT * FROM join_requests ORDER BY created_at DESC LIMIT 100").fetchall()]
        approved_users = [dict(r) for r in con.execute("SELECT * FROM approved_users ORDER BY approved_at DESC LIMIT 100").fetchall()]
        pending_count = con.execute("SELECT COUNT(1) c FROM join_requests WHERE status = 'pending'").fetchone()["c"]
        approved_count = con.execute("SELECT COUNT(1) c FROM approved_users").fetchone()["c"]
    return web.json_response({
        "requests": requests,
        "approved_users": approved_users,
        "pending_count": pending_count,
        "approved_count": approved_count,
    })

async def route_access_submit(req):
    try:
        d = await req.json()
        account_id = (d.get("account_id") or "").strip()
        email = (d.get("email") or "").strip().lower()
        if not account_id or not email:
            return web.json_response({"ok": False, "msg": "البيانات ناقصة"}, status=400)
        with db_connect() as con:
            approved = con.execute(
                "SELECT 1 FROM approved_users WHERE account_id = ? AND email = ? LIMIT 1",
                (account_id, email),
            ).fetchone()
        if not approved:
            return web.json_response({"ok": False, "msg": "الحساب غير مقبول بعد"}, status=400)
        with db_connect() as con:
            pending_access = con.execute(
                "SELECT 1 FROM access_requests WHERE account_id = ? AND status = 'pending' LIMIT 1",
                (account_id,),
            ).fetchone()
        if pending_access:
            return web.json_response({"ok": False, "msg": "يوجد طلب دخول قيد المراجعة"}, status=400)
        rec = {
            "id": uuid.uuid4().hex[:10],
            "account_id": account_id,
            "email": email,
            "status": "pending",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        with db_connect() as con:
            con.execute(
                """
                INSERT INTO access_requests(id, account_id, email, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (rec["id"], rec["account_id"], rec["email"], rec["status"], rec["created_at"], rec["updated_at"]),
            )
        async with aiohttp.ClientSession() as session:
            ok, msg, _ = await send_access_request_to_tg(session, rec)
            if not ok:
                L.warning(f"Access request telegram not sent: {msg}")
        return web.json_response({"ok": True, "id": rec["id"]})
    except Exception as e:
        return web.json_response({"ok": False, "msg": str(e)}, status=500)

async def route_access_approve(req):
    req_id = req.match_info.get("req_id")
    with db_connect() as con:
        row = con.execute("SELECT * FROM access_requests WHERE id = ?", (req_id,)).fetchone()
    item = dict(row) if row else None
    if not item:
        return web.json_response({"ok": False, "msg": "الطلب غير موجود"}, status=404)
    updated_at = now_iso()
    with db_connect() as con:
        con.execute("UPDATE access_requests SET status='approved', updated_at=? WHERE id=?", (updated_at, req_id))
        con.execute(
            """
            INSERT OR REPLACE INTO active_users(account_id, access_request_id, email, activated_at)
            VALUES (?, ?, ?, ?)
            """,
            (item["account_id"], item["id"], item["email"], updated_at),
        )
    return web.json_response({"ok": True})

async def route_access_reject(req):
    req_id = req.match_info.get("req_id")
    with db_connect() as con:
        row = con.execute("SELECT * FROM access_requests WHERE id = ?", (req_id,)).fetchone()
    item = dict(row) if row else None
    if not item:
        return web.json_response({"ok": False, "msg": "الطلب غير موجود"}, status=404)
    with db_connect() as con:
        con.execute("UPDATE access_requests SET status='rejected', updated_at=? WHERE id=?", (now_iso(), req_id))
    return web.json_response({"ok": True})

async def route_admin_overview(req):
    with db_connect() as con:
        join_requests = [dict(r) for r in con.execute("SELECT * FROM join_requests ORDER BY created_at DESC LIMIT 100").fetchall()]
        active_users = [dict(r) for r in con.execute("SELECT * FROM active_users ORDER BY activated_at DESC LIMIT 100").fetchall()]
        access_requests = [dict(r) for r in con.execute("SELECT * FROM access_requests ORDER BY created_at DESC LIMIT 100").fetchall()]
        pending_join = con.execute("SELECT COUNT(1) c FROM join_requests WHERE status='pending'").fetchone()["c"]
        pending_access = con.execute("SELECT COUNT(1) c FROM access_requests WHERE status='pending'").fetchone()["c"]
        active_count = con.execute("SELECT COUNT(1) c FROM active_users").fetchone()["c"]
    return web.json_response({
        "join_requests": join_requests,
        "active_users": active_users,
        "access_requests": access_requests,
        "pending_join": pending_join,
        "pending_access": pending_access,
        "active_count": active_count,
    })

async def route_join_approve(req):
    req_id = req.match_info.get("req_id")
    target = find_request(req_id)
    if not target:
        return web.json_response({"ok": False, "msg": "الطلب غير موجود"}, status=404)
    set_request_status(target, "approved")
    async with aiohttp.ClientSession() as session:
        await clear_join_request_buttons(session, target)
    return web.json_response({"ok": True})

async def route_join_reject(req):
    req_id = req.match_info.get("req_id")
    target = find_request(req_id)
    if not target:
        return web.json_response({"ok": False, "msg": "الطلب غير موجود"}, status=404)
    set_request_status(target, "rejected")
    async with aiohttp.ClientSession() as session:
        await clear_join_request_buttons(session, target)
    return web.json_response({"ok": True})

async def route_cfg_get(req):
    hidden = {"admin_pass", "tg_token", "tg_channel", "access_tg_token", "access_tg_channel", "oanda_key", "groq_key", "claude_key"}
    safe = {k:v for k,v in CONFIG.items() if k not in hidden}
    return web.json_response(safe)

async def route_cfg_set(req):
    d=await req.json()
    for k,v in d.items():
        if k in CONFIG and k!="admin_pass": CONFIG[k]=v
    try:
        CONFIG["minimum_ai_confidence"] = max(50, min(95, int(CONFIG.get("minimum_ai_confidence", 75))))
    except Exception:
        CONFIG["minimum_ai_confidence"] = 75
    mode = str(CONFIG.get("ai_failure_mode", "reject")).lower()
    CONFIG["ai_failure_mode"] = mode if mode in ("reject", "strong_only") else "reject"
    try:
        CONFIG["news_filter_before_min"] = max(0, min(180, int(CONFIG.get("news_filter_before_min", 30))))
    except Exception:
        CONFIG["news_filter_before_min"] = 30
    try:
        CONFIG["news_filter_after_min"] = max(0, min(180, int(CONFIG.get("news_filter_after_min", 15))))
    except Exception:
        CONFIG["news_filter_after_min"] = 15
    if CONFIG.get("auto_telegram"):
        CONFIG["strategy"] = "smart_auto"
        forced_pairs = []
        for group_pairs in ALL_PAIRS.values():
            for pair in group_pairs:
                if pair not in forced_pairs:
                    forced_pairs.append(pair)
        if forced_pairs:
            CONFIG["active_pairs"] = forced_pairs
    return web.json_response({"ok":True})

async def route_economic_calendar(req):
    range_key = req.query.get("range", "today")
    currency = req.query.get("currency", "all").upper()
    importance = req.query.get("importance", "all")
    if currency not in {"ALL", "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "NZD"}:
        currency = "ALL"
    if importance not in {"all", "1", "2", "3"}:
        importance = "all"
    if range_key not in {"yesterday", "today", "tomorrow", "week", "next_week"}:
        range_key = "today"
    now = time.time()
    use_server_side_filters = (ECONOMIC_CALENDAR_PROVIDER == "rapidapi" and bool(RAPIDAPI_KEY))
    cached = (not use_server_side_filters) and (now - CALENDAR_CACHE["ts"]) < 180 and CALENDAR_CACHE["items"]
    if not cached:
        source = "mock"
        provider = "mock"
        items = []
        try:
            async with aiohttp.ClientSession() as session:
                # Provider modes:
                # - tradingeconomics: use Trading Economics calendar API
                # - investing_scraper: scrape investing calendar page server-side
                # - rapidapi: use RapidAPI economic calendar provider
                # - github: use self-hosted github economic-calendar-api
                # - nfs: use JSON calendar feeds directly
                # - auto: try tradingeconomics then investing_scraper then rapidapi then mock fallback
                if ECONOMIC_CALENDAR_PROVIDER == "tradingeconomics":
                    items = await fetch_calendar_from_tradingeconomics(session)
                    if items:
                        source = "api"
                        provider = "tradingeconomics"
                elif ECONOMIC_CALENDAR_PROVIDER == "investing_scraper":
                    if INVESTING_SCRAPER_PROXY_URL:
                        items = await fetch_investing_calendar_from_proxy(session)
                    else:
                        html = await fetch_investing_calendar_html(session)
                        items = parse_investing_calendar(html)
                    if items:
                        source = "api"
                        provider = "investing_scraper_proxy" if INVESTING_SCRAPER_PROXY_URL else "investing_scraper"
                    elif RAPIDAPI_KEY:
                        items = await fetch_calendar_from_rapidapi(session, range_key, currency, importance)
                        if items:
                            source = "api"
                            provider = "rapidapi-economic-calendar-api"
                    if not items:
                        items = await fetch_calendar_from_nfs_api(session)
                        if items:
                            source = "api"
                            provider = "nfs-calendar-feed"
                elif ECONOMIC_CALENDAR_PROVIDER == "rapidapi" and RAPIDAPI_KEY:
                    items = await fetch_calendar_from_rapidapi(session, range_key, currency, importance)
                    if items:
                        source = "api"
                        provider = "rapidapi-economic-calendar-api"
                elif ECONOMIC_CALENDAR_PROVIDER == "github" and ECONOMIC_CALENDAR_URL:
                    items = await fetch_calendar_from_github_api(session)
                    if items:
                        source = "api"
                        provider = "github-economic-calendar-api"
                elif ECONOMIC_CALENDAR_PROVIDER == "nfs":
                    items = await fetch_calendar_from_nfs_api(session)
                    if items:
                        source = "api"
                        provider = "nfs-calendar-feed"
                elif ECONOMIC_CALENDAR_PROVIDER == "auto":
                    try:
                        items = await fetch_calendar_from_tradingeconomics(session)
                    except Exception:
                        items = []
                    if items:
                        source = "api"
                        provider = "tradingeconomics"
                    if not items:
                        try:
                            if INVESTING_SCRAPER_PROXY_URL:
                                items = await fetch_investing_calendar_from_proxy(session)
                            else:
                                html = await fetch_investing_calendar_html(session)
                                items = parse_investing_calendar(html)
                        except Exception:
                            items = []
                    if items and source == "mock":
                        source = "api"
                        provider = "investing_scraper_proxy" if INVESTING_SCRAPER_PROXY_URL else "investing_scraper"
                    if not items and RAPIDAPI_KEY:
                        items = await fetch_calendar_from_rapidapi(session, range_key, currency, importance)
                        if items:
                            source = "api"
                            provider = "rapidapi-economic-calendar-api"
                    if not items:
                        items = await fetch_calendar_from_nfs_api(session)
                        if items:
                            source = "api"
                            provider = "nfs-calendar-feed"
        except Exception as e:
            L.warning(f"Economic calendar provider failed: {e}")
        if not items:
            items = _calendar_mock_items()
        CALENDAR_CACHE["ts"] = now
        CALENDAR_CACHE["items"] = items
        CALENDAR_CACHE["source"] = source
        CALENDAR_CACHE["provider"] = provider
    if use_server_side_filters:
        # RapidAPI already receives range/currency/importance filters server-side.
        items = list(CALENDAR_CACHE["items"])
    else:
        items = filter_calendar_items(list(CALENDAR_CACHE["items"]), range_key, currency, importance)
    if CALENDAR_MAJOR_ONLY:
        items = [x for x in items if _is_major_calendar_event(x.get("event", ""))]
    return web.json_response({
        "ok": True,
        "cached": cached,
        "source": CALENDAR_CACHE.get("source", "mock"),
        "provider": CALENDAR_CACHE.get("provider", "mock"),
        "items": items,
    })

async def route_status(req):
    latest = HISTORY[0] if HISTORY else None
    market_open = is_trading_window_open()
    return web.json_response({
        "running" : CONFIG["bot_running"],
        "total"   : STATS["total"],
        "sent_tg" : STATS["sent_tg"],
        "cycles"  : STATS["cycles"],
        "ai"      : STATS["ai"],
        "cd"      : cd_val,
        "count"   : len(HISTORY),
        "latest"  : latest,
        "market_open": market_open,
        "market_msg": "" if market_open else market_closed_message(),
    })

async def route_start(req):
    global bot_task
    if CONFIG["bot_running"]: return web.json_response({"ok":True})
    if not is_trading_window_open():
        return web.json_response({"ok":False,"msg":market_closed_message()})
    if CONFIG.get("auto_telegram"):
        CONFIG["strategy"] = "smart_auto"
        forced_pairs = []
        for group_pairs in ALL_PAIRS.values():
            for pair in group_pairs:
                if pair not in forced_pairs:
                    forced_pairs.append(pair)
        if forced_pairs:
            CONFIG["active_pairs"] = forced_pairs
    if not CONFIG["active_pairs"]: return web.json_response({"ok":False,"msg":"اختر أزواجاً أولاً"})
    CONFIG["bot_running"]=True
    bot_task=asyncio.create_task(bot_loop())
    return web.json_response({"ok":True})

async def route_stop(req):
    global cd_val
    CONFIG["bot_running"]=False; cd_val=-1
    if bot_task: bot_task.cancel()
    return web.json_response({"ok":True})

async def route_analyze(req):
    if not is_trading_window_open():
        return web.json_response({"signal":None, "msg":market_closed_message()})
    async with aiohttp.ClientSession() as session:
        pairs_data=[]
        market_data={}
        for ins in CONFIG["active_pairs"]:
            cn=await get_candles(session,ins)
            if not cn:
                continue
            if not market_is_moving(ins, cn):
                continue
            res=analyze_local(ins, cn, CONFIG.get("strategy"))
            if res:
                pairs_data.append(res)
                market_data[ins] = cn
        if not pairs_data:
            return web.json_response({"signal":None})
        sig=await build_signal(session,pairs_data, market_data=market_data)
        if not sig or sig["confidence"]<CONFIG["min_confidence"]:
            return web.json_response({"signal":None})
        if not can_emit_signal(sig):
            return web.json_response({"signal":None})
        sig["time"]    = datetime.now().strftime("%H:%M:%S")
        sig["next_min"]= next_minute()
        HISTORY.insert(0,sig); STATS["total"]+=1
        while len(HISTORY)>30: HISTORY.pop()
        return web.json_response({"signal":sig})

async def route_tg_send(req):
    d=await req.json()
    sig=d.get("signal") or (HISTORY[0] if HISTORY else None)
    if not sig: return web.json_response({"ok":False,"msg":"لا توجد إشارة"})
    msg=build_tg(sig)
    async with aiohttp.ClientSession() as session:
        ok,err=await send_tg(session,msg)
        if ok: STATS["sent_tg"]+=1
        return web.json_response({"ok":ok,"msg":err})

async def route_tg_test(req):
    msg="✅ اختبار ناجح\n📈 إشارات التداول\nالبوت يعمل!\nصفقة واحدة كل دقيقة — الأقوى"
    async with aiohttp.ClientSession() as session:
        ok,err=await send_tg(session,msg)
        return web.json_response({"ok":ok,"msg":err})

# ══════════════════════════════════════════
#  التشغيل
# ══════════════════════════════════════════
def main():
    global tg_updates_task
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    app=web.Application()
    app.router.add_get("/",                     route_landing)
    app.router.add_get("/login",                route_login_page)
    app.router.add_get("/dashboard",            route_dash)
    app.router.add_get("/app",                  route_dash)
    app.router.add_get("/admin",                route_admin_page)
    app.router.add_get("/join",                 route_join_page)
    app.router.add_get("/access",               route_access_page)
    app.router.add_post("/api/join-request",    route_join_submit)
    app.router.add_get("/api/join-requests",    route_join_requests)
    app.router.add_post("/api/join-request/{req_id}/approve", route_join_approve)
    app.router.add_post("/api/join-request/{req_id}/reject",  route_join_reject)
    app.router.add_post("/api/access-request",  route_access_submit)
    app.router.add_post("/api/access-request/{req_id}/approve", route_access_approve)
    app.router.add_post("/api/access-request/{req_id}/reject",  route_access_reject)
    app.router.add_get("/api/admin/overview",   route_admin_overview)
    app.router.add_post("/api/login",           route_login)
    app.router.add_post("/api/user/login",      route_user_login)
    app.router.add_get("/api/config",           route_cfg_get)
    app.router.add_post("/api/config",          route_cfg_set)
    app.router.add_get("/api/economic-calendar", route_economic_calendar)
    app.router.add_get("/api/status",           route_status)
    app.router.add_post("/api/bot/start",       route_start)
    app.router.add_post("/api/bot/stop",        route_stop)
    app.router.add_post("/api/analyze",         route_analyze)
    app.router.add_post("/api/telegram/send",   route_tg_send)
    app.router.add_post("/api/telegram/test",   route_tg_test)
    app.router.add_static("/uploads", str(UPLOAD_DIR))

    async def on_startup(_app):
        global tg_updates_task, bot_task
        if CONFIG.get("access_tg_token") or CONFIG.get("tg_token"):
            tg_updates_task = asyncio.create_task(process_tg_updates())
            L.info("🤖 Telegram callback listener started")
        # Auto-run bot on process start when Telegram is configured.
        if CONFIG.get("tg_token") and CONFIG.get("tg_channel") and not CONFIG.get("bot_running") and is_trading_window_open():
            CONFIG["auto_telegram"] = True
            CONFIG["bot_running"] = True
            if not CONFIG.get("active_pairs"):
                CONFIG["active_pairs"] = ["EUR_JPY", "AUD_JPY", "GBP_USD", "USD_JPY", "EUR_AUD", "AUD_CHF", "EUR_GBP"]
            bot_task = asyncio.create_task(bot_loop())
            L.info("🚀 Auto start enabled: bot started with Telegram sending")

    async def on_cleanup(_app):
        global tg_updates_task
        if tg_updates_task:
            tg_updates_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tg_updates_task

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    port=int(os.environ.get("PORT", CONFIG["port"]))
    L.info("="*55)
    L.info("Elite Bot v5.0 — Quotex M1")
    L.info(f"🌐 الواجهة الرئيسية : http://localhost:{port}")
    L.info(f"🛡 لوحة الإدمن : http://localhost:{port}/admin")
    L.info(f"🔒 كلمة المرور : {CONFIG['admin_pass']}")
    L.info(f"📝 طلبات الانضمام: http://localhost:{port}/join")
    L.info(f"🔑 طلبات الدخول : http://localhost:{port}/access")
    L.info("🔐 TG ENV: TG_BOT_TOKEN + TG_CHANNEL_ID")
    L.info("🔐 ACCESS TG ENV: ACCESS_REQUEST_TG_BOT_TOKEN + ACCESS_REQUEST_TG_CHANNEL_ID")
    L.info(f"🗓 Calendar provider : {ECONOMIC_CALENDAR_PROVIDER} ({ECONOMIC_CALENDAR_URL or RAPIDAPI_HOST})")
    L.info(f"⚡ AI : Groq Llama 70B → Claude → محلي")
    L.info(f"⏰ الإشارة قبل نهاية الدقيقة بـ 23 ثانية")
    L.info(f"💱 الأزواج : {', '.join(pname(p) for p in CONFIG['active_pairs'])}")
    L.info("="*55)
    web.run_app(app, host="0.0.0.0", port=port, print=None)

if __name__=="__main__":
    main()
