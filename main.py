import asyncio
import logging
import sqlite3
import datetime
import os
from contextlib import suppress
from typing import List, Dict, Optional, Any

from aiogram import Router, F, Bot, Dispatcher, types, filters
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, InputFile, FSInputFile, URLInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

# --- Configuration ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "123456789") # Comma separated

if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

ADMIN_IDS = [int(id.strip()) for id in ADMIN_IDS_STR.split(",") if id.strip().isdigit()]

# --- Database Setup (SQLite) ---
DB_NAME = "bot_control_hub.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        # Main Bot Users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                join_date TEXT
            )
        ''')

        # Force Join Channels
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                channel_id INTEGER PRIMARY KEY,
                channel_title TEXT,
                channel_link TEXT
            )
        ''')

        # Client Bots connected by users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS client_bots (
                bot_id INTEGER PRIMARY KEY,
                owner_id INTEGER,
                bot_token TEXT,
                bot_username TEXT,
                welcome_text TEXT,
                welcome_img_id TEXT,
                buttons_json TEXT,
                created_at TEXT
            )
        ''')

        # Users for each client bot (for broadcast)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS client_bot_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER,
                user_id INTEGER,
                joined_at TEXT,
                UNIQUE(bot_id, user_id)
            )
        ''')

        # Broadcast Admins for client bots
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS broadcast_admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER,
                user_id INTEGER,
                UNIQUE(bot_id, user_id)
            )
        ''')
        conn.commit()

# Call DB Init
init_db()

# --- Helpers ---
def get_db():
    return sqlite3.connect(DB_NAME)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# --- FSM States ---
class Form(StatesGroup):
    # Add Bot Flow
    add_bot_token = State()
    add_bot_img = State()
    add_bot_text = State()
    add_btn_count = State()
    add_btn_name = State()
    add_btn_url = State()
    
    # Broadcast Setup
    select_bot_broadcast = State()
    set_broadcast_admins = State()
    
    # Client Bot Broadcast
    client_broadcast_msg = State()
    client_broadcast_confirm = State()

    # Admin Broadcast
    admin_broadcast_msg = State()
    admin_broadcast_confirm = State()
    
    # Admin Channel Mgmt
    add_channel_link = State()

# --- Keyboards ---
def get_main_keyboard():
    kb = [
        [KeyboardButton(text="🤖 আমার বটস"), KeyboardButton(text="➕ নতুন বট যোগ করুন")],
        [KeyboardButton(text="📢 ব্রডকাস্ট সেটআপ"), KeyboardButton(text="📞 এডমিন যোগাযোগ")],
        [KeyboardButton(text="ℹ️ সাহায্য")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_admin_keyboard():
    kb = [
        [KeyboardButton(text="📊 স্ট্যাটাস"), KeyboardButton(text="📢 ইউজার ব্রডকাস্ট")],
        [KeyboardButton(text="📺 চ্যানেল ম্যানেজ"), KeyboardButton(text="🔙 মেনুতে ফিরুন")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_back_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ বাতিল করুন")]], resize_keyboard=True)

def get_skip_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⏭️ স্কিপ করুন")]], resize_keyboard=True)

# --- Main Router ---
router = Router()

# --- Global Middleware for Force Join ---
@router.message()
async def check_subscription(message: Message, state: FSMContext):
    # Allow admins always
    if is_admin(message.from_user.id):
        return
    
    # Check if in a flow (FSM state active)
    current_state = await state.get_state()
    if current_state is not None:
        return # Let the specific handler deal with it, or assume they are already verified

    # Check DB for channels
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_title, channel_link FROM channels")
    channels = cursor.fetchall()
    conn.close()

    if not channels:
        return # No channels required

    # We need the bot instance to check membership. 
    # Since we use `router`, we don't have `bot` directly injected in message middleware like in dp.message.
    # But we can access it via message.bot
    
    not_joined = []
    for ch_id, title, link in channels:
        try:
            member = await message.bot.get_chat_member(ch_id, message.from_user.id)
            if member.status in ["left", "kicked"]:
                not_joined.append((ch_id, title, link))
        except TelegramAPIError:
            # If bot not in channel or error, skip check to avoid spam
            continue

    if not_joined:
        # Build Force Join Keyboard
        buttons = []
        for _, title, link in not_joined:
            buttons.append([InlineKeyboardButton(text=f"➡️ {title}", url=link)])
        buttons.append([InlineKeyboardButton(text="✅ আমি জয়েন করেছি", callback_data="check_subs")])
        
        text = (
            "😡 এই একটু থামুন!\n\n"
            "আপনি আমাদের নির্দিষ্ট চ্যানেলে জয়েন করেননি। বট ব্যবহার করতে হলে আগে নিচের চ্যানেলে জয়েন হন, "
            "তারপর 'আমি জয়েন করেছি' বাটনে ক্লিক করুন!\n\n"
            "এটা আমাদের নিয়ম, ভালো থাকার জন্যই! 😉"
        )
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return False # Stop further processing
    
    return True

# --- Handlers: Start & Help ---
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    # Register User
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, join_date) VALUES (?, ?, ?, ?)",
                   (message.from_user.id, message.from_user.username, message.from_user.first_name, str(datetime.datetime.now())))
    conn.commit()
    conn.close()

    # Check Admin
    if is_admin(message.from_user.id):
        await message.answer(
            "👋 স্বাগতম মহামান্য এডমিন!\n\nআপনাকে দেখে খুব খুশি হলাম। আজ কি করবেন? নিচের প্যানেল থেকে বেছে নিন! 😎",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "🤖 **Bot Control Hub**-এ স্বাগতম!\n\n"
            "এখানে আপনি আপনার নিজের টেলিগ্রাম বট যোগ করতে পারবেন, সুন্দর সুন্দর ওয়েলকাম মেসেজ সেট করতে পারবেন এবং "
            "ব্রডকাস্ট পরিচালনা করতে পারবেন। সব মিলিয়ে এক ম্যানেজমেন্ট সেন্টার! 😍\n\n"
            "নিচের মেনু থেকে কাজ শুরু করুন:",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )

@router.message(Command("help"))
@router.message(F.text == "ℹ️ সাহায্য")
async def cmd_help(message: Message):
    text = (
        "🆘 **সাহায্য গাইড:**\n\n"
        "1. **নতুন বট যোগ:** আপনার বটের টোকেন দিয়ে এখানে কানেক্ট করুন।\n"
        "2. **ওয়েলকাম মেসেজ:** ইমেজ, টেক্সট ও বাটন দিয়ে সাজিয়ে নিন।\n"
        "3. **ব্রডকাস্ট:** আপনার বটের ইউজারদের মেসেজ পাঠান।\n\n"
        "কোনো সমস্যা হলে এডমিনের সাথে যোগাযোগ করুন।"
    )
    buttons = [[InlineKeyboardButton(text="📞 এডমিন যোগাযোগ", url="tg://user?id=123456789")]] # Replace with dynamic if needed
    await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# --- Handler: Back to Menu ---
@router.message(F.text == "🔙 মেনুতে ফিরুন")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("মেনুতে ফিরে এলাম! 😊", reply_markup=get_admin_keyboard())
    else:
        await message.answer("মেনুতে ফিরে এলাম! 😊", reply_markup=get_main_keyboard())

# --- Flow: Add New Bot ---
@router.message(F.text == "➕ নতুন বট যোগ করুন")
async def add_bot_start(message: Message, state: FSMContext):
    await message.answer(
        "🤖 চলুন নতুন বট যোগ করি!\n\n"
        "প্রথমে আপনার বটের **API Token** টি পাঠান।\n"
        "(টোকেন পাবেন @BotFather থেকে)",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(Form.add_bot_token)

@router.message(Form.add_bot_token)
async def process_token(message: Message, state: FSMContext):
    if message.text == "❌ বাতিল করুন":
        await state.clear()
        await message.answer("বাতিল করা হলো।", reply_markup=get_main_keyboard())
        return

    token = message.text
    try:
        # Validate token
        new_bot = Bot(token=token)
        bot_info = await new_bot.get_me()
        await new_bot.session.close()
        
        # Save to state
        await state.update_data(token=token, bot_id=bot_info.id, bot_username=bot_info.username)
        
        await message.answer(
            f"✅ বট পাওয়া গেছে: @{bot_info.username}\n\n"
            "এখন ওয়েলকাম মেসেজের জন্য একটি ছবি পাঠান।\n"
            "অথবা 'স্কিপ' করুন।",
            reply_markup=get_skip_keyboard()
        )
        await state.set_state(Form.add_bot_img)
    except Exception as e:
        await message.answer("❌ অবৈধ টোকেন! আবার চেষ্টা করুন অথবা বাতিল করুন।")

@router.message(Form.add_bot_img)
async def process_image(message: Message, state: FSMContext):
    img_id = None
    if message.photo:
        img_id = message.photo[-1].file_id # Best quality
        await state.update_data(img_id=img_id)
    elif message.text == "⏭️ স্কিপ করুন":
        pass # img_id remains None
    elif message.text == "❌ বাতিল করুন":
        await state.clear()
        await message.answer("বাতিল করা হলো।", reply_markup=get_main_keyboard())
        return
    else:
        await message.answer("শুধু ছবি পাঠান অথবা স্কিপ করুন!")
        return

    await message.answer("চমৎকার! এখন ওয়েলকাম মেসেজের টেক্সট লিখুন:")
    await state.set_state(Form.add_bot_text)

@router.message(Form.add_bot_text)
async def process_text(message: Message, state: FSMContext):
    if message.text == "❌ বাতিল করুন":
        await state.clear()
        await message.answer("বাতিল করা হলো।", reply_markup=get_main_keyboard())
        return

    await state.update_data(text=message.text)
    await message.answer("ওয়েলকাম মেসেজে কয়টি বাটন থাকবে? (০ থেকে ৩ এর মধ্যে সংখ্যা দিন):")
    await state.set_state(Form.add_btn_count)

@router.message(Form.add_btn_count)
async def process_btn_count(message: Message, state: FSMContext):
    if message.text == "❌ বাতিল করুন":
        await state.clear()
        await message.answer("বাতিল করা হলো।", reply_markup=get_main_keyboard())
        return

    try:
        count = int(message.text)
        if 0 <= count <= 3:
            if count == 0:
                # Save bot to DB
                data = await state.get_data()
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO client_bots (bot_id, owner_id, bot_token, bot_username, welcome_text, welcome_img_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (data['bot_id'], message.from_user.id, data['token'], data['bot_username'], data['text'], data.get('img_id'), str(datetime.datetime.now()))
                )
                conn.commit()
                conn.close()
                
                # Notify Admin
                await notify_admin_new_bot(message.bot, message.from_user, data)
                
                await state.clear()
                await message.answer("🎉 বট সফলভাবে যোগ হয়েছে এবং সেটআপ সম্পন্ন!", reply_markup=get_main_keyboard())
            else:
                await state.update_data(btn_count=count, current_btn=0, buttons=[])
                await message.answer(f"বাটন ১ এর নাম লিখুন:")
                await state.set_state(Form.add_btn_name)
        else:
            await message.answer("সংখ্যা ০ থেকে ৩ এর মধ্যে হতে হবে!")
    except ValueError:
        await message.answer("সংখ্যা দিন!")

# Recursive button add
@router.message(Form.add_btn_name)
async def process_btn_name(message: Message, state: FSMContext):
    if message.text == "❌ বাতিল করুন":
        await state.clear()
        await message.answer("বাতিল করা হলো।", reply_markup=get_main_keyboard())
        return

    await state.update_data(current_btn_name=message.text)
    await message.answer("বাটনের URL লিখুন:")
    await state.set_state(Form.add_btn_url)

@router.message(Form.add_btn_url)
async def process_btn_url(message: Message, state: FSMContext):
    if message.text == "❌ বাতিল করুন":
        await state.clear()
        await message.answer("বাতিল করা হলো।", reply_markup=get_main_keyboard())
        return

    url = message.text
    # Simple URL check
    if not url.startswith("http"):
        await message.answer("সঠিক URL দিন (http/https)!")
        return

    data = await state.get_data()
    buttons = data.get('buttons', [])
    buttons.append({"name": data['current_btn_name'], "url": url})
    
    current_idx = data.get('current_btn', 0) + 1
    total_btns = data.get('btn_count', 0)

    if current_idx < total_btns:
        await state.update_data(buttons=buttons, current_btn=current_idx)
        await message.answer(f"বাটন {current_idx + 1} এর নাম লিখুন:")
        await state.set_state(Form.add_btn_name)
    else:
        # Save Bot
        import json
        data = await state.get_data()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO client_bots (bot_id, owner_id, bot_token, bot_username, welcome_text, welcome_img_id, buttons_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (data['bot_id'], message.from_user.id, data['token'], data['bot_username'], data['text'], data.get('img_id'), json.dumps(buttons), str(datetime.datetime.now()))
        )
        conn.commit()
        conn.close()
        
        await notify_admin_new_bot(message.bot, message.from_user, data)
        
        await state.clear()
        await message.answer("🎉 বট সফলভাবে যোগ হয়েছে এবং সেটআপ সম্পন্ন!", reply_markup=get_main_keyboard())

async def notify_admin_new_bot(main_bot: Bot, user: types.User, data: dict):
    text = (
        f"🚀 **নতুন বট যোগ হয়েছে!**\n\n"
        f"👤 ইউজার: {user.mention_html} (`{user.id}`)\n"
        f"🤖 বট: @{data['bot_username']} (`{data['bot_id']}`)\n"
        f"📅 তারিখ: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await main_bot.send_message(admin_id, text, parse_mode="HTML")
        except:
            pass

# --- Handler: My Bots ---
@router.message(F.text == "🤖 আমার বটস")
async def show_my_bots(message: Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT bot_id, bot_username, welcome_text FROM client_bots WHERE owner_id = ?", (message.from_user.id,))
    bots = cursor.fetchall()
    conn.close()

    if not bots:
        await message.answer("আপনার কোনো বট যোগ করা হয়নি। '➕ নতুন বট যোগ করুন' বাটনে ক্লিক করুন!", reply_markup=get_main_keyboard())
        return

    text = "তোমার বট তালিকা:\n\n"
    keyboard = []
    for bot_id, username, wtext in bots:
        text += f"🤖 @{username}\n"
        keyboard.append([InlineKeyboardButton(text=f"⚙️ {username}", callback_data=f"manage_{bot_id}")])

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@router.callback_query(F.data.startswith("manage_"))
async def manage_bot(callback: CallbackQuery):
    bot_id = int(callback.data.split("_")[1])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT bot_username FROM client_bots WHERE bot_id = ? AND owner_id = ?", (bot_id, callback.from_user.id))
    bot = cursor.fetchone()
    conn.close()

    if not bot:
        await callback.answer("বট পাওয়া যায়নি!", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(text="✏️ ওয়েলকাম এডিট", callback_data=f"edit_{bot_id}")],
        [InlineKeyboardButton(text="🗑️ বট ডিলিট করুন", callback_data=f"del_{bot_id}")],
        [InlineKeyboardButton(text="📊 ইউজার সংখ্যা", callback_data=f"stat_{bot_id}")]
    ]
    await callback.message.edit_text(f"🤖 বট: @{bot[0]}\n\nপছন্দ করুন:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("del_"))
async def delete_bot(callback: CallbackQuery):
    bot_id = int(callback.data.split("_")[1])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM client_bots WHERE bot_id = ? AND owner_id = ?", (bot_id, callback.from_user.id))
    cursor.execute("DELETE FROM client_bot_users WHERE bot_id = ?", (bot_id,))
    cursor.execute("DELETE FROM broadcast_admins WHERE bot_id = ?", (bot_id,))
    conn.commit()
    conn.close()
    await callback.message.edit_text("🗑️ বট মুছে ফেলা হয়েছে।")

# --- Flow: Broadcast Setup ---
@router.message(F.text == "📢 ব্রডকাস্ট সেটআপ")
async def setup_broadcast_start(message: Message, state: FSMContext):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT bot_id, bot_username FROM client_bots WHERE owner_id = ?", (message.from_user.id,))
    bots = cursor.fetchall()
    conn.close()

    if not bots:
        await message.answer("আপনার কোনো বট নেই। প্রথমে বট যোগ করুন।")
        return

    buttons = []
    for bid, bname in bots:
        buttons.append([InlineKeyboardButton(text=bname, callback_data=f"bc_setup_{bid}")])
    
    await message.answer("কোন বটের জন্য ব্রডকাস্ট এডমিন সেট করবেন?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(Form.select_bot_broadcast)

@router.callback_query(StateFilter(Form.select_bot_broadcast), F.data.startswith("bc_setup_"))
async def ask_broadcast_admins(callback: CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split("_")[2])
    await state.update_data(selected_bot_id=bot_id)
    await callback.message.edit_text("এখন ব্রডকাস্ট এডমিনের User ID গুলো পাঠান।\n(একাধিক হলে কমা দিয়ে আলাদা করুন, যেমন: 12345, 67890)")
    await state.set_state(Form.set_broadcast_admins)

@router.message(StateFilter(Form.set_broadcast_admins))
async def save_broadcast_admins(message: Message, state: FSMContext):
    try:
        ids = [int(x.strip()) for x in message.text.split(",")]
        data = await state.get_data()
        bot_id = data['selected_bot_id']
        
        conn = get_db()
        cursor = conn.cursor()
        # Clear old
        cursor.execute("DELETE FROM broadcast_admins WHERE bot_id = ?", (bot_id,))
        # Insert new
        for uid in ids:
            cursor.execute("INSERT INTO broadcast_admins (bot_id, user_id) VALUES (?, ?)", (bot_id, uid))
        conn.commit()
        conn.close()
        
        await state.clear()
        await message.answer(f"✅ ব্রডকাস্ট এডমিন সেট করা হয়েছে! ({len(ids)} জন)", reply_markup=get_main_keyboard())
    except ValueError:
        await message.answer("শুধু সংখ্যা (ID) দিন!")

# --- Admin Panel ---
@router.message(F.text == "📊 স্ট্যাটাস")
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id): return

    conn = get_db()
    cursor = conn.cursor()
    u = cursor.execute("SELECT count(*) FROM users").fetchone()[0]
    b = cursor.execute("SELECT count(*) FROM client_bots").fetchone()[0]
    c = cursor.execute("SELECT count(*) FROM channels").fetchone()[0]
    conn.close()

    text = f"📊 **Bot Control Hub Stats**\n\n👥 Total Users: {u}\n🤖 Connected Bots: {b}\n📺 Force Join Channels: {c}"
    await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "📺 চ্যানেল ম্যানেজ")
async def manage_channels(message: Message):
    if not is_admin(message.from_user.id): return
    
    conn = get_db()
    cursor = conn.cursor()
    channels = cursor.execute("SELECT channel_id, channel_title, channel_link FROM channels").fetchall()
    conn.close()
    
    text = "📺 **বর্তমান চ্যানেল তালিকা:**\n\n"
    buttons = []
    if channels:
        for cid, title, link in channels:
            text += f"• {title}\n"
            buttons.append([InlineKeyboardButton(text=f"❌ {title}", callback_data=f"rmch_{cid}")])
    else:
        text += "কোনো চ্যানেল নেই।"
    
    buttons.append([InlineKeyboardButton(text="➕ নতুন চ্যানেল", callback_data="addch")])
    await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data == "addch")
async def add_channel_step(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("চ্যানেলের পাবলিক লিংক পাঠান (যেমন: https://t.me/mychannel):")
    await state.set_state(Form.add_channel_link)

@router.message(StateFilter(Form.add_channel_link))
async def save_channel(message: Message, state: FSMContext):
    link = message.text
    if "t.me/" not in link:
        await message.answer("সঠিক টেলিগ্রাম লিংক দিন!")
        return
    
    # Try to get chat ID
    try:
        chat = await message.bot.get_chat(link)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO channels (channel_id, channel_title, channel_link) VALUES (?, ?, ?)",
                       (chat.id, chat.title, link))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer(f"✅ {chat.title} যোগ হয়েছে!", reply_markup=get_admin_keyboard())
    except Exception as e:
        await message.answer(f"এরর: {e}. বট কি চ্যানেলে এডমিন?")

@router.callback_query(F.data.startswith("rmch_"))
async def remove_channel(callback: CallbackQuery):
    cid = int(callback.data.split("_")[1])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (cid,))
    conn.commit()
    conn.close()
    await callback.message.edit_text("চ্যানেল সরানো হয়েছে।")

# Admin Broadcast to Main Bot Users
@router.message(F.text == "📢 ইউজার ব্রডকাস্ট")
async def admin_broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await message.answer("মেইন বটের ইউজারদের কি মেসেজ পাঠাবেন? (শুধু টেক্সট):")
    await state.set_state(Form.admin_broadcast_msg)

@router.message(StateFilter(Form.admin_broadcast_msg))
async def admin_broadcast_confirm(message: Message, state: FSMContext):
    await state.update_data(msg=message.text)
    await message.answer("আপনি কি নিশ্চিত? (হ্যাঁ/না)")
    await state.set_state(Form.admin_broadcast_confirm)

@router.message(StateFilter(Form.admin_broadcast_confirm))
async def admin_broadcast_send(message: Message, state: FSMContext):
    if message.text.lower() in ["হ্যাঁ", "yes", "ha"]:
        data = await state.get_data()
        msg_text = data['msg']
        
        conn = get_db()
        cursor = conn.cursor()
        users = cursor.execute("SELECT user_id FROM users").fetchall()
        conn.close()
        
        count = 0
        for (uid,) in users:
            try:
                await message.bot.send_message(uid, msg_text)
                count += 1
                await asyncio.sleep(0.05) # Prevent flood
            except:
                pass
        
        await message.answer(f"✅ ব্রডকাস্ট সম্পন্ন! পাঠানো হয়েছে {count} জনকে।", reply_markup=get_admin_keyboard())
    else:
        await message.answer("বাতিল করা হলো।")
    await state.clear()

# --- Client Bot Handler (The Logic for Connected Bots) ---
# Since we are running multiple bots, we need to handle updates for them.
# In a single-process environment with webhooks or polling, we usually handle them separately.
# Here we simulate a simple multiplexer or we rely on the fact that we can't easily poll multiple bots in one script without threading.
# FOR RENDER DEPLOYMENT: We will assume this script manages the MAIN BOT. 
# The Client Bots logic must be triggered. Since we cannot spawn infinite pollers on free Render,
# We implement a **Dispatcher that can handle updates from multiple bots via Webhook** OR
# For simplicity in this specific request (Single main.py, polling): 
# We will implement a polling loop that polls the main bot AND polls client bots dynamically.

# --- Client Bot Dispatcher Logic ---
# We need a way to run client bots. We'll create a manager for them.

class ClientBotManager:
    def __init__(self):
        self.active_bots: Dict[int, Bot] = {}
        self.dispatcher = Dispatcher()
        self.setup_handlers()

    def setup_handlers(self):
        # Register handlers for client bots
        @self.dispatcher.message(Command("start"))
        async def client_start(message: Message, bot: Bot):
            # Identify bot
            bot_id = bot.id
            
            # Save User to client_bot_users
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO client_bot_users (bot_id, user_id, joined_at) VALUES (?, ?, ?)",
                           (bot_id, message.from_user.id, str(datetime.datetime.now())))
            conn.commit()
            
            # Fetch Config
            cursor.execute("SELECT welcome_text, welcome_img_id, buttons_json FROM client_bots WHERE bot_id = ?", (bot_id,))
            config = cursor.fetchone()
            conn.close()
            
            if config:
                text, img_id, btn_json = config
                btns = None
                if btn_json:
                    import json
                    btn_list = json.loads(btn_json)
                    kb = [[InlineKeyboardButton(text=b['name'], url=b['url'])] for b in btn_list]
                    btns = InlineKeyboardMarkup(inline_keyboard=kb)
                
                try:
                    if img_id:
                        await message.answer_photo(img_id, caption=text, reply_markup=btns)
                    else:
                        await message.answer(text, reply_markup=btns)
                except Exception as e:
                    print(f"Error sending welcome for client bot: {e}")
            else:
                await message.answer("হ্যালো! বটটি কনফিগার করা হয়নি।")

        @self.dispatcher.message(Command("broadcast"))
        async def client_broadcast(message: Message, bot: Bot):
            bot_id = bot.id
            user_id = message.from_user.id
            
            # Check if broadcast admin
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM broadcast_admins WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
            is_auth = cursor.fetchone()
            conn.close()
            
            if not is_auth:
                await message.answer("⛔ আপনার এই কমান্ড ব্যবহার করার অনুমতি নেই!")
                return
            
            # Use FSM for flow? Since client bots share a dp, we need state storage isolation.
            # Simplified: Ask for message now.
            # For simplicity in this single-file constraint, let's do a simple flow:
            # "Send me the text to broadcast"
            # We can't easily use FSM here without complex setup, so we use a dict state or assume admin sends text immediately? 
            # Let's use a simplified FSM memory storage for client bots.
            
            await message.answer("📢 ব্রডকাস্ট মেসেজ পাঠান (শুধু টেক্সট):")
            # In a real multi-bot FSM scenario, we'd set state. 
            # Here we'll just save the state in a temporary dict keyed by user_id+bot_id
            
            # For the sake of this complete code, we will treat the next message as broadcast content if they are admin.
            # BUT, without FSM it's risky. Let's just use a simple text expectation.
            # Since we cannot easily define FSM States dynamically for client bots in this scope without duplication,
            # We'll use a placeholder logic: Admin sends /broadcast -> Bot says "Send text" -> Admin sends text -> Bot broadcasts.
            # To achieve this: We need to track that they are in "broadcast mode".
            
            # Simple solution: Use the Database as state.
            cursor = get_db().cursor()
            cursor.execute("INSERT OR REPLACE INTO temp_states (key, value) VALUES (?, ?)", (f"bc_{bot_id}_{user_id}", "waiting"))
            get_db().commit() # Assuming temp_states table exists (we add it to init)
            
        @self.dispatcher.message()
        async def client_text_handler(message: Message, bot: Bot):
            # Check if in broadcast mode
            conn = get_db()
            cursor = conn.cursor()
            # Create table if not exists (lazy)
            cursor.execute("CREATE TABLE IF NOT EXISTS temp_states (key TEXT PRIMARY KEY, value TEXT)")
            conn.commit()
            
            key = f"bc_{bot.id}_{message.from_user.id}"
            cursor.execute("SELECT value FROM temp_states WHERE key = ?", (key,))
            state = cursor.fetchone()
            
            if state and state[0] == "waiting":
                # It is broadcast text
                cursor.execute("DELETE FROM temp_states WHERE key = ?", (key,))
                conn.commit()
                
                # Broadcast
                cursor.execute("SELECT user_id FROM client_bot_users WHERE bot_id = ?", (bot.id,))
                targets = cursor.fetchall()
                conn.close()
                
                success = 0
                for (tid,) in targets:
                    try:
                        await bot.send_message(tid, message.text)
                        success += 1
                        await asyncio.sleep(0.05)
                    except:
                        pass
                
                await message.answer(f"✅ ব্রডকাস্ট সম্পন্ন! পাঠানো হয়েছে {success} জনকে।")
            else:
                conn.close()
                await message.answer("আমি এই মেসেজটি বুঝতে পারছি না। 😅")

    async def start_bot(self, token: str):
        if token not in self.active_bots:
            bot = Bot(token=token)
            self.active_bots[token] = bot
            # We cannot start a separate poller easily in one async loop without creating tasks
            asyncio.create_task(self._poll(bot))

    async def _poll(self, bot: Bot):
        # Simple long polling loop for client bot
        offset = None
        while True:
            try:
                updates = await bot.get_updates(offset=offset, timeout=10)
                for update in updates:
                    offset = update.update_id + 1
                    # Feed update to dispatcher
                    await self.dispatcher.feed_update(bot, update)
            except Exception as e:
                print(f"Error polling client bot: {e}")
                await asyncio.sleep(5)

# We need to integrate this manager into the main startup
# Initialize ClientBotManager globally
client_manager = ClientBotManager()

# And update init_db to include temp_states
def init_db():
    # ... previous code ...
    with sqlite3.connect(DB_NAME) as conn:
        # ... previous tables ...
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS temp_states (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()

# We need to load existing bots on startup
async def on_startup(dispatcher: Dispatcher):
    print("Starting up...")
    # Init DB again to be sure
    init_db()
    
    # Load client bots
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT bot_token FROM client_bots")
    tokens = cursor.fetchall()
    conn.close()
    
    for (token,) in tokens:
        try:
            await client_manager.start_bot(token)
            print(f"Started client bot with token ending in ...{token[-5:]}")
        except Exception as e:
            print(f"Failed to start client bot: {e}")

# --- Main Entry ---
async def main():
    # Initialize Bot
    bot = Bot(token=TOKEN)
    # Memory storage for FSM
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Register routers
    dp.include_router(router)
    
    # Run startup hook
    dp.startup.register(on_startup)
    
    # Start polling for Main Bot
    print("Main Bot is running...")
    
    # We need to run the main bot polling AND the client bot manager tasks
    # Since dp.start_polling is blocking, we run it.
    # Client bots are started in 'on_startup' as background tasks.
    
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
