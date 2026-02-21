import asyncio
import logging
import os
import sqlite3
import json
import sys
import re
from datetime import datetime
from typing import List, Dict, Optional, Any

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, ContentType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# --- CONFIGURATION & CONSTANTS ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "0").split(",") if id.isdigit()]
# Load required channels from env or DB later
REQUIRED_CHANNELS = [ch for ch in os.getenv("REQUIRED_CHANNELS", "").split(",") if ch]
PORT = int(os.getenv("PORT", 5000))
DB_NAME = "bot_control_hub.db"

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot_logs.log", mode='a')
    ]
)
logger = logging.getLogger("BotHub")

# --- DATABASE LAYER ---
class DatabaseManager:
    def __init__(self, db_name: str):
        self.db_name = db_name
        self.lock = asyncio.Lock()
    
    def _get_connection(self):
        return sqlite3.connect(self.db_name, check_same_thread=False)

    def execute_write(self, query: str, params: tuple = ()):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database Write Error: {e}")

    def execute_fetch(self, query: str, params: tuple = ()) -> List[tuple]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Database Fetch Error: {e}")
            return []

db = DatabaseManager(DB_NAME)

def init_db():
    queries = [
        """CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            join_date TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS client_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            bot_token TEXT UNIQUE,
            bot_username TEXT,
            bot_id INTEGER UNIQUE,
            added_date TEXT,
            is_active INTEGER DEFAULT 1
        )""",
        """CREATE TABLE IF NOT EXISTS welcome_settings (
            bot_id INTEGER PRIMARY KEY,
            image_file_id TEXT,
            welcome_text TEXT,
            buttons TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS client_bot_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_bot_id INTEGER,
            user_id INTEGER,
            UNIQUE(client_bot_id, user_id)
        )""",
        """CREATE TABLE IF NOT EXISTS broadcast_admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_bot_id INTEGER,
            admin_user_id INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER,
            error_text TEXT,
            timestamp TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS force_join_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_username TEXT
        )"""
    ]
    for query in queries:
        db.execute_write(query)
    logger.info("Database initialized successfully.")

init_db()

# Load force join channels from DB into global list
def load_force_join_channels():
    global REQUIRED_CHANNELS
    channels = db.execute_fetch("SELECT channel_username FROM force_join_channels")
    # Merge with env channels (env has priority usually, but here we combine)
    env_channels = [ch for ch in os.getenv("REQUIRED_CHANNELS", "").split(",") if ch]
    db_channels = [ch[0] for ch in channels]
    REQUIRED_CHANNELS = list(set(env_channels + db_channels))

load_force_join_channels()

# --- FSM STATES ---
class MainStates(StatesGroup):
    waiting_for_token = State()
    waiting_for_image_decision = State()
    waiting_for_image = State()
    waiting_for_welcome_text = State()
    waiting_for_button_count = State()
    waiting_for_button_details = State()
    broadcast_setup_ids = State()
    # Client Bot Broadcast States
    client_bc_text = State()
    client_bc_photo = State()
    client_bc_confirm = State()
    # Admin Broadcast States
    admin_bc_photo = State()
    admin_bc_text = State()
    admin_bc_btn = State()
    admin_bc_confirm = State()
    # Force Join Management
    admin_add_channel = State()

# --- GLOBALS & STORAGE ---
router = Router()
# Structure: {bot_id: {"bot": Bot, "dp": Dispatcher, "task": asyncio.Task}}
client_bots: Dict[int, Dict] = {} 

# --- HELPERS ---
def get_bengali_welcome():
    return (
        "👋 স্বাগতম! আমি হলাম **Bot Control Hub**।\n\n"
        "এখানে আপনি আপনার নিজের টেলিগ্রাম বট যুক্ত করে তার স্বাগত বার্তা এবং "
        "ব্রডকাস্ট সিস্টেম সেটআপ করতে পারবেন।\n\n"
        "শুরু করতে নিচের বাটমে ক্লিক করুন! 😼"
    )

