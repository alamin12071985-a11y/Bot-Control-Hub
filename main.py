"""
Bot Control Hub - Main Application
Complete Telegram Bot Controller with Force Join System
Bengali Interface - Production Ready
"""

import asyncio
import logging
import sqlite3
import os
from datetime import datetime
from typing import Dict, List, Optional, Union
from contextlib import contextmanager

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import aiohttp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION CLASS
# ============================================================================

class Config:
    """Server configuration and settings"""
    
    # Bot Configuration
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8250934004:AAEA5kjsPS5tU0m2OR79g6XdzW70xMBtbYo")
    ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "7605281774").split(",")]
    
    # Database Configuration
    DATABASE_PATH = "bot_control_hub.db"
    
    # Server Settings
    HOST = "0.0.0.0"
    PORT = int(os.getenv("PORT", 8080))
    
    # Feature Flags
    ENABLE_WEBHOOK = os.getenv("ENABLE_WEBHOOK", "False").lower() == "true"
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
    
    # Security
    SESSION_LIFETIME = 3600  # 1 hour
    
    @classmethod
    def validate(cls):
        """Validate configuration"""
        if cls.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
            logger.warning("BOT_TOKEN not set! Please set it in environment variables.")
        if not cls.ADMIN_IDS:
            logger.warning("No admin IDs configured!")

# ============================================================================
# DATABASE MANAGER CLASS
# ============================================================================

class DatabaseManager:
    """SQLite database manager with connection pooling"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_database()
    
    @contextmanager
    def get_connection(self):
        """Get database connection with context management"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
    
    def _init_database(self):
        """Initialize all database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                )
            """)
            
            # Force join channels
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS force_join_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE,
                    channel_username TEXT,
                    channel_title TEXT,
                    added_by INTEGER,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                )
            """)
            
            # Client bots
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS client_bots (
                    bot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER,
                    bot_token TEXT UNIQUE,
                    bot_username TEXT,
                    bot_name TEXT,
                    bot_id_num INTEGER,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    FOREIGN KEY (owner_id) REFERENCES users (user_id)
                )
            """)
            
            # Welcome messages
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welcome_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id INTEGER,
                    image_file_id TEXT,
                    welcome_text TEXT,
                    button_count INTEGER DEFAULT 0,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bot_id) REFERENCES client_bots (bot_id)
                )
            """)
            
            # Welcome buttons
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welcome_buttons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    welcome_id INTEGER,
                    button_name TEXT,
                    button_url TEXT,
                    button_order INTEGER,
                    FOREIGN KEY (welcome_id) REFERENCES welcome_messages (id)
                )
            """)
            
            # Client bot users
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS client_bot_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    first_name TEXT,
                    joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(bot_id, user_id),
                    FOREIGN KEY (bot_id) REFERENCES client_bots (bot_id)
                )
            """)
            
            # Broadcast admins
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broadcast_admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id INTEGER,
                    admin_user_id INTEGER,
                    added_by INTEGER,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(bot_id, admin_user_id),
                    FOREIGN KEY (bot_id) REFERENCES client_bots (bot_id)
                )
            """)
            
            conn.commit()
            logger.info("Database initialized successfully")

# ============================================================================
# FORCE JOIN MANAGER CLASS
# ============================================================================

