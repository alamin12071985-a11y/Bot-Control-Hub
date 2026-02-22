# bot.py
import asyncio
import logging
import json
import sys
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramNotFound, TelegramBadRequest

import database as db
from config import MAIN_BOT_TOKEN, States as CustomStates

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO)

# --- Initialize Main Bot ---
main_bot = Bot(token=MAIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# --- Container for running client bots ---
# Format: {bot_token: {'bot': BotInstance, 'dp': DispatcherInstance}}
active_client_bots = {}

# ==========================================
# FSM States Definition
# ==========================================
class Form(StatesGroup):
    # Add Bot
    token = State()
    image = State()
    text = State()
    button_count = State()
    button_details = State()
    
    # Edit Bot
    edit_text = State()
    edit_image = State()
    edit_buttons_count = State()
    edit_buttons_details = State()
    
    # Broadcast Setup
    broadcast_admins = State()
    
    # Client Broadcast
    client_image = State()
    client_text = State()
    client_button = State()
    client_confirm = State()

# ==========================================
# KEYBOARDS
# ==========================================
def get_main_menu():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🤖 My Bots"))
    builder.add(KeyboardButton(text="➕ Add New Bot"))
    builder.add(KeyboardButton(text="📢 Broadcast Setup"))
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)

def get_cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Cancel")]], resize_keyboard=True)

def get_skip_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⏭ Skip")]], resize_keyboard=True)

def get_skip_cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⏭ Skip"), KeyboardButton(text="❌ Cancel")]
    ], resize_keyboard=True)

# ==========================================
# MAIN BOT HANDLERS
# ==========================================

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    db.add_user(user.id, user.username, user.first_name)
    await message.answer(
        f"👋 Welcome <b>{user.first_name}</b>!\n\n"
        "This is the <b>Bot Control Hub</b>. Connect your own bots here and manage them easily.",
        reply_markup=get_main_menu()
    )

