import asyncio
import logging
import os
import sqlite3
import json
import sys
from datetime import datetime
from typing import List, Dict, Optional, Any

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, ContentType
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramNotFound
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# --- CONFIGURATION & CONSTANTS ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "0").split(",") if id.isdigit()]
REQUIRED_CHANNELS = [ch for ch in os.getenv("REQUIRED_CHANNELS", "").split(",") if ch]

# Render friendly port (unused in polling but good for binding if needed)
PORT = int(os.getenv("PORT", 5000))

# Database Name
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
    """Initialize database tables."""
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
        )"""
    ]
    for query in queries:
        db.execute_write(query)
    logger.info("Database initialized successfully.")

init_db()

# --- FSM STATES ---
class MainStates(StatesGroup):
    waiting_for_token = State()
    waiting_for_image_decision = State()
    waiting_for_image = State()
    waiting_for_welcome_text = State()
    waiting_for_button_count = State()
    waiting_for_button_details = State()
    broadcast_setup_ids = State()
    admin_broadcast_image = State()
    admin_broadcast_text = State()
    admin_broadcast_btn = State()
    managing_bot = State()

class ClientBroadcastStates(StatesGroup):
    waiting_image = State()
    waiting_text = State()
    waiting_buttons = State()

# --- GLOBALS & STORAGE ---
router = Router()
client_bots: Dict[int, Dict] = {} # {bot_id: {"bot": Bot, "dp": Dispatcher, "task": Task}}

# --- HELPERS ---
def get_bengali_welcome():
    return (
        "👋 স্বাগতম! আমি হলাম **Bot Control Hub**।\n\n"
        "এখানে আপনি আপনার নিজের টেলিগ্রাম বট যুক্ত করে তার স্বাগত বার্তা এবং "
        "ব্রডকাস্ট সিস্টেম সেটআপ করতে পারবেন।\n\n"
        "শুরু করতে নিচের বাটমে ক্লিক করুন! 😼"
    )

# --- KEYBOARDS ---
def get_main_keyboard():
    buttons = [
        [InlineKeyboardButton(text="🤖 আমার বট সমূহ", callback_data="my_bots")],
        [InlineKeyboardButton(text="➕ নতুন বট যুক্ত করুন", callback_data="add_new_bot")],
        [InlineKeyboardButton(text="📢 ব্রডকাস্ট সেটআপ", callback_data="setup_broadcast")],
    ]
    if ADMIN_IDS:
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
            return False
    return True

# --- MAIN BOT HANDLERS ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    user = message.from_user
    
    # Register User
    db.execute_write(
        "INSERT OR IGNORE INTO users (user_id, full_name, username, join_date) VALUES (?, ?, ?, ?)",
        (user_id, user.full_name, user.username, str(datetime.now()))
    )

    # Check Force Join
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
        reply_markup=get_main_keyboard()
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
            reply_markup=get_main_keyboard()
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
    await message.answer(text, parse_mode="Markdown", 
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [InlineKeyboardButton(text="📩 অ্যাডমিনে যোগাযোগ", url=f"tg://user?id={ADMIN_IDS[0] if ADMIN_IDS else 0}")]
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
    
    # Check if bot already exists
    existing = db.execute_fetch("SELECT bot_id FROM client_bots WHERE bot_token=?", (token,))
    if existing:
        await message.answer("❌ এই বট টি ইতিমধ্যে সিস্টেমে যুক্ত আছে।")
        return

    # Validate Token
    try:
        new_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        bot_info = await new_bot.get_me()
        await new_bot.session.close()
    except Exception as e:
        await message.answer(f"❌ টোকেন অবৈধ! আবার চেষ্টা করুন।\nError: `{e}`", parse_mode="Markdown")
        return

    # Save to DB
    db.execute_write(
        "INSERT INTO client_bots (owner_id, bot_token, bot_username, bot_id, added_date) VALUES (?, ?, ?, ?, ?)",
        (message.from_user.id, token, bot_info.username, bot_info.id, str(datetime.now()))
    )

    # Alert Admin
    if ADMIN_IDS:
        alert_text = (
            f"🆕 <b>New Bot Connected!</b>\n"
            f"User: {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n"
            f"Bot: @{bot_info.username} (<code>{bot_info.id}</code>)\n"
            f"Time: {datetime.now()}"
        )
        await bot.send_message(ADMIN_IDS[0], alert_text)

    await state.update_data(current_bot_token=token, current_bot_id=bot_info.id, current_bot_username=bot_info.username)
    
    # Start Setup Flow
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
    except:
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
    asyncio.create_task(start_client_bot_task(token, bot_id))

    await state.clear()
    await message.answer(
        "🎉 **বট সেটআপ সম্পন্ন!**\n\n"
        "আপনার বট এখন ব্যবহারযোগ্য। আপনার বটে /start দিলে এই সেটআপ দেখাবে।",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

# --- MY BOTS & MANAGEMENT ---

@router.callback_query(F.data == "my_bots")
async def list_my_bots(callback: types.CallbackQuery):
    bots = db.execute_fetch(
        "SELECT id, bot_username, bot_id FROM client_bots WHERE owner_id=?", 
        (callback.from_user.id,)
    )

    if not bots:
        await callback.message.edit_text("😕 আপনার কোনো বট যুক্ত নেই।", reply_markup=get_main_keyboard())
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
        task = client_bots[bot_id]['task']
        task.cancel()
        del client_bots[bot_id]

    db.execute_write("DELETE FROM client_bots WHERE bot_id=?", (bot_id,))
    db.execute_write("DELETE FROM welcome_settings WHERE bot_id=?", (bot_id,))
    db.execute_write("DELETE FROM client_bot_users WHERE client_bot_id=?", (bot_id,))
    db.execute_write("DELETE FROM broadcast_admins WHERE client_bot_id=?", (bot_id,))
    
    await callback.answer("✅ বট সফলভাবে ডিলিট হয়েছে।")
    await callback.message.edit_text("🏠 মূল মেনুতে ফিরে এসেছেন।", reply_markup=get_main_keyboard())

@router.callback_query(F.data.startswith("restart_bot_"))
async def restart_bot_handler(callback: types.CallbackQuery):
    bot_id = int(callback.data.split("_")[-1])
    
    bot_data = db.execute_fetch("SELECT bot_token FROM client_bots WHERE bot_id=?", (bot_id,))
    if not bot_data:
        await callback.answer("বট খুঁজে পাওয়া যায়নি।", show_alert=True)
        return

    token = bot_data[0][0]
    
    if bot_id in client_bots:
        client_bots[bot_id]['task'].cancel()
        del client_bots[bot_id]

    asyncio.create_task(start_client_bot_task(token, bot_id))
    await callback.answer("বট রিস্টার্ট করা হচ্ছে...")
    
    # Refresh UI
    await manage_bot(callback, None)

@router.callback_query(F.data == "back_home")
async def back_home(callback: types.CallbackQuery):
    await callback.message.edit_text(get_bengali_welcome(), parse_mode="Markdown", reply_markup=get_main_keyboard())

# --- BROADCAST SETUP ---

@router.callback_query(F.data == "setup_broadcast")
async def setup_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
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
    
    # Show current admins
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
        reply_markup=get_main_keyboard()
    )

# --- ADMIN PANEL ---
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
            [InlineKeyboardButton(text="📢 সব ইউজারে ব্রডকাস্ট", callback_data="admin_broadcast_start")],
            [InlineKeyboardButton(text="🔄 সব বট রিস্টার্ট", callback_data="admin_restart_all")],
            [InlineKeyboardButton(text="🔙 পেছনে", callback_data="back_home")]
        ])
    )

@router.callback_query(F.data == "admin_restart_all")
async def admin_restart_all(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    
    await callback.answer("সব বট রিস্টার্ট হচ্ছে...")
    await restart_all_client_bots()
    await callback.message.edit_text("✅ সব বট রিস্টার্ট কমান্ড দেওয়া হয়েছে।", reply_markup=get_main_keyboard())

# Admin Broadcast Flow
@router.callback_query(F.data == "admin_broadcast_start")
async def admin_bc_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(MainStates.admin_broadcast_image)
    await callback.message.edit_text("📢 ব্রডকাস্ট শুরু।\n\n🖼️ ছবি পাঠান বা স্কিপ করুন।",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ ছবি স্কিপ", callback_data="ad_bc_skip_img")]
        ])
    )

@router.callback_query(F.data == "ad_bc_skip_img")
async def admin_bc_skip_img(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(bc_img=None)
    await state.set_state(MainStates.admin_broadcast_text)
    await callback.message.edit_text("📝 এখন টেক্সট লিখুন।",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ বাতিল", callback_data="back_home")]
        ])
    )

@router.message(MainStates.admin_broadcast_image, F.content_type == ContentType.PHOTO)
async def admin_bc_img(message: Message, state: FSMContext):
    await state.update_data(bc_img=message.photo[-1].file_id)
    await state.set_state(MainStates.admin_broadcast_text)
    await message.answer("✅ ছবি নেওয়া হয়েছে। এখন টেক্সট লিখুন।")

@router.message(MainStates.admin_broadcast_text)
async def admin_bc_text(message: Message, state: FSMContext):
    await state.update_data(bc_text=message.text)
    await state.set_state(MainStates.admin_broadcast_btn)
    await message.answer("🔘 বাটন দিতে চাইলে `নাম | URL` লিখুন, অথবা স্কিপ করুন।",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ বাটন স্কিপ", callback_data="ad_bc_skip_btn")]
        ])
    )

@router.callback_query(F.data == "ad_bc_skip_btn")
async def admin_bc_skip_btn(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(bc_btn=None)
    await execute_admin_broadcast(callback.message, state)

@router.message(MainStates.admin_broadcast_btn)
async def admin_bc_btn(message: Message, state: FSMContext):
    try:
        parts = message.text.split("|")
        btn = [{"name": parts[0].strip(), "url": parts[1].strip()}]
    except:
        await message.answer("❌ ফরম্যাট ঠিক নেই।")
        return
    await state.update_data(bc_btn=btn)
    await execute_admin_broadcast(message, state)

async def execute_admin_broadcast(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    
    users = [x[0] for x in db.execute_fetch("SELECT user_id FROM users")]

    kb = None
    if data.get('bc_btn'):
        btns = [InlineKeyboardButton(text=b['name'], url=b['url']) for b in data['bc_btn']]
        kb = InlineKeyboardMarkup(inline_keyboard=[btns])

    bot = message.bot
    sent = 0
    fail = 0
    
    status_msg = await message.answer("🔄 ব্রডকাস্ট চলছে...")
    
    for uid in users:
        try:
            if data.get('bc_img'):
                await bot.send_photo(uid, data['bc_img'], caption=data.get('bc_text'), reply_markup=kb)
            elif data.get('bc_text'):
                await bot.send_message(uid, data['bc_text'], reply_markup=kb)
            sent += 1
        except TelegramForbiddenError:
            # User blocked bot
            pass
        except Exception as e:
            logger.error(f"Broadcast error to {uid}: {e}")
            fail += 1
        
        await asyncio.sleep(0.05) # Flood control

    await status_msg.edit_text(f"✅ ব্রডকাস্ট শেষ!\n\nসফল: {sent}\nব্যর্থ: {fail}")

# --- CLIENT BOT SYSTEM ---

async def start_client_bot_task(token: str, bot_id: int):
    """Task to run a single client bot."""
    if bot_id in client_bots:
        logger.info(f"Bot {bot_id} already running.")
        return

    try:
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()
        
        # Register generic handlers with closure for bot_id
        @dp.message(CommandStart())
        async def client_start(message: Message):
            uid = message.from_user.id
            # Save user
            db.execute_write(
                "INSERT OR IGNORE INTO client_bot_users (client_bot_id, user_id) VALUES (?, ?)",
                (bot_id, uid)
            )
            
            # Get Settings
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
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text=b['name'], url=b['url'])] for b in btns_list
                        ])
                    except: pass
                
                if img:
                    await bot.send_photo(message.chat.id, img, caption=txt, reply_markup=kb)
                elif txt:
                    await message.answer(txt, reply_markup=kb)
            else:
                await message.answer("👋 হ্যালো! আমি একটি বট।")

        # Simple Broadcast Command for Client Bot
        # Using a basic text-based flow for simplicity in multi-bot architecture
        @dp.message(Command("broadcast"))
        async def client_broadcast_trigger(message: Message):
            uid = message.from_user.id
            # Check Admin
            is_admin = db.execute_fetch(
                "SELECT 1 FROM broadcast_admins WHERE client_bot_id=? AND admin_user_id=?", 
                (bot_id, uid)
            )
            if not is_admin:
                await message.answer("⛔ আপনার অনুমতি নেই।")
                return

            await message.answer(
                "📢 ব্রডকাস্ট মোড চালু।\n\n"
                "ব্রডকাস্ট মেসেজ এখনই পাঠান।\n"
                "ফরম্যাট: `Photo | Caption | ButtonName | ButtonUrl` (সব অপশনাল)\n\n"
                "অথবা শুধু টেক্সট পাঠান।"
            )
            # Wait for next message (Simplified FSM)
            
            # Note: Implementing full FSM for multiple dynamic bots in a single file requires 
            # more complex state management. Here we use a one-shot approach.
            
            # Filter for next message from same user
            # In production, we'd register a temporary handler or use external state.

        # We need a way to handle the response. 
        # Since we can't easily dynamically register FSM states for N bots without memory leaks or complex factory:
        # We will register a generic message handler that checks if the user is in 'broadcast mode' via DB or Memory.
        
        # For this iteration, we will implement a direct "Send to all" command logic for simplicity:
        # !broadcast <message> -> sends to all.
        
        # Re-defining /broadcast for immediate execution for code stability in single file.
        # Usage: /broadcast <message>
        
        # Override previous definition
        @dp.message(Command("broadcast"))
        async def client_broadcast_exec(message: Message):
            uid = message.from_user.id
            is_admin = db.execute_fetch(
                "SELECT 1 FROM broadcast_admins WHERE client_bot_id=? AND admin_user_id=?", 
                (bot_id, uid)
            )
            if not is_admin:
                return

            if not message.text or len(message.text) <= 11:
                await message.answer("⚠️ ব্যবহার: `/broadcast আপনার মেসেজ`")
                return
            
            broadcast_text = message.text[11:]
            users = db.execute_fetch("SELECT user_id FROM client_bot_users WHERE client_bot_id=?", (bot_id,))
            
            status = await message.answer(f"📢 ব্রডকাস্ট শুরু হলো... ({len(users)} জন)")
            success = 0
            for u in users:
                try:
                    await bot.send_message(u[0], broadcast_text)
                    success += 1
                    await asyncio.sleep(0.04)
                except:
                    pass
            await status.edit_text(f"✅ ব্রডকাস্ট শেষ। সফল: {success}")

        # Store in global dict
        client_bots[bot_id] = {'bot': bot, 'dp': dp}
        
        logger.info(f"Client Bot {bot_id} started polling.")
        await dp.start_polling(bot, handle_signals=False)
        
    except asyncio.CancelledError:
        logger.info(f"Bot {bot_id} stopped.")
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
    """Load and start all active bots from database."""
    logger.info("Restarting all client bots...")
    bots = db.execute_fetch("SELECT bot_token, bot_id FROM client_bots")
    tasks = []
    for token, bot_id in bots:
        tasks.append(asyncio.create_task(start_client_bot_task(token, bot_id)))
    
    if tasks:
        await asyncio.gather(*tasks)

# --- MAIN ENTRY POINT ---
async def on_startup(bot: Bot):
    await bot.send_message(ADMIN_IDS[0], "🚀 **Bot Control Hub Started!**\n\nSystem Online.", parse_mode="Markdown")
    # Start client bots in background
    asyncio.create_task(restart_all_client_bots())

async def on_shutdown(bot: Bot):
    logger.info("Shutting down...")
    # Close all client bot sessions
    for bot_id, data in client_bots.items():
        try:
            await data['bot'].session.close()
        except: pass

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found in environment variables.")
        return

    # Init Main Bot
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Main Bot Controller starting...")
    
    try:
        await dp.start_polling(bot, handle_signals=True)
    except Exception as e:
        logger.critical(f"Main Bot Polling Error: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
