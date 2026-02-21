import os
import sqlite3
import asyncio
from datetime import datetime
from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, InputMediaPhoto
)
from pyrogram.errors import ApiIdInvalid, AccessTokenInvalid, BadRequest

# ━━━━━━━━━━━━━━━━━━━━
# ⚙️ CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))  # আপনার টেলিগ্রাম ID এখানে Environment Variable দিয়ে দিন

# ━━━━━━━━━━━━━━━━━━━━
# 🗄️ DATABASE SETUP
# ━━━━━━━━━━━━━━━━━━━━
DB_NAME = "bot_hub.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Main Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    join_date TEXT
                )''')
    
    # Client Bots Table
    c.execute('''CREATE TABLE IF NOT EXISTS client_bots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER,
                    bot_token TEXT,
                    bot_username TEXT,
                    bot_id INTEGER,
                    welcome_text TEXT,
                    welcome_photo TEXT,
                    buttons TEXT,
                    broadcast_admins TEXT,
                    created_at TEXT
                )''')
    
    # Client Bot Users Table (For broadcast)
    c.execute('''CREATE TABLE IF NOT EXISTS bot_users (
                    bot_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (bot_id, user_id)
                )''')
    
    conn.commit()
    conn.close()

init_db()

# ━━━━━━━━━━━━━━━━━━━━
# 🤖 MAIN BOT (CONTROLLER)
# ━━━━━━━━━━━━━━━━━━━━

app = Client("ControlHub", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Dictionary to store temporary states
user_states = {}

# ━━━━━━━━━━━━━━━━━━━━
# 🛠️ HELPER FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━

def get_main_menu():
    keyboard = [
        [KeyboardButton("🤖 আমার বটস"), KeyboardButton("➕ নতুন বট যোগ করুন")],
        [KeyboardButton("📢 ব্রডকাস্ট সেটআপ")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_db():
    conn = sqlite3.connect(DB_NAME)
    return conn

def is_user_registered(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res is not None

def register_user(user_id, first_name, username):
    if not is_user_registered(user_id):
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", 
                  (user_id, first_name, username, str(datetime.now())))
        conn.commit()
        conn.close()
        return True
    return False

# ━━━━━━━━━━━━━━━━━━━━
# 📜 COMMANDS & HANDLERS
# ━━━━━━━━━━━━━━━━━━━━

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    user = message.from_user
    is_new = register_user(user.id, user.first_name, user.username)
    
    text = (
        f"👋 হ্যালো **{user.first_name}**!\n\n"
        f"স্বাগতম **Bot Control Hub**-এ! এখানে আপনি আপনার টেলিগ্রাম বটগুলো নিজের মতো সাজিয়ে নিতে পারবেন, "
        f"ওয়েলকাম মেসেজ ঠিক করতে পারবেন এবং ব্রডকাস্ট করতে পারবেন।\n\n"
        f"নিচের মেনু থেকে যেকোনো অপশন সিলেক্ট করুন:"
    )
    
    if is_new and ADMIN_ID:
        # Notify Admin
        notif_text = (
            f"🔔 **নতুন ইউজার এসেছে!**\n\n"
            f"👤 নাম: {user.first_name}\n"
            f"🆔 ID: `{user.id}`\n"
            f"🌐 Username: @{user.username if user.username else 'N/A'}"
        )
        await client.send_message(ADMIN_ID, notif_text)
        
    await message.reply(text, reply_markup=get_main_menu(), parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.command("help") & filters.private)
async def help_handler(client, message):
    text = (
        "🆘 **সাহায্য গাইড:**\n\n"
        "১. **➕ নতুন বট যোগ করুন:** আপনার বটের টোকেন দিয়ে কানেক্ট করুন।\n"
        "২. **🤖 আমার বটস:** কানেক্ট করা বটগুলো দেখুন এবং এডিট করুন।\n"
        "৩. **📢 ব্রডকাস্ট সেটআপ:** আপনার বটের জন্য ব্রডকাস্ট অ্যাডমিন ঠিক করুন।\n\n"
        "⚠️ মনে রাখবেন, আপনার বটকে এডমিন বা মেম্বার হিসেবে গ্রুপে রাখলে সে সব মেসেজ দেখতে পাবে।"
    )
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("👮 অ্যাডমিনের সাথে যোগাযোগ", url=f"tg://user?id={ADMIN_ID}")]])
    await message.reply(text, reply_markup=buttons, parse_mode=enums.ParseMode.MARKDOWN)

# ━━━━━━━━━━━━━━━━━━━━
# 🚀 ADD NEW BOT FLOW
# ━━━━━━━━━━━━━━━━━━━━

@app.on_message(filters.private & filters.text("➕ নতুন বট যোগ করুন"))
async def add_bot_start(client, message):
    await message.reply("ঠিক আছে! আপনার নতুন বটের **API Token** টি পাঠান।\n\n(example: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)", parse_mode=enums.ParseMode.MARKDOWN)
    user_states[message.from_user.id] = {"step": "wait_token"}

@app.on_message(filters.private & filters.text)
async def text_handler(client, message):
    user_id = message.from_user.id
    text = message.text
    
    # Skip if it's a menu button
    if text in ["🤖 আমার বটস", "➕ নতুন বট যোগ করুন", "📢 ব্রডকাস্ট সেটআপ", "🏠 মেনু"]:
        await handle_menu(client, message)
        return

    if user_id not in user_states:
        return

    state = user_states[user_id]

    # Step 1: Validate Token
    if state.get("step") == "wait_token":
        if ":" not in text:
            await message.reply("❌ টোকেনটি সঠিক নয়! আবার চেষ্টা করুন।")
            return

        try:
            # Verify token temporarily
            temp_bot = Client(":memory:", api_id=API_ID, api_hash=API_HASH, bot_token=text)
            await temp_bot.connect()
            bot_info = await temp_bot.get_me()
            await temp_bot.disconnect()

            # Check if bot already exists
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT 1 FROM client_bots WHERE bot_id = ?", (bot_info.id,))
            if c.fetchone():
                await message.reply("⚠️ এই বটটি ইতিমধ্যে সিস্টেমে আছে!")
                conn.close()
                return
            conn.close()

            state["bot_token"] = text
            state["bot_username"] = bot_info.username
            state["bot_id"] = bot_info.id
            state["step"] = "wait_photo"

            await message.reply(
                f"✅ সফল! বট: @{bot_info.username}\n\n"
                f"এখন ওয়েলকাম মেসেজের জন্য একটি **ছবি** পাঠান।\n"
                f"ছবি ছাড়াই চাইলে 'Skip' লিখুন।",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            await message.reply(f"❌ টোকেন ভ্যালিডেশন ব্যর্থ হয়েছে। ভুল: `{str(e)}`", parse_mode=enums.ParseMode.MARKDOWN)

    # Step 3: Welcome Text
    elif state.get("step") == "wait_text":
        state["welcome_text"] = text
        state["step"] = "wait_button_count"
        await message.reply("✅ টেক্সট সেভ হয়েছে!\n\nএখন বলুন, ওয়েলকাম মেসেজে কয়টি **বাটন** থাকবে? (১ থেকে ৩ এর মধ্যে লিখুন, ০ লিখলে বাটন থাকবে না)")

    # Step 4: Button Count
    elif state.get("step") == "wait_button_count":
        if not text.isdigit() or not (0 <= int(text) <= 3):
            await message.reply("⚠️ দয়া করে ০ থেকে ৩ এর মধ্যে একটি সংখ্যা দিন।")
            return
        
        count = int(text)
        if count == 0:
            await finalize_bot(client, message, user_id, state)
        else:
            state["buttons"] = []
            state["button_count"] = count
            state["current_button_index"] = 1
            state["step"] = "wait_button_name"
            await message.reply(f"১ নম্বর বাটনের **নাম** কী হবে?")

    # Step 5: Button Details
    elif state.get("step") == "wait_button_name":
        state["current_button_name"] = text
        state["step"] = "wait_button_url"
        await message.reply("এই বাটনের **URL** কী?")

    elif state.get("step") == "wait_button_url":
        if not text.startswith("http"):
            await message.reply("⚠️ অবশ্যই একটি সঠিক URL হতে হবে (http/https দিয়ে শুরু)।")
            return

        btn_name = state.pop("current_button_name")
        state["buttons"].append({"name": btn_name, "url": text})
        
        idx = state["current_button_index"]
        total = state["button_count"]

        if idx < total:
            state["current_button_index"] += 1
            state["step"] = "wait_button_name"
            await message.reply(f"{idx + 1} নম্বর বাটনের **নাম** কী হবে?")
        else:
            await finalize_bot(client, message, user_id, state)

    # ━━━ Broadcast Setup ━━━
    elif state.get("step") == "select_bot_for_broadcast":
        # User clicked a bot username from list
        bot_username = text
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM client_bots WHERE owner_id=? AND bot_username=?", (user_id, bot_username))
        bot = c.fetchone()
        conn.close()
        
        if bot:
            state["selected_bot_id"] = bot[0]
            state["step"] = "wait_broadcast_ids"
            await message.reply(
                "📢 ব্রডকাস্ট অ্যাডমিন সেটআপ:\n\n"
                "যাদেরকে ব্রডকাস্ট করার অনুমতি দিতে চান, তাদের **User ID** লিখুন।\n"
                "একাধিক ID হলে কমা (,) দিয়ে আলাদা করুন।\n\n"
                "উদাহরণ: `123456789, 987654321`",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        else:
            await message.reply("⚠️ বট খুঁজে পাওয়া যায়নি।")
            user_states.pop(user_id, None)

    elif state.get("step") == "wait_broadcast_ids":
        try:
            ids = [int(x.strip()) for x in text.split(",")]
            bot_id = state["selected_bot_id"]
            
            conn = get_db()
            c = conn.cursor()
            c.execute("UPDATE client_bots SET broadcast_admins = ? WHERE id = ?", (",".join(map(str, ids)), bot_id))
            conn.commit()
            conn.close()
            
            await message.reply(f"✅ সফলভাবে {len(ids)} জন ব্রডকাস্ট অ্যাডমিন সেট হয়েছে!")
            user_states.pop(user_id, None)
        except ValueError:
            await message.reply("❌ শুধুমাত্র সংখ্যা (ID) ব্যবহার করুন।")

# Handle Photo for Welcome
@app.on_message(filters.private & filters.photo)
async def photo_handler(client, message):
    user_id = message.from_user.id
    if user_id not in user_states or user_states[user_id].get("step") != "wait_photo":
        return
    
    file_id = message.photo.file_id
    user_states[user_id]["welcome_photo"] = file_id
    user_states[user_id]["step"] = "wait_text"
    
    await message.reply("✅ ছবি পাওয়া গেছে!\n\nএখন **ওয়েলকাম টেক্সট** লিখুন:")

async def finalize_bot(client, message, user_id, state):
    conn = get_db()
    c = conn.cursor()
    
    import json
    buttons_json = json.dumps(state.get("buttons", []))
    
    c.execute("""INSERT INTO client_bots 
                 (owner_id, bot_token, bot_username, bot_id, welcome_text, welcome_photo, buttons, created_at) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
              (user_id, state["bot_token"], state["bot_username"], state["bot_id"], 
               state.get("welcome_text", ""), state.get("welcome_photo", ""), 
               buttons_json, str(datetime.now())))
    conn.commit()
    conn.close()
    
    user_states.pop(user_id, None)
    
    # Notify Admin
    if ADMIN_ID:
        await client.send_message(ADMIN_ID, 
            f"🔔 **নতুন বট কানেক্ট হয়েছে!**\n\n"
            f"👤 Owner ID: `{user_id}`\n"
            f"🤖 Bot: @{state['bot_username']}\n"
            f"🆔 Bot ID: `{state['bot_id']}`\n"
            f"🗓 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    
    await message.reply(
        "🎉 **দারুণ! আপনার বট সফলভাবে যোগ হয়েছে!**\n\n"
        "এখন আপনার বটে কেউ `/start` দিলে আপনার কনফিগার করা মেসেজ দেখতে পাবে।",
        reply_markup=get_main_menu()
    )

# ━━━━━━━━━━━━━━━━━━━━
# 🤖 MY BOTS MENU
# ━━━━━━━━━━━━━━━━━━━━

@app.on_message(filters.private & filters.text("🤖 আমার বটস"))
async def my_bots_menu(client, message):
    user_id = message.from_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT bot_username, bot_id FROM client_bots WHERE owner_id = ?", (user_id,))
    bots = c.fetchall()
    conn.close()
    
    if not bots:
        await message.reply("😕 আপনি এখনো কোনো বট যোগ করেননি। '➕ নতুন বট যোগ করুন' চাপুন।")
        return
    
    keyboard = []
    for bot in bots:
        keyboard.append([InlineKeyboardButton(f"🤖 @{bot[0]}", callback_data=f"view_{bot[1]}")])
    
    await message.reply(
        "🤖 **আপনার কানেক্ট করা বটগুলো:**", 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=enums.ParseMode.MARKDOWN
    )

@app.on_callback_query(filters.regex(r"^view_(\d+)"))
async def view_bot_details(client, callback):
    bot_id = int(callback.matches[0].group(1))
    owner_id = callback.from_user.id
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT bot_username, bot_token FROM client_bots WHERE bot_id=? AND owner_id=?", (bot_id, owner_id))
    bot = c.fetchone()
    conn.close()
    
    if not bot:
        await callback.answer("অনুমতি নেই!", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ ওয়েলকাম এডিট", callback_data=f"edit_{bot_id}"),
         InlineKeyboardButton("🗑️ বট ডিলিট", callback_data=f"del_{bot_id}")],
        [InlineKeyboardButton("📊 স্ট্যাটাস", callback_data=f"stats_{bot_id}")]
    ])
    
    # Mask token for security
    token_part = bot[1].split(":")[0] + ":****************"
    
    await callback.message.edit(
        f"**বটের বিবরণ:**\n\n"
        f"🆔 Bot ID: `{bot_id}`\n"
        f"🌐 Username: @{bot[0]}\n"
        f"🔑 Token: `{token_part}`",
        reply_markup=keyboard,
        parse_mode=enums.ParseMode.MARKDOWN
    )

@app.on_callback_query(filters.regex(r"^del_(\d+)"))
async def delete_bot_handler(client, callback):
    bot_id = int(callback.matches[0].group(1))
    owner_id = callback.from_user.id
    
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM client_bots WHERE bot_id=? AND owner_id=?", (bot_id, owner_id))
    conn.commit()
    conn.close()
    
    await callback.answer("✅ বট ডিলিট করা হয়েছে!")
    await callback.message.edit("✅ বটটি সফলভাবে সরিয়ে ফেলা হয়েছে।")

@app.on_callback_query(filters.regex(r"^edit_(\d+)"))
async def edit_welcome_start(client, callback):
    bot_id = int(callback.matches[0].group(1))
    user_id = callback.from_user.id
    
    user_states[user_id] = {"step": "edit_wait_photo", "bot_id": bot_id}
    await callback.message.edit(
        "✏️ **ওয়েলকাম মেসেজ এডিট:**\n\n"
        "নতুন ছবি পাঠান অথবা 'Skip' লিখুন পুরনোটা রাখতে।"
    )

# ━━━━━━━━━━━━━━━━━━━━
# 📢 BROADCAST SETUP FLOW
# ━━━━━━━━━━━━━━━━━━━━

@app.on_message(filters.private & filters.text("📢 ব্রডকাস্ট সেটআপ"))
async def broadcast_setup_start(client, message):
    user_id = message.from_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT bot_username FROM client_bots WHERE owner_id = ?", (user_id,))
    bots = c.fetchall()
    conn.close()
    
    if not bots:
        await message.reply("⚠️ আপনার কোনো বট নেই। প্রথমে একটি বট যোগ করুন।")
        return
        
    keyboard = ReplyKeyboardMarkup([[KeyboardButton(b[0]) for b in bots]], resize_keyboard=True)
    user_states[user_id] = {"step": "select_bot_for_broadcast"}
    await message.reply("📢 কোন বটের জন্য ব্রডকাস্ট সেটআপ করতে চান? নিচ থেকে সিলেক্ট করুন:", reply_markup=keyboard)


# ━━━━━━━━━━━━━━━━━━━━
# 📡 CLIENT BOT WORKER
# ━━━━━━━━━━━━━━━━━━━━

# Dictionary to keep active client instances
active_clients = {}

async def start_client_bot(token):
    if token in active_clients:
        return active_clients[token]
    
    bot = Client(f"bot_{token.split(':')[0]}", api_id=API_ID, api_hash=API_HASH, bot_token=token)
    await bot.start()
    active_clients[token] = bot
    return bot

@app.on_message(filters.private)
async def handle_menu(client, message):
    text = message.text
    if text == "🏠 মেনু":
        await message.reply("🏠 মেনুতে স্বাগতম!", reply_markup=get_main_menu())

# On startup, load all bots and start them
async def load_all_bots():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT bot_token FROM client_bots")
    tokens = c.fetchall()
    conn.close()
    
    print(f"🚀 Starting {len(tokens)} client bots...")
    for t in tokens:
        try:
            await start_client_bot(t[0])
        except Exception as e:
            print(f"Failed to start {t[0]}: {e}")

# Client Bot Handlers (Dynamically attached)
@app.on_message(filters.private & filters.command("start"))
async def client_start_handler(client, message):
    bot_id = client.me.id
    user_id = message.from_user.id
    
    # Save user to bot_users
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO bot_users VALUES (?, ?)", (bot_id, user_id))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # Already exists
    
    # Fetch Welcome Config
    c.execute("SELECT welcome_text, welcome_photo, buttons FROM client_bots WHERE bot_id=?", (bot_id,))
    res = c.fetchone()
    conn.close()
    
    if res:
        text, photo, btns_json = res
        import json
        btns_list = json.loads(btns_json)
        
        markup = None
        if btns_list:
            btns_row = [InlineKeyboardButton(b['name'], url=b['url']) for b in btns_list]
            markup = InlineKeyboardMarkup([btns_row])
            
        try:
            if photo:
                await message.reply_photo(photo, caption=text, reply_markup=markup)
            elif text:
                await message.reply(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception as e:
            await message.reply("⚠️ ওয়েলকাম মেসেজ পাঠাতে সমস্যা হয়েছে।")

    else:
        await message.reply("👋 হ্যালো! আমি একটি বট।")

@app.on_message(filters.private & filters.command("broadcast"))
async def client_broadcast_handler(client, message):
    bot_id = client.me.id
    user_id = message.from_user.id
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT broadcast_admins FROM client_bots WHERE bot_id=?", (bot_id,))
    res = c.fetchone()
    conn.close()
    
    if not res or not res[0]:
        await message.reply("⚠️ ব্রডকাস্ট সেটআপ করা হয়নি।")
        return
        
    admin_ids = [int(x) for x in res[0].split(",")]
    
    if user_id not in admin_ids:
        await message.reply("🚫 আপনার ব্রডকাস্ট করার অনুমতি নেই।")
        return
    
    # Start Broadcast Flow
    user_states[user_id] = {"step": "bc_photo", "bot_id": bot_id, "client": client}
    await message.reply("📢 **ব্রডকাস্ট শুরু!**\n\nপ্রথমে একটি ছবি পাঠান অথবা 'Skip' লিখুন।")

# Handle Broadcast Steps (Generic Handler for client bots)
# We need a global message handler to intercept text/photos for client bots during setup
# Since Pyrogram handles updates per client, we need to register these on the main app logic
# but checking the state.

# Extending the main text/photo handlers to cover client bot states

async def handle_broadcast_step(client, message, state_data):
    user_id = message.from_user.id
    step = state_data.get("step")
    
    if step == "bc_photo":
        if message.photo:
            state_data["photo"] = message.photo.file_id
        elif message.text and message.text.lower() == "skip":
            state_data["photo"] = None
        else:
            # If user sent text instead of photo for bc_photo step, treat as skip photo and take as text
            # Or strictly ask for photo. Let's allow skipping.
            if message.text:
                state_data["photo"] = None
                # Process text immediately as next step
                state_data["text"] = message.text
                state_data["step"] = "bc_button"
                await message.reply("✅ টেক্সট সেভ হয়েছে। এখন বাটনের নাম ও URL লিখুন (ফরম্যাট: `নাম - URL`) অথবা 'Skip' লিখুন।")
                return
            else:
                await message.reply("ছবি পাঠান বা 'Skip' লিখুন।")
                return

        state_data["step"] = "bc_text"
        await message.reply("✏️ এখন টেক্সট বা ক্যাপশন লিখুন:")
    
    elif step == "bc_text":
        if message.text:
            state_data["text"] = message.text
            state_data["step"] = "bc_button"
            await message.reply("🔗 বাটন যোগ করতে চাইলে লিখুন (ফরম্যাট: `নাম - URL`)।\nবাটন ছাড়াই পাঠাতে 'Skip' লিখুন।")
        else:
            await message.reply("⚠️ শুধুমাত্র টেক্সট পাঠান।")

    elif step == "bc_button":
        btn = None
        if message.text and message.text.lower() != "skip" and " - " in message.text:
            parts = message.text.split(" - ", 1)
            if len(parts) == 2 and parts[1].startswith("http"):
                btn = {"name": parts[0], "url": parts[1]}
        
        state_data["button"] = btn
        state_data["step"] = "bc_confirm"
        
        preview_text = state_data.get("text", "")
        preview_photo = state_data.get("photo")
        markup = None
        if btn:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn['name'], url=btn['url'])]])
        
        await message.reply("👁️ **প্রিভিউ:**", parse_mode=enums.ParseMode.MARKDOWN)
        if preview_photo:
            await message.reply_photo(preview_photo, caption=preview_text, reply_markup=markup)
        elif preview_text:
            await message.reply(preview_text, reply_markup=markup, disable_web_page_preview=True)
        
        state_data["step"] = "bc_send"
        await message.reply("👆 ঠিক আছে?\n\nহ্যাঁ হলে **'Send'** লিখুন। বাতিল করতে **'Cancel'** লিখুন।")

    elif step == "bc_send":
        if message.text and message.text.lower() == "send":
            await message.reply("🚀 ব্রডকাস্ট শুরু হচ্ছে...")
            await perform_broadcast(state_data)
            await message.reply("✅ ব্রডকাস্ট সম্পন্ন!")
            user_states.pop(user_id, None)
        else:
            await message.reply("❌ ব্রডকাস্ট বাতিল করা হয়েছে।")
            user_states.pop(user_id, None)

async def perform_broadcast(state):
    bot_id = state["bot_id"]
    text = state.get("text")
    photo = state.get("photo")
    btn = state.get("button")
    bot_client = state.get("client")
    
    markup = None
    if btn:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn['name'], url=btn['url'])]])
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM bot_users WHERE bot_id = ?", (bot_id,))
    users = c.fetchall()
    conn.close()
    
    count = 0
    for u in users:
        try:
            if photo:
                await bot_client.send_photo(u[0], photo, caption=text, reply_markup=markup)
            elif text:
                await bot_client.send_message(u[0], text, reply_markup=markup, disable_web_page_preview=True)
            count += 1
            await asyncio.sleep(0.05) # Avoid flood
        except Exception:
            continue
            
    # Log to console
    print(f"Broadcast sent to {count} users for bot {bot_id}")

# Patching Pyrogram to handle updates for client bots and routing them
# Since we are running multiple clients, we need to register a common handler.
# We can attach a handler to the main app that forwards updates? No, Pyrogram supports multiple clients.
# We iterate and start them.
# We need to register the logic for ALL clients. We will use a decorator wrapper.

def setup_handlers(client):
    @client.on_message(filters.private & filters.command("start"))
    async def _(c, m):
        await client_start_handler(c, m)
        
    @client.on_message(filters.private & filters.command("broadcast"))
    async def _(c, m):
        await client_broadcast_handler(c, m)
        
    @client.on_message(filters.private)
    async def _(c, m):
        user_id = m.from_user.id
        if user_id in user_states and "client" in user_states[user_id]:
            # It's a client bot flow
            if user_states[user_id]["client"] == c:
                await handle_broadcast_step(c, m, user_states[user_id])
        # else: ignore generic text in client bots

# ━━━━━━━━━━━━━━━━━━━━
# 🏃‍♂️ RUNNER
# ━━━━━━━━━━━━━━━━━━━━

print("🤖 Bot Control Hub is starting...")

# Load existing bots on startup
async def main():
    async with app:
        print("✅ Main Controller is online.")
        
        # Load DB bots
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT bot_token FROM client_bots")
        tokens = c.fetchall()
        conn.close()
        
        for t in tokens:
            try:
                bot = Client(f"bot_{t[0].split(':')[0]}", api_id=API_ID, api_hash=API_HASH, bot_token=t[0])
                setup_handlers(bot)
                await bot.start()
                active_clients[t[0]] = bot
                print(f"✅ Client Bot started: {t[0][:10]}...")
            except Exception as e:
                print(f"❌ Failed to start client {t[0][:10]}: {e}")
        
        await asyncio.Event().wait()

app.run(main())
