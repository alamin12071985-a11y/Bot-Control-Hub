import os
import json
import logging
import httpx
from typing import Optional, List, Dict
from fastapi import FastAPI, HTTPException, Header, Request, Response
from pydantic import BaseModel

# --- Aiogram 3.x Imports ---
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# --- Configuration ---
BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("API_KEY", "default_secret_key_change_me")
DATA_FILE = "bots.json"

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Database Helpers ---
def load_bots() -> Dict:
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_bots(data: Dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# --- Global Storage ---
# Stores active Bot and Dispatcher instances
active_bots: Dict[str, Dict] = {}

# --- Models ---
class ButtonModel(BaseModel):
    name: str
    url: str

class BotCreateRequest(BaseModel):
    token: str
    text: str
    image: Optional[str] = None
    buttons: List[ButtonModel] = []

class BotDeleteRequest(BaseModel):
    token: str

# --- Logic ---

async def validate_token(token: str) -> Optional[dict]:
    """Validates bot token using getMe."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data.get("result")
    except Exception as e:
        logger.error(f"Validation error: {e}")
    return None

def get_credit_footer() -> str:
    return "\n\n━━━━━━━━━━━━━━━\n🤖 Powered by: @YourBotUsername"

def build_keyboard(buttons: List[ButtonModel]) -> InlineKeyboardMarkup:
    keyboard = []
    for btn in buttons:
        keyboard.append([InlineKeyboardButton(text=btn.name, url=btn.url)])
    return InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else None

# --- Bot Handlers ---

async def on_start(message: types.Message, bot: Bot):
    """Handles /start for all bots."""
    token = bot.token
    db = load_bots()
    config = db.get(token)
    
    if not config:
        await message.answer("Bot configuration not found.")
        return

    text = config.get('text', 'Welcome!')
    image = config.get('image')
    buttons = config.get('buttons', [])

    final_text = text + get_credit_footer()
    keyboard = build_keyboard([ButtonModel(**b) for b in buttons])

    try:
        if image:
            await bot.send_photo(
                chat_id=message.chat.id, 
                photo=image, 
                caption=final_text, 
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        else:
            await message.answer(
                text=final_text, 
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
    except TelegramAPIError as e:
        logger.error(f"Error in bot {token[:6]}: {e}")

async def register_bot_instance(token: str):
    """Creates and stores a Bot and Dispatcher instance."""
    if token in active_bots:
        return

    # Initialize Bot and Dispatcher for this specific token
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    
    # Register the /start handler specifically for this dispatcher
    dp.message.register(on_start, types.Command("start"))
    
    active_bots[token] = {"bot": bot, "dp": dp}
    logger.info(f"Bot instance {token[:6]}... initialized.")

# --- FastAPI App ---

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    """Restore bots on server restart."""
    logger.info("Startup: Restoring bots...")
    if not BASE_URL:
        logger.warning("WARNING: BASE_URL env variable is not set! Webhooks will fail.")
        
    db = load_bots()
    for token, config in db.items():
        await register_bot_instance(token)
        # Set webhook
        wh_url = f"{BASE_URL}/webhook/{token}"
        try:
            await active_bots[token]['bot'].set_webhook(wh_url)
            logger.info(f"Webhook set: {wh_url}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")

@app.post("/api/create-bot")
async def create_bot(data: BotCreateRequest, x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")

    # 1. Validate Token
    bot_info = await validate_token(data.token)
    if not bot_info:
        raise HTTPException(status_code=400, detail="Invalid Bot Token")

    # 2. Save to DB
    db = load_bots()
    db[data.token] = data.dict()
    save_bots(db)

    # 3. Init instance
    await register_bot_instance(data.token)

    # 4. Set Webhook
    wh_url = f"{BASE_URL}/webhook/{data.token}"
    await active_bots[data.token]['bot'].set_webhook(wh_url)

    return {"status": "success", "message": f"Bot @{bot_info.get('username')} created."}

@app.post("/api/delete-bot")
async def delete_bot(data: BotDeleteRequest, x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    
    token = data.token
    db = load_bots()

    if token in active_bots:
        try:
            await active_bots[token]['bot'].delete_webhook()
            await active_bots[token]['bot'].session.close()
        except: pass
        del active_bots[token]
    
    if token in db:
        del db[token]
        save_bots(db)
        return {"status": "success", "message": "Bot deleted"}
    
    raise HTTPException(status_code=404, detail="Bot not found")

@app.get("/api/status")
async def status(token: str, x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    
    db = load_bots()
    if token not in db:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {"status": "active", "config": db[token]}

@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    if token not in active_bots:
        return Response(status_code=404)
    
    try:
        data = await request.json()
        update = types.Update(**data)
        bot = active_bots[token]['bot']
        dp = active_bots[token]['dp']
        
        # Feed update to the specific dispatcher
        await dp.feed_update(bot, update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return Response(status_code=500)

if __name__ == "__main__":
    import uvicorn
    # Render sets the PORT env variable
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
