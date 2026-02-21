import logging
import sqlite3
import json
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    Application
)
from telegram.error import InvalidToken, TelegramError

# --- CONFIGURATION & LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('bot_hub.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS hub_users (user_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS client_bots (
                 bot_token TEXT PRIMARY KEY,
                 owner_id INTEGER,
                 bot_username TEXT,
                 welcome_text TEXT,
                 welcome_image_id TEXT,
                 buttons_json TEXT,
                 broadcast_admins TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_subscribers (
                 bot_token TEXT,
                 user_id INTEGER,
                 PRIMARY KEY (bot_token, user_id))''')
    conn.commit()
    conn.close()

init_db()

# --- CONSTANTS ---
WAITING_TOKEN, WAITING_IMAGE, WAITING_TEXT, WAITING_BUTTON_COUNT, WAITING_BUTTON_DATA, WAITING_BC_ADMINS = range(6)
BC_IMAGE, BC_TEXT, BC_BUTTON, BC_CONFIRM = range(10, 14)

# --- HELPER FUNCTIONS ---
def get_db():
    return sqlite3.connect('bot_hub.db')

def save_bot(data):
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO client_bots 
                 (bot_token, owner_id, bot_username, welcome_text, welcome_image_id, buttons_json) 
                 VALUES (?, ?, ?, ?, ?, ?)''', 
              (data['token'], data['owner'], data['username'], data['text'], data.get('image'), json.dumps(data['buttons'])))
    conn.commit()
    conn.close()

# --- CLIENT BOT LOGIC ---
client_apps = {}

async def client_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = context.bot.token
    user_id = update.effective_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO bot_subscribers (bot_token, user_id) VALUES (?, ?)", (token, user_id))
    c.execute("SELECT welcome_text, welcome_image_id, buttons_json FROM client_bots WHERE bot_token = ?", (token,))
    bot_data = c.fetchone()
    conn.commit()
    conn.close()

    if bot_data:
        text, image_id, buttons_raw = bot_data
        buttons = json.loads(buttons_raw)
        keyboard = [[InlineKeyboardButton(btn['name'], url=btn['url'])] for btn in buttons]
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        if image_id:
            await update.message.reply_photo(photo=image_id, caption=text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text=text, reply_markup=reply_markup)

async def client_broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = context.bot.token
    user_id = update.effective_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT owner_id, broadcast_admins FROM client_bots WHERE bot_token = ?", (token,))
    res = c.fetchone()
    conn.close()
    if not res: return ConversationHandler.END
    owner_id, admins_str = res
    allowed_admins = [int(x.strip()) for x in admins_str.split(',')] if admins_str else []
    allowed_admins.append(owner_id)
    if user_id not in allowed_admins:
        await update.message.reply_text("🚫 দুঃখিত! আপনার এই কমান্ড ব্যবহার করার অনুমতি নেই।")
        return ConversationHandler.END
    await update.message.reply_text("📢 ব্রডকাস্টিং শুরু করছি...\nপ্রথমে একটি ছবি দিন (অথবা স্কিপ করতে /skip লিখুন):")
    return BC_IMAGE

async def bc_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bc_img'] = update.message.photo[-1].file_id if update.message.photo else None
    await update.message.reply_text("এখন ব্রডকাস্ট মেসেজটি লিখুন:")
    return BC_TEXT

async def bc_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bc_txt'] = update.message.text
    await update.message.reply_text("একটি বাটন যোগ করতে চান? (Format: Name | URL) অথবা স্কিপ করতে /skip লিখুন:")
    return BC_BUTTON

async def bc_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if val and val.lower() != '/skip' and '|' in val:
        name, url = val.split('|')
        context.user_data['bc_btn'] = {'name': name.strip(), 'url': url.strip()}
    else:
        context.user_data['bc_btn'] = None
    await update.message.reply_text("সব ঠিক আছে? ব্রডকাস্ট শুরু করতে 'YES' লিখুন।")
    return BC_CONFIRM

async def bc_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.upper() != 'YES':
        await update.message.reply_text("ব্রডকাস্ট বাতিল করা হয়েছে।")
        return ConversationHandler.END
    token = context.bot.token
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM bot_subscribers WHERE bot_token = ?", (token,))
    users = c.fetchall()
    conn.close()
    img = context.user_data.get('bc_img')
    txt = context.user_data.get('bc_txt')
    btn = context.user_data.get('bc_btn')
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(btn['name'], url=btn['url'])]]) if btn else None
    count = 0
    for (uid,) in users:
        try:
            if img: await context.bot.send_photo(uid, photo=img, caption=txt, reply_markup=kb)
            else: await context.bot.send_message(uid, text=txt, reply_markup=kb)
            count += 1
        except: continue
    await update.message.reply_text(f"✅ সফলভাবে {count} জন ইউজারের কাছে মেসেজ পাঠানো হয়েছে!")
    return ConversationHandler.END

async def run_client_bot(token):
    try:
        app = ApplicationBuilder().token(token).build()
        bc_handler = ConversationHandler(
            entry_points=[CommandHandler('broadcast', client_broadcast_cmd)],
            states={
                BC_IMAGE: [MessageHandler(filters.PHOTO | filters.TEXT, bc_image)],
                BC_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bc_text)],
                BC_BUTTON: [MessageHandler(filters.TEXT, bc_button)],
                BC_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, bc_confirm)],
            },
            fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
        )
        app.add_handler(CommandHandler('start', client_start))
        app.add_handler(bc_handler)
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        client_apps[token] = app
        return True
    except: return False

