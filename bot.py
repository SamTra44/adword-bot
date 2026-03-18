import os
import threading
import requests
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ============================================================
# CONFIG — Railway pe Environment Variables se aayega
# ============================================================
API_KEY     = os.environ.get("SMM_API_KEY", "877f4a9fcf5d5770b86f97867beea5bc")
API_URL     = "https://honestsmm.com/api/v2"
SERVICE_ID  = "1554"
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
ALLOWED_IDS = os.environ.get("ALLOWED_IDS", "7259603771")
# ============================================================

# Flask — Railway ke liye port binding (zaroori hai)
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ AdWord Bot is running!", 200

# Active sessions
sessions = {}  # uid -> {stop, placed, ok, total}

# ── Helpers ──────────────────────────────────────────────

def is_allowed(uid: int) -> bool:
    if not ALLOWED_IDS.strip():
        return True
    return str(uid) in [x.strip() for x in ALLOWED_IDS.split(",")]

def place_one(link, qty):
    r = requests.post(API_URL, data={
        "key": API_KEY, "action": "add",
        "service": SERVICE_ID, "link": link, "quantity": qty
    }, timeout=15)
    return r.json()

# ── Commands ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("❌ Access denied.")
        return
    await update.message.reply_text(
        "👋 *AdWord Auto Order Bot*\n\n"
        "📌 Commands:\n\n"
        "▶ `/order [link] [qty] [total] [gap]`\n"
        "Misal:\n`/order https://facebook.com/live/xyz 100 5 30`\n\n"
        "⏹ `/stop` — Session band karo\n"
        "📊 `/status` — Status dekho\n"
        "💰 `/balance` — Account balance dekho\n\n"
        "📝 _qty: 20–5000 | gap: min 5 sec_",
        parse_mode="Markdown"
    )

