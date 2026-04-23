import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import yfinance as yf
import numpy as np
import pandas as pd
from groq import Groq

# =========================
# 🔑 KEYS (تأكد من إضافتها في Render Environment Variables)
# =========================
TOKEN = os.getenv("TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)

# =========================
# 📊 TRADING LOGIC
# =========================
def get_data(symbol):
    data = yf.Ticker(symbol).history(period="6mo")
    if data.empty or len(data) < 60:
        return None
    return data

def rsi(data):
    delta = data["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def macd(data):
    fast = data["Close"].ewm(span=12).mean()
    slow = data["Close"].ewm(span=26).mean()
    line = fast - slow
    signal = line.ewm(span=9).mean()
    return line, signal

def trend(data):
    ma20 = data["Close"].rolling(20).mean()
    ma50 = data["Close"].rolling(50).mean()
    return "UP" if ma20.iloc[-1] > ma50.iloc[-1] else "DOWN"

def signal(rsi_v, macd_v, macd_s, trend_v):
    score = 0
    if rsi_v < 30: score += 2
    elif rsi_v > 70: score -= 2
    if macd_v.iloc[-1] > macd_s.iloc[-1]: score += 1
    else: score -= 1
    if trend_v == "UP": score += 1
    else: score -= 1
    
    if score >= 3: return "BUY 🟢"
    elif score <= -2: return "SELL 🔴"
    else: return "WAIT ⚪"

def risk(price):
    sl = round(price * 0.97, 2)
    tp = round(price * 1.05, 2)
    return sl, tp

def ai_analysis(symbol, price, sig, rsi_v, trend_v):
    prompt = f"Analyze {symbol} at {price}. Signal: {sig}, RSI: {rsi_v}, Trend: {trend_v}. Short professional summary."
    res = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )
    return res.choices[0].message.content

# =========================
# 🤖 TELEGRAM HANDLERS
# =========================
async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("💡 يرجى كتابة رمز السهم، مثال: /analyze NVDA")
            return
            
        symbol = context.args[0].upper()
        data = get_data(symbol)

        if data is None:
            await update.message.reply_text("❌ لم يتم العثور على بيانات لهذا السهم.")
            return

        price = round(data["Close"].iloc[-1], 2)
        rsi_v = rsi(data).iloc[-1]
        macd_v, macd_s = macd(data)
        trend_v = trend(data)
        sig = signal(rsi_v, macd_v, macd_s, trend_v)
        sl, tp = risk(price)
        analysis = ai_analysis(symbol, price, sig, round(rsi_v, 2), trend_v)

        await update.message.reply_text(f"📊 {symbol} @ {price}$\n\n🎯 SIGNAL: {sig}\n🛑 SL: {sl}\n🎯 TP: {tp}\n\n📈 Trend: {trend_v}\n📉 RSI: {round(rsi_v, 2)}\n\n🤖 AI:\n{analysis}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ حدث خطأ: {str(e)}")

# =========================
# 🌐 FLASK SERVER (For Render Health Check)
# =========================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is running!", 200

def run_flask():
    # Render بيطلب إننا نفتح Port وإلا بيعتبر التطبيق فشل
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# =========================
# 🚀 MAIN RUNNER
# =========================
if __name__ == "__main__":
    # 1. تشغيل Flask في Thread منفصل عشان ما يعطل البوت
    threading.Thread(target=run_flask, daemon=True).start()

    # 2. تشغيل البوت بنظام Polling
    print("🚀 Bot is starting...")
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("analyze", analyze))
    
    application.run_polling()
