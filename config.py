# config.py

MAIN_BOT_TOKEN = "8250934004:AAGVjnnRnnQw0vz3TZ7arrjVFcX4MFz92Qc"

# Database Name
DB_NAME = "bot_control.db"

# States for Conversation
class States:
    # Add Bot Flow
    ADD_BOT_TOKEN = "add_bot_token"
    ADD_BOT_IMAGE = "add_bot_image"
    ADD_BOT_TEXT = "add_bot_text"
    ADD_BOT_BUTTON_COUNT = "add_bot_button_count"
    ADD_BOT_BUTTON_DETAILS = "add_bot_button_details"
    
    # Broadcast Setup
    SET_BROADCAST_ADMINS = "set_broadcast_admins"
    
    # Client Bot Broadcast Flow
    CLIENT_BROADCAST_IMAGE = "client_broadcast_image"
    CLIENT_BROADCAST_TEXT = "client_broadcast_text"
    CLIENT_BROADCAST_BUTTON = "client_broadcast_button"
    CLIENT_BROADCAST_CONFIRM = "client_broadcast_confirm"