def is_valid_url(url: str) -> bool:
    """Check if url is valid http/https or tg:// deep link."""
    if not url: return False
    if url.startswith("tg://"): return True
    regex = re.compile(
        r'^(?:http|ftp)s?://' 
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' 
        r'localhost|' 
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' 
        r'(?::\d+)?' 
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

# --- KEYBOARDS ---
def get_main_keyboard(user_id: int):
    buttons = [
        [InlineKeyboardButton(text="🤖 আমার বট সমূহ", callback_data="my_bots")],
        [InlineKeyboardButton(text="➕ নতুন বট যুক্ত করুন", callback_data="add_new_bot")],
        [InlineKeyboardButton(text="📢 ব্রডকাস্ট সেটআপ", callback_data="setup_broadcast")],
    ]
    # Only show Admin Panel if user is in ADMIN_IDS
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="🛠️ অ্যাডমিন প্যানেল", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_force_join_keyboard():
    buttons = []
    for ch in REQUIRED_CHANNELS:
        link = f"https://t.me/{ch.replace('@', '')}"
        buttons.append([InlineKeyboardButton(text=f"🔗 {ch}", url=link)])
    buttons.append([InlineKeyboardButton(text="✅ আমি জয়েন করেছি", callback_data="check_join")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- MIDDLEWARE: FORCE JOIN ---
async def check_subscription(user_id: int, bot: Bot) -> bool:
    if not REQUIRED_CHANNELS:
        return True
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception as e:
            logger.warning(f"Subscription check error for {channel}: {e}")
            # If bot is not admin in channel, we assume user might have issues, but let's not block entirely if check fails
            # However, usually, we should return False to prompt admin to fix.
            return False
    return True

# --- MAIN BOT HANDLERS ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    user = message.from_user
    
    db.execute_write(
        "INSERT OR IGNORE INTO users (user_id, full_name, username, join_date) VALUES (?, ?, ?, ?)",
        (user_id, user.full_name, user.username, str(datetime.now()))
    )

    if not await check_subscription(user_id, bot):
        await message.answer(
            "🔒 দুঃখিত! বট ব্যবহার করতে হলে নিচের চ্যানেলগুলোতে জয়েন করতে হবে।",
            reply_markup=get_force_join_keyboard()
        )
        return

    await state.clear()
    await message.answer(
        get_bengali_welcome(),
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

@router.callback_query(F.data == "check_join")
async def process_check_join(callback: types.CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if await check_subscription(user_id, bot):
        try:
            await callback.message.delete()
        except:
            pass
        await callback.message.answer(
            "✅ ধন্যবাদ! আপনি সফলভাবে যুক্ত হয়েছেন।",
            reply_markup=get_main_keyboard(user_id)
        )
    else:
        await callback.answer("⚠️ আপনি এখনো সব চ্যানেলে জয়েন করেননি!", show_alert=True)

@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "🆘 **সাহায্য গাইড**\n\n"
        "1. ➕ নতুন বট যুক্ত করুন বাটনে ক্লিক করুন।\n"
        "2. BotFather থেকে টোকেন নিয়ে আসুন।\n"
        "3. আপনার বট এর স্বাগতম বার্তা সেট করুন।\n"
        "4. ব্রডকাস্ট সিস্টেম সেট করুন।\n\n"
        "⚠️ বট টোকেন সুরক্ষিত রাখুন।"
    )
    admin_contact = f"tg://user?id={ADMIN_IDS[0]}" if ADMIN_IDS else "https://t.me/your_admin"
    await message.answer(text, parse_mode="Markdown", 
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [InlineKeyboardButton(text="📩 অ্যাডমিনে যোগাযোগ", url=admin_contact)]
                         ]))

# --- BOT MANAGEMENT FLOW ---

@router.callback_query(F.data == "add_new_bot")
async def add_new_bot(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(MainStates.waiting_for_token)
    await callback.message.edit_text(
        "🤖 **নতুন বট যুক্ত করা হচ্ছে**\n\n"
        "অনুগ্রহ করে BotFather থেকে আপনার বটের **API Token** পাঠান।\n"
        "উদাহরণ: `123456:ABC-DEF...`",
        parse_mode="Markdown"
    )

@router.message(MainStates.waiting_for_token)
async def process_token(message: Message, state: FSMContext, bot: Bot):
    token = message.text.strip()
    
    existing = db.execute_fetch("SELECT bot_id FROM client_bots WHERE bot_token=?", (token,))
    if existing:
        await message.answer("❌ এই বট টি ইতিমধ্যে সিস্টেমে যুক্ত আছে।")
        return

    try:
        new_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        bot_info = await new_bot.get_me()
        await new_bot.session.close()
    except Exception as e:
        await message.answer(f"❌ টোকেন অবৈধ! আবার চেষ্টা করুন।\nError: `{e}`", parse_mode="Markdown")
        return

    db.execute_write(
        "INSERT INTO client_bots (owner_id, bot_token, bot_username, bot_id, added_date) VALUES (?, ?, ?, ?, ?)",
        (message.from_user.id, token, bot_info.username, bot_info.id, str(datetime.now()))
    )

    if ADMIN_IDS:
        alert_text = (
            f"🆕 <b>New Bot Connected!</b>\n"
            f"User: {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n"
            f"Bot: @{bot_info.username} (<code>{bot_info.id}</code>)\n"
            f"Time: {datetime.now()}"
        )
        try:
            await bot.send_message(ADMIN_IDS[0], alert_text)
        except: pass

    await state.update_data(current_bot_token=token, current_bot_id=bot_info.id, current_bot_username=bot_info.username)
    
    await state.set_state(MainStates.waiting_for_image_decision)
    await message.answer(
        f"✅ বট সফলভাবে যুক্ত হয়েছে: @{bot_info.username}\n\n"
        "আপনি কি স্বাগতম বার্তায় ছবি চান? 🖼️",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ হ্যাঁ, ছবি দিব", callback_data="img_yes")],
            [InlineKeyboardButton(text="⏭️ ছবি লাগবে না", callback_data="img_skip")]
        ])
    )

@router.callback_query(StateFilter(MainStates.waiting_for_image_decision), F.data == "img_yes")
async def ask_for_image(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(MainStates.waiting_for_image)
    await callback.message.edit_text("🖼️ অনুগ্রহ করে স্বাগতম বার্তার ছবি পাঠান।")

@router.message(MainStates.waiting_for_image, F.content_type == ContentType.PHOTO)
async def save_image(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(image_file_id=file_id)
    await state.set_state(MainStates.waiting_for_welcome_text)
    await message.answer("✅ ছবি সংরক্ষিত। এখন স্বাগতম বার্তা (টেক্সট) লিখুন।")

@router.callback_query(StateFilter(MainStates.waiting_for_image_decision), F.data == "img_skip")
async def skip_image(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(image_file_id=None)
    await state.set_state(MainStates.waiting_for_welcome_text)
    await callback.message.edit_text("⏭️ ঠিক আছে। এখন স্বাগতম বার্তা (টেক্সট) লিখুন।")

@router.message(MainStates.waiting_for_welcome_text)
async def save_welcome_text(message: Message, state: FSMContext):
    await state.update_data(welcome_text=message.text)
    await state.set_state(MainStates.waiting_for_button_count)
    await message.answer(
        "বাটন কয়টি দিতে চান? (০ থেকে ৩)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=str(i), callback_data=f"btn_count_{i}") for i in range(4)]
        ])
    )

@router.callback_query(StateFilter(MainStates.waiting_for_button_count), F.data.startswith("btn_count_"))
async def process_button_count(callback: types.CallbackQuery, state: FSMContext):
    count = int(callback.data.split("_")[-1])
    data = await state.get_data()
    
    if count == 0:
        await finalize_bot_setup(callback.message, state, data, [])
        return

    await state.update_data(button_count=count, current_button_index=0, buttons_list=[])
    await state.set_state(MainStates.waiting_for_button_details)
    await callback.message.edit_text(f"🔘 বাটন ১: অনুগ্রহ করে **নাম** এবং **URL** দিন।\n\nফরম্যাট: `নাম | URL`", parse_mode="Markdown")

@router.message(MainStates.waiting_for_button_details)
async def process_button_details(message: Message, state: FSMContext):
    data = await state.get_data()
    idx = data['current_button_index']
    count = data['button_count']
    
    try:
        parts = message.text.split("|")
        if len(parts) < 2: raise ValueError
        name = parts[0].strip()
        url = parts[1].strip()
        
        if not is_valid_url(url):
            await message.answer("⚠️ অবৈধ URL! অনুগ্রহ করে সঠিক লিংক দিন।\nউদাহরণ: `https://t.me/username` অথবা `tg://resolve?domain=username`", parse_mode="Markdown")
            return
            
    except ValueError:
        await message.answer("❌ ফরম্যাট ঠিক নেই! আবার লিখুন: `নাম | URL`", parse_mode="Markdown")
        return

    buttons = data.get('buttons_list', [])
    buttons.append({"name": name, "url": url})
    
    idx += 1
    if idx < count:
        await state.update_data(current_button_index=idx, buttons_list=buttons)
        await message.answer(f"✅ বাটন {idx} সেট হয়েছে। এখন বাটন {idx+1} দিন।")
    else:
        await finalize_bot_setup(message, state, data, buttons)

async def finalize_bot_setup(message: Message, state: FSMContext, data: Dict, buttons: List):
    bot_id = data['current_bot_id']
    image_id = data.get('image_file_id')
    text = data.get('welcome_text')
    btn_json = json.dumps(buttons)

    db.execute_write(
        "INSERT INTO welcome_settings (bot_id, image_file_id, welcome_text, buttons) VALUES (?, ?, ?, ?)",
        (bot_id, image_id, text, btn_json)
    )
    
    # Start the client bot immediately
    token = data['current_bot_token']
    # Check if bot is already running (e.g. duplicate callback)
    if bot_id not in client_bots:
        task = asyncio.create_task(start_client_bot_task(token, bot_id))
    
    await state.clear()
    await message.answer(
        "🎉 **বট সেটআপ সম্পন্ন!**\n\n"
        "আপনার বট এখন ব্যবহারযোগ্য। আপনার বটে /start দিলে এই সেটআপ দেখাবে।",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# --- MY BOTS & MANAGEMENT ---

@router.callback_query(F.data == "my_bots")
async def list_my_bots(callback: types.CallbackQuery):
    bots = db.execute_fetch(
        "SELECT id, bot_username, bot_id FROM client_bots WHERE owner_id=?", 
        (callback.from_user.id,)
    )

    if not bots:
        await callback.message.edit_text("😕 আপনার কোনো বট যুক্ত নেই।", reply_markup=get_main_keyboard(callback.from_user.id))
        return

    keyboard = []
    for b in bots:
        status = "🟢" if b[2] in client_bots else "🔴"
        keyboard.append([InlineKeyboardButton(text=f"{status} 🤖 @{b[1]}", callback_data=f"manage_bot_{b[2]}")])
    keyboard.append([InlineKeyboardButton(text="🔙 পেছনে", callback_data="back_home")])
    
    await callback.message.edit_text("🤖 **আপনার যুক্ত বট সমূহ:**", parse_mode="Markdown", 
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@router.callback_query(F.data.startswith("manage_bot_"))
async def manage_bot(callback: types.CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split("_")[-1])
    
    # Store in state for later use
    await state.update_data(managing_bot_id=bot_id)

    is_running = bot_id in client_bots
    status_text = "🟢 চলছে" if is_running else "🔴 বন্ধ"
    
    await callback.message.edit_text(
        f"⚙️ **বট ম্যানেজমেন্ট**\n\n"
        f"স্ট্যাটাস: {status_text}\n"
        f"আপনি কি করতে চান?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ স্বাগতম বার্তা পরিবর্তন", callback_data="edit_welcome")],
            [InlineKeyboardButton(text="📢 ব্রডকাস্ট শুরু করুন", callback_data=f"client_bc_start_{bot_id}")],
            [InlineKeyboardButton(text="🔄 রিস্টার্ট বট", callback_data=f"restart_bot_{bot_id}")],
            [InlineKeyboardButton(text="🗑️ বট ডিলিট করুন", callback_data=f"delete_bot_{bot_id}")],
            [InlineKeyboardButton(text="🔙 পেছনে", callback_data="my_bots")]
        ])
    )

