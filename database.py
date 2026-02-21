import sqlite3
import logging
from config import DB_PATH

logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Main Controller Users
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Client Bots added by users
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            bot_token TEXT,
            bot_username TEXT,
            bot_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Welcome settings for Client Bots
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS welcome_settings (
            bot_id INTEGER PRIMARY KEY,
            image_file_id TEXT,
            welcome_text TEXT,
            buttons TEXT,
            FOREIGN KEY(bot_id) REFERENCES bots(bot_id)
        )
    ''')
    
    # Users collected by Client Bots (for broadcast)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER,
            user_id INTEGER,
            full_name TEXT,
            joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bot_id, user_id)
        )
    ''')
    
    # Broadcast Admins for Client Bots
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS broadcast_admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER,
            admin_id INTEGER,
            UNIQUE(bot_id, admin_id)
        )
    ''')

    # Force Join Channels
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            channel_link TEXT,
            active INTEGER DEFAULT 1
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("Database Initialized.")

# --- Helper Functions ---

def get_db():
    return sqlite3.connect(DB_PATH)

def add_user(user_id, full_name, username):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id, full_name, username) VALUES (?, ?, ?)", 
                     (user_id, full_name, username))

def add_bot(owner_id, token, username, bot_id):
    with get_db() as conn:
        conn.execute("INSERT INTO bots (owner_id, bot_token, bot_username, bot_id) VALUES (?, ?, ?, ?)",
                     (owner_id, token, username, bot_id))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def get_user_bots(owner_id):
    with get_db() as conn:
        return conn.execute("SELECT bot_id, bot_username FROM bots WHERE owner_id = ?", (owner_id,)).fetchall()

def get_bot_owner(bot_id):
    with get_db() as conn:
        res = conn.execute("SELECT owner_id FROM bots WHERE bot_id = ?", (bot_id,)).fetchone()
        return res[0] if res else None

def get_bot_token(bot_id):
    with get_db() as conn:
        res = conn.execute("SELECT bot_token FROM bots WHERE bot_id = ?", (bot_id,)).fetchone()
        return res[0] if res else None

def save_welcome(bot_id, image_id, text, buttons):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO welcome_settings (bot_id, image_file_id, welcome_text, buttons) VALUES (?, ?, ?, ?)",
                     (bot_id, image_id, text, str(buttons)))

def get_welcome(bot_id):
    with get_db() as conn:
        return conn.execute("SELECT image_file_id, welcome_text, buttons FROM welcome_settings WHERE bot_id = ?", (bot_id,)).fetchone()

def add_broadcast_admins(bot_id, admin_ids):
    with get_db() as conn:
        for aid in admin_ids:
            conn.execute("INSERT OR IGNORE INTO broadcast_admins (bot_id, admin_id) VALUES (?, ?)", (bot_id, int(aid)))

def get_broadcast_admins(bot_id):
    with get_db() as conn:
        return [r[0] for r in conn.execute("SELECT admin_id FROM broadcast_admins WHERE bot_id = ?", (bot_id,)).fetchall()]

def add_client_user(bot_id, user_id, full_name):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO client_users (bot_id, user_id, full_name) VALUES (?, ?, ?)",
                     (bot_id, user_id, full_name))

def get_client_users(bot_id):
    with get_db() as conn:
        return conn.execute("SELECT user_id FROM client_users WHERE bot_id = ?", (bot_id,)).fetchall()

def delete_bot(bot_id):
    with get_db() as conn:
        conn.execute("DELETE FROM bots WHERE bot_id = ?", (bot_id,))
        conn.execute("DELETE FROM welcome_settings WHERE bot_id = ?", (bot_id,))
        conn.execute("DELETE FROM broadcast_admins WHERE bot_id = ?", (bot_id,))
        conn.execute("DELETE FROM client_users WHERE bot_id = ?", (bot_id,))

def add_channel(channel_id, link):
    with get_db() as conn:
        conn.execute("INSERT INTO channels (channel_id, channel_link) VALUES (?, ?)", (channel_id, link))

def get_channels():
    with get_db() as conn:
        return conn.execute("SELECT channel_id, channel_link FROM channels WHERE active = 1").fetchall()

def total_stats():
    with get_db() as conn:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        bots = conn.execute("SELECT COUNT(*) FROM bots").fetchone()[0]
        return users, bots
