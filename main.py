import os
import json
import logging
import httpx
from typing import Optional, List, Dict
from fastapi import FastAPI, HTTPException, Header, Request, Response
from pydantic import BaseModel

# python-telegram-bot imports
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext
from telegram.error import InvalidToken, TelegramError

# --- Configuration & Constants ---
BASE_URL = os.getenv("BASE_URL")  # e.g., https://your-app.onrender.com
API_KEY = os.getenv("API_KEY", "default_secret_key_change_me")
DATA_FILE = "bots.json"

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Database (JSON) Helpers ---
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

# --- Global Bot Storage ---
# Stores active Application instances: { "token": Application }
active_bots: Dict[str, Application] = {}

# --- Pydantic Models ---
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

# --- Helper Functions ---

async def validate_token(token: str) -> Optional[dict]:
    """Validates bot token using httpx to call getMe."""
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
    """Generates the mandatory footer."""
    return "\n\n━━━━━━━━━━━━━━━\n🤖 Powered by: @YourBotUsername"

def build_keyboard(buttons: List[ButtonModel]) -> InlineKeyboardMarkup:
    """Builds Inline Keyboard from button list."""
    keyboard = []
    for btn in buttons:
        keyboard.append([InlineKeyboardButton(text=btn.name, url=btn.url)])
    return InlineKeyboardMarkup(keyboard) if keyboard else None

# --- Bot Logic (Handlers) ---

async def start_handler(update: Update, context: CallbackContext):
    """Generic /start handler for all bots."""
    token = context.bot.token
    db = load_bots()
    config = db.get(token)
    
    if not config:
        await update.message.reply_text("Bot configuration not found. Please recreate via API.")
        return

    text = config.get('text', 'Welcome!')
    image = config.get('image')
    buttons = config.get('buttons', [])

    # Append Mandatory Credit
    final_text = text + get_credit_footer()
    keyboard = build_keyboard([ButtonModel(**b) for b in buttons])

    try:
        if image:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id, 
                photo=image, 
                caption=final_text, 
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await update.message.reply_text(
                text=final_text, 
                parse_mode="HTML",
                reply_markup=keyboard
            )
    except TelegramError as e:
        logger.error(f"Telegram error for bot {token[:10]}...: {e}")

# --- Bot Lifecycle Management ---

async def init_bot(token: str, config: dict):
    """Initialize a python-telegram-bot Application and store it."""
    if token in active_bots:
        return # Already running

    # Create Application
    application = Application.builder().token(token).build()
    
    # Add handler
    application.add_handler(CommandHandler("start", start_handler))
    
    # Initialize the application (sets up internal bot object)
    await application.initialize()
    
    active_bots[token] = application
    logger.info(f"Bot {token[:10]}... initialized.")

async def setup_webhook(token: str):
    """Registers webhook with Telegram."""
    if not BASE_URL:
        logger.warning("BASE_URL not set. Webhook not registered.")
        return False
    
    webhook_url = f"{BASE_URL}/webhook/{token}"
    
    # Use the bot instance to set webhook
    if token in active_bots:
        bot = active_bots[token].bot
        try:
            await bot.set_webhook(url=webhook_url)
            logger.info(f"Webhook set for {token[:10]}... -> {webhook_url}")
            return True
        except TelegramError as e:
            logger.error(f"Failed to set webhook: {e}")
            return False
    return False

# --- FastAPI App ---

app = FastAPI(title="Telegram Multi-Bot Factory (PTB)")

@app.on_event("startup")
async def startup_event():
    """Auto-restart bots from JSON on server restart."""
    logger.info("Startup: Restoring bots...")
    db = load_bots()
    for token, config in db.items():
        await init_bot(token, config)
        await setup_webhook(token)
    logger.info(f"Restored {len(db)} bots.")

@app.post("/api/create-bot")
async def create_bot(
    data: BotCreateRequest, 
    x_api_key: str = Header(None, alias="X-API-KEY")
):
    # Security Check
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")

    # 1. Validate Token
    bot_info = await validate_token(data.token)
    if not bot_info:
        raise HTTPException(status_code=400, detail="Invalid Bot Token")

    # 2. Save Config to DB
    db = load_bots()
    bot_data = data.dict()
    db[data.token] = bot_data
    save_bots(db)

    # 3. Initialize Bot in Memory
    await init_bot(data.token, bot_data)

    # 4. Set Webhook
    success = await setup_webhook(data.token)
    
    if not success:
        return {"status": "warning", "message": "Bot created but webhook setup failed (check BASE_URL)."}

    return {
        "status": "success", 
        "message": f"Bot @{bot_info.get('username')} created and running."
    }

@app.get("/api/status")
async def status(token: str, x_api_key: str = Header(None, alias="X-API-KEY")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    
    db = load_bots()
    if token not in db:
        raise HTTPException(status_code=404, detail="Bot not found in database")
    
    is_active = token in active_bots
    return {
        "status": "found",
        "active": is_active,
        "config": db[token]
    }

@app.post("/api/delete-bot")
async def delete_bot(data: BotDeleteRequest, x_api_key: str = Header(None, alias="X-API-KEY")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")

    token = data.token
    db = load_bots()

    if token in active_bots:
        # Shutdown and delete webhook
        app_instance = active_bots[token]
        try:
            await app_instance.bot.delete_webhook()
            await app_instance.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down bot: {e}")
        del active_bots[token]
    
    if token in db:
        del db[token]
        save_bots(db)
        return {"status": "success", "message": "Bot deleted"}
    
    raise HTTPException(status_code=404, detail="Bot not found")

# --- Webhook Endpoint ---

@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    """Handles incoming updates from Telegram."""
    if token not in active_bots:
        logger.warning(f"Update received for unknown token: {token[:10]}...")
        return Response(status_code=404)

    try:
        update_data = await request.json()
        update = Update.de_json(update_data, active_bots[token].bot)
        
        # Process update using python-telegram-bot
        await active_bots[token].process_update(update)
        return Response(status_code=200)
    
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return Response(status_code=500)

# --- Entry Point for Uvicorn ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
