import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import database as db
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

logger = logging.getLogger(__name__)

# Store running bots
active_bots = {}

class BroadcastState(StatesClass):
    image = State()
    text = State()
    button = State()
    confirm = State()

async def load_all_bots():
    """Load all bots from DB on startup."""
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT bot_id, bot_token FROM bots")
    bots = cursor.fetchall()
    conn.close()
    
    for bot_id, token in bots:
        await load_client_bot(token)

async def load_client_bot(token):
    if token in active_bots:
        return # Already running

    try:
        bot = Bot(token=token)
        dp = Dispatcher()
        
        # Register handlers for this bot
        @dp.message(Command("start"))
        async def client_start(message: types.Message):
            # Save user to client_users table
            bot_info = await bot.get_me()
            db.add_client_user(bot_info.id, message.from_user.id, message.from_user.full_name)
            
            # Fetch welcome settings
            settings = db.get_welcome(bot_info.id)
            if settings:
                img, txt, btns = settings
                keyboard = None
                if btns and str(btns) != '[]':
                    # Parse buttons saved as string repr of list
                    import ast
                    btn_list = ast.literal_eval(btns)
                    kb_rows = []
                    for b in btn_list:
                        kb_rows.append([InlineKeyboardButton(text=b['name'], url=b['url'])])
                    keyboard = InlineKeyboardMarkup(inline_keyboard=kb_rows)
                
                if img:
                    await message.answer_photo(img, caption=txt, reply_markup=keyboard)
                else:
                    await message.answer(txt, reply_markup=keyboard)
            else:
                await message.answer("👋 স্বাগতম! বট এখনো কনফিগার করা হয়নি।")

        @dp.message(Command("broadcast"))
        async def client_broadcast_start(message: types.Message, state: FSMContext):
            bot_info = await bot.get_me()
            admins = db.get_broadcast_admins(bot_info.id)
            
            if message.from_user.id not in admins:
                await message.answer("⛔ আপনার অনুমতি নেই।")
                return
            
            await state.set_state(BroadcastState.image)
            await message.answer("📢 Broadcast Image পাঠান অথবা 'Skip' লিখুন।")

        @dp.message(BroadcastState.image)
        async def bc_img(message: types.Message, state: FSMContext):
            img_id = None
            if message.photo:
                img_id = message.photo[-1].file_id
            elif not (message.text and message.text.lower() == 'skip'):
                await message.answer("⚠️ ইমেজ বা Skip লিখুন।")
                return
            
            await state.update_data(img=img_id)
            await state.set_state(BroadcastState.text)
            await message.answer("📝 Broadcast Text লিখুন বা Skip করুন।")

        @dp.message(BroadcastState.text)
        async def bc_text(message: types.Message, state: FSMContext):
            txt = message.text if message.text.lower() != 'skip' else None
            await state.update_data(txt=txt)
            await state.set_state(BroadcastState.button)
            await message.answer("🔘 Button দিন (নাম - URL) বা Skip করুন।")

        @dp.message(BroadcastState.button)
        async def bc_btn(message: types.Message, state: FSMContext):
            btn_data = None
            if message.text.lower() != 'skip':
                try:
                    n, u = message.text.split(" - ")
                    btn_data = [{"name": n.strip(), "url": u.strip()}]
                except:
                    await message.answer("❌ ফরম্যাট ঠিক নেই। আবার দিন বা Skip করুন।")
                    return
            
            await state.update_data(btn=btn_data)
            data = await state.get_data()
            
            # Confirm
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ কনফার্ম করুন", callback_data="confirm_bc")]
            ])
            await message.answer("✅ Ready to broadcast! কনফার্ম করুন।", reply_markup=kb)

        @dp.callback_query(F.data == "confirm_bc")
        async def bc_confirm(callback: types.CallbackQuery, state: FSMContext):
            data = await state.get_data()
            bot_info = await bot.get_me()
            
            users = db.get_client_users(bot_info.id)
            await callback.message.edit_text(f"🚀 Broadcast শুরু হচ্ছে... ({len(users)} Users)")
            
            # Build Keyboard
            kb = None
            if data.get('btn'):
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=data['btn'][0]['name'], url=data['btn'][0]['url'])]])
            
            success = 0
            for uid in users:
                try:
                    if data['img']:
                        await bot.send_photo(uid[0], data['img'], caption=data.get('txt'), reply_markup=kb)
                    elif data.get('txt'):
                        await bot.send_message(uid[0], data['txt'], reply_markup=kb)
                    success += 1
                    await asyncio.sleep(0.05) # Anti-flood
                except Exception as e:
                    logger.error(f"Broadcast error: {e}")
            
            await state.clear()
            await callback.message.edit_text(f"✅ Broadcast Complete!\nSent to {success} users.")

        # Start polling in background
        asyncio.create_task(dp.start_polling(bot))
        active_bots[token] = dp
        logger.info(f"Client Bot Started: {token[:6]}...")

    except Exception as e:
        logger.error(f"Failed to start client bot {token}: {e}")
