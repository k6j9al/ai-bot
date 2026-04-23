import os
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import yfinance as yf
import numpy as np
import pandas as pd
from groq import Groq

# =========================
# 🔑 KEYS
# =========================
TOKEN = os.getenv("TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

client = Groq(api_key=GROQ_API_KEY)

# =========================
# 📊 DATA
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

    if rsi_v < 30:
        score += 2
    elif rsi_v > 70:
        score -= 2

    if macd_v.iloc[-1] > macd_s.iloc[-1]:
        score += 1
    else:
        score -= 1

    if trend_v == "UP":
        score += 1
    else:
        score -= 1

    if score >= 3:
        return "BUY 🟢"
    elif score <= -2:
        return "SELL 🔴"
    else:
        return "WAIT ⚪"

def risk(price):
    sl = round(price * 0.97, 2)
    tp = round(price * 1.05, 2)
    return sl, tp

def ai(symbol, price, sig, rsi_v, trend_v):
    prompt = f"""
You are a professional trading analyst.

Stock: {symbol}
Price: {price}
Signal: {sig}
RSI: {rsi_v}
Trend: {trend_v}

Explain:
- market condition
- risk
- simple strategy
"""

    res = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    return res.choices[0].message.content

# =========================
# 🤖 TELEGRAM
# =========================
app = ApplicationBuilder().token(TOKEN).build()

async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        data = get_data(symbol)

        if data is None:
            await update.message.reply_text("❌ No data")
            return

        price = round(data["Close"].iloc[-1], 2)
        rsi_v = rsi(data).iloc[-1]
        macd_v, macd_s = macd(data)
        trend_v = trend(data)

        sig = signal(rsi_v, macd_v, macd_s, trend_v)
        sl, tp = risk(price)

        analysis = ai(symbol, price, sig, round(rsi_v,2), trend_v)

        await update.message.reply_text(f"""📊 {symbol} @ {price}$

🎯 SIGNAL: {sig}

🛑 SL: {sl}
🎯 TP: {tp}

📈 Trend: {trend_v}
📉 RSI: {round(rsi_v,2)}

🤖 AI:
{analysis}
""")

    except Exception as e:
        print(e)
        await update.message.reply_text("⚠️ error")

app.add_handler(CommandHandler("analyze", analyze))

# =========================
# 🌐 FLASK (WEBHOOK)
# =========================
flask_app = Flask(__name__)

@flask_app.route(f"/{TOKEN}", methods=["POST"])
async def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return "ok"

@flask_app.route("/")
def home():
    return "Bot is running!"

# =========================
# 🚀 RUN
# =========================
if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))

    print("🚀 BOT RUNNING (WEBHOOK MODE)")

    app.bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}")

    flask_app.run(host="0.0.0.0", port=PORT)