# --- MAIN HUB LOGIC ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO hub_users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()
    text = "👋 আসসালামু আলাইকুম! **Bot Control Hub**-এ স্বাগতম।\nনিচের মেনু থেকে একটি অপশন বেছে নিন।"
    keyboard = [[KeyboardButton("🤖 My Bots"), KeyboardButton("➕ Add New Bot")],
                [KeyboardButton("📢 Broadcast Setup"), KeyboardButton("❓ Help")]]
    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode='Markdown')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🆘 সাহায্য প্রয়োজন হলে @AdminUsername এ নক দিন।")

async def add_bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 আপনার বোটের **Bot Token** টি পাঠান:")
    return WAITING_TOKEN

async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text
    try:
        temp_app = ApplicationBuilder().token(token).build()
        bot_info = await temp_app.bot.get_me()
        context.user_data['new_bot'] = {'token': token, 'username': bot_info.username, 'owner': update.effective_user.id, 'buttons': []}
        await update.message.reply_text(f"✅ বোট: @{bot_info.username}\nএখন একটি **Welcome Image** পাঠান (অথবা /skip):")
        return WAITING_IMAGE
    except:
        await update.message.reply_text("❌ টোকেন সঠিক নয়।")
        return WAITING_TOKEN

async def handle_welcome_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_bot']['image'] = update.message.photo[-1].file_id if update.message.photo else None
    await update.message.reply_text("এখন বোটের জন্য একটি **Welcome Text** লিখুন:")
    return WAITING_TEXT

async def handle_welcome_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_bot']['text'] = update.message.text
    await update.message.reply_text("বাটন সংখ্যা দিন (০-৩):")
    return WAITING_BUTTON_COUNT

async def handle_button_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        count = int(update.message.text)
        context.user_data['btn_count'] = count
        context.user_data['current_btn'] = 1
        if count == 0:
            save_bot(context.user_data['new_bot'])
            asyncio.create_task(run_client_bot(context.user_data['new_bot']['token']))
            await update.message.reply_text("🎉 বোট সেটআপ সফল!")
            return ConversationHandler.END
        await update.message.reply_text(f"বাটন ১-এর তথ্য দিন (Name | URL):")
        return WAITING_BUTTON_DATA
    except: await update.message.reply_text("সংখ্যা দিন।")

async def handle_button_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if '|' not in text: return WAITING_BUTTON_DATA
    name, url = text.split('|')
    context.user_data['new_bot']['buttons'].append({'name': name.strip(), 'url': url.strip()})
    if context.user_data['current_btn'] < context.user_data['btn_count']:
        context.user_data['current_btn'] += 1
        await update.message.reply_text(f"বাটন {context.user_data['current_btn']}-এর তথ্য দিন:")
        return WAITING_BUTTON_DATA
    else:
        save_bot(context.user_data['new_bot'])
        asyncio.create_task(run_client_bot(context.user_data['new_bot']['token']))
        await update.message.reply_text("🎉 বোট সেটআপ সফল!")
        return ConversationHandler.END

async def my_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT bot_username FROM client_bots WHERE owner_id = ?", (update.effective_user.id,))
    bots = c.fetchall(); conn.close()
    if not bots: await update.message.reply_text("কোনো বোট নেই।")
    else: await update.message.reply_text("🤖 আপনার বোটসমূহ:\n" + "\n".join([f"@{b[0]}" for b in bots]))

async def bc_setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT bot_username, bot_token FROM client_bots WHERE owner_id = ?", (update.effective_user.id,))
    bots = c.fetchall(); conn.close()
    if not bots: return await update.message.reply_text("বোট নেই।")
    kb = [[InlineKeyboardButton(f"@{b[0]}", callback_data=f"bcsetup_{b[1][:10]}")] for b in bots]
    await update.message.reply_text("বোট বেছে নিন:", reply_markup=InlineKeyboardMarkup(kb))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data.startswith("bcsetup_"):
        context.user_data['target_bot_short'] = query.data.split("_")[1]
        await query.edit_message_text("Broadcast Admin User IDs দিন (কমা দিয়ে):")
        return WAITING_BC_ADMINS

async def save_bc_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_ids = update.message.text
    short = context.user_data.get('target_bot_short')
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE client_bots SET broadcast_admins = ? WHERE bot_token LIKE ?", (admin_ids, f"{short}%"))
    conn.commit(); conn.close()
    await update.message.reply_text("✅ আপডেট সফল!")
    return ConversationHandler.END

async def startup_client_bots():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT bot_token FROM client_bots")
    bots = c.fetchall(); conn.close()
    for (token,) in bots: asyncio.create_task(run_client_bot(token))

def main():
    # এখানে আপনার মেইন বোটের টোকেনটি দিন
    HUB_TOKEN = "8250934004:AAEA5kjsPS5tU0m2OR79g6XdzW70xMBtbYo"
    app = ApplicationBuilder().token(HUB_TOKEN).build()
    
    add_bot_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('➕ Add New Bot'), add_bot_start)],
        states={
            WAITING_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_token)],
            WAITING_IMAGE: [MessageHandler(filters.PHOTO | filters.COMMAND, handle_welcome_image)],
            WAITING_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_welcome_text)],
            WAITING_BUTTON_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_count)],
            WAITING_BUTTON_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_data)],
        },
        fallbacks=[CommandHandler('cancel', start)]
    )

    bc_setup_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('📢 Broadcast Setup'), bc_setup_start)],
        states={WAITING_BC_ADMINS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_bc_admins)]},
        fallbacks=[CommandHandler('cancel', start)]
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.Regex('🤖 My Bots'), my_bots))
    app.add_handler(MessageHandler(filters.Regex('❓ Help'), help_cmd))
    app.add_handler(add_bot_conv)
    app.add_handler(bc_setup_conv)
    app.add_handler(CallbackQueryHandler(handle_callback))

    asyncio.get_event_loop().create_task(startup_client_bots())
    app.run_polling()

if __name__ == '__main__':
    main()