@router.callback_query(F.data.startswith("delete_bot_"))
async def delete_bot(callback: types.CallbackQuery):
    bot_id = int(callback.data.split("_")[-1])
    
    # Stop bot if running
    if bot_id in client_bots:
        try:
            task = client_bots[bot_id]['task']
            task.cancel()
            try: await asyncio.wait_for(task, timeout=2.0)
            except: pass 
            del client_bots[bot_id]
        except Exception as e:
            logger.error(f"Error stopping bot {bot_id}: {e}")

    db.execute_write("DELETE FROM client_bots WHERE bot_id=?", (bot_id,))
    db.execute_write("DELETE FROM welcome_settings WHERE bot_id=?", (bot_id,))
    db.execute_write("DELETE FROM client_bot_users WHERE client_bot_id=?", (bot_id,))
    db.execute_write("DELETE FROM broadcast_admins WHERE client_bot_id=?", (bot_id,))
    
    await callback.answer("✅ বট সফলভাবে ডিলিট হয়েছে।")
    await callback.message.edit_text("🏠 মূল মেনুতে ফিরে এসেছেন।", reply_markup=get_main_keyboard(callback.from_user.id))

@router.callback_query(F.data.startswith("restart_bot_"))
async def restart_bot_handler(callback: types.CallbackQuery):
    bot_id = int(callback.data.split("_")[-1])
    
    bot_data = db.execute_fetch("SELECT bot_token FROM client_bots WHERE bot_id=?", (bot_id,))
    if not bot_data:
        await callback.answer("বট খুঁজে পাওয়া যায়নি।", show_alert=True)
        return

    token = bot_data[0][0]
    
    # Stop existing task if running
    if bot_id in client_bots:
        try:
            client_bots[bot_id]['task'].cancel()
            del client_bots[bot_id]
        except: pass

    # Create new task
    asyncio.create_task(start_client_bot_task(token, bot_id))
    await callback.answer("বট রিস্টার্ট হচ্ছে...")
    
    await callback.message.edit_text(
        f"⚙️ **বট ম্যানেজমেন্ট**\n\n"
        f"স্ট্যাটাস: 🔄 রিস্টার্ট হচ্ছে...\n",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
             [InlineKeyboardButton(text="🔄 রিফ্রেশ", callback_data=f"manage_bot_{bot_id}")],
        ])
    )