@router.message(F.text == "❌ Cancel")
async def cancel_action(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Action cancelled.", reply_markup=get_main_menu())

# --- ➕ ADD NEW BOT FLOW ---

@router.message(F.text == "➕ Add New Bot")
async def add_bot_start(message: types.Message, state: FSMContext):
    await message.answer(
        "Let's connect your new bot!\n\n"
        "1️⃣ Please send me the <b>Bot Token</b>.\n"
        "(You can get it from @BotFather)",
        reply_markup=get_cancel_kb()
    )
    await state.set_state(Form.token)

@router.message(Form.token)
async def process_token(message: types.Message, state: FSMContext):
    token = message.text.strip()
    
    # Validate Token
    try:
        new_bot = Bot(token=token)
        bot_info = await new_bot.get_me()
        await new_bot.session.close()
        
        # Save temp data
        await state.update_data(token=token, bot_username=bot_info.username)
        
        await message.answer(
            f"✅ Validated: <b>@{bot_info.username}</b>\n\n"
            "2️⃣ Send a <b>Welcome Image</b> for your bot's /start message.",
            reply_markup=get_skip_cancel_kb()
        )
        await state.set_state(Form.image)
        
    except Exception as e:
        await message.answer("❌ Invalid token. Please try again or check @BotFather.", reply_markup=get_cancel_kb())

@router.message(Form.image, F.photo)
async def process_image(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(image=file_id)
    await message.answer("✅ Image saved.\n\n3️⃣ Send the <b>Welcome Text</b>:", reply_markup=get_cancel_kb())
    await state.set_state(Form.text)

@router.message(Form.image, F.text == "⏭ Skip")
async def skip_image(message: types.Message, state: FSMContext):
    await state.update_data(image=None)
    await message.answer("⏭ Skipped.\n\n3️⃣ Send the <b>Welcome Text</b>:", reply_markup=get_cancel_kb())
    await state.set_state(Form.text)

@router.message(Form.text)
async def process_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("✅ Text saved.\n\n4️⃣ How many buttons? (Enter a number: 0, 1, 2, or 3)", reply_markup=get_cancel_kb())
    await state.set_state(Form.button_count)

@router.message(Form.button_count)
async def process_button_count(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) not in range(0, 4):
        await message.answer("Please enter a valid number (0-3).")
        return
    
    count = int(message.text)
    if count == 0:
        # Finish flow
        await finish_bot_creation(message, state, buttons=[])
        return

    await state.update_data(button_count=count, current_button_index=0, buttons_list=[])
    await message.answer(f"Button 1/{count}:\nSend <b>Name</b> and <b>URL</b> separated by a new line or space.\n\nExample:\nGoogle\nhttps://google.com", reply_markup=get_cancel_kb())
    await state.set_state(Form.button_details)

@router.message(Form.button_details)
async def process_button_details(message: types.Message, state: FSMContext):
    data = await state.get_data()
    count = data['button_count']
    index = data['current_button_index']
    btns_list = data['buttons_list']
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Invalid format. Please send Name + URL.")
        return
    
    # Assuming first part is name, last is URL, or split by newline
    if "\n" in message.text:
        name, url = message.text.split("\n", 1)
    else:
        name = " ".join(parts[:-1])
        url = parts[-1]
        
    btns_list.append({"name": name.strip(), "url": url.strip()})
    
    if index + 1 < count:
        await state.update_data(current_button_index=index+1, buttons_list=btns_list)
        await message.answer(f"✅ Button {index+1} saved.\n\nButton {index+2}/{count}:", reply_markup=get_cancel_kb())
    else:
        # All buttons collected
        await finish_bot_creation(message, state, buttons=btns_list)

async def finish_bot_creation(message: types.Message, state: FSMContext, buttons):
    data = await state.get_data()
    db.add_client_bot(
        owner_id=message.from_user.id,
        token=data['token'],
        username=data['bot_username'],
        text=data.get('text'),
        image=data.get('image'),
        buttons=buttons
    )
    
    # Start the client bot polling immediately
    await start_client_bot(data['token'])
    
    await state.clear()
    await message.answer(
        f"🎉 <b>Success!</b>\n"
        f"Your bot @{data['bot_username']} is now live and managed by the Hub.\n\n"
        f"Use /start on your bot to see the magic!",
        reply_markup=get_main_menu()
    )

# --- 🤖 MY BOTS ---

@router.message(F.text == "🤖 My Bots")
async def show_my_bots(message: types.Message):
    bots = db.get_user_bots(message.from_user.id)
    if not bots:
        await message.answer("You have no bots connected. Use '➕ Add New Bot' to start.")
        return
    
    builder = InlineKeyboardBuilder()
    for bot_id, username in bots:
        builder.row(InlineKeyboardButton(text=f"@{username}", callback_data=f"manage_{bot_id}"))
    
    await message.answer("📋 <b>Select a bot to manage:</b>", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("manage_"))
async def manage_bot_menu(callback: types.CallbackQuery):
    bot_id = int(callback.data.split("_")[1])
    bot_info = db.get_bot_info(bot_id)
    
    if not bot_info:
        await callback.answer("Bot not found.", show_alert=True)
        return
    
    text = (f"ℹ️ <b>Bot: @{bot_info[2]}</b>\n"
            f"Welcome Text: {bot_info[4] or 'Not set'}\n"
            f"Broadcast Admins: {len(json.loads(bot_info[7])) if bot_info[7] else 0}")
            
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Edit Welcome", callback_data=f"edit_{bot_id}")],
        [InlineKeyboardButton(text="🗑 Delete Bot", callback_data=f"delete_{bot_id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="back_list")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)

@router.callback_query(F.data == "back_list")
async def back_to_list(callback: types.CallbackQuery):
    await callback.message.delete()
    # Resend list
    bots = db.get_user_bots(callback.from_user.id)
    if not bots:
        await callback.message.answer("No bots found.")
        return
    
    builder = InlineKeyboardBuilder()
    for bot_id, username in bots:
        builder.row(InlineKeyboardButton(text=f"@{username}", callback_data=f"manage_{bot_id}"))
    
    await callback.message.answer("📋 <b>Select a bot to manage:</b>", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("delete_"))
async def delete_bot_handler(callback: types.CallbackQuery):
    bot_id = int(callback.data.split("_")[1])
    # Stop polling if running
    bot_info = db.get_bot_info(bot_id)
    if bot_info and bot_info[2] in active_client_bots:
        # Stop dispatcher
        # Note: In production, graceful shutdown is needed. Here we just remove from dict.
        del active_client_bots[bot_info[2]]
        
    db.delete_bot(bot_id, callback.from_user.id)
    await callback.answer("Bot deleted successfully!")
    await callback.message.delete()

# --- ✏️ EDIT BOT (Simplified Re-configuration) ---
@router.callback_query(F.data.startswith("edit_"))
async def edit_bot_start(callback: types.CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split("_")[1])
    bot_info = db.get_bot_info(bot_id)
    if not bot_info:
        await callback.answer("Error.")
        return
        
    await state.update_data(edit_bot_id=bot_id)
    await callback.message.answer(
        "✏️ <b>Editing Bot</b>\n\n"
        "Send new Welcome Text (Current will be replaced):",
        reply_markup=get_cancel_kb()
    )
    await state.set_state(Form.edit_text)
    await callback.message.delete()

@router.message(Form.edit_text)
async def edit_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("Send new Welcome Image (or Skip to remove existing):", reply_markup=get_skip_kb())
    await state.set_state(Form.edit_image)

@router.message(Form.edit_image, F.photo)
async def edit_image(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(image=file_id)
    await message.answer("How many buttons? (0-3)")
    await state.set_state(Form.edit_buttons_count)

@router.message(Form.edit_image, F.text == "⏭ Skip")
async def edit_skip_image(message: types.Message, state: FSMContext):
    await state.update_data(image=None)
    await message.answer("How many buttons? (0-3)")
    await state.set_state(Form.edit_buttons_count)

@router.message(Form.edit_buttons_count)
async def edit_btn_count(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) not in range(0, 4):
        await message.answer("Enter 0-3.")
        return
    
    count = int(message.text)
    data = await state.get_data()
    
    if count == 0:
        db.update_bot_welcome(data['edit_bot_id'], data['text'], data['image'], [])
        await state.clear()
        await message.answer("✅ Bot updated!", reply_markup=get_main_menu())
        return
        
    await state.update_data(button_count=count, current_button_index=0, buttons_list=[])
    await message.answer("Button 1 Name + URL:")
    await state.set_state(Form.edit_buttons_details)

@router.message(Form.edit_buttons_details)
async def edit_btn_details(message: types.Message, state: FSMContext):
    # Similar logic to creation
    data = await state.get_data()
    count = data['button_count']
    index = data['current_button_index']
    btns_list = data['buttons_list']
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Invalid format.")
        return
    
    name = " ".join(parts[:-1])
    url = parts[-1]
    btns_list.append({"name": name, "url": url})
    
    if index + 1 < count:
        await state.update_data(current_button_index=index+1, buttons_list=btns_list)
        await message.answer(f"Button {index+2}/{count}:")
    else:
        # Done
        db.update_bot_welcome(data['edit_bot_id'], data['text'], data['image'], btns_list)
        await state.clear()
        await message.answer("✅ Bot updated!", reply_markup=get_main_menu())

# --- 📢 BROADCAST SETUP ---

@router.message(F.text == "📢 Broadcast Setup")
async def broadcast_setup_start(message: types.Message, state: FSMContext):
    bots = db.get_user_bots(message.from_user.id)
    if not bots:
        await message.answer("No bots available.")
        return
        
    builder = InlineKeyboardBuilder()
    for bot_id, username in bots:
        builder.row(InlineKeyboardButton(text=f"@{username}", callback_data=f"bc_setup_{bot_id}"))
    
    await message.answer("Select bot to setup broadcast admins:", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("bc_setup_"))
async def bc_setup_ask_ids(callback: types.CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split("_")[2])
    await state.update_data(bc_bot_id=bot_id)
    
    bot_info = db.get_bot_info(bot_id)
    current_admins = json.loads(bot_info[7]) if bot_info[7] else []
    
    await callback.message.answer(
        f"Current Admin IDs: {current_admins}\n\n"
        "Send new User IDs allowed to broadcast (comma separated):\n"
        "<i>Example: 12345678, 98765432</i>",
        reply_markup=get_cancel_kb()
    )
    await state.set_state(Form.broadcast_admins)

@router.message(Form.broadcast_admins)
async def bc_save_ids(message: types.Message, state: FSMContext):
    try:
        ids = [int(x.strip()) for x in message.text.split(",")]
        data = await state.get_data()
        db.set_broadcast_admins(data['bc_bot_id'], ids)
        await state.clear()
        await message.answer("✅ Broadcast admins updated!", reply_markup=get_main_menu())
    except ValueError:
        await message.answer("Invalid format. Send numbers separated by commas.")

# ==========================================
# CLIENT BOT HANDLERS (Dynamic)
# ==========================================

async def start_client_bot(token):
    """Starts polling for a specific client bot."""
    if token in active_client_bots:
        return # Already running

    client_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    client_dp = Dispatcher()
    client_router = Router()
    client_dp.include_router(client_router)
    
    # Define handlers for client bots
    
    @client_router.message(CommandStart())
    async def client_start(msg: types.Message):
        # Identify bot by token
        bot_data = db.get_bot_by_token(token)
        if not bot_data:
            await msg.answer("Bot not configured in hub.")
            return
            
        bot_id = bot_data[0]
        # Save user for this bot
        db.add_client_user(msg.from_user.id, bot_id)
        
        # Send welcome message
        full_info = db.get_bot_info(bot_id)
        _, _, _, welcome_text, welcome_image, buttons_json, _ = full_info
        
        buttons = json.loads(buttons_json) if buttons_json else []
        
        # Build Inline Keyboard
        kb = None
        if buttons:
            builder = InlineKeyboardBuilder()
            for btn in buttons:
                builder.add(InlineKeyboardButton(text=btn['name'], url=btn['url']))
            kb = builder.as_markup()
            
        try:
            if welcome_image:
                await msg.answer_photo(welcome_image, caption=welcome_text or "Welcome!", reply_markup=kb)
            else:
                await msg.answer(welcome_text or "Welcome!", reply_markup=kb)
        except Exception as e:
            await msg.answer("Error showing welcome message.")

    @client_router.message(Command("broadcast"))
    async def client_broadcast_start(msg: types.Message, state: FSMContext):
        bot_data = db.get_bot_by_token(token)
        if not bot_data: return
        
        # Check permission
        admins = json.loads(bot_data[2]) if bot_data[2] else []
        if msg.from_user.id not in admins:
            await msg.answer("⛔ You are not authorized to use this command.")
            return
            
        await state.set_state(Form.client_image)
        await msg.answer("📢 <b>Broadcast Mode</b>\n\nSend Image (or Skip):", reply_markup=get_skip_kb())

    @client_router.message(Form.client_image)
    async def client_bc_image(msg: types.Message, state: FSMContext):
        img = msg.photo[-1].file_id if msg.photo else None
        if msg.text == "⏭ Skip": img = None
        await state.update_data(bc_img=img)
        await state.set_state(Form.client_text)
        await msg.answer("Send Text (or Skip):", reply_markup=get_skip_kb())

    @client_router.message(Form.client_text)
    async def client_bc_text(msg: types.Message, state: FSMContext):
        txt = msg.text if msg.text != "⏭ Skip" else None
        if not txt and (await state.get_data()).get('bc_img') is None:
            await msg.answer("You must send at least Text or Image.")
            return
            
        await state.update_data(bc_txt=txt)
        await state.set_state(Form.client_button)
        await msg.answer("Send Button (Name URL) or Skip:", reply_markup=get_skip_kb())

    @client_router.message(Form.client_button)
    async def client_bc_button(msg: types.Message, state: FSMContext):
        btn = None
        if msg.text and msg.text != "⏭ Skip":
            parts = msg.text.split()
            if len(parts) >= 2:
                btn = {"name": " ".join(parts[:-1]), "url": parts[-1]}
        
        await state.update_data(bc_btn=btn)
        await state.set_state(Form.client_confirm)
        
        data = await state.get_data()
        preview = "📢 <b>Preview</b>\n\n"
        if data.get('bc_txt'): preview += data['bc_txt'] + "\n"
        preview += "Ready to send to all users. Confirm?"
        
        await msg.answer(preview, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Send", callback_data="confirm_send"),
             InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_send")]
        ]))

    @client_router.callback_query(F.data == "confirm_send")
    async def confirm_send_handler(c: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        await state.clear()
        await c.message.edit_text("🚀 Broadcasting started...")
        
        bot_data = db.get_bot_by_token(token)
        bot_id = bot_data[0]
        users = db.get_all_client_users(bot_id)
        
        # Build message
        kb = None
        if data.get('bc_btn'):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=data['bc_btn']['name'], url=data['bc_btn']['url'])]
            ])
            
        sent_count = 0
        for user_id in users:
            try:
                if data.get('bc_img'):
                    await client_bot.send_photo(user_id, data['bc_img'], caption=data.get('bc_txt'), reply_markup=kb)
                elif data.get('bc_txt'):
                    await client_bot.send_message(user_id, data['bc_txt'], reply_markup=kb)
                sent_count += 1
            except Exception:
                pass # User blocked bot, etc.
        
        await c.message.edit_text(f"✅ Broadcast finished!\nSent to {sent_count} users.")

    @client_router.callback_query(F.data == "cancel_send")
    async def cancel_send_handler(c: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await c.message.edit_text("Cancelled.")

    # Store in global dict
    active_client_bots[token] = {'bot': client_bot, 'dp': client_dp}
    
    # Start polling in background
    asyncio.create_task(client_dp.start_polling(client_bot, handle_signals=False))

# ==========================================
# MAIN ENTRY POINT
# ==========================================

async def on_startup():
    print("🚀 Starting Bot Control Hub...")
    db.init_db()
    
    # Restart all existing client bots from DB
    print("🔄 Loading existing client bots...")
    conn = sqlite3.connect(db.DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT bot_token FROM client_bots")
    tokens = cursor.fetchall()
    conn.close()
    
    for t in tokens:
        await start_client_bot(t[0])
    print("✅ All client bots loaded.")

async def main():
    await on_startup()
    await dp.start_polling(main_bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped")