async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("❌ Access denied.")
        return
    try:
        r = requests.post(API_URL, data={"key": API_KEY, "action": "balance"}, timeout=10)
        d = r.json()
        if "balance" in d:
            bal = float(d["balance"])
            emoji = "🟢" if bal >= 50 else "🔴"
            await update.message.reply_text(
                f"💰 *Account Balance*\n\n{emoji} ₹{bal:.2f}\n\n"
                + ("⚠️ _Balance low hai! Add funds._" if bal < 50 else "_Balance theek hai._"),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Balance fetch nahi hua. Try again.")
    except Exception:
        await update.message.reply_text("❌ Connection error. Try again.")

async def cmd_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text("❌ Access denied.")
        return

    if uid in sessions and not sessions[uid]["stop"].is_set():
        await update.message.reply_text("⚠️ Session already chal raha hai.\nPehle /stop karo.")
        return

    args = ctx.args
    if len(args) < 4:
        await update.message.reply_text(
            "❌ *Format galat hai!*\n\n"
            "Sahi format:\n`/order [link] [qty] [total] [gap]`\n\n"
            "Misal:\n`/order https://facebook.com/live/xyz 100 5 30`\n\n"
            "• link = Facebook Live URL\n"
            "• qty = ek order mein kitne views (20–5000)\n"
            "• total = kitne orders dalne hain\n"
            "• gap = orders ke beech kitne seconds ka gap",
            parse_mode="Markdown"
        )
        return

    link = args[0]
    try:
        qty   = int(args[1])
        total = int(args[2])
        gap   = int(args[3])
    except ValueError:
        await update.message.reply_text("❌ qty, total aur gap sirf numbers hone chahiye!")
        return

    # Validations
    if "facebook.com" not in link:
        await update.message.reply_text("❌ Valid Facebook Live link daalo!")
        return
    if not (20 <= qty <= 5000):
        await update.message.reply_text("❌ Quantity 20 se 5000 ke beech honi chahiye!")
        return
    if total < 1:
        await update.message.reply_text("❌ Total orders kam se kam 1 hona chahiye!")
        return
    if gap < 5:
        await update.message.reply_text("❌ Gap kam se kam 5 seconds hona chahiye!")
        return

    stop_ev = threading.Event()
    sessions[uid] = {"stop": stop_ev, "placed": 0, "ok": 0, "total": total}

    await update.message.reply_text(
        f"✅ *Session Shuru!*\n\n"
        f"🔗 `{link}`\n"
        f"📦 Qty per order: *{qty}*\n"
        f"🔢 Total orders: *{total}*\n"
        f"⏱ Gap: *{gap}s*\n\n"
        f"_Pehla order place ho raha hai..._",
        parse_mode="Markdown"
    )

    bot_obj = ctx.bot
    chat_id = update.effective_chat.id
    loop    = asyncio.get_event_loop()

    def run_orders():
        ok = 0
        for i in range(1, total + 1):
            if stop_ev.is_set():
                break
            sessions[uid]["placed"] = i
            try:
                d = place_one(link, qty)
                if "order" in d:
                    ok += 1
                    sessions[uid]["ok"] = ok
                    asyncio.run_coroutine_threadsafe(
                        bot_obj.send_message(
                            chat_id=chat_id,
                            text=f"✅ Order #{i}/{total} — ID: `{d['order']}`",
                            parse_mode="Markdown"
                        ), loop
                    )
                elif "error" in d:
                    err = d["error"].lower()
                    if any(w in err for w in ["balance","fund","credit","insufficient"]):
                        asyncio.run_coroutine_threadsafe(
                            bot_obj.send_message(
                                chat_id=chat_id,
                                text="🔴 *Insufficient Balance!*\nFunds add karo aur dobara try karo.",
                                parse_mode="Markdown"
                            ), loop
                        )
                        stop_ev.set()
                        break
                    else:
                        asyncio.run_coroutine_threadsafe(
                            bot_obj.send_message(
                                chat_id=chat_id,
                                text=f"❌ Order #{i} failed: {d['error']}"
                            ), loop
                        )
            except Exception as e:
                asyncio.run_coroutine_threadsafe(
                    bot_obj.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ Order #{i} — Connection error. Next try karega."
                    ), loop
                )

            if i < total and not stop_ev.is_set():
                stop_ev.wait(gap)

        # Final summary
        if stop_ev.is_set():
            summary = f"⏹ *Session Rok di gayi.*\n✅ {ok} orders successful."
        else:
            summary = f"🎉 *Session Complete!*\n✅ {ok} / {total} orders successful."

        asyncio.run_coroutine_threadsafe(
            bot_obj.send_message(chat_id=chat_id, text=summary, parse_mode="Markdown"),
            loop
        )
        sessions.pop(uid, None)

    threading.Thread(target=run_orders, daemon=True).start()

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in sessions:
        sessions[uid]["stop"].set()
        await update.message.reply_text(
            "⏹ *Stop signal bheja gaya.*\n"
            "Current order complete hone ke baad band ho jayega.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("ℹ️ Koi active session nahi hai.")

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in sessions:
        await update.message.reply_text("ℹ️ Koi active session nahi hai.")
        return
    s = sessions[uid]
    running = not s["stop"].is_set()
    pct = int((s["placed"] / s["total"]) * 100) if s["total"] > 0 else 0
    await update.message.reply_text(
        f"📊 *Current Status*\n\n"
        f"{'🟢 Running' if running else '🔴 Stopping...'}\n\n"
        f"📦 Placed: {s['placed']} / {s['total']} ({pct}%)\n"
        f"✅ Successful: {s['ok']}\n"
        f"❌ Failed: {s['placed'] - s['ok']}",
        parse_mode="Markdown"
    )

# ── Flask thread ─────────────────────────────────────────

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)

# ── Main ─────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN environment variable set nahi hai!")
        print("Railway Variables mein BOT_TOKEN add karo.")
        return

    # Flask alag thread mein (Railway port binding ke liye)
    threading.Thread(target=run_flask, daemon=True).start()
    print("✅ Flask server chalu...")

    # Telegram bot
    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start",   cmd_start))
    tg_app.add_handler(CommandHandler("order",   cmd_order))
    tg_app.add_handler(CommandHandler("stop",    cmd_stop))
    tg_app.add_handler(CommandHandler("status",  cmd_status))
    tg_app.add_handler(CommandHandler("balance", cmd_balance))

    print("✅ Telegram bot polling shuru...")
    tg_app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