@router.callback_query(F.data == "back_home")
async def back_home(callback: types.CallbackQuery):
    await callback.message.edit_text(get_bengali_welcome(), parse_mode="Markdown", reply_markup=get_main_keyboard(callback.from_user.id))

# --- CLIENT BOT BROADCAST SYSTEM (FIXED) ---

@router.callback_query(F.data.startswith("client_bc_start_"))
async def client_bc_start(callback: types.CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split("_")[-1])
    
    # Permission check
    is_admin = db.execute_fetch(
        "SELECT 1 FROM broadcast_admins WHERE client_bot_id=? AND admin_user_id=?", 
        (bot_id, callback.from_user.id)
    )
    is_owner = db.execute_fetch("SELECT 1 FROM client_bots WHERE bot_id=? AND owner_id=?", (bot_id, callback.from_user.id))
    
    if not is_admin and not is_owner and callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ আপনার এই বটে ব্রডকাস্ট করার অনুমতি নেই।", show_alert=True)
        return

    await state.update_data(bc_bot_id=bot_id)
    await state.set_state(MainStates.client_bc_photo)
    
    await callback.message.edit_text(
        "📢 **ক্লায়েন্ট বট ব্রডকাস্ট**\n\n"
        "প্রথমে একটি ছবি পাঠান, অথবা ছবি ছাড়াই টেক্সট পাঠাতে 'স্কিপ' বাটনে ক্লিক করুন।",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ ছবি স্কিপ করুন", callback_data="client_bc_skip_photo")]
        ])
    )

