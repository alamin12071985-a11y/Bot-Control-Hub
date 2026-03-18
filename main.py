import json
import os
import httpx
import logging
from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# =========================
# CONFIG
# =========================
API_KEY = os.getenv("API_KEY", "mysecretkey")
BASE_URL = os.getenv("BASE_URL", "https://your-app-name.onrender.com")
DB_FILE = "bots.json"

app = FastAPI()

logging.basicConfig(level=logging.INFO)

# =========================
# DATABASE (JSON)
# =========================
def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r") as f:
        return json.load(f)


def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)


# =========================
# SECURITY
# =========================
def check_api_key(request: Request):
    key = request.headers.get("X-API-KEY")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


# =========================
# TELEGRAM VALIDATION
# =========================
async def validate_token(token):
    url = f"https://api.telegram.org/bot{token}/getMe"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        return r.status_code == 200 and r.json().get("ok")


# =========================
# SET WEBHOOK
# =========================
async def set_webhook(token):
    webhook_url = f"{BASE_URL}/webhook/{token}"
    url = f"https://api.telegram.org/bot{token}/setWebhook"

    async with httpx.AsyncClient() as client:
        await client.post(url, json={"url": webhook_url})


# =========================
# BUTTON BUILDER
# =========================
def build_keyboard(buttons):
    kb = InlineKeyboardMarkup()
    for b in buttons:
        kb.add(InlineKeyboardButton(text=b["name"], url=b["url"]))
    return kb


# =========================
# CREDIT SYSTEM
# =========================
def apply_credit(text):
    return text + "\n\n━━━━━━━━━━━━━━━\n🤖 Powered by: @YourBotUsername"


# =========================
# CREATE BOT
# =========================
@app.post("/api/create-bot")
async def create_bot(request: Request):
    check_api_key(request)
    data = await request.json()

    token = data.get("token")
    text = data.get("text", "")
    image = data.get("image")
    buttons = data.get("buttons", [])

    if not token:
        raise HTTPException(400, "Token required")

    valid = await validate_token(token)
    if not valid:
        raise HTTPException(400, "Invalid bot token")

    db = load_db()
    db[token] = {
        "text": text,
        "image": image,
        "buttons": buttons
    }
    save_db(db)

    await set_webhook(token)

    return {
        "status": "success",
        "message": "Bot created and running"
    }


# =========================
# STATUS
# =========================
@app.get("/api/status")
async def status(token: str, request: Request):
    check_api_key(request)
    db = load_db()

    if token in db:
        return {"status": "running"}
    return {"status": "not found"}


# =========================
# DELETE BOT
# =========================
@app.post("/api/delete-bot")
async def delete_bot(request: Request):
    check_api_key(request)
    data = await request.json()
    token = data.get("token")

    db = load_db()

    if token not in db:
        raise HTTPException(404, "Bot not found")

    del db[token]
    save_db(db)

    # remove webhook
    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{token}/deleteWebhook")

    return {"status": "deleted"}


# =========================
# WEBHOOK HANDLER
# =========================
@app.post("/webhook/{token}")
async def webhook(token: str, request: Request):
    db = load_db()

    if token not in db:
        return {"ok": False}

    data = db[token]

    bot = Bot(token=token)

    update = types.Update(**await request.json())

    if update.message and update.message.text == "/start":
        chat_id = update.message.chat.id

        text = apply_credit(data["text"])
        keyboard = build_keyboard(data["buttons"])

        try:
            if data["image"] and data["image"] != "none":
                await bot.send_photo(
                    chat_id,
                    photo=data["image"],
                    caption=text,
                    reply_markup=keyboard
                )
            else:
                await bot.send_message(
                    chat_id,
                    text=text,
                    reply_markup=keyboard
                )
        except Exception as e:
            logging.error(str(e))

    return {"ok": True}


# =========================
# AUTO LOAD (optional)
# =========================
@app.on_event("startup")
async def startup():
    if not os.path.exists(DB_FILE):
        save_db({})
    logging.info("Server started...")
