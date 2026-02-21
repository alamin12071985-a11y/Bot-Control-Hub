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
    CallbackQuery_handlers,
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
    # Main Hub Users
    c.execute('''CREATE TABLE IF NOT EXISTS hub_users (user_id INTEGER PRIMARY KEY)''')
    # Client Bots
    c.execute('''CREATE TABLE IF NOT EXISTS client_bots (
                 bot_token TEXT PRIMARY KEY,
                 owner_id INTEGER,
                 bot_username TEXT,
                 welcome_text TEXT,
                 welcome_image_id TEXT,
                 buttons_json TEXT,
                 broadcast_admins TEXT)''')
    # Subscribers of Client Bots
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

# --- CLIENT BOT LOGIC (DYNAMIC) ---
client_apps = {}

async def client_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = context.bot.token
    user_id = update.effective_user.id
    
    # Register subscriber
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO bot_subscribers (bot_token, user_id) VALUES (?, ?)", (token, user_id))
    
    # Get Config
    c.execute("SELECT welcome_text, welcome_image_id, buttons_json FROM client_bots WHERE bot_token = ?", (token,))
    bot_data = c.fetchone()
    conn.commit()
    conn.close()

    if bot_data:
        text, image_id, buttons_raw = bot_data
        buttons = json.loads(buttons_raw)
        keyboard = []
        for btn in buttons:
            keyboard.append([InlineKeyboardButton(btn['name'], url=btn['url'])])
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
    
    if not res: return
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
    if val.lower() != '/skip' and '|' in val:
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
    except Exception as e:
        logger.error(f"Error starting client bot {token}: {e}")
        return False