@router.callback_query(F.data == "client_bc_skip_photo", MainStates.client_bc_photo)
async def client_bc_skip_photo(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(bc_photo=None)
    await state.set_state(MainStates.client_bc_text)
    await callback.message.edit_text(
        "📝 এখন ব্রডকাস্ট মেসেজ (টেক্সট) লিখুন।",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ বাতিল", callback_data="my_bots")]
        ])
    )

@router.message(MainStates.client_bc_photo, F.content_type == ContentType.PHOTO)
async def client_bc_photo_received(message: Message, state: FSMContext):
    await state.update_data(bc_photo=message.photo[-1].file_id)
    await state.set_state(MainStates.client_bc_text)
    await message.answer("✅ ছবি সংরক্ষিত। এখন ব্রডকাস্ট টেক্সট লিখুন।")

@router.message(MainStates.client_bc_text)
async def client_bc_text_received(message: Message, state: FSMContext):
    await state.update_data(bc_text=message.text)
    data = await state.get_data()
    
    # Show preview
    text = data.get('bc_text')
    photo = data.get('bc_photo')
    
    await state.set_state(MainStates.client_bc_confirm)
    
    caption = (
        f"📢 **প্রিভিউ:**\n\n"
        f"{text}\n\n"
        f"আপনি কি এই মেসেজটি এই বটের সকল ইউজারদের পাঠাতে চান?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ হ্যাঁ, পাঠান", callback_data="client_bc_confirm_yes")],
        [InlineKeyboardButton(text="❌ বাতিল", callback_data="client_bc_cancel")]
    ])
    
    try:
        if photo:
            await message.answer_photo(photo, caption=caption, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await message.answer(caption, parse_mode="Markdown", reply_markup=keyboard)
    except Exception as e:
        # Fallback if markdown parsing fails in preview
        await message.answer(f"📢 **প্রিভিউ:**\n\n{text}\n\nআপনি কি এই মেসেজটি পাঠাতে চান?", reply_markup=keyboard)

@router.callback_query(F.data == "client_bc_confirm_yes", MainStates.client_bc_confirm)
async def client_bc_execute(callback: types.CallbackQuery, state: FSMContext, main_bot: Bot):
    data = await state.get_data()
    bot_id = data['bc_bot_id']
    text = data['bc_text']
    photo = data['bc_photo']
    
    await state.clear()
    await callback.message.edit_text("🔄 ব্রডকাস্ট শুরু হয়েছে...")
    
    # Get client bot instance
    if bot_id not in client_bots:
        await callback.answer("বট চলছে না!", show_alert=True)
        return
        
    bot_instance = client_bots[bot_id]['bot']
    
    # Get users
    users = db.execute_fetch("SELECT user_id FROM client_bot_users WHERE client_bot_id=?", (bot_id,))
    
    success = 0
    fail = 0
    
    for u in users:
        uid = u[0]
        try:
            if photo:
                await bot_instance.send_photo(uid, photo, caption=text)
            else:
                await bot_instance.send_message(uid, text)
            success += 1
            await asyncio.sleep(0.05) # Rate limit
        except Exception:
            fail += 1
            
    await callback.message.edit_text(f"✅ ব্রডকাস্ট শেষ!\n\nসফল: {success}\nব্যর্থ: {fail}")

@router.callback_query(F.data == "client_bc_cancel")
async def client_bc_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🚫 ব্রডকাস্ট বাতিল করা হয়েছে।", reply_markup=get_main_keyboard(callback.from_user.id))

# --- MAIN BROADCAST SETUP (FOR ADMINS) ---

@router.callback_query(F.data == "setup_broadcast")
async def setup_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    # This is for configuring who can broadcast, as per original code
    bots = db.execute_fetch("SELECT bot_id, bot_username FROM client_bots WHERE owner_id=?", (callback.from_user.id,))
    
    if not bots:
        await callback.answer("প্রথমে একটি বট যুক্ত করুন!", show_alert=True)
        return

    keyboard = []
    for b in bots:
        keyboard.append([InlineKeyboardButton(text=f"🤖 @{b[1]}", callback_data=f"select_bc_bot_{b[0]}")])
    
    await callback.message.edit_text(
        "📢 কোন বটের জন্য ব্রডকাস্ট অ্যাডমিন সেটআপ করবেন?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("select_bc_bot_"))
async def ask_bc_admins(callback: types.CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split("_")[-1])
    await state.update_data(bc_setup_bot_id=bot_id)
    await state.set_state(MainStates.broadcast_setup_ids)
    
    current_admins = db.execute_fetch("SELECT admin_user_id FROM broadcast_admins WHERE client_bot_id=?", (bot_id,))
    admins_str = ", ".join([str(a[0]) for a in current_admins]) if current_admins else "কেউ নেই"
    
    await callback.message.edit_text(
        "📢 **ব্রডকাস্ট অ্যাডমিন সেটআপ**\n\n"
        f"বর্তমান অ্যাডমিন: {admins_str}\n\n"
        "যাদের কে ব্রডকাস্ট করার অনুমতি দিবেন তাদের **User ID** পাঠান।\n"
        "একাধিক হলে কমা (,) দিয়ে আলাদা করুন।\n"
        "উদাহরণ: `123456, 987654`",
        parse_mode="Markdown"
    )

@router.message(MainStates.broadcast_setup_ids)
async def save_bc_admins(message: Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data['bc_setup_bot_id']
    
    try:
        ids = [int(x.strip()) for x in message.text.split(",")]
    except:
        await message.answer("❌ অবৈধ ID! শুধু নম্বর ব্যবহার করুন।")
        return

    db.execute_write("DELETE FROM broadcast_admins WHERE client_bot_id=?", (bot_id,))
    for uid in ids:
        db.execute_write("INSERT INTO broadcast_admins (client_bot_id, admin_user_id) VALUES (?, ?)", (bot_id, uid))

    await state.clear()
    await message.answer(
        f"✅ ব্রডকাস্ট অ্যাডমিন সেট হয়েছে!\n\nঅ্যাডমিন IDs: {ids}",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# --- ADMIN PANEL (UPDATED) ---

@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ অননুমোদিত!", show_alert=True)
        return

    total_users = db.execute_fetch("SELECT COUNT(*) FROM users")[0][0]
    total_bots = db.execute_fetch("SELECT COUNT(*) FROM client_bots")[0][0]
    active_bots = len(client_bots)

    text = (
        f"🛠️ **অ্যাডমিন প্যানেল**\n\n"
        f"👥 মোট ইউজার: `{total_users}`\n"
        f"🤖 মোট কানেক্টেড বট: `{total_bots}`\n"
        f"🟢 সক্রিয় বট: `{active_bots}`"
    )
    
    await callback.message.edit_text(text, parse_mode="Markdown", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 মূল ইউজারদের ব্রডকাস্ট", callback_data="admin_bc_main")],
            [InlineKeyboardButton(text="🌐 গ্লোবাল ব্রডকাস্ট", callback_data="admin_bc_global")],
            [InlineKeyboardButton(text="🔒 ফোর্স জয়েন ম্যানেজমেন্ট", callback_data="admin_force_join")],
            [InlineKeyboardButton(text="🔄 সব বট রিস্টার্ট", callback_data="admin_restart_all")],
            [InlineKeyboardButton(text="🔙 পেছনে", callback_data="back_home")]
        ])
    )

# --- ADMIN FORCE JOIN MANAGEMENT ---

@router.callback_query(F.data == "admin_force_join")
async def admin_force_join_menu(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    
    channels = db.execute_fetch("SELECT id, channel_username FROM force_join_channels")
    text = "🔒 **ফোর্স জয়েন চ্যানেল সমূহ:**\n\n"
    keyboard = []
    if channels:
        for ch in channels:
            text += f"• `{ch[1]}`\n"
            keyboard.append([InlineKeyboardButton(text=f"❌ {ch[1]} ডিলিট করুন", callback_data=f"del_ch_{ch[0]}")])
    else:
        text += "কোনো চ্যানেল যুক্ত নেই।"
    
    keyboard.append([InlineKeyboardButton(text="➕ নতুন চ্যানেল যুক্ত করুন", callback_data="admin_add_channel")])
    keyboard.append([InlineKeyboardButton(text="🔙 পেছনে", callback_data="admin_panel")])
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@router.callback_query(F.data == "admin_add_channel")
async def admin_add_channel_step(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.set_state(MainStates.admin_add_channel)
    await callback.message.edit_text("➕ অনুগ্রহ করে চ্যানেলের ইউজারনেম পাঠান (যেমন: `@mychannel` অথবা `mychannel`)।", parse_mode="Markdown")

@router.message(MainStates.admin_add_channel)
async def admin_save_channel(message: Message, state: FSMContext):
    ch_name = message.text.strip()
    if not ch_name.startswith("@"): ch_name = "@" + ch_name
    
    db.execute_write("INSERT INTO force_join_channels (channel_username) VALUES (?)", (ch_name,))
    load_force_join_channels() # Reload global list
    await state.clear()
    await message.answer(f"✅ `{ch_name} যুক্ত হয়েছে।`", parse_mode="Markdown", reply_markup=get_main_keyboard(message.from_user.id))

@router.callback_query(F.data.startswith("del_ch_"))
async def admin_del_channel(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    ch_id = int(callback.data.split("_")[-1])
    db.execute_write("DELETE FROM force_join_channels WHERE id=?", (ch_id,))
    load_force_join_channels()
    await callback.answer("ডিলিট হয়েছে।")
    # Refresh menu
    await admin_force_join_menu(callback)

# --- ADMIN BROADCAST LOGICS ---

# Helper for global broadcast
async def broadcast_to_users(bot: Bot, user_ids: List[int], text: str, photo: str = None):
    success = 0
    fail = 0
    for uid in user_ids:
        try:
            if photo:
                await bot.send_photo(uid, photo, caption=text)
            else:
                await bot.send_message(uid, text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            fail += 1
    return success, fail

# Admin Main Broadcast
@router.callback_query(F.data == "admin_bc_main")
async def admin_bc_main_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.update_data(bc_type="main")
    await state.set_state(MainStates.admin_bc_photo)
    await callback.message.edit_text("📢 **মূল ইউজার ব্রডকাস্ট**\n\nছবি পাঠান বা স্কিপ করুন।",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ ছবি স্কিপ", callback_data="admin_bc_skip_photo")]
        ])
    )

# Admin Global Broadcast
@router.callback_query(F.data == "admin_bc_global")
async def admin_bc_global_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.update_data(bc_type="global")
    await state.set_state(MainStates.admin_bc_photo)
    await callback.message.edit_text("🌐 **গ্লোবাল ব্রডকাস্ট**\n\nছবি পাঠান বা স্কিপ করুন।",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ ছবি স্কিপ", callback_data="admin_bc_skip_photo")]
        ])
    )

@router.callback_query(F.data == "admin_bc_skip_photo", MainStates.admin_bc_photo)
async def admin_bc_skip_photo(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(bc_photo=None)
    await state.set_state(MainStates.admin_bc_text)
    await callback.message.edit_text("📝 এখন টেক্সট লিখুন।")

@router.message(MainStates.admin_bc_photo, F.content_type == ContentType.PHOTO)
async def admin_bc_photo(message: Message, state: FSMContext):
    await state.update_data(bc_photo=message.photo[-1].file_id)
    await state.set_state(MainStates.admin_bc_text)
    await message.answer("✅ ছবি নেওয়া হয়েছে। এখন টেক্সট লিখুন।")

@router.message(MainStates.admin_bc_text)
async def admin_bc_text(message: Message, state: FSMContext):
    await state.update_data(bc_text=message.text)
    data = await state.get_data()
    
    # Preview
    text = f"📢 **প্রিভিউ:**\n\n{message.text}\n\nপাঠানোর আগে নিশ্চিত হন।"
    await state.set_state(MainStates.admin_bc_confirm)
    
    if data.get('bc_photo'):
        await message.answer_photo(data['bc_photo'], caption=text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ পাঠান", callback_data="admin_bc_send")],
                [InlineKeyboardButton(text="❌ বাতিল", callback_data="admin_panel")]
            ]))
    else:
        await message.answer(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ পাঠান", callback_data="admin_bc_send")],
                [InlineKeyboardButton(text="❌ বাতিল", callback_data="admin_panel")]
            ]))

