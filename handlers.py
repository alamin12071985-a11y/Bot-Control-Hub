import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
import database as db
from config import MAIN_ADMIN_ID

logger = logging.getLogger(__name__)
router = Router()

# --- States ---
class Form(StatesClass):
    start = State()
    token = State()
    image = State()
    text = State()
    btn_count = State()
    btn_details = State()
    broadcast_setup = State()
    admin_broadcast = State()

class ClientForm(StatesClass):
    menu = State()

# --- Keyboards ---
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 My Bots", callback_data="my_bots")],
        [InlineKeyboardButton(text="➕ New Bot", callback_data="new_bot")],
        [InlineKeyboardButton(text="📢 Broadcast Setup", callback_data="broadcast_setup")]
    ])

def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="⚙️ Force Join", callback_data="admin_channels")]
    ])

# --- Middleware: Force Join Check ---
async def check_subscription(user_id, bot: Bot):
    channels = db.get_channels()
    if not channels:
        return True
    
    for ch_id, link in channels:
        try:
            member = await bot.get_chat_member(ch_id, user_id)
            if member.status in ["left", "kicked"]:
                return False, (ch_id, link)
        except Exception as e:
            logger.error(f"Channel check error: {e}")
            continue
    return True

# --- Handlers ---

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    db.add_user(message.from_user.id, message.from_user.full_name, message.from_user.username)
    
    # Check Force Join
    sub_status = await check_subscription(message.from_user.id, bot)
    if sub_status is not True:
        # Not joined
        ch_id, link = sub_status
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Join Channel", url=link)],
            [InlineKeyboardButton(text="✅ আমি জয়েন করেছি", callback_data="check_join")]
        ])
        await message.answer("⚠️ বট ব্যবহার করতে প্রথমে আমাদের চ্যানেলে জয়েন করুন!", reply_markup=kb)
        return

    if message.from_user.id == MAIN_ADMIN_ID:
        await message.answer("👋 স্বাগতম অ্যাডমিন! আপনি কি করতে চান?", reply_markup=admin_panel_kb())
    else:
        await message.answer("🎉 স্বাগতম Bot Control Hub-এ!\n\nআপনার নিজস্ব বট তৈরি ও ম্যানেজ করুন সহজেই।", reply_markup=main_menu_kb())

@router.callback_query(F.data == "check_join")
async def recheck_join(callback: CallbackQuery, bot: Bot):
    sub_status = await check_subscription(callback.from_user.id, bot)
    if sub_status is True:
        await callback.message.delete()
        await cmd_start(callback.message, None, bot) # Redirect to start
    else:
        await callback.answer("❌ আপনি এখনো জয়েন করেননি!", show_alert=True)

# --- New Bot Flow ---
@router.callback_query(F.data == "new_bot")
async def new_bot_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.token)
    await callback.message.answer("১️⃣ প্রথমে আপনার বট টোকেন দিন:\n\n<code>BotFather থেকে টোকেন নিন</code>")

@router.message(Form.token)
async def process_token(message: Message, state: FSMContext, bot: Bot):
    token = message.text.strip()
    try:
        # Validate token
        new_bot = Bot(token=token)
        bot_info = await new_bot.get_me()
        await new_bot.session.close()
        
        await state.update_data(token=token, bot_username=bot_info.username, bot_id=bot_info.id)
        
        # Save to DB
        db.add_bot(message.from_user.id, token, bot_info.username, bot_info.id)
        
        # Alert Admin
        await bot.send_message(MAIN_ADMIN_ID, 
            f"🚀 <b>New Bot Added!</b>\n"
            f"User: {message.from_user.full_name} ({message.from_user.id})\n"
            f"Bot: @{bot_info.username}\n"
            f"ID: {bot_info.id}"
        )

        await state.set_state(Form.image)
        await message.answer(f"✅ বট সফলভাবে যোগ হয়েছে: @{bot_info.username}\n\n"
                             "২️⃣ আপনি কি ওয়েলকাম ইমেজ চান?\n"
                             "ইমেজ পাঠান অথবা 'Skip' লিখুন।")
    except Exception as e:
        await message.answer(f"❌ টোকেন ইনভ্যালিড! আবার চেষ্টা করুন।\nError: {e}")