# --- MAIN HUB LOGIC ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO hub_users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()
    
    text = (
        "👋 আসসালামু আলাইকুম! **Bot Control Hub**-এ আপনাকে স্বাগতম।\n\n"
        "আমি আপনাকে আপনার নিজস্ব টেলিগ্রাম বোট সেটআপ এবং কন্ট্রোল করতে সাহায্য করবো। "
        "নিচের মেনু থেকে একটি অপশন বেছে নিন।"
    )
    keyboard = [
        [KeyboardButton("🤖 My Bots"), KeyboardButton("➕ Add New Bot")],
        [KeyboardButton("📢 Broadcast Setup"), KeyboardButton("❓ Help")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 সাহায্য প্রয়োজন?\n\n"
        "১. নতুন বোট যোগ করতে 'Add New Bot' বাটনে ক্লিক করুন।\n"
        "২. বোটের টোকেন দিন এবং সেটআপ শেষ করুন।\n"
        "৩. আপনার বোটে ইউজারদের মেসেজ পাঠাতে Broadcast ব্যবহার করুন।\n\n"
        "যেকোনো প্রয়োজনে যোগাযোগ করুন: @AdminUsername",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Contact Admin", url="https://t.me/your_admin_link")]])
    )

async def add_bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 চমৎকার! আপনার নতুন বোটের **Bot Token** টি এখানে পাঠান।\n(এটি আপনি @BotFather থেকে পাবেন)")
    return WAITING_TOKEN

async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text
    try:
        temp_app = ApplicationBuilder().token(token).build()
        bot_info = await temp_app.bot.get_me()
        context.user_data['new_bot'] = {
            'token': token, 
            'username': bot_info.username,
            'owner': update.effective_user.id,
            'buttons': []
        }
        await update.message.reply_text(f"✅ বোট পাওয়া গেছে: @{bot_info.username}\n\nএখন একটি **Welcome Image** পাঠান (অথবা স্কিপ করতে /skip লিখুন):")
        return WAITING_IMAGE
    except (InvalidToken, TelegramError):
        await update.message.reply_text("❌ উফ! টোকেনটি সঠিক নয়। দয়া করে সঠিক টোকেনটি আবার পাঠান।")
        return WAITING_TOKEN

async def handle_welcome_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data['new_bot']['image'] = update.message.photo[-1].file_id
    else:
        context.user_data['new_bot']['image'] = None
    
    await update.message.reply_text("চমৎকার! এখন বোটের জন্য একটি **Welcome Text** লিখুন:")
    return WAITING_TEXT

async def handle_welcome_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_bot']['text'] = update.message.text
    await update.message.reply_text("আপনার বোটে কয়টি বাটন যোগ করতে চান? (১ থেকে ৩ এর মধ্যে সংখ্যা দিন, অথবা ০ দিন):")
    return WAITING_BUTTON_COUNT

async def handle_button_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        count = int(update.message.text)
        if 0 <= count <= 3:
            context.user_data['btn_count'] = count
            context.user_data['current_btn'] = 1
            if count == 0:
                save_bot(context.user_data['new_bot'])
                asyncio.create_task(run_client_bot(context.user_data['new_bot']['token']))
                await update.message.reply_text("🎉 অভিনন্দন! আপনার বোটটি সফলভাবে সেটআপ হয়েছে।")
                return ConversationHandler.END
            await update.message.reply_text(f"বাটন ১-এর নাম এবং লিঙ্ক দিন।\nFormat: Name | URL")
            return WAITING_BUTTON_DATA
        else:
            await update.message.reply_text("দয়া করে ১ থেকে ৩ এর মধ্যে একটি সংখ্যা দিন।")
    except ValueError:
        await update.message.reply_text("ভুল ইনপুট! সংখ্যা দিন।")

async def handle_button_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if '|' not in text:
        await update.message.reply_text("ভুল ফরম্যাট! (Name | URL) এভাবে দিন।")
        return WAITING_BUTTON_DATA
    
    name, url = text.split('|')
    context.user_data['new_bot']['buttons'].append({'name': name.strip(), 'url': url.strip()})
    
    curr = context.user_data['current_btn']
    total = context.user_data['btn_count']
    
    if curr < total:
        context.user_data['current_btn'] += 1
        await update.message.reply_text(f"বাটন {curr+1}-এর নাম এবং লিঙ্ক দিন।")
        return WAITING_BUTTON_DATA
    else:
        save_bot(context.user_data['new_bot'])
        asyncio.create_task(run_client_bot(context.user_data['new_bot']['token']))
        await update.message.reply_text("🎉 অভিনন্দন! আপনার বোটটি সফলভাবে সেটআপ হয়েছে।")
        return ConversationHandler.END

async def my_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT bot_username, bot_token FROM client_bots WHERE owner_id = ?", (update.effective_user.id,))
    bots = c.fetchall()
    conn.close()
    
    if not bots:
        await update.message.reply_text("আপনার কোনো বোট এখনও যুক্ত করা নেই।")
        return
    
    msg = "🤖 **আপনার বোটসমূহ:**\n\n"
    keyboard = []
    for username, token in bots:
        msg += f"🔹 @{username}\n"
        keyboard.append([InlineKeyboardButton(f"⚙️ Manage @{username}", callback_data=f"manage_{token[:10]}")])
    
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def bc_setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT bot_username, bot_token FROM client_bots WHERE owner_id = ?", (update.effective_user.id,))
    bots = c.fetchall()
    conn.close()
    
    if not bots:
        await update.message.reply_text("আগে একটি বোট যুক্ত করুন।")
        return
    
    kb = [[InlineKeyboardButton(f"@{b[0]}", callback_data=f"bcsetup_{b[1][:10]}")] for b in bots]
    await update.message.reply_text("কোন বোটের জন্য ব্রডকাস্ট এডমিন সেটআপ করতে চান?", reply_markup=InlineKeyboardMarkup(kb))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("bcsetup_"):
        short_token = query.data.split("_")[1]
        context.user_data['target_bot_short'] = short_token
        await query.edit_message_text("যাদের ব্রডকাস্ট করার অনুমতি দিতে চান তাদের Telegram User ID কমা (,) দিয়ে আলাদা করে লিখুন:\n(যেমন: 123456, 789101)")
        return WAITING_BC_ADMINS
    
    if query.data.startswith("manage_"):
        short_token = query.data.split("_")[1]
        # In a real app, you'd match full token via DB. Simplified here.
        await query.edit_message_text("বোট ম্যানেজমেন্ট ফিচারটি শীঘ্রই আসছে! আপাতত ডিলিট করতে চাইলে এডমিনের সাহায্য নিন।")

async def save_bc_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_ids = update.message.text
    short_token = context.user_data.get('target_bot_short')
    
    conn = get_db()
    c = conn.cursor()
    # Find full token by partial match (simple logic for example)
    c.execute("UPDATE client_bots SET broadcast_admins = ? WHERE bot_token LIKE ?", (admin_ids, f"{short_token}%"))
    conn.commit()
    conn.close()
    
    await update.message.reply_text("✅ ব্রডকাস্ট এডমিন লিস্ট আপডেট করা হয়েছে!")
    return ConversationHandler.END

# --- MAIN RUNNER ---
async def startup_client_bots():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT bot_token FROM client_bots")
    bots = c.fetchall()
    conn.close()
    for (token,) in bots:
        asyncio.create_task(run_client_bot(token))

def main():
    # Replace 'YOUR_HUB_BOT_TOKEN' with your main Hub Token
    HUB_TOKEN = "YOUR_HUB_BOT_TOKEN" 
    app = ApplicationBuilder().token(HUB_TOKEN).build()

    # Add Bot Conv
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

    # Broadcast Setup Conv
    bc_setup_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('📢 Broadcast Setup'), bc_setup_start)],
        states={
            WAITING_BC_ADMINS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_bc_admins)],
        },
        fallbacks=[CommandHandler('cancel', start)],
        allow_reentry=True
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(MessageHandler(filters.Regex('🤖 My Bots'), my_bots))
    app.add_handler(MessageHandler(filters.Regex('❓ Help'), help_cmd))
    app.add_handler(add_bot_conv)
    app.add_handler(bc_setup_conv)
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Run client bots
    loop = asyncio.get_event_loop()
    loop.create_task(startup_client_bots())

    print("Hub Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
