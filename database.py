# database.py
import sqlite3
import json
import os

DB_NAME = "bot_control.db"

def init_db():
    """Initialize the database tables."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Table for Main Bot Users
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_date TEXT
        )
    ''')
    
    # Table for Connected Client Bots
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            bot_token TEXT,
            bot_username TEXT,
            welcome_text TEXT,
            welcome_image TEXT,
            buttons TEXT,
            broadcast_admins TEXT
        )
    ''')
    
    # Table for Client Bot Users (People who start the client bots)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_users (
            user_id INTEGER,
            bot_id INTEGER,
            PRIMARY KEY (user_id, bot_id)
        )
    ''')
    
    conn.commit()
    conn.close()

def add_user(user_id, username, first_name):
    """Register user in main bot."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)", 
                   (user_id, username, first_name))
    conn.commit()
    conn.close()

def add_client_bot(owner_id, token, username, text, image, buttons):
    """Save a new client bot."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO client_bots (owner_id, bot_token, bot_username, welcome_text, welcome_image, buttons)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (owner_id, token, username, text, image, json.dumps(buttons)))
    conn.commit()
    conn.close()

def get_user_bots(owner_id):
    """Get all bots belonging to a user."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, bot_username FROM client_bots WHERE owner_id = ?", (owner_id,))
    bots = cursor.fetchall()
    conn.close()
    return bots

def get_bot_info(bot_id):
    """Get specific bot details."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM client_bots WHERE id = ?", (bot_id,))
    bot = cursor.fetchone()
    conn.close()
    return bot

def delete_bot(bot_id, owner_id):
    """Delete a bot."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM client_bots WHERE id = ? AND owner_id = ?", (bot_id, owner_id))
    conn.commit()
    conn.close()

def update_bot_welcome(bot_id, text, image, buttons):
    """Update welcome message settings."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE client_bots 
        SET welcome_text = ?, welcome_image = ?, buttons = ?
        WHERE id = ?
    ''', (text, image, json.dumps(buttons), bot_id))
    conn.commit()
    conn.close()

def set_broadcast_admins(bot_id, admins_list):
    """Set broadcast admins for a bot."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE client_bots SET broadcast_admins = ? WHERE id = ?", 
                   (json.dumps(admins_list), bot_id))
    conn.commit()
    conn.close()

def add_client_user(user_id, bot_id):
    """Add user to a client bot's database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO client_users (user_id, bot_id) VALUES (?, ?)", 
                   (user_id, bot_id))
    conn.commit()
    conn.close()

def get_all_client_users(bot_id):
    """Get all user IDs for a specific client bot."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM client_users WHERE bot_id = ?", (bot_id,))
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_bot_by_token(token):
    """Find bot by token (used by client bot instance)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, owner_id, broadcast_admins FROM client_bots WHERE bot_token = ?", (token,))
    bot = cursor.fetchone()
    conn.close()
    return bot