@router.callback_query(F.data == "admin_bc_send", MainStates.admin_bc_confirm)
async def admin_bc_send_action(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    bc_type = data.get('bc_type')
    text = data.get('bc_text')
    photo = data.get('bc_photo')
    
    await state.clear()
    status_msg = await callback.message.edit_text("🔄 ব্রডকাস্ট প্রসেসিং চলছে...")
    
    users = []
    if bc_type == "main":
        users = [x[0] for x in db.execute_fetch("SELECT user_id FROM users")]
    elif bc_type == "global":
        # Main users
        main_users = set(x[0] for x in db.execute_fetch("SELECT user_id FROM users"))
        # Client bot users
        client_users = set(x[0] for x in db.execute_fetch("SELECT user_id FROM client_bot_users"))
        users = list(main_users.union(client_users))
        
    success, fail = await broadcast_to_users(bot, users, text, photo)
    await status_msg.edit_text(f"✅ ব্রডকাস্ট শেষ!\n\nসফল: {success}\nব্যর্থ: {fail}")

@router.callback_query(F.data == "admin_restart_all")
async def admin_restart_all(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.answer("সব বট রিস্টার্ট হচ্ছে...")
    await restart_all_client_bots()
    await callback.message.edit_text("✅ সব বট রিস্টার্ট কমান্ড দেওয়া হয়েছে।", reply_markup=get_main_keyboard(callback.from_user.id))

# --- CLIENT BOT SYSTEM ---

async def start_client_bot_task(token: str, bot_id: int):
    """Task to run a single client bot."""
    
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    
    current_task = asyncio.current_task()
    client_bots[bot_id] = {'bot': bot, 'dp': dp, 'task': current_task}

    # Register Handlers
    @dp.message(CommandStart())
    async def client_start(message: Message):
        uid = message.from_user.id
        db.execute_write(
            "INSERT OR IGNORE INTO client_bot_users (client_bot_id, user_id) VALUES (?, ?)",
            (bot_id, uid)
        )
        
        settings = db.execute_fetch(
            "SELECT image_file_id, welcome_text, buttons FROM welcome_settings WHERE bot_id=?", 
            (bot_id,)
        )
        
        if settings:
            img, txt, btns_json = settings[0]
            kb = None
            if btns_json:
                try:
                    btns_list = json.loads(btns_json)
                    valid_btns = []
                    for b in btns_list:
                        if is_valid_url(b.get('url', '')):
                            valid_btns.append([InlineKeyboardButton(text=b['name'], url=b['url'])])
                    
                    if valid_btns:
                        kb = InlineKeyboardMarkup(inline_keyboard=valid_btns)
                except Exception as e:
                    logger.error(f"Button JSON error for bot {bot_id}: {e}")
            
            try:
                if img:
                    await bot.send_photo(message.chat.id, img, caption=txt, reply_markup=kb)
                elif txt:
                    await message.answer(txt, reply_markup=kb)
            except TelegramBadRequest as e:
                logger.error(f"Send error in bot {bot_id}: {e}")
                await message.answer("⚠️ স্বাগতম বার্তা দেখাতে সমস্যা হচ্ছে। বাটন URL ভুল থাকতে পারে।")
            except Exception as e:
                logger.error(f"Generic send error in bot {bot_id}: {e}")
        else:
            await message.answer("👋 হ্যালো! আমি একটি বট।")

    logger.info(f"Client Bot {bot_id} started polling.")
    
    try:
        await dp.start_polling(bot, handle_signals=False)
    except asyncio.CancelledError:
        logger.info(f"Bot {bot_id} stopped gracefully.")
    except Exception as e:
        logger.error(f"Client Bot {bot_id} crashed: {e}")
        db.execute_write(
            "INSERT INTO error_logs (bot_id, error_text, timestamp) VALUES (?, ?, ?)",
            (bot_id, str(e), str(datetime.now()))
        )
    finally:
        if bot_id in client_bots:
            del client_bots[bot_id]
        await bot.session.close()

async def restart_all_client_bots():
    logger.info("Restarting all client bots...")
    bots = db.execute_fetch("SELECT bot_token, bot_id FROM client_bots")
    tasks = []
    for token, bot_id in bots:
        if bot_id not in client_bots:
            tasks.append(asyncio.create_task(start_client_bot_task(token, bot_id)))
    
    if tasks:
        await asyncio.gather(*tasks)

# --- WEBHOOK / RENDER SETUP ---
from aiohttp import web

async def handle_webhook(request: web.Request):
    """Handle incoming webhook requests."""
    # This is a simplified webhook handler. 
    # For main bot, we need to verify secret if set, then feed update to dispatcher.
    # Since this bot is primarily polling based in structure, 
    # Render deployment often uses polling with keep-alive or proper webhook setup.
    # Given the request, we'll stick to polling but add a health check server.
    return web.Response(text="Bot is running.")

async def on_startup(bot: Bot):
    if ADMIN_IDS:
        try:
            await bot.send_message(ADMIN_IDS[0], "🚀 **Bot Control Hub Started!**\n\nSystem Online.", parse_mode="Markdown")
        except: pass
    asyncio.create_task(restart_all_client_bots())

async def on_shutdown(bot: Bot):
    logger.info("Shutting down...")
    for bot_id, data in client_bots.items():
        try:
            if 'task' in data: data['task'].cancel()
            await data['bot'].session.close()
        except: pass

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found.")
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Main Bot Controller starting...")
    
    # Start aiohttp server for Render health check / port binding
    app = web.Application()
    app.add_routes([web.get('/', handle_webhook), web.post('/', handle_webhook)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

    try:
        # Start polling
        await dp.start_polling(bot, handle_signals=True)
    except Exception as e:
        logger.critical(f"Main Bot Polling Error: {e}")
    finally:
        await bot.session.close()
        await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