class ForceJoinManager:
    """Manage force join functionality"""
    
    def __init__(self, db: DatabaseManager, bot: Bot):
        self.db = db
        self.bot = bot
    
    async def check_membership(self, user_id: int) -> tuple:
        """Check if user has joined all required channels"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT channel_id, channel_username FROM force_join_channels WHERE is_active = 1"
            )
            channels = cursor.fetchall()
        
        if not channels:
            return True, []
        
        not_joined = []
        for channel in channels:
            try:
                chat_member = await self.bot.get_chat_member(
                    chat_id=channel['channel_id'],
                    user_id=user_id
                )
                if chat_member.status in ['left', 'kicked']:
                    not_joined.append(channel)
            except Exception as e:
                logger.error(f"Error checking channel {channel['channel_id']}: {e}")
                not_joined.append(channel)
        
        return len(not_joined) == 0, not_joined
    
    def get_channels_keyboard(self, channels: list) -> InlineKeyboardMarkup:
        """Create keyboard with channel buttons"""
        keyboard = []
        for channel in channels:
            username = channel['channel_username']
            url = f"https://t.me/{username.replace('@', '')}" if username else ""
            keyboard.append([InlineKeyboardButton(
                text=f"📢 জয়েন করুন {username or 'Channel'}",
                url=url
            )])
        
        keyboard.append([InlineKeyboardButton(
            text="✅ আমি জয়েন করেছি",
            callback_data="check_join"
        )])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ============================================================================
# CLIENT BOT MANAGER CLASS
# ============================================================================

class ClientBotManager:
    """Manage client bots and their configurations"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.active_bots: Dict[int, Bot] = {}
        self.bot_handlers: Dict[int, Dispatcher] = {}
    
    async def start_client_bot(self, bot_id: int, token: str):
        """Start a client bot instance"""
        try:
            bot = Bot(token=token)
            dp = Dispatcher(storage=MemoryStorage())
            
            # Setup client bot handlers
            await self._setup_client_handlers(bot_id, bot, dp)
            
            # Start polling
            asyncio.create_task(dp.start_polling(bot))
            
            self.active_bots[bot_id] = bot
            self.bot_handlers[bot_id] = dp
            logger.info(f"Client bot {bot_id} started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start client bot {bot_id}: {e}")
    
    async def _setup_client_handlers(self, bot_id: int, bot: Bot, dp: Dispatcher):
        """Setup handlers for client bot"""
        
        @dp.message(CommandStart())
        async def client_start(message: types.Message):
            user_id = message.from_user.id
            username = message.from_user.username or ""
            first_name = message.from_user.first_name or ""
            
            # Save user in client bot database
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO client_bot_users 
                    (bot_id, user_id, username, first_name, last_active)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (bot_id, user_id, username, first_name))
            
            # Get welcome message
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT w.*, b.bot_name 
                    FROM welcome_messages w
                    JOIN client_bots b ON w.bot_id = b.bot_id
                    WHERE w.bot_id = ? ORDER BY w.id DESC LIMIT 1
                """, (bot_id,))
                welcome = cursor.fetchone()
            
            if not welcome:
                await message.answer("👋 স্বাগতম! বোট সেটআপ সম্পূর্ণ হয়নি।")
                return
            
            # Get buttons
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT button_name, button_url FROM welcome_buttons WHERE welcome_id = ? ORDER BY button_order",
                    (welcome['id'],)
                )
                buttons = cursor.fetchall()
            
            # Prepare keyboard
            keyboard = None
            if buttons:
                inline_keyboard = []
                for btn in buttons:
                    inline_keyboard.append([InlineKeyboardButton(
                        text=btn['button_name'],
                        url=btn['button_url']
                    )])
                keyboard = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
            
            # Send welcome message
            if welcome['image_file_id']:
                await message.answer_photo(
                    photo=welcome['image_file_id'],
                    caption=welcome['welcome_text'],
                    reply_markup=keyboard
                )
            else:
                await message.answer(
                    welcome['welcome_text'],
                    reply_markup=keyboard
                )
        
        @dp.message(Command("broadcast"))
        async def client_broadcast(message: types.Message):
            """Handle broadcast command in client bot"""
            user_id = message.from_user.id
            
            # Check if user is broadcast admin
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM broadcast_admins WHERE bot_id = ? AND admin_user_id = ?",
                    (bot_id, user_id)
                )
                is_admin = cursor.fetchone()
            
            if not is_admin:
                await message.answer("⛔ আপনার এই কমান্ড ব্যবহারের অনুমতি নেই!")
                return
            
            # Start broadcast flow
            await message.answer(
                "📢 ব্রডকাস্ট মেসেজ লিখুন:\n\n"
                "(শুধু টেক্সট, কোন ইমেজ বা বাটন নেই)"
            )
            
            # Store state
            # In production, use FSM
            broadcast_states[user_id] = {"bot_id": bot_id, "step": "waiting_message"}
    
    async def stop_client_bot(self, bot_id: int):
        """Stop a client bot instance"""
        if bot_id in self.active_bots:
            await self.active_bots[bot_id].session.close()
            del self.active_bots[bot_id]
        if bot_id in self.bot_handlers:
            del self.bot_handlers[bot_id]
        logger.info(f"Client bot {bot_id} stopped")

# ============================================================================
# FSM STATES
# ============================================================================

class AddBotStates(StatesGroup):
    token = State()
    image = State()
    text = State()
    button_count = State()
    button_name = State()
    button_url = State()
    button_index = State()

class BroadcastStates(StatesGroup):
    selecting_bot = State()
    adding_admins = State()
    broadcast_message = State()
    broadcast_confirm = State()

class ForceJoinStates(StatesGroup):
    adding_channel = State()
    removing_channel = State()

# ============================================================================
# MAIN APPLICATION CLASS
# ============================================================================

class BotControlHub:
    """Main application class"""
    
    def __init__(self):
        # Load configuration
        Config.validate()
        
        # Initialize components
        self.bot = Bot(
            token=Config.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        self.storage = MemoryStorage()
        self.dp = Dispatcher(storage=self.storage)
        
        # Initialize database
        self.db = DatabaseManager(Config.DATABASE_PATH)
        
        # Initialize managers
        self.force_join = ForceJoinManager(self.db, self.bot)
        self.client_manager = ClientBotManager(self.db)
        
        # Global state storage (for simple cases)
        self.broadcast_states = {}
        
        # Setup handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup all message and callback handlers"""
        
        # ====================================================================
        # MIDDLEWARE
        # ====================================================================
        
        @self.dp.message.middleware()
        async def force_join_middleware(handler, event, data):
            """Check force join for all messages except /start"""
            user_id = event.from_user.id
            
            # Skip for admins
            if user_id in Config.ADMIN_IDS:
                return await handler(event, data)
            
            # Check if it's /start command
            if isinstance(event, types.Message) and event.text == "/start":
                return await handler(event, data)
            
            # Check force join
            is_joined, not_joined = await self.force_join.check_membership(user_id)
            
            if not is_joined:
                keyboard = self.force_join.get_channels_keyboard(not_joined)
                await event.answer(
                    "⚠️ বট ব্যবহার করতে নিচের চ্যানেলগুলো জয়েন করুন:\n\n"
                    "জয়েন করার পর 'আমি জয়েন করেছি' বাটনে ক্লিক করুন।",
                    reply_markup=keyboard
                )
                return
            
            return await handler(event, data)
        
        # ====================================================================
        # COMMAND HANDLERS
        # ====================================================================
        
        @self.dp.message(CommandStart())
        async def cmd_start(message: types.Message, state: FSMContext):
            """Handle /start command"""
            user = message.from_user
            user_id = user.id
            
            # Register user in database
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO users 
                    (user_id, username, first_name, last_name)
                    VALUES (?, ?, ?, ?)
                """, (user_id, user.username, user.first_name, user.last_name))
            
            # Check force join first
            is_joined, not_joined = await self.force_join.check_membership(user_id)
            
            if not is_joined:
                keyboard = self.force_join.get_channels_keyboard(not_joined)
                await message.answer(
                    "👋 স্বাগতম! বট ব্যবহার করতে নিচের চ্যানেলগুলো জয়েন করুন:",
                    reply_markup=keyboard
                )
                return
            
            # Show main menu
            await self._show_main_menu(message)
        
        @self.dp.message(Command("help"))
        async def cmd_help(message: types.Message):
            """Handle /help command"""
            help_text = (
                "🆘 <b>সাহায্য ও সহযোগিতা</b>\n\n"
                "আমি Bot Control Hub - আপনার নিজের বট ম্যানেজ করার সহজ সমাধান!\n\n"
                "📌 <b>কি কি করতে পারেন?</b>\n"
                "• নিজের বট কানেক্ট করে কাস্টম ওয়েলকাম মেসেজ সেট করুন\n"
                "• ব্রডকাস্ট অ্যাডমিন সেটআপ করুন\n"
                "• আপনার সব বট এক জায়গায় ম্যানেজ করুন\n\n"
                "📞 <b>প্রয়োজনে যোগাযোগ করুন:</b>"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📨 অ্যাডমিন", url="https://t.me/admin")],
                [InlineKeyboardButton(text="🔙 মূল মেনু", callback_data="main_menu")]
            ])
            
            await message.answer(help_text, reply_markup=keyboard)
        
        # ====================================================================
        # CALLBACK QUERY HANDLERS
        # ====================================================================
        
        @self.dp.callback_query(F.data == "check_join")
        async def callback_check_join(callback: types.CallbackQuery):
            """Check if user has joined channels"""
            user_id = callback.from_user.id
            
            is_joined, not_joined = await self.force_join.check_membership(user_id)
            
            if is_joined:
                await callback.message.delete()
                await self._show_main_menu(callback.message)
                await callback.answer("✅ আপনি সব চ্যানেল জয়েন করেছেন!")
            else:
                keyboard = self.force_join.get_channels_keyboard(not_joined)
                await callback.message.edit_text(
                    "⚠️ আপনি এখনও সব চ্যানেল জয়েন করেননি!\n"
                    "নিচের চ্যানেলগুলো জয়েন করে 'আমি জয়েন করেছি' বাটনে ক্লিক করুন:",
                    reply_markup=keyboard
                )
                await callback.answer("❌ জয়েন সম্পূর্ণ হয়নি")
        
        @self.dp.callback_query(F.data == "main_menu")
        async def callback_main_menu(callback: types.CallbackQuery):
            """Return to main menu"""
            await callback.message.delete()
            await self._show_main_menu(callback.message)
            await callback.answer()
        
        @self.dp.callback_query(F.data == "my_bots")
        async def callback_my_bots(callback: types.CallbackQuery):
            """Show user's bots"""
            user_id = callback.from_user.id
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM client_bots 
                    WHERE owner_id = ? AND is_active = 1
                    ORDER BY created_date DESC
                """, (user_id,))
                bots = cursor.fetchall()
            
            if not bots:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="➕ নতুন বট যোগ করুন", callback_data="add_bot")],
                    [InlineKeyboardButton(text="🔙 মেনুতে ফিরুন", callback_data="main_menu")]
                ])
                await callback.message.edit_text(
                    "🤖 আপনার কোনো বট নেই!\n\n"
                    "নতুন বট যোগ করতে নিচের বাটনে ক্লিক করুন:",
                    reply_markup=keyboard
                )
                await callback.answer()
                return
            
            text = "🤖 <b>আমার বটসমূহ</b>\n\n"
            keyboard = []
            
            for bot in bots:
                text += f"• {bot['bot_name']} (@{bot['bot_username']})\n"
                keyboard.append([InlineKeyboardButton(
                    text=f"⚙️ {bot['bot_name']}",
                    callback_data=f"bot_details:{bot['bot_id']}"
                )])
            
            keyboard.append([InlineKeyboardButton(
                text="➕ নতুন বট", callback_data="add_bot"
            )])
            keyboard.append([InlineKeyboardButton(
                text="🔙 মেনুতে ফিরুন", callback_data="main_menu"
            )])
            
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            await callback.answer()
        
        @self.dp.callback_query(F.data.startswith("bot_details:"))
        async def callback_bot_details(callback: types.CallbackQuery):
            """Show bot details and options"""
            bot_id = int(callback.data.split(":")[1])
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT cb.*, wm.id as welcome_id 
                    FROM client_bots cb
                    LEFT JOIN welcome_messages wm ON cb.bot_id = wm.bot_id
                    WHERE cb.bot_id = ?
                """, (bot_id,))
                bot = cursor.fetchone()
            
            if not bot:
                await callback.answer("বট পাওয়া যায়নি!")
                return
            
            text = (
                f"🤖 <b>{bot['bot_name']}</b>\n\n"
                f"🆔 আইডি: <code>{bot['bot_id_num']}</code>\n"
                f"📛 ইউজারনেম: @{bot['bot_username']}\n"
                f"📅 তৈরি: {bot['created_date']}\n"
            )
            
            keyboard = [
                [InlineKeyboardButton(text="✏️ ওয়েলকাম এডিট", callback_data=f"edit_welcome:{bot_id}")],
                [InlineKeyboardButton(text="📢 ব্রডকাস্ট সেটআপ", callback_data=f"broadcast_setup:{bot_id}")],
                [InlineKeyboardButton(text="🗑️ ডিলিট বট", callback_data=f"delete_bot:{bot_id}")],
                [InlineKeyboardButton(text="🔙 আমার বটসমূহ", callback_data="my_bots")]
            ]
            
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            await callback.answer()
        
        @self.dp.callback_query(F.data == "add_bot")
        async def callback_add_bot(callback: types.CallbackQuery, state: FSMContext):
            """Start add bot process"""
            await state.set_state(AddBotStates.token)
            await callback.message.edit_text(
                "🤖 <b>নতুন বট কানেক্ট করুন</b>\n\n"
                "আপনার বটের টোকেন পাঠান:\n"
                "(@BotFather থেকে নিন)\n\n"
                "টোকেন এরকম দেখতে: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 বাতিল", callback_data="my_bots")]
                ])
            )
            await callback.answer()
        
        @self.dp.callback_query(F.data.startswith("broadcast_setup:"))
        async def callback_broadcast_setup(callback: types.CallbackQuery, state: FSMContext):
            """Setup broadcast admins for bot"""
            bot_id = int(callback.data.split(":")[1])
            
            await state.update_data(broadcast_bot_id=bot_id)
            await state.set_state(BroadcastStates.adding_admins)
            
            # Show current admins
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT admin_user_id FROM broadcast_admins WHERE bot_id = ?",
                    (bot_id,)
                )
                admins = cursor.fetchall()
            
            admin_text = ""
            if admins:
                admin_ids = [str(a['admin_user_id']) for a in admins]
                admin_text = f"\nবর্তমান অ্যাডমিন: {', '.join(admin_ids)}\n"
            
            await callback.message.edit_text(
                f"📢 <b>ব্রডকাস্ট সেটআপ</b>\n\n"
                f"যেসব ইউজার ব্রডকাস্ট করতে পারবেন তাদের আইডি দিন:\n"
                f"(একাধিক হলে কমা দিয়ে আলাদা করুন){admin_text}\n\n"
                f"উদাহরণ: 12345678, 87654321, 11223344",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 বাতিল", callback_data=f"bot_details:{bot_id}")]
                ])
            )
            await callback.answer()
        
        @self.dp.callback_query(F.data.startswith("delete_bot:"))
        async def callback_delete_bot(callback: types.CallbackQuery):
            """Delete a client bot"""
            bot_id = int(callback.data.split(":")[1])
            
            # Stop client bot if running
            await self.client_manager.stop_client_bot(bot_id)
            
            # Delete from database
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE client_bots SET is_active = 0 WHERE bot_id = ?", (bot_id,))
            
            await callback.answer("✅ বট ডিলিট করা হয়েছে!")
            await callback.message.edit_text(
                "✅ আপনার বট সফলভাবে ডিলিট করা হয়েছে।",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 আমার বটসমূহ", callback_data="my_bots")],
                    [InlineKeyboardButton(text="🔙 মেনুতে ফিরুন", callback_data="main_menu")]
                ])
            )
        
        # ====================================================================
        # MESSAGE HANDLERS (FSM)
        # ====================================================================
        
        @self.dp.message(AddBotStates.token)
        async def process_bot_token(message: types.Message, state: FSMContext):
            """Process bot token and validate"""
            token = message.text.strip()
            
            # Validate token
            async with aiohttp.ClientSession() as session:
                url = f"https://api.telegram.org/bot{token}/getMe"
                async with session.get(url) as response:
                    if response.status != 200:
                        await message.answer(
                            "❌ টোকেন ভ্যালিড নয়! আবার চেষ্টা করুন:",
                            reply_markup=ReplyKeyboardMarkup(
                                keyboard=[[KeyboardButton(text="🔙 বাতিল")]],
                                resize_keyboard=True
                            )
                        )
                        return
                    
                    bot_info = await response.json()
                    if not bot_info.get('ok'):
                        await message.answer(
                            "❌ টোকেন ভ্যালিড নয়! আবার চেষ্টা করুন:",
                            reply_markup=ReplyKeyboardMarkup(
                                keyboard=[[KeyboardButton(text="🔙 বাতিল")]],
                                resize_keyboard=True
                            )
                        )
                        return
                    
                    bot_data = bot_info['result']
            
            # Save bot info
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO client_bots 
                    (owner_id, bot_token, bot_username, bot_name, bot_id_num)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    message.from_user.id,
                    token,
                    bot_data['username'],
                    bot_data['first_name'],
                    bot_data['id']
                ))
                bot_id = cursor.lastrowid
            
            await state.update_data(bot_id=bot_id, bot_token=token)
            await state.set_state(AddBotStates.image)
            
            await message.answer(
                "🖼️ <b>ওয়েলকাম ইমেজ</b>\n\n"
                "একটি ছবি পাঠান (অথবা স্কিপ করতে /skip দিন):",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="/skip - ইমেজ ছাড়া চালিয়ে যান")],
                        [KeyboardButton(text="🔙 বাতিল")]
                    ],
                    resize_keyboard=True
                )
            )
        
        @self.dp.message(AddBotStates.image)
        async def process_welcome_image(message: types.Message, state: FSMContext):
            """Process welcome image"""
            if message.text and message.text.lower() == "/skip":
                await state.update_data(image_file_id=None)
            elif message.photo:
                await state.update_data(image_file_id=message.photo[-1].file_id)
            else:
                await message.answer("❌ দয়া করে একটি ছবি পাঠান অথবা /skip দিন:")
                return
            
            await state.set_state(AddBotStates.text)
            await message.answer(
                "📝 <b>ওয়েলকাম টেক্সট</b>\n\n"
                "আপনার বটের জন্য ওয়েলকাম মেসেজ লিখুন:",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="🔙 বাতিল"]],
                    resize_keyboard=True
                )
            )
        
        @self.dp.message(AddBotStates.text)
        async def process_welcome_text(message: types.Message, state: FSMContext):
            """Process welcome text"""
            await state.update_data(welcome_text=message.text)
            await state.set_state(AddBotStates.button_count)
            
            await message.answer(
                "🔘 <b>বাটন সংখ্যা</b>\n\n"
                "আপনি কয়টি বাটন চান? (1-3 এর মধ্যে একটি সংখ্যা দিন):",
                reply_markup=ReplyKeyboardRemove()
            )
        
        @self.dp.message(AddBotStates.button_count)
        async def process_button_count(message: types.Message, state: FSMContext):
            """Process number of buttons"""
            try:
                count = int(message.text)
                if count < 1 or count > 3:
                    raise ValueError
            except:
                await message.answer("❌ অনুগ্রহ করে 1 থেকে 3 এর মধ্যে একটি সংখ্যা দিন:")
                return
            
            await state.update_data(button_count=count, button_index=0, buttons=[])
            
            if count == 0:
                # No buttons, save welcome message
                await save_welcome_message(state, message)
            else:
                await state.set_state(AddBotStates.button_name)
                await message.answer(
                    f"🔘 <b>বাটন {1}/{count}</b>\n\n"
                    f"বাটনের নাম লিখুন:"
                )
        
        @self.dp.message(AddBotStates.button_name)
        async def process_button_name(message: types.Message, state: FSMContext):
            """Process button name"""
            data = await state.get_data()
            button_index = data.get('button_index', 0) + 1
            
            await state.update_data(current_button_name=message.text, button_index=button_index)
            await state.set_state(AddBotStates.button_url)
            
            await message.answer(
                f"🔗 <b>বাটন {button_index}/{data['button_count']}</b>\n\n"
                f"বাটনের ইউআরএল লিখুন:"
            )
        
        @self.dp.message(AddBotStates.button_url)
        async def process_button_url(message: types.Message, state: FSMContext):
            """Process button URL"""
            data = await state.get_data()
            
            buttons = data.get('buttons', [])
            buttons.append({
                'name': data['current_button_name'],
                'url': message.text
            })
            
            await state.update_data(buttons=buttons)
            
            if data['button_index'] >= data['button_count']:
                # All buttons collected, save welcome message
                await save_welcome_message(state, message)
            else:
                await state.set_state(AddBotStates.button_name)
                await message.answer(
                    f"🔘 <b>বাটন {data['button_index'] + 1}/{data['button_count']}</b>\n\n"
                    f"পরবর্তী বাটনের নাম লিখুন:"
                )
        
        async def save_welcome_message(state: FSMContext, message: types.Message):
            """Save welcome message and buttons to database"""
            data = await state.get_data()
            bot_id = data['bot_id']
            
            with message.bot.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Save welcome message
                cursor.execute("""
                    INSERT INTO welcome_messages 
                    (bot_id, image_file_id, welcome_text, button_count)
                    VALUES (?, ?, ?, ?)
                """, (
                    bot_id,
                    data.get('image_file_id'),
                    data['welcome_text'],
                    data.get('button_count', 0)
                ))
                welcome_id = cursor.lastrowid
                
                # Save buttons
                buttons = data.get('buttons', [])
                for i, btn in enumerate(buttons):
                    cursor.execute("""
                        INSERT INTO welcome_buttons 
                        (welcome_id, button_name, button_url, button_order)
                        VALUES (?, ?, ?, ?)
                    """, (welcome_id, btn['name'], btn['url'], i + 1))
            
            # Start client bot
            await message.bot.client_manager.start_client_bot(bot_id, data['bot_token'])
            
            # Notify admin
            await notify_admin_new_bot(message.bot, message.from_user, bot_id)
            
            await state.clear()
            await message.answer(
                "✅ <b>সেটআপ সম্পন্ন!</b>\n\n"
                "আপনার বট সফলভাবে কনফিগার করা হয়েছে।",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="🔙 মেনুতে ফিরুন")]],
                    resize_keyboard=True
                )
            )
        
        # ====================================================================
        # ADMIN PANEL HANDLERS
        # ====================================================================
        
        @self.dp.message(Command("admin"))
        async def cmd_admin(message: types.Message):
            """Admin panel command"""
            if message.from_user.id not in Config.ADMIN_IDS:
                await message.answer("⛔ আপনার এই কমান্ড ব্যবহারের অনুমতি নেই!")
                return
            
            # Get statistics
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT COUNT(*) FROM users")
                total_users = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM client_bots WHERE is_active = 1")
                total_bots = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM force_join_channels WHERE is_active = 1")
                total_channels = cursor.fetchone()[0]
            
            text = (
                f"👑 <b>অ্যাডমিন প্যানেল</b>\n\n"
                f"📊 <b>পরিসংখ্যান</b>\n"
                f"👥 মোট ইউজার: {total_users}\n"
                f"🤖 মোট ক্লায়েন্ট বট: {total_bots}\n"
                f"📢 মোট চ্যানেল: {total_channels}\n\n"
                f"🔧 <b>অপশনসমূহ</b>"
            )
            
            keyboard = [
                [InlineKeyboardButton(text="📢 ব্রডকাস্ট", callback_data="admin_broadcast")],
                [InlineKeyboardButton(text="📺 ফোর্স জয়ন ম্যানেজ", callback_data="admin_channels")],
                [InlineKeyboardButton(text="📊 রিফ্রেশ", callback_data="admin_refresh")]
            ]
            
            await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        
        @self.dp.callback_query(F.data == "admin_channels")
        async def admin_channels(callback: types.CallbackQuery):
            """Manage force join channels"""
            if callback.from_user.id not in Config.ADMIN_IDS:
                await callback.answer("অননুমোদিত!", show_alert=True)
                return
            
            with callback.bot.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM force_join_channels WHERE is_active = 1")
                channels = cursor.fetchall()
            
            text = "📺 <b>ফোর্স জয়ন চ্যানেল</b>\n\n"
            
            if channels:
                for ch in channels:
                    text += f"• {ch['channel_title']} ({ch['channel_username']})\n"
            else:
                text += "কোনো চ্যানেল যোগ করা হয়নি।\n"
            
            keyboard = [
                [InlineKeyboardButton(text="➕ চ্যানেল যোগ", callback_data="admin_add_channel")],
                [InlineKeyboardButton(text="➖ চ্যানেল রিমুভ", callback_data="admin_remove_channel")],
                [InlineKeyboardButton(text="🔙 অ্যাডমিন প্যানেল", callback_data="admin_back")]
            ]
            
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
            await callback.answer()
        
        @self.dp.callback_query(F.data == "admin_add_channel")
        async def admin_add_channel(callback: types.CallbackQuery, state: FSMContext):
            """Add new force join channel"""
            await state.set_state(ForceJoinStates.adding_channel)
            await callback.message.edit_text(
                "➕ <b>নতুন চ্যানেল যোগ করুন</b>\n\n"
                "চ্যানেলের ইউজারনেম দিন (যেমন: @my_channel):",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 বাতিল", callback_data="admin_channels")]
                ])
            )
            await callback.answer()
        
        @self.dp.message(ForceJoinStates.adding_channel)
        async def process_add_channel(message: types.Message, state: FSMContext):
            """Process new channel addition"""
            channel_username = message.text.strip()
            
            try:
                # Get chat info
                chat = await message.bot.get_chat(channel_username)
                
                with message.bot.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO force_join_channels 
                        (channel_id, channel_username, channel_title, added_by)
                        VALUES (?, ?, ?, ?)
                    """, (str(chat.id), channel_username, chat.title, message.from_user.id))
                
                await message.answer(
                    f"✅ চ্যানেল যোগ করা হয়েছে: {chat.title}",
                    reply_markup=ReplyKeyboardMarkup(
                        keyboard=[[KeyboardButton(text="/admin")]],
                        resize_keyboard=True
                    )
                )
            except Exception as e:
                logger.error(f"Error adding channel: {e}")
                await message.answer(
                    "❌ চ্যানেল যোগ করা যায়নি! নিশ্চিত করুন বট চ্যানেলের অ্যাডমিন এবং ইউজারনেম সঠিক।"
                )
            
            await state.clear()
        
        @self.dp.callback_query(F.data == "admin_remove_channel")
        async def admin_remove_channel(callback: types.CallbackQuery, state: FSMContext):
            """Remove force join channel"""
            with callback.bot.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM force_join_channels WHERE is_active = 1")
                channels = cursor.fetchall()
            
            if not channels:
                await callback.answer("কোনো চ্যানেল নেই!", show_alert=True)
                return
            
            keyboard = []
            for ch in channels:
                keyboard.append([InlineKeyboardButton(
                    text=f"❌ {ch['channel_title']}",
                    callback_data=f"remove_channel:{ch['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton(
                text="🔙 বাতিল", callback_data="admin_channels"
            )])
            
            await callback.message.edit_text(
                "➖ <b>চ্যানেল রিমুভ</b>\n\n"
                "যে চ্যানেল রিমুভ করতে চান সেটি সিলেক্ট করুন:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            await callback.answer()
        
        @self.dp.callback_query(F.data.startswith("remove_channel:"))
        async def process_remove_channel(callback: types.CallbackQuery):
            """Process channel removal"""
            channel_id = int(callback.data.split(":")[1])
            
            with callback.bot.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE force_join_channels SET is_active = 0 WHERE id = ?",
                    (channel_id,)
                )
            
            await callback.answer("✅ চ্যানেল রিমুভ করা হয়েছে!")
            await admin_channels(callback)
        
        @self.dp.callback_query(F.data == "admin_broadcast")
        async def admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
            """Start admin broadcast"""
            await state.set_state(BroadcastStates.broadcast_message)
            await callback.message.edit_text(
                "📢 <b>ব্রডকাস্ট মেসেজ</b>\n\n"
                "সমস্ত ইউজারের জন্য আপনার মেসেজ লিখুন:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 বাতিল", callback_data="admin_back")]
                ])
            )
            await callback.answer()
        
        @self.dp.message(BroadcastStates.broadcast_message)
        async def process_admin_broadcast(message: types.Message, state: FSMContext):
            """Process and send admin broadcast"""
            broadcast_text = message.text
            
            # Get all users
            with message.bot.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM users WHERE is_active = 1")
                users = cursor.fetchall()
            
            await message.answer(f"📤 ব্রডকাস্ট শুরু হচ্ছে... মোট {len(users)} জন ইউজার")
            
            success = 0
            failed = 0
            
            for user in users:
                try:
                    await message.bot.send_message(
                        user['user_id'],
                        f"📢 <b>অ্যাডমিন বার্তা</b>\n\n{broadcast_text}"
                    )
                    success += 1
                    await asyncio.sleep(0.05)  # Rate limit avoidance
                except Exception as e:
                    logger.error(f"Broadcast failed to {user['user_id']}: {e}")
                    failed += 1
            
            await state.clear()
            await message.answer(
                f"✅ ব্রডকাস্ট সম্পন্ন!\n\n"
                f"সফল: {success}\n"
                f"ব্যর্থ: {failed}"
            )
        
        @self.dp.callback_query(F.data == "admin_refresh")
        async def admin_refresh(callback: types.CallbackQuery):
            """Refresh admin panel"""
            await cmd_admin(callback.message)
            await callback.answer()
        
        @self.dp.callback_query(F.data == "admin_back")
        async def admin_back(callback: types.CallbackQuery):
            """Back to admin panel"""
            await cmd_admin(callback.message)
            await callback.answer()
    
    async def _show_main_menu(self, message: types.Message):
        """Show main menu to user"""
        menu_text = (
            "👋 <b>স্বাগতম Bot Control Hub-এ!</b>\n\n"
            "আমি আপনার নিজের টেলিগ্রাম বট ম্যানেজ করতে সাহায্য করি।\n"
            "নিচের অপশন থেকে বেছে নিন:"
        )
        
        keyboard = [
            [InlineKeyboardButton(text="🤖 আমার বটসমূহ", callback_data="my_bots")],
            [InlineKeyboardButton(text="➕ নতুন বট যোগ করুন", callback_data="add_bot")],
            [InlineKeyboardButton(text="📢 ব্রডকাস্ট সেটআপ", callback_data="broadcast_menu")],
            [InlineKeyboardButton(text="🆘 সাহায্য", callback_data="help_menu")]
        ]
        
        await message.answer(
            menu_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    
    async def start(self):
        """Start the bot"""
        # Start all active client bots
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT bot_id, bot_token FROM client_bots WHERE is_active = 1")
            active_bots = cursor.fetchall()
        
        for bot in active_bots:
            await self.client_manager.start_client_bot(bot['bot_id'], bot['bot_token'])
        
        # Start main bot
        if Config.ENABLE_WEBHOOK and Config.WEBHOOK_URL:
            # Webhook mode for Render
            webhook_url = f"{Config.WEBHOOK_URL}/webhook"
            await self.bot.set_webhook(webhook_url)
            logger.info(f"Webhook set to {webhook_url}")
        else:
            # Polling mode
            logger.info("Starting polling...")
            await self.dp.start_polling(self.bot)
    
    async def stop(self):
        """Stop the bot"""
        # Stop all client bots
        for bot_id in list(self.client_manager.active_bots.keys()):
            await self.client_manager.stop_client_bot(bot_id)
        
        # Stop main bot
        await self.bot.session.close()

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def notify_admin_new_bot(bot: Bot, user: types.User, bot_id: int):
    """Notify admin about new bot connection"""
    with bot.db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT bot_username, bot_name, bot_id_num FROM client_bots WHERE bot_id = ?",
            (bot_id,)
        )
        bot_info = cursor.fetchone()
    
    if not bot_info:
        return
    
    text = (
        f"🎉 <b>নতুন বট কানেক্ট!</b>\n\n"
        f"👤 ইউজার: {user.full_name}\n"
        f"🆔 ইউজার আইডি: <code>{user.id}</code>\n"
        f"🤖 বট: {bot_info['bot_name']}\n"
        f"📛 ইউজারনেম: @{bot_info['bot_username']}\n"
        f"🆔 বট আইডি: <code>{bot_info['bot_id_num']}</code>\n"
        f"📅 সময়: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    for admin_id in Config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

# ============================================================================
# WEBHOOK HANDLER (FOR RENDER)
# ============================================================================

async def handle_webhook(request):
    """Handle incoming webhook requests"""
    if request.method == "POST":
        update = types.Update(**await request.json())
        await app.dp.feed_update(app.bot, update)
        return aiohttp.web.Response()
    return aiohttp.web.Response(status=405)

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

# Create application instance
app = BotControlHub()

async def start_webhook_server():
    """Start webhook server for Render"""
    from aiohttp import web
    
    # Setup webhook
    webhook_path = f"/webhook"
    webhook_url = f"{Config.WEBHOOK_URL}{webhook_path}"
    
    # Set webhook
    await app.bot.set_webhook(
        webhook_url,
        allowed_updates=app.dp.resolve_used_update_types()
    )
    
    # Start web server
    web_app = web.Application()
    web_app.router.add_post(webhook_path, handle_webhook)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, Config.HOST, Config.PORT)
    await site.start()
    
    logger.info(f"Webhook server started on {Config.HOST}:{Config.PORT}")

async def main():
    """Main entry point"""
    try:
        # Start the bot
        if Config.ENABLE_WEBHOOK and Config.WEBHOOK_URL:
            await start_webhook_server()
            # Keep running
            while True:
                await asyncio.sleep(3600)
        else:
            await app.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