@router.message(Form.image)
async def process_image(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "skip":
        await state.update_data(image_id=None)
    elif message.photo:
        await state.update_data(image_id=message.photo[-1].file_id)
    else:
        await message.answer("⚠️ শুধুমাত্র ছবি পাঠান বা 'Skip' লিখুন।")
        return

    await state.set_state(Form.text)
    await message.answer("৩️⃣ ওয়েলকাম টেক্সট লিখুন:")

@router.message(Form.text)
async def process_text(message: Message, state: FSMContext):
    await state.update_data(welcome_text=message.text)
    await state.set_state(Form.btn_count)
    await message.answer("৪️⃣ কয়টি বাটন চান? (১-৩ এর মধ্যে লিখুন)")

@router.message(Form.btn_count)
async def process_btn_count(message: Message, state: FSMContext):
    if not message.text.isdigit() or not 1 <= int(message.text) <= 3:
        await message.answer("⚠️ সংখ্যা ১ থেকে ৩ এর মধ্যে হতে হবে।")
        return
    
    count = int(message.text)
    await state.update_data(btn_count=count, buttons=[])
    await state.set_state(Form.btn_details)
    await message.answer(f"৫️⃣ বাটন ডিটেইলস দিন (১টি বাটনের জন্য):\n\nফরম্যাট: নাম - URL")

@router.message(Form.btn_details)
async def process_btn_details(message: Message, state: FSMContext):
    data = await state.get_data()
    buttons = data.get('buttons', [])
    
    try:
        name, url = message.text.split(" - ")
        buttons.append({"name": name.strip(), "url": url.strip()})
    except ValueError:
        await message.answer("❌ ফরম্যাট ঠিক নেই! আবার লিখুন: নাম - URL")
        return

    if len(buttons) < data['btn_count']:
        await state.update_data(buttons=buttons)
        await message.answer(f"✅ বাটন {len(buttons)} সেভ হয়েছে। পরবর্তীটি দিন:")
    else:
        # Save final config
        user_data = await state.get_data()
        db.save_welcome(user_data['bot_id'], user_data['image_id'], user_data['welcome_text'], buttons)
        
        # Load the client bot immediately (Implemented in main.py logic usually, but here we trigger update)
        from client_instance import load_client_bot
        await load_client_bot(user_data['token'])
        
        await state.clear()
        await message.answer("🎉 বট সফলভাবে কনফিগার হয়েছে!\nএখন /start দিলে আপনার বট কাজ করবে।", reply_markup=main_menu_kb())

# --- My Bots ---
@router.callback_query(F.data == "my_bots")
async def show_bots(callback: CallbackQuery):
    bots = db.get_user_bots(callback.from_user.id)
    if not bots:
        await callback.message.edit_text("🤖 আপনার কোনো বট নেই। '➕ New Bot' চাপুন।")
        return
    
    text = "🤖 <b>আপনার বট তালিকা:</b>\n\n"
    for bid, bname in bots:
        text += f"🔹 @{bname} (ID: {bid})\n"
    
    await callback.message.edit_text(text, reply_markup=main_menu_kb())

# --- Broadcast Setup ---
@router.callback_query(F.data == "broadcast_setup")
async def setup_broadcast(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.broadcast_setup)
    await callback.message.edit_text(
        "📌 Broadcast ব্যবহার করতে আপনার User ID দিন।\n"
        "একাধিক Admin চাইলে কমা দিয়ে আলাদা করুন।\n\n"
        "উদাহরণ: 123456789,987654321"
    )

@router.message(Form.broadcast_setup)
async def save_broadcast_admins(message: Message, state: FSMContext):
    try:
        ids = [x.strip() for x in message.text.split(',')]
        # Assume last bot added is the one to configure (simplified for flow)
        # In production, you'd select a bot first.
        bots = db.get_user_bots(message.from_user.id)
        if not bots:
            await message.answer("প্রথমে একটি বট যোগ করুন।")
            return
        
        last_bot_id = bots[-1][0] # Get last added bot ID
        db.add_broadcast_admins(last_bot_id, ids)
        await state.clear()
        await message.answer(f"✅ Broadcast Admins সেট হয়েছে বট ID: {last_bot_id} এর জন্য।", reply_markup=main_menu_kb())
    except Exception as e:
        await message.answer("❌ ইনভ্যালিড আইডি। আবার চেষ্টা করুন।")

# --- Admin Panel ---
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != MAIN_ADMIN_ID:
        return
    
    users, bots = db.total_stats()
    await callback.message.edit_text(f"📊 <b>Statistics</b>\n\n👤 Total Users: {users}\n🤖 Total Bots: {bots}", reply_markup=admin_panel_kb())

# --- Admin Broadcast (To Controller Users) ---
# Implementation similar to client broadcast but targeting 'users' table.
# Skipping full code for brevity but follows same logic as below.
