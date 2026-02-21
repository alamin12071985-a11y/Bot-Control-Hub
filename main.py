import os
import logging
import sqlite3
import asyncio
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from contextlib import contextmanager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode
import aiosqlite

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')  # Set this in Render environment variables
ADMIN_IDS = [int(id) for id in os.environ.get('ADMIN_IDS', '').split(',') if id]  # Comma-separated admin IDs

# Database setup
DATABASE_FILE = 'bot_control_hub.db'

# Conversation states
(
    WAITING_BOT_TOKEN,
    WAITING_WELCOME_IMAGE,
    WAITING_WELCOME_TEXT,
    WAITING_BUTTON_COUNT,
    WAITING_BUTTON_NAME,
    WAITING_BUTTON_URL,
    WAITING_BROADCAST_IDS,
    WAITING_BROADCAST_MESSAGE,
    WAITING_BROADCAST_CONFIRM,
    WAITING_ADD_CHANNEL,
    WAITING_REMOVE_CHANNEL,
    WAITING_ADMIN_BROADCAST,
) = range(12)

# Temporary storage for user sessions
user_sessions: Dict[int, Dict] = {}

# Database helper functions
@contextmanager
def get_db():
    """Synchronous database connection context manager."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

async def init_database():
    """Initialize database tables asynchronously."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Users table (main bot users)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        
        # Force join channels table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS force_join_channels (
                channel_id TEXT PRIMARY KEY,
                channel_username TEXT,
                channel_title TEXT,
                added_by INTEGER,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (added_by) REFERENCES users(user_id)
            )
        ''')
        
        # Client bots table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS client_bots (
                bot_token TEXT PRIMARY KEY,
                bot_id INTEGER,
                bot_username TEXT,
                bot_name TEXT,
                owner_id INTEGER,
                welcome_image TEXT,
                welcome_text TEXT,
                button_count INTEGER DEFAULT 0,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY (owner_id) REFERENCES users(user_id)
            )
        ''')
        
        # Bot buttons table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS bot_buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_token TEXT,
                button_name TEXT,
                button_url TEXT,
                button_order INTEGER,
                FOREIGN KEY (bot_token) REFERENCES client_bots(bot_token)
            )
        ''')
        
        # Client bot users table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS client_bot_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_token TEXT,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bot_token, user_id),
                FOREIGN KEY (bot_token) REFERENCES client_bots(bot_token)
            )
        ''')
        
        # Broadcast admins table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS broadcast_admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_token TEXT,
                admin_id INTEGER,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bot_token, admin_id),
                FOREIGN KEY (bot_token) REFERENCES client_bots(bot_token)
            )
        ''')
        
        await db.commit()

# Helper functions
async def check_force_join(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, List[Dict]]:
    """Check if user has joined all required channels."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT channel_id, channel_username, channel_title FROM force_join_channels') as cursor:
            channels = await cursor.fetchall()
    
    if not channels:
        return True, []
    
    not_joined = []
    for channel in channels:
        channel_id, username, title = channel
        try:
            member = await context.bot.get_chat_member(chat_id=f"@{username}", user_id=user_id)
            if member.status in ['left', 'kicked']:
                not_joined.append({'id': channel_id, 'username': username, 'title': title})
        except Exception as e:
            logger.error(f"Error checking channel {username}: {e}")
            not_joined.append({'id': channel_id, 'username': username, 'title': title})
    
    return len(not_joined) == 0, not_joined

def get_main_menu_keyboard():
    """Get main menu reply keyboard."""
    keyboard = [
        [KeyboardButton("🤖 আমার বটসমূহ"), KeyboardButton("➕ নতুন বট যুক্ত করুন")],
        [KeyboardButton("📢 ব্রডকাস্ট সেটআপ"), KeyboardButton("🆘 সাহায্য")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_back_keyboard():
    """Get back button keyboard."""
    keyboard = [[KeyboardButton("🔙 ফিরে যান")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard():
    """Get admin panel keyboard."""
    keyboard = [
        [KeyboardButton("📊 পরিসংখ্যান"), KeyboardButton("📢 ব্রডকাস্ট")],
        [KeyboardButton("📺 ফোর্স জয়েন"), KeyboardButton("🔙 ফিরে যান")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    
    # Register user in database
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, joined_date)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user.id, user.username, user.first_name, user.last_name))
        await db.commit()
    
    # Check force join
    joined, channels = await check_force_join(user.id, context)
    
    if not joined:
        keyboard = []
        for channel in channels:
            keyboard.append([InlineKeyboardButton(f"📢 {channel['title']}", url=f"https://t.me/{channel['username']}")])
        keyboard.append([InlineKeyboardButton("✅ আমি জয়েন করেছি", callback_data="check_join")])
        
        await update.message.reply_text(
            "🤖 **বট কন্ট্রোল হাবে স্বাগতম!**\n\n"
            "বট ব্যবহার করার জন্য নিচের চ্যানেলগুলোতে জয়েন করুন:\n\n"
            "জয়েন করার পর 'আমি জয়েন করেছি' বাটনে ক্লিক করুন।",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Welcome message
    welcome_text = (
        f"👋 হ্যালো {user.first_name}!\n\n"
        "🎉 **বট কন্ট্রোল হাবে আপনাকে স্বাগতম!**\n\n"
        "আমি আপনার ব্যক্তিগত টেলিগ্রাম বট ম্যানেজার। আপনি এখানে:\n\n"
        "✅ আপনার নিজের বট কানেক্ট করতে পারবেন\n"
        "✅ ওয়েলকাম মেসেজ সেটআপ করতে পারবেন\n"
        "✅ ব্রডকাস্ট অ্যাডমিন সেট করতে পারবেন\n"
        "✅ এবং আরও অনেক কিছু!\n\n"
        "**নিচের মেনু থেকে আপনার পছন্দের অপশন সিলেক্ট করুন:**"
    )
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "🆘 **সাহায্য ও সমর্থন**\n\n"
        "**বট ব্যবহারের নিয়ম:**\n"
        "1. /start - মূল মেনু দেখুন\n"
        "2. '🤖 আমার বটসমূহ' - আপনার বটগুলোর তালিকা\n"
        "3. '➕ নতুন বট যুক্ত করুন' - নতুন বট কানেক্ট করুন\n"
        "4. '📢 ব্রডকাস্ট সেটআপ' - ব্রডকাস্ট অ্যাডমিন সেট করুন\n\n"
        "**প্রয়োজনে:**\n"
        "• কোন সমস্যা হলে অ্যাডমিনের সাথে যোগাযোগ করুন\n"
        "• বট টোকেন সঠিক আছে কিনা চেক করুন\n"
        "• প্রতিটি বটের জন্য আলাদা সেটিংস রাখুন\n\n"
        "📞 **অ্যাডমিনের সাথে যোগাযোগ:**"
    )
    
    keyboard = [[InlineKeyboardButton("📞 অ্যাডমিন", url="https://t.me/your_admin_username")]]
    await update.message.reply_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

# Force join check callback
async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle check join button callback."""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    joined, channels = await check_force_join(user.id, context)
    
    if joined:
        await query.edit_message_text(
            "✅ **ধন্যবাদ! আপনি সব চ্যানেলে জয়েন করেছেন।**\n\n"
            "এখন আপনি বট ব্যবহার করতে পারবেন। /start দিন আবার।",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        keyboard = []
        for channel in channels:
            keyboard.append([InlineKeyboardButton(f"📢 {channel['title']}", url=f"https://t.me/{channel['username']}")])
        keyboard.append([InlineKeyboardButton("✅ আমি জয়েন করেছি", callback_data="check_join")])
        
        await query.edit_message_text(
            "❌ আপনি এখনও সব চ্যানেলে জয়েন করেননি!\n\n"
            "নিচের চ্যানেলগুলোতে জয়েন করে 'আমি জয়েন করেছি' বাটনে ক্লিক করুন:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

# Add new bot conversation
async def add_new_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start add new bot conversation."""
    # Check force join first
    user = update.effective_user
    joined, _ = await check_force_join(user.id, context)
    
    if not joined:
        await update.message.reply_text(
            "❌ আগে সব চ্যানেলে জয়েন করুন! /start দিন।"
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        "🤖 **নতুন বট কানেক্ট করুন**\n\n"
        "আপনার বটের টোকেন দিন। টোকেন পেতে @BotFather থেকে /newbot করে বট বানান।\n\n"
        "টোকেন দেখতে এমন হবে:\n`1234567890:ABCdefGHIJklmNOPqrstUVwxyz`",
        reply_markup=get_back_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_BOT_TOKEN

async def process_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process bot token."""
    if update.message.text == "🔙 ফিরে যান":
        await update.message.reply_text(
            "মূল মেনুতে ফিরে আসছি...",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END
    
    token = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Validate token by trying to get bot info
    try:
        # Create temporary application for this bot
        temp_app = Application.builder().token(token).build()
        async with temp_app:
            bot = temp_app.bot
            bot_info = await bot.get_me()
            
            # Save bot info temporarily
            context.user_data['temp_bot_token'] = token
            context.user_data['temp_bot_info'] = {
                'id': bot_info.id,
                'username': bot_info.username,
                'name': bot_info.first_name
            }
            
            await update.message.reply_text(
                f"✅ **বট পাওয়া গেছে!**\n\n"
                f"বটের নাম: {bot_info.first_name}\n"
                f"ইউজারনেম: @{bot_info.username}\n"
                f"বট আইডি: `{bot_info.id}`\n\n"
                f"এখন একটি ওয়েলকাম ইমেজ দিন (অথবা স্কিপ করতে /skip দিন):",
                parse_mode=ParseMode.MARKDOWN
            )
            return WAITING_WELCOME_IMAGE
            
    except Exception as e:
        logger.error(f"Token validation error: {e}")
        await update.message.reply_text(
            "❌ **ভুল টোকেন!**\n\n"
            "টোকেন সঠিক কিনা চেক করুন। @BotFather থেকে টোকেন কপি করে আবার দিন।",
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_BOT_TOKEN

async def process_welcome_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process welcome image."""
    if update.message.text == "/skip":
        context.user_data['temp_welcome_image'] = None
        await update.message.reply_text(
            "📝 এখন ওয়েলকাম টেক্সট দিন:\n\n"
            "এই টেক্সটটি আপনার বটে /start দিলে ইউজার দেখতে পাবে।"
        )
        return WAITING_WELCOME_TEXT
    
    if update.message.photo:
        # Get the largest photo
        photo = update.message.photo[-1]
        context.user_data['temp_welcome_image'] = photo.file_id
        
        await update.message.reply_text(
            "✅ ইমেজ সংরক্ষিত হয়েছে!\n\n"
            "📝 এখন ওয়েলকাম টেক্সট দিন:"
        )
        return WAITING_WELCOME_TEXT
    
    await update.message.reply_text("❌ দয়া করে একটি ইমেজ দিন অথবা /skip দিন।")
    return WAITING_WELCOME_IMAGE

async def process_welcome_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process welcome text."""
    if update.message.text == "🔙 ফিরে যান":
        await update.message.reply_text(
            "মূল মেনুতে ফিরে আসছি...",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END
    
    context.user_data['temp_welcome_text'] = update.message.text
    
    await update.message.reply_text(
        "🔘 **বাটন সংখ্যা দিন**\n\n"
        "ওয়েলকাম মেসেজে কয়টি বাটন থাকবে? (1-3 এর মধ্যে সংখ্যা দিন)",
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_BUTTON_COUNT

async def process_button_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process button count."""
    try:
        count = int(update.message.text)
        if 1 <= count <= 3:
            context.user_data['temp_button_count'] = count
            context.user_data['temp_buttons'] = []
            context.user_data['temp_current_button'] = 1
            
            await update.message.reply_text(
                f"🔘 **বাটন {count}টি সেট করা হবে**\n\n"
                f"বাটন ১ এর নাম দিন:"
            )
            return WAITING_BUTTON_NAME
        else:
            raise ValueError
    except:
        await update.message.reply_text("❌ দয়া করে 1 থেকে 3 এর মধ্যে একটি সংখ্যা দিন।")
        return WAITING_BUTTON_COUNT

async def process_button_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process button name."""
    if update.message.text == "🔙 ফিরে যান":
        await update.message.reply_text(
            "মূল মেনুতে ফিরে আসছি...",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END
    
    current = context.user_data.get('temp_current_button', 1)
    context.user_data['temp_current_button_name'] = update.message.text
    
    await update.message.reply_text(
        f"🔗 বাটন {current} এর URL দিন (https:// দিয়ে শুরু করুন):"
    )
    return WAITING_BUTTON_URL

async def process_button_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process button URL."""
    url = update.message.text
    if not url.startswith(('https://', 'http://', 't.me/')):
        await update.message.reply_text("❌ দয়া করে সঠিক URL দিন (https:// দিয়ে শুরু করুন)।")
        return WAITING_BUTTON_URL
    
    current = context.user_data.get('temp_current_button', 1)
    name = context.user_data.get('temp_current_button_name')
    
    context.user_data['temp_buttons'].append({
        'name': name,
        'url': url,
        'order': current
    })
    
    total = context.user_data.get('temp_button_count', 0)
    
    if current < total:
        context.user_data['temp_current_button'] = current + 1
        await update.message.reply_text(f"🔘 বাটন {current + 1} এর নাম দিন:")
        return WAITING_BUTTON_NAME
    else:
        # Save everything to database
        user_id = update.effective_user.id
        token = context.user_data['temp_bot_token']
        bot_info = context.user_data['temp_bot_info']
        welcome_image = context.user_data.get('temp_welcome_image')
        welcome_text = context.user_data['temp_welcome_text']
        buttons = context.user_data['temp_buttons']
        button_count = len(buttons)
        
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Save bot
            await db.execute('''
                INSERT INTO client_bots 
                (bot_token, bot_id, bot_username, bot_name, owner_id, welcome_image, welcome_text, button_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (token, bot_info['id'], bot_info['username'], bot_info['name'], 
                  user_id, welcome_image, welcome_text, button_count))
            
            # Save buttons
            for button in buttons:
                await db.execute('''
                    INSERT INTO bot_buttons (bot_token, button_name, button_url, button_order)
                    VALUES (?, ?, ?, ?)
                ''', (token, button['name'], button['url'], button['order']))
            
            await db.commit()
        
        # Notify system admin
        admin_notification = (
            f"🆕 **নতুন বট কানেক্ট হয়েছে!**\n\n"
            f"**মালিক:** {update.effective_user.first_name}\n"
            f"**মালিক আইডি:** `{user_id}`\n"
            f"**বট ইউজারনেম:** @{bot_info['username']}\n"
            f"**বট আইডি:** `{bot_info['id']}`\n"
            f"**তারিখ:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    admin_notification,
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
        
        # Clear temp data
        for key in ['temp_bot_token', 'temp_bot_info', 'temp_welcome_image', 
                    'temp_welcome_text', 'temp_buttons', 'temp_button_count',
                    'temp_current_button', 'temp_current_button_name']:
            context.user_data.pop(key, None)
        
        await update.message.reply_text(
            "🎉 **অভিনন্দন! আপনার বট সফলভাবে কানেক্ট হয়েছে!**\n\n"
            f"বটের নাম: {bot_info['name']}\n"
            f"ইউজারনেম: @{bot_info['username']}\n\n"
            "এখন আপনার বটে /start দিয়ে দেখতে পারেন।\n\n"
            "**পরবর্তী ধাপ:**\n"
            "• '📢 ব্রডকাস্ট সেটআপ' থেকে ব্রডকাস্ট অ্যাডমিন সেট করুন\n"
            "• '🤖 আমার বটসমূহ' থেকে বট এডিট করুন\n\n"
            "মূল মেনুতে ফিরে আসছি...",
            reply_markup=get_main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

# My bots
async def my_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's bots."""
    user_id = update.effective_user.id
    
    # Check force join
    joined, _ = await check_force_join(user_id, context)
    if not joined:
        await update.message.reply_text("❌ আগে সব চ্যানেলে জয়েন করুন! /start দিন।")
        return
    
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('''
            SELECT bot_token, bot_name, bot_username, welcome_text, button_count, created_date
            FROM client_bots 
            WHERE owner_id = ? AND is_active = 1
            ORDER BY created_date DESC
        ''', (user_id,)) as cursor:
            bots = await cursor.fetchall()
    
    if not bots:
        await update.message.reply_text(
            "🤔 আপনি এখনও কোন বট কানেক্ট করেননি!\n\n"
            "➕ 'নতুন বট যুক্ত করুন' বাটনে ক্লিক করে আপনার প্রথম বট কানেক্ট করুন।",
            reply_markup=get_main_menu_keyboard()
        )
        return
    
    for bot in bots:
        token, name, username, text, button_count, date = bot
        date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
        
        # Get buttons for this bot
        async with aiosqlite.connect(DATABASE_FILE) as db:
            async with db.execute('''
                SELECT button_name, button_url FROM bot_buttons 
                WHERE bot_token = ? ORDER BY button_order
            ''', (token,)) as cursor:
                buttons = await cursor.fetchall()
        
        buttons_text = ""
        if buttons:
            buttons_list = []
            for i, (name, url) in enumerate(buttons, 1):
                buttons_list.append(f"{i}. {name}")
            buttons_text = f"\n🔘 বাটন: {', '.join(buttons_list)}"
        
        bot_info = (
            f"🤖 **{name}**\n"
            f"🆔 @{username}\n"
            f"📝 ওয়েলকাম: {text[:50]}...\n"
            f"🔢 বাটন সংখ্যা: {button_count}{buttons_text}\n"
            f"📅 যোগের তারিখ: {date_obj.strftime('%d %b %Y, %I:%M %p')}\n\n"
            f"**অপশন:**"
        )
        
        keyboard = [
            [InlineKeyboardButton("✏️ ওয়েলকাম এডিট", callback_data=f"edit_welcome_{token}")],
            [InlineKeyboardButton("🗑 ডিলিট", callback_data=f"delete_bot_{token}")],
            [InlineKeyboardButton("ℹ️ বিস্তারিত", callback_data=f"bot_info_{token}")]
        ]
        
        await update.message.reply_text(
            bot_info,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    
    await update.message.reply_text(
        "🔝 মূল মেনুতে ফিরে যান:",
        reply_markup=get_main_menu_keyboard()
    )

# Broadcast setup
async def broadcast_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start broadcast setup conversation."""
    user_id = update.effective_user.id
    
    # Check force join
    joined, _ = await check_force_join(user_id, context)
    if not joined:
        await update.message.reply_text("❌ আগে সব চ্যানেলে জয়েন করুন! /start দিন।")
        return ConversationHandler.END
    
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('''
            SELECT bot_token, bot_name FROM client_bots 
            WHERE owner_id = ? AND is_active = 1
        ''', (user_id,)) as cursor:
            bots = await cursor.fetchall()
    
    if not bots:
        await update.message.reply_text(
            "🤔 আপনার কোন বট নেই! প্রথমে একটি বট কানেক্ট করুন।",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END
    
    keyboard = []
    for token, name in bots:
        keyboard.append([InlineKeyboardButton(f"🤖 {name}", callback_data=f"broadcast_bot_{token}")])
    
    await update.message.reply_text(
        "📢 **ব্রডকাস্ট সেটআপ**\n\n"
        "আপনার কোন বটের জন্য ব্রডকাস্ট অ্যাডমিন সেট করতে চান?\n\n"
        "ব্রডকাস্ট অ্যাডমিনরা আপনার বটে /broadcast কমান্ড ব্যবহার করে সব ইউজারকে মেসেজ পাঠাতে পারবেন।",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_BROADCAST_IDS

async def broadcast_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast bot selection."""
    query = update.callback_query
    await query.answer()
    
    token = query.data.replace('broadcast_bot_', '')
    context.user_data['broadcast_bot_token'] = token
    
    # Get current broadcast admins
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('''
            SELECT admin_id FROM broadcast_admins WHERE bot_token = ?
        ''', (token,)) as cursor:
            admins = await cursor.fetchall()
    
    admins_text = ""
    if admins:
        admin_list = [str(admin[0]) for admin in admins]
        admins_text = f"\nবর্তমান অ্যাডমিন: {', '.join(admin_list)}"
    
    await query.edit_message_text(
        f"📢 **ব্রডকাস্ট অ্যাডমিন সেট করুন**{admins_text}\n\n"
        "ইউজার আইডি দিন (একাধিক আইডি কমা দিয়ে আলাদা করুন):\n\n"
        "উদাহরণ: `123456789, 987654321, 456789123`",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_BROADCAST_IDS

async def process_broadcast_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process broadcast admin IDs."""
    if update.message.text == "🔙 ফিরে যান":
        await update.message.reply_text(
            "মূল মেনুতে ফিরে আসছি...",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END
    
    token = context.user_data.get('broadcast_bot_token')
    if not token:
        await update.message.reply_text("❌ কিছু সমস্যা হয়েছে। আবার চেষ্টা করুন।")
        return ConversationHandler.END
    
    try:
        admin_ids = [int(id.strip()) for id in update.message.text.split(',') if id.strip().isdigit()]
        
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Clear old admins
            await db.execute('DELETE FROM broadcast_admins WHERE bot_token = ?', (token,))
            
            # Add new admins
            for admin_id in admin_ids:
                await db.execute('''
                    INSERT OR REPLACE INTO broadcast_admins (bot_token, admin_id)
                    VALUES (?, ?)
                ''', (token, admin_id))
            
            await db.commit()
        
        # Get bot info
        async with aiosqlite.connect(DATABASE_FILE) as db:
            async with db.execute('SELECT bot_name FROM client_bots WHERE bot_token = ?', (token,)) as cursor:
                result = await cursor.fetchone()
                bot_name = result[0] if result else "অজানা বট"
        
        await update.message.reply_text(
            f"✅ **সেটআপ সম্পন্ন!**\n\n"
            f"বট: {bot_name}\n"
            f"ব্রডকাস্ট অ্যাডমিন: {len(admin_ids)} জন\n\n"
            f"এখন এই ইউজাররা আপনার বটে /broadcast কমান্ড ব্যবহার করতে পারবেন।",
            reply_markup=get_main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Clear temp data
        context.user_data.pop('broadcast_bot_token', None)
        
    except Exception as e:
        logger.error(f"Broadcast setup error: {e}")
        await update.message.reply_text(
            "❌ ভুল ফরম্যাট! দয়া করে সঠিক আইডি দিন।\n\n"
            "উদাহরণ: `123456789, 987654321`",
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_BROADCAST_IDS
    
    return ConversationHandler.END

# Admin panel
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "❌ এই প্যানেল শুধুমাত্র অ্যাডমিনদের জন্য!",
            reply_markup=get_main_menu_keyboard()
        )
        return
    
    await update.message.reply_text(
        "👑 **অ্যাডমিন প্যানেল**\n\n"
        "আপনি এখান থেকে সবকিছু নিয়ন্ত্রণ করতে পারবেন।",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin statistics."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Total users
        async with db.execute('SELECT COUNT(*) FROM users WHERE is_active = 1') as cursor:
            total_users = (await cursor.fetchone())[0]
        
        # Total client bots
        async with db.execute('SELECT COUNT(*) FROM client_bots WHERE is_active = 1') as cursor:
            total_bots = (await cursor.fetchone())[0]
        
        # Total channels
        async with db.execute('SELECT COUNT(*) FROM force_join_channels') as cursor:
            total_channels = (await cursor.fetchone())[0]
        
        # Active bots today
        async with db.execute('''
            SELECT COUNT(*) FROM client_bots 
            WHERE date(created_date) = date('now')
        ''') as cursor:
            new_bots_today = (await cursor.fetchone())[0]
        
        # New users today
        async with db.execute('''
            SELECT COUNT(*) FROM users 
            WHERE date(joined_date) = date('now')
        ''') as cursor:
            new_users_today = (await cursor.fetchone())[0]
    
    stats_text = (
        "📊 **পরিসংখ্যান**\n\n"
        f"👥 মোট ইউজার: {total_users}\n"
        f"🆕 আজকের ইউজার: {new_users_today}\n\n"
        f"🤖 মোট বট: {total_bots}\n"
        f"🆕 আজকের বট: {new_bots_today}\n\n"
        f"📺 ফোর্স জয়েন চ্যানেল: {total_channels}\n\n"
        f"**সিস্টেম তথ্য:**\n"
        f"📅 তারিখ: {datetime.now().strftime('%d %B %Y')}\n"
        f"⏰ সময়: {datetime.now().strftime('%I:%M %p')}"
    )
    
    await update.message.reply_text(
        stats_text,
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start admin broadcast."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    await update.message.reply_text(
        "📢 **অ্যাডমিন ব্রডকাস্ট**\n\n"
        "সব ইউজারকে পাঠানোর জন্য আপনার মেসেজ লিখুন:\n\n"
        "(শুধু টেক্সট সাপোর্ট করে)",
        reply_markup=get_back_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_ADMIN_BROADCAST

async def process_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process admin broadcast message."""
    if update.message.text == "🔙 ফিরে যান":
        await update.message.reply_text(
            "অ্যাডমিন প্যানেলে ফিরে আসছি...",
            reply_markup=get_admin_keyboard()
        )
        return ConversationHandler.END
    
    message = update.message.text
    
    # Get all users
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT user_id FROM users WHERE is_active = 1') as cursor:
            users = await cursor.fetchall()
    
    sent = 0
    failed = 0
    
    status_msg = await update.message.reply_text(
        "📤 ব্রডকাস্ট পাঠানো হচ্ছে... 0%",
        reply_markup=get_admin_keyboard()
    )
    
    for i, (user_id,) in enumerate(users, 1):
        try:
            await context.bot.send_message(
                user_id,
                f"📢 **অ্যাডমিন বার্তা**\n\n{message}",
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
        except Exception as e:
            logger.error(f"Broadcast to {user_id} failed: {e}")
            failed += 1
        
        if i % 10 == 0:
            percentage = (i / len(users)) * 100
            await status_msg.edit_text(f"📤 ব্রডকাস্ট পাঠানো হচ্ছে... {percentage:.1f}%")
    
    await status_msg.edit_text(
        f"✅ **ব্রডকাস্ট সম্পন্ন!**\n\n"
        f"✓ সফল: {sent}\n"
        f"✗ ব্যর্থ: {failed}\n"
        f"📊 মোট: {len(users)}",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return ConversationHandler.END

async def force_join_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show force join management menu."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('''
            SELECT channel_username, channel_title, added_date FROM force_join_channels
            ORDER BY added_date DESC
        ''') as cursor:
            channels = await cursor.fetchall()
    
    channels_text = ""
    if channels:
        channel_list = []
        for username, title, date in channels:
            date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
            channel_list.append(f"📺 {title} (@{username}) - {date_obj.strftime('%d %b')}")
        channels_text = "**বর্তমান চ্যানেল:**\n" + "\n".join(channel_list) + "\n\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ চ্যানেল যোগ করুন", callback_data="add_channel")],
        [InlineKeyboardButton("🗑 চ্যানেল রিমুভ করুন", callback_data="remove_channel")],
        [InlineKeyboardButton("🔙 ফিরে যান", callback_data="back_to_admin")]
    ]
    
    await update.message.reply_text(
        f"📺 **ফোর্স জয়েন ম্যানেজমেন্ট**\n\n"
        f"{channels_text}"
        f"মোট চ্যানেল: {len(channels)}টি",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle add channel callback."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "➕ **নতুন চ্যানেল যোগ করুন**\n\n"
        "চ্যানেলের ইউজারনেম দিন (শুধু ইউজারনেম, @ ছাড়া):\n\n"
        "উদাহরণ: `my_channel_name`",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_ADD_CHANNEL

async def process_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process add channel."""
    username = update.message.text.strip().replace('@', '')
    
    try:
        # Verify channel exists
        chat = await context.bot.get_chat(f"@{username}")
        
        if chat.type not in ['channel', 'supergroup']:
            await update.message.reply_text(
                "❌ এটি একটি বৈধ চ্যানেল নয়! দয়া করে সঠিক চ্যানেল ইউজারনেম দিন।"
            )
            return WAITING_ADD_CHANNEL
        
        # Save to database
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute('''
                INSERT OR REPLACE INTO force_join_channels (channel_id, channel_username, channel_title, added_by)
                VALUES (?, ?, ?, ?)
            ''', (str(chat.id), username, chat.title, update.effective_user.id))
            await db.commit()
        
        await update.message.reply_text(
            f"✅ **চ্যানেল যোগ করা হয়েছে!**\n\n"
            f"নাম: {chat.title}\n"
            f"ইউজারনেম: @{username}\n"
            f"আইডি: `{chat.id}`\n\n"
            f"এখন থেকে ইউজারদের এই চ্যানেলে জয়েন করতে হবে।",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Add channel error: {e}")
        await update.message.reply_text(
            "❌ চ্যানেল যাচাই করতে সমস্যা হয়েছে!\n\n"
            "নিশ্চিত করুন:\n"
            "• ইউজারনেম সঠিক\n"
            "• বট চ্যানেলের অ্যাডমিন\n"
            "• চ্যানেল পাবলিক",
            reply_markup=get_admin_keyboard()
        )
    
    return ConversationHandler.END

async def remove_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle remove channel callback."""
    query = update.callback_query
    await query.answer()
    
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT channel_username, channel_title FROM force_join_channels') as cursor:
            channels = await cursor.fetchall()
    
    if not channels:
        await query.edit_message_text(
            "❌ কোন চ্যানেল নেই!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 ফিরে যান", callback_data="back_to_admin")
            ]])
        )
        return ConversationHandler.END
    
    keyboard = []
    for username, title in channels:
        keyboard.append([InlineKeyboardButton(f"🗑 {title} (@{username})", callback_data=f"del_channel_{username}")])
    keyboard.append([InlineKeyboardButton("🔙 ফিরে যান", callback_data="back_to_admin")])
    
    await query.edit_message_text(
        "🗑 **চ্যানেল রিমুভ করুন**\n\n"
        "কোন চ্যানেলটি রিমুভ করতে চান?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_REMOVE_CHANNEL

async def process_remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process remove channel."""
    # This is handled by callback query
    pass

async def delete_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle delete channel callback."""
    query = update.callback_query
    await query.answer()
    
    username = query.data.replace('del_channel_', '')
    
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute('DELETE FROM force_join_channels WHERE channel_username = ?', (username,))
        await db.commit()
    
    await query.edit_message_text(
        f"✅ @{username} চ্যানেলটি রিমুভ করা হয়েছে!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 ফিরে যান", callback_data="back_to_admin")
        ]])
    )
    
    return ConversationHandler.END

async def back_to_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle back to admin callback."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👑 অ্যাডমিন প্যানেলে ফিরে আসছি...",
        reply_markup=get_admin_keyboard()
    )
    
    return ConversationHandler.END

# Bot info callbacks
async def edit_welcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle edit welcome callback."""
    query = update.callback_query
    await query.answer()
    
    token = query.data.replace('edit_welcome_', '')
    context.user_data['edit_bot_token'] = token
    
    await query.edit_message_text(
        "✏️ **ওয়েলকাম মেসেজ এডিট**\n\n"
        "নতুন ওয়েলকাম টেক্সট দিন:",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_WELCOME_TEXT

async def delete_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle delete bot callback."""
    query = update.callback_query
    await query.answer()
    
    token = query.data.replace('delete_bot_', '')
    
    keyboard = [
        [InlineKeyboardButton("✅ হ্যাঁ, ডিলিট করুন", callback_data=f"confirm_delete_{token}")],
        [InlineKeyboardButton("❌ না, বাতিল করুন", callback_data="cancel_delete")]
    ]
    
    await query.edit_message_text(
        "⚠️ **আপনি কি নিশ্চিত?**\n\n"
        "এই বট ডিলিট করলে এর সব তথ্য মুছে যাবে!\n\n"
        "আপনি কি এগিয়ে যেতে চান?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def confirm_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle confirm delete callback."""
    query = update.callback_query
    await query.answer()
    
    token = query.data.replace('confirm_delete_', '')
    
    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Delete bot and related data
        await db.execute('DELETE FROM bot_buttons WHERE bot_token = ?', (token,))
        await db.execute('DELETE FROM broadcast_admins WHERE bot_token = ?', (token,))
        await db.execute('DELETE FROM client_bot_users WHERE bot_token = ?', (token,))
        await db.execute('DELETE FROM client_bots WHERE bot_token = ?', (token,))
        await db.commit()
    
    await query.edit_message_text(
        "✅ **বট সফলভাবে ডিলিট করা হয়েছে!**",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 ফিরে যান", callback_data="back_to_bots")
        ]]),
        parse_mode=ParseMode.MARKDOWN
    )

async def cancel_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancel delete callback."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "✅ ডিলিট বাতিল করা হয়েছে।",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 ফিরে যান", callback_data="back_to_bots")
        ]])
    )

async def bot_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bot info callback."""
    query = update.callback_query
    await query.answer()
    
    token = query.data.replace('bot_info_', '')
    
    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Get bot info
        async with db.execute('''
            SELECT bot_name, bot_username, bot_id, welcome_text, button_count, created_date
            FROM client_bots WHERE bot_token = ?
        ''', (token,)) as cursor:
            bot = await cursor.fetchone()
        
        if not bot:
            await query.edit_message_text("❌ বট পাওয়া যায়নি!")
            return
        
        name, username, bot_id, text, button_count, date = bot
        
        # Get buttons
        async with db.execute('''
            SELECT button_name, button_url FROM bot_buttons 
            WHERE bot_token = ? ORDER BY button_order
        ''', (token,)) as cursor:
            buttons = await cursor.fetchall()
        
        # Get broadcast admins
        async with db.execute('''
            SELECT admin_id FROM broadcast_admins WHERE bot_token = ?
        ''', (token,)) as cursor:
            admins = await cursor.fetchall()
        
        # Get total users
        async with db.execute('''
            SELECT COUNT(*) FROM client_bot_users WHERE bot_token = ?
        ''', (token,)) as cursor:
            total_users = (await cursor.fetchone())[0]
    
    date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
    
    buttons_text = ""
    if buttons:
        buttons_list = []
        for i, (name, url) in enumerate(buttons, 1):
            buttons_list.append(f"{i}. [{name}]({url})")
        buttons_text = "\n".join(buttons_list)
    
    admins_text = ""
    if admins:
        admin_list = [str(a[0]) for a in admins]
        admins_text = f"📢 ব্রডকাস্ট অ্যাডমিন: {', '.join(admin_list)}"
    
    info_text = (
        f"ℹ️ **বটের বিস্তারিত তথ্য**\n\n"
        f"🤖 **নাম:** {name}\n"
        f"🆔 **ইউজারনেম:** @{username}\n"
        f"🔢 **বট আইডি:** `{bot_id}`\n"
        f"📝 **ওয়েলকাম টেক্সট:**\n{text}\n\n"
        f"🔘 **বাটন ({button_count}টি):**\n{buttons_text}\n\n"
        f"{admins_text}\n"
        f"👥 **মোট ইউজার:** {total_users}\n"
        f"📅 **যোগের তারিখ:** {date_obj.strftime('%d %b %Y, %I:%M %p')}"
    )
    
    await query.edit_message_text(
        info_text,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

async def back_to_bots_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle back to bots callback."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🤖 আপনার বটের তালিকায় ফিরে যান /start দিন।"
    )

# Handle menu buttons
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu button presses."""
    text = update.message.text
    
    if text == "🤖 আমার বটসমূহ":
        await my_bots(update, context)
    elif text == "➕ নতুন বট যুক্ত করুন":
        await add_new_bot(update, context)
    elif text == "📢 ব্রডকাস্ট সেটআপ":
        await broadcast_setup(update, context)
    elif text == "🆘 সাহায্য":
        await help_command(update, context)
    elif text == "📊 পরিসংখ্যান" and update.effective_user.id in ADMIN_IDS:
        await admin_stats(update, context)
    elif text == "📢 ব্রডকাস্ট" and update.effective_user.id in ADMIN_IDS:
        await admin_broadcast(update, context)
    elif text == "📺 ফোর্স জয়েন" and update.effective_user.id in ADMIN_IDS:
        await force_join_management(update, context)
    elif text == "👑 অ্যাডমিন প্যানেল" and update.effective_user.id in ADMIN_IDS:
        await admin_panel(update, context)
    elif text == "🔙 ফিরে যান":
        await update.message.reply_text(
            "মূল মেনুতে ফিরে আসছি...",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            "🤔 দয়া করে মেনু থেকে একটি অপশন সিলেক্ট করুন।",
            reply_markup=get_main_menu_keyboard()
        )

# Cancel conversation
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation."""
    await update.message.reply_text(
        "🚫 অপারেশন বাতিল করা হয়েছে।",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "😔 দুঃখিত, একটি ত্রুটি হয়েছে। আবার চেষ্টা করুন।"
            )
    except:
        pass

# Client bot handling
async def handle_client_bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle start command for client bots."""
    # This function will be called when someone starts a client bot
    # We need to get the bot token from the context
    bot_token = context.bot.token
    
    user = update.effective_user
    
    # Save user in client bot's database
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute('''
            INSERT OR REPLACE INTO client_bot_users (bot_token, user_id, username, first_name, joined_date)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (bot_token, user.id, user.username, user.first_name))
        await db.commit()
    
    # Get welcome message for this bot
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('''
            SELECT welcome_image, welcome_text FROM client_bots WHERE bot_token = ?
        ''', (bot_token,)) as cursor:
            result = await cursor.fetchone()
        
        if not result:
            await update.message.reply_text(
                "🤖 এই বটটি সঠিকভাবে কনফিগার করা হয়নি।"
            )
            return
        
        welcome_image, welcome_text = result
        
        # Get buttons
        async with db.execute('''
            SELECT button_name, button_url FROM bot_buttons 
            WHERE bot_token = ? ORDER BY button_order
        ''', (bot_token,)) as cursor:
            buttons = await cursor.fetchall()
    
    # Send welcome message
    keyboard = []
    if buttons:
        for name, url in buttons:
            keyboard.append([InlineKeyboardButton(name, url=url)])
    
    if welcome_image:
        await update.message.reply_photo(
            photo=welcome_image,
            caption=welcome_text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )
    else:
        await update.message.reply_text(
            welcome_text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )

async def handle_client_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast command for client bots."""
    user_id = update.effective_user.id
    bot_token = context.bot.token
    
    # Check if user is broadcast admin
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('''
            SELECT admin_id FROM broadcast_admins 
            WHERE bot_token = ? AND admin_id = ?
        ''', (bot_token, user_id)) as cursor:
            result = await cursor.fetchone()
    
    if not result:
        await update.message.reply_text(
            "❌ আপনার এই কমান্ড ব্যবহারের অনুমতি নেই।"
        )
        return
    
    # Ask for broadcast message
    await update.message.reply_text(
        "📢 **ব্রডকাস্ট মেসেজ লিখুন**\n\n"
        "যা পাঠাতে চান তা লিখুন (শুধু টেক্সট):",
        parse_mode=ParseMode.MARKDOWN
    )
    
    context.user_data['broadcast_message'] = True
    return WAITING_BROADCAST_MESSAGE

async def process_client_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process client broadcast message."""
    if not context.user_data.get('broadcast_message'):
        return
    
    message = update.message.text
    bot_token = context.bot.token
    
    # Get all users of this bot
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('''
            SELECT user_id FROM client_bot_users WHERE bot_token = ?
        ''', (bot_token,)) as cursor:
            users = await cursor.fetchall()
    
    sent = 0
    failed = 0
    
    status_msg = await update.message.reply_text(
        "📤 ব্রডকাস্ট পাঠানো হচ্ছে..."
    )
    
    for (user_id,) in users:
        try:
            await context.bot.send_message(
                user_id,
                f"📢 **ব্রডকাস্ট বার্তা**\n\n{message}",
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
        except:
            failed += 1
    
    await status_msg.edit_text(
        f"✅ **ব্রডকাস্ট সম্পন্ন!**\n\n"
        f"✓ সফল: {sent}\n"
        f"✗ ব্যর্থ: {failed}\n"
        f"📊 মোট: {len(users)}",
        parse_mode=ParseMode.MARKDOWN
    )
    
    context.user_data.pop('broadcast_message', None)

def main():
    """Main function to run the bot."""
    # Initialize database
    asyncio.run(init_database())
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add conversation handler for adding new bot
    add_bot_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^➕ নতুন বট যুক্ত করুন$'), add_new_bot)],
        states={
            WAITING_BOT_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_bot_token)],
            WAITING_WELCOME_IMAGE: [
                MessageHandler(filters.PHOTO, process_welcome_image),
                MessageHandler(filters.Regex('^/skip$'), process_welcome_image)
            ],
            WAITING_WELCOME_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_welcome_text)],
            WAITING_BUTTON_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_button_count)],
            WAITING_BUTTON_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_button_name)],
            WAITING_BUTTON_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_button_url)],
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex('^🔙 ফিরে যান$'), cancel)]
    )
    
    # Add conversation handler for broadcast setup
    broadcast_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📢 ব্রডকাস্ট সেটআপ$'), broadcast_setup)],
        states={
            WAITING_BROADCAST_IDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_broadcast_ids)],
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex('^🔙 ফিরে যান$'), cancel)]
    )
    
    # Add conversation handler for admin broadcast
    admin_broadcast_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📢 ব্রডকাস্ট$'), admin_broadcast)],
        states={
            WAITING_ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_admin_broadcast)],
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex('^🔙 ফিরে যান$'), cancel)]
    )
    
    # Add conversation handler for add channel
    add_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_channel_callback, pattern='^add_channel$')],
        states={
            WAITING_ADD_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_channel)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Add conversation handler for remove channel
    remove_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_channel_callback, pattern='^remove_channel$')],
        states={
            WAITING_REMOVE_CHANNEL: [CallbackQueryHandler(delete_channel_callback, pattern='^del_channel_')],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Add conversation handler for edit welcome
    edit_welcome_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_welcome_callback, pattern='^edit_welcome_')],
        states={
            WAITING_WELCOME_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_welcome_text)],
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex('^🔙 ফিরে যান$'), cancel)]
    )
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Add menu handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    
    # Add conversation handlers
    application.add_handler(add_bot_conv)
    application.add_handler(broadcast_conv)
    application.add_handler(admin_broadcast_conv)
    application.add_handler(add_channel_conv)
    application.add_handler(remove_channel_conv)
    application.add_handler(edit_welcome_conv)
    
    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(check_join_callback, pattern='^check_join$'))
    application.add_handler(CallbackQueryHandler(broadcast_bot_callback, pattern='^broadcast_bot_'))
    application.add_handler(CallbackQueryHandler(delete_bot_callback, pattern='^delete_bot_'))
    application.add_handler(CallbackQueryHandler(confirm_delete_callback, pattern='^confirm_delete_'))
    application.add_handler(CallbackQueryHandler(cancel_delete_callback, pattern='^cancel_delete$'))
    application.add_handler(CallbackQueryHandler(bot_info_callback, pattern='^bot_info_'))
    application.add_handler(CallbackQueryHandler(back_to_admin_callback, pattern='^back_to_admin$'))
    application.add_handler(CallbackQueryHandler(back_to_bots_callback, pattern='^back_to_bots$'))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("🤖 Bot Control Hub is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
