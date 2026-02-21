const express = require('express');
const { Telegraf, Markup, session } = require('telegraf');
const Database = require('better-sqlite3');
const path = require('path');

// ================= CONFIGURATION =================
const BOT_TOKEN = process.env.BOT_TOKEN || 'YOUR_BOT_TOKEN_HERE';
const ADMIN_IDS = process.env.ADMIN_IDS ? process.env.ADMIN_IDS.split(',').map(Number) : [123456789]; // Replace with your ID
const PORT = process.env.PORT || 3000;

// ================= EXPRESS & BOT SETUP =================
const app = express();
app.use(express.json());

// Initialize Bot
const bot = new Telegraf(BOT_TOKEN);

// ================= DATABASE SETUP (better-sqlite3) =================
// This creates a file 'botControlHub.db' in the current directory
const db = new Database('botControlHub.db');

// Create tables
db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS force_join (
    channel_id TEXT PRIMARY KEY,
    channel_title TEXT
  );

  CREATE TABLE IF NOT EXISTS client_bots (
    bot_id INTEGER PRIMARY KEY,
    owner_id INTEGER,
    token TEXT,
    username TEXT,
    welcome_text TEXT,
    welcome_image TEXT,
    buttons TEXT,
    broadcast_admins TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS client_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER,
    user_id INTEGER,
    UNIQUE(bot_id, user_id)
  );
`);

console.log('✅ Connected to SQLite Database.');

// ================= SESSION HANDLING =================
// Using a simple in-memory store for sessions (Suitable for single instance on Render)
const store = new Map();

bot.use(session({
  defaultSession: () => ({ step: null, data: {}, tempBot: {} })
}));

// ================= HELPER FUNCTIONS =================
const isUserAdmin = (userId) => ADMIN_IDS.includes(userId);

const requireAdmin = async (ctx, next) => {
  if (!isUserAdmin(ctx.from.id)) {
    return ctx.reply('🚫 আপনি এডমিন নন! এই কমান্ডটি শুধুমাত্র এডমিনদের জন্য।');
  }
  return next();
};

// ================= FORCE JOIN MIDDLEWARE =================
const checkForceJoin = async (ctx, next) => {
  const userId = ctx.from.id;
  if (isUserAdmin(userId)) return next(); // Admins bypass

  const channels = db.prepare("SELECT * FROM force_join").all();
  if (channels.length === 0) return next();

  let notJoined = [];
  for (const ch of channels) {
    try {
      const member = await ctx.telegram.getChatMember(ch.channel_id, userId);
      if (['left', 'kicked'].includes(member.status)) {
        notJoined.push(ch);
      }
    } catch (e) {
      console.error(`Error checking channel ${ch.channel_id}:`, e.message);
    }
  }

  if (notJoined.length > 0) {
    const buttons = notJoined.map(ch => 
      [Markup.button.url(`📢 ${ch.channel_title}`, `https://t.me/${ch.channel_id.replace('@', '')}`)]
    );
    buttons.push([Markup.button.callback('✅ আমি জয়েন করেছি', 'check_join')]);
    
    return ctx.reply(
      '🔒 **অ্যাক্সেস করতে প্রথমে নিচের চ্যানেলগুলোতে জয়েন করুন!**',
      { parse_mode: 'Markdown', ...Markup.inlineKeyboard(buttons) }
    );
  }
  return next();
};

bot.use(checkForceJoin);

// ================= CLIENT BOT LAUNCHER =================
const activeBots = {}; // Track running bots

const launchClientBot = (token, botId) => {
  if (activeBots[botId]) return; // Already running

  const clientBot = new Telegraf(token);
  
  clientBot.start(async (ctx) => {
    const userId = ctx.from.id;
    // Save user to client_users
    try {
      db.prepare(`INSERT OR IGNORE INTO client_users (bot_id, user_id) VALUES (?, ?)`).run(botId, userId);
    } catch(e) {}

    // Fetch welcome config
    const row = db.prepare(`SELECT * FROM client_bots WHERE bot_id = ?`).get(botId);
    
    if (!row) return ctx.reply('👋 স্বাগতম! এই বটটি এখনও সেটআপ হয়নি।');

    let message = row.welcome_text || '👋 স্বাগতম!';
    let buttons = [];
    
    try {
      if (row.buttons) buttons = JSON.parse(row.buttons);
    } catch (e) {}

    const keyboard = buttons.length > 0 ? Markup.inlineKeyboard(buttons) : Markup.removeKeyboard();

    if (row.welcome_image) {
      ctx.replyWithPhoto(row.welcome_image, { 
        caption: message, 
        parse_mode: 'HTML', 
        ...keyboard 
      }).catch(() => ctx.reply(message, { parse_mode: 'HTML', ...keyboard }));
    } else {
      ctx.reply(message, { parse_mode: 'HTML', ...keyboard });
    }
  });

  // Client Broadcast Logic
  clientBot.command('broadcast', async (ctx) => {
    const userId = ctx.from.id;
    const row = db.prepare(`SELECT broadcast_admins FROM client_bots WHERE bot_id = ?`).get(botId);
    
    if (!row) return;
    const admins = row.broadcast_admins ? row.broadcast_admins.split(',').map(Number) : [];
    
    if (!admins.includes(userId)) return ctx.reply('🚫 আপনার এই কমান্ড ব্যবহার করার অনুমতি নেই।');

    ctx.session = ctx.session || {};
    ctx.session.step = 'client_broadcast_image';
    ctx.session.data = { botId };
    ctx.reply('📢 **ব্রডকাস্ট শুরু!**\n\nছবি পাঠান বা "Skip" লিখুন।', { parse_mode: 'Markdown' });
  });

  // Client Broadcast Flow Handling
  clientBot.on('text', async (ctx) => {
    if (!ctx.session || !ctx.session.step || !ctx.session.step.startsWith('client_broadcast')) return;

    const step = ctx.session.step;
    const text = ctx.message.text;

    if (step === 'client_broadcast_image') {
      if (text.toLowerCase() === 'skip') {
        ctx.session.step = 'client_broadcast_text';
        return ctx.reply('✅ এখন টেক্সট লিখুন বা Skip করুন।');
      }
      ctx.reply('⚠️ ছবি পাঠান বা Skip লিখুন।');
    } 
    else if (step === 'client_broadcast_text') {
      ctx.session.data.text = text.toLowerCase() === 'skip' ? null : text;
      ctx.session.step = 'client_broadcast_button';
      ctx.reply('🔘 বাটন? (নাম - url) অথবা Skip।', { parse_mode: 'Markdown' });
    }
    else if (step === 'client_broadcast_button') {
      ctx.session.data.button = text.toLowerCase() === 'skip' ? null : text;
      ctx.session.step = 'client_broadcast_confirm';
      ctx.reply('✅ কনফার্ম করতে "Yes" লিখুন।');
    }
    else if (step === 'client_broadcast_confirm') {
      if (text.toLowerCase() !== 'yes') {
        ctx.session = null;
        return ctx.reply('❌ বাতিল।');
      }

      const { text: msgText, button } = ctx.session.data;
      const users = db.prepare(`SELECT user_id FROM client_users WHERE bot_id = ?`).all(ctx.session.data.botId);
      
      let buttons = [];
      if (button && button.includes('-')) {
        const parts = button.split('-').map(p => p.trim());
        buttons.push([Markup.button.url(parts[0], parts[1])]);
      }

      let count = 0;
      for (const u of users) {
        try {
          if (msgText) {
            await clientBot.telegram.sendMessage(u.user_id, msgText, {
              parse_mode: 'HTML',
              ...(buttons.length > 0 && Markup.inlineKeyboard(buttons))
            });
            count++;
          }
        } catch (e) {}
      }
      ctx.reply(`✅ সফলভাবে ${count} জনকে পাঠানো হয়েছে।`);
      ctx.session = null;
    }
  });

  clientBot.on('photo', (ctx) => {
    if (ctx.session && ctx.session.step === 'client_broadcast_image') {
      ctx.session.data.image = ctx.message.photo[ctx.message.photo.length - 1].file_id;
      ctx.session.step = 'client_broadcast_text';
      ctx.reply('✅ ছবি সেভ হলো। টেক্সট লিখুন।');
    }
  });

  clientBot.launch().then(() => {
    activeBots[botId] = clientBot;
    console.log(`🤖 Client Bot Started: ${botId}`);
  }).catch(e => console.error(`Failed to start bot ${botId}:`, e.message));
};

// Load existing bots on startup
const existingBots = db.prepare(`SELECT bot_id, token FROM client_bots`).all();
existingBots.forEach(r => launchClientBot(r.token, r.bot_id));

// ================= MAIN BOT HANDLERS =================

bot.start(async (ctx) => {
  const user = ctx.from;
  db.prepare(`INSERT OR REPLACE INTO users (user_id, first_name, username) VALUES (?, ?, ?)`).run(user.id, user.first_name, user.username);

  ctx.reply(
    `👋 হ্যালো *${user.first_name}*!\n\nআমি *Bot Control Hub*।\n\n🚀 Get Started বাটনে ক্লিক করুন।`,
    { 
      parse_mode: 'Markdown', 
      ...Markup.inlineKeyboard([[Markup.button.callback('🚀 Get Started', 'start_menu')]])
    }
  );
});

bot.action('check_join', async (ctx) => {
  await ctx.deleteMessage();
  ctx.reply('🔄 চেক করা হচ্ছে... আবার /start দিন।');
});

bot.action('start_menu', (ctx) => {
  const isAdmin = isUserAdmin(ctx.from.id);
  const buttons = [
    [Markup.button.callback('🤖 My Bots', 'my_bots')],
    [Markup.button.callback('➕ New Bot', 'new_bot_start')],
    [Markup.button.callback('📢 Broadcast Setup', 'broadcast_setup_menu')]
  ];
  if (isAdmin) buttons.push([Markup.button.callback('🛠️ Admin Panel', 'admin_panel')]);
  
  ctx.editMessageText('🏠 **মূল মেনু**', { parse_mode: 'Markdown', ...Markup.inlineKeyboard(buttons) });
});

// ================= NEW BOT FLOW =================
bot.action('new_bot_start', (ctx) => {
  ctx.session.step = 'new_bot_token';
  ctx.editMessageText('1️⃣ **নতুন বট সেটআপ**\n\nবট টোকেন পাঠান।', { parse_mode: 'Markdown' });
});

bot.on('text', async (ctx) => {
  const step = ctx.session.step;
  const text = ctx.message.text;

  // --- NEW BOT SETUP ---
  if (step === 'new_bot_token') {
    if (!text.includes(':')) return ctx.reply('❌ ভুল টোকেন।');
    try {
      const tempBot = new Telegraf(text);
      const botInfo = await tempBot.telegram.getMe();
      
      ctx.session.tempBot = { token: text, username: botInfo.username, id: botInfo.id };
      ctx.session.step = 'new_bot_image';
      ctx.reply(`✅ বট: @${botInfo.username}\n\n2️⃣ ওয়েলকাম ইমেজ পাঠান বা "Skip"।`);
    } catch (e) {
      ctx.reply('❌ ভুল টোকেন।');
    }
  }
  else if (step === 'new_bot_image') {
    if (text.toLowerCase() === 'skip') {
      ctx.session.tempBot.image = null;
      ctx.session.step = 'new_bot_text';
      return ctx.reply('✅ এখন ওয়েলকাম টেক্সট লিখুন।');
    }
    ctx.reply('⚠️ ছবি পাঠান বা Skip লিখুন।');
  }
  else if (step === 'new_bot_text') {
    ctx.session.tempBot.text = text;
    ctx.session.step = 'new_bot_button_count';
    ctx.reply('✅ কতগুলো বাটন? (1-3)');
  }
  else if (step === 'new_bot_button_count') {
    const count = parseInt(text);
    if (isNaN(count) || count < 1 || count > 3) return ctx.reply('⚠️ 1 থেকে 3 এর মধ্যে দিন।');
    
    ctx.session.tempBot.buttons = [];
    ctx.session.tempBot.buttonCount = count;
    ctx.session.tempBot.currentButton = 1;
    ctx.session.step = 'new_button_details';
    ctx.reply(`🔘 বাটন 1: নাম - URL`);
  }
  else if (step === 'new_button_details') {
    if (!text.includes('-')) return ctx.reply('⚠️ ফরম্যাট: নাম - URL');
    
    const parts = text.split('-');
    ctx.session.tempBot.buttons.push([Markup.button.url(parts[0].trim(), parts[1].trim())]);
    
    const next = ctx.session.tempBot.currentButton + 1;
    const total = ctx.session.tempBot.buttonCount;

    if (next <= total) {
      ctx.session.tempBot.currentButton = next;
      ctx.reply(`✅ বাটন ${next-1} সেট।\n🔘 বাটন ${next}:`);
    } else {
      const b = ctx.session.tempBot;
      const buttonsJson = JSON.stringify(b.buttons);
      
      const info = db.prepare(`INSERT INTO client_bots (owner_id, token, username, welcome_text, welcome_image, buttons) VALUES (?, ?, ?, ?, ?, ?)`).run(ctx.from.id, b.token, b.username, b.text, b.image, buttonsJson);
      
      const botDbId = info.lastInsertRowid;
      launchClientBot(b.token, botDbId);
      
      // Alert Admin
      const alertMsg = `🆕 নতুন বট:\n👤 User: ${ctx.from.id}\n🤖 Bot: @${b.username}`;
      ADMIN_IDS.forEach(id => bot.telegram.sendMessage(id, alertMsg));
      
      ctx.session = {};
      ctx.reply(`🎉 বট তৈরি হয়েছে! @${b.username}`);
    }
  }

  // --- ADMIN BROADCAST / FORCE JOIN ---
  else if (ctx.session.step === 'add_force_channel') {
    if (text.includes('-')) {
      const parts = text.split('-');
      db.prepare(`INSERT INTO force_join (channel_id, channel_title) VALUES (?, ?)`).run(parts[0].trim(), parts[1].trim());
      ctx.reply(`✅ চ্যানেল যোগ হয়েছে।`);
      ctx.session = {};
    } else ctx.reply('⚠️ ফরম্যাট: -100ID - Title');
  }
  else if (ctx.session.step === 'input_bc_admins') {
    const botId = ctx.session.data.targetBotId;
    db.prepare(`UPDATE client_bots SET broadcast_admins = ? WHERE bot_id = ?`).run(text, botId);
    ctx.reply('✅ ব্রডকাস্ট এডমিন সেট হয়েছে।');
    ctx.session = {};
  }

  // --- ADMIN BROADCAST FLOW (Similar logic as before) ---
  else if (ctx.session.step === 'adm_bc_img') {
    if (text.toLowerCase() === 'skip') ctx.session.data.img = null;
    ctx.session.step = 'adm_bc_text';
    ctx.reply('2. টেক্সট লিখুন।');
  }
  else if (ctx.session.step === 'adm_bc_text') {
    if (text.toLowerCase() === 'skip') ctx.session.data.txt = null;
    ctx.session.step = 'adm_bc_btn';
    ctx.reply('3. বাটন (নাম - url) বা Skip।');
  }
  else if (ctx.session.step === 'adm_bc_btn') {
    if (text.toLowerCase() !== 'skip') {
       const parts = text.split('-');
       ctx.session.data.btn = [[Markup.button.url(parts[0].trim(), parts[1].trim())]];
    } else ctx.session.data.btn = null;
    ctx.session.step = 'adm_bc_confirm';
    ctx.reply('কনফার্ম করতে Yes লিখুন।');
  }
  else if (ctx.session.step === 'adm_bc_confirm') {
    if (text.toLowerCase() !== 'yes') { ctx.session = {}; return ctx.reply('বাতিল'); }
    
    const { img, txt, btn } = ctx.session.data;
    const type = ctx.session.data.broadcastType;
    
    let users = [];
    if (type === 'main') users = db.prepare(`SELECT user_id FROM users`).all();
    else users = db.prepare(`SELECT user_id FROM client_users`).all();

    ctx.reply(`🚀 পাঠানো হচ্ছে ${users.length} জনকে...`);
    
    const opts = { parse_mode: 'HTML' };
    if (btn) opts.reply_markup = Markup.inlineKeyboard(btn).reply_markup;

    let count = 0;
    for (const u of users) {
      try {
        if (img) await bot.telegram.sendPhoto(u.user_id, img, { caption: txt || '', ...opts });
        else if (txt) await bot.telegram.sendMessage(u.user_id, txt, opts);
        count++;
      } catch(e) {}
    }
    ctx.reply(`✅ সম্পন্ন ${count}`);
    ctx.session = {};
  }
});

bot.on('photo', (ctx) => {
  if (ctx.session.step === 'new_bot_image') {
    ctx.session.tempBot.image = ctx.message.photo[ctx.message.photo.length - 1].file_id;
    ctx.session.step = 'new_bot_text';
    ctx.reply('✅ এখন টেক্সট লিখুন।');
  }
  else if (ctx.session.step === 'adm_bc_img') {
    ctx.session.data.img = ctx.message.photo[ctx.message.photo.length - 1].file_id;
    ctx.session.step = 'adm_bc_text';
    ctx.reply('✅ টেক্সট লিখুন।');
  }
});

// ================= MENUS & ACTIONS =================

bot.action('my_bots', (ctx) => {
  const rows = db.prepare(`SELECT * FROM client_bots WHERE owner_id = ?`).all(ctx.from.id);
  if (rows.length === 0) return ctx.editMessageText('😢 কোনো বট নেই।', Markup.inlineKeyboard([[Markup.button.callback('➕ Add', 'new_bot_start')]]));

  const buttons = rows.map(r => [Markup.button.callback(`🤖 @${r.username}`, `manage_bot_${r.bot_id}`)]);
  buttons.push([Markup.button.callback('🔙 ব্যাক', 'start_menu')]);
  ctx.editMessageText('🤖 আপনার বট:', { ...Markup.inlineKeyboard(buttons) });
});

bot.action(/manage_bot_(\d+)/, (ctx) => {
  const botId = ctx.match[1];
  const row = db.prepare(`SELECT * FROM client_bots WHERE bot_id = ?`).get(botId);
  if (!row) return ctx.reply('Error');
  
  ctx.editMessageText(`🔧 Manage: @${row.username}`, 
    Markup.inlineKeyboard([
      [Markup.button.callback('🗑️ Delete', `delete_bot_${botId}`)],
      [Markup.button.callback('🔙 ব্যাক', 'my_bots')]
    ])
  );
});

bot.action(/delete_bot_(\d+)/, (ctx) => {
  const botId = ctx.match[1];
  if (activeBots[botId]) { activeBots[botId].stop(); delete activeBots[botId]; }
  
  db.prepare(`DELETE FROM client_bots WHERE bot_id = ?`).run(botId);
  db.prepare(`DELETE FROM client_users WHERE bot_id = ?`).run(botId);
  ctx.editMessageText('✅ ডিলিট হয়েছে।', Markup.inlineKeyboard([[Markup.button.callback('🔙 ব্যাক', 'my_bots')]]));
});

bot.action('broadcast_setup_menu', (ctx) => {
  const rows = db.prepare(`SELECT bot_id, username FROM client_bots WHERE owner_id = ?`).all(ctx.from.id);
  if (rows.length === 0) return ctx.editMessageText('বট নেই।');
  
  const buttons = rows.map(r => [Markup.button.callback(`📢 @${r.username}`, `set_bc_admin_${r.bot_id}`)]);
  ctx.editMessageText('কোন বটের জন্য?', Markup.inlineKeyboard(buttons));
});

bot.action(/set_bc_admin_(\d+)/, (ctx) => {
  const botId = ctx.match[1];
  ctx.session.step = 'input_bc_admins';
  ctx.session.data.targetBotId = botId;
  ctx.editMessageText('User ID গুলো পাঠান (কমা দিয়ে):');
});

// ================= ADMIN PANEL =================

bot.action('admin_panel', requireAdmin, (ctx) => {
  ctx.editMessageText('🛠️ এডমিন প্যানেল', 
    Markup.inlineKeyboard([
      [Markup.button.callback('📊 Stats', 'admin_stats')],
      [Markup.button.callback('📢 Main Broadcast', 'admin_main_bc')],
      [Markup.button.callback('🌍 Global Broadcast', 'admin_global_bc')],
      [Markup.button.callback('🔒 Force Join', 'admin_force')],
      [Markup.button.callback('🔙 ব্যাক', 'start_menu')]
    ])
  );
});

bot.action('admin_stats', requireAdmin, (ctx) => {
  const u = db.prepare(`SELECT count(*) as count FROM users`).get();
  const b = db.prepare(`SELECT count(*) as count FROM client_bots`).get();
  ctx.editMessageText(`📊 Stats:\n👥 Users: ${u.count}\n🤖 Bots: ${b.count}`, Markup.inlineKeyboard([[Markup.button.callback('🔙 ব্যাক', 'admin_panel')]]));
});

bot.action('admin_force', requireAdmin, (ctx) => {
  const rows = db.prepare(`SELECT * FROM force_join`).all();
  let msg = "🔒 Channels:\n";
  rows.forEach(r => msg += `${r.channel_title}\n`);
  ctx.editMessageText(msg, Markup.inlineKeyboard([
    [Markup.button.callback('➕ Add', 'add_force')],
    [Markup.button.callback('🗑️ Clear', 'clear_force')],
    [Markup.button.callback('🔙 ব্যাক', 'admin_panel')]
  ]));
});

bot.action('add_force', (ctx) => {
  ctx.session.step = 'add_force_channel';
  ctx.editMessageText('ফরম্যাট: `-100ID - Title`');
});

bot.action('clear_force', requireAdmin, (ctx) => {
  db.prepare(`DELETE FROM force_join`).run();
  ctx.editMessageText('✅ Cleared.', Markup.inlineKeyboard([[Markup.button.callback('🔙 ব্যাক', 'admin_force')]]));
});

bot.action('admin_main_bc', requireAdmin, (ctx) => {
  ctx.session.data.broadcastType = 'main';
  ctx.session.step = 'adm_bc_img';
  ctx.editMessageText('📢 Main Broadcast:\n1. ছবি পাঠান বা Skip।');
});

bot.action('admin_global_bc', requireAdmin, (ctx) => {
  ctx.session.data.broadcastType = 'global';
  ctx.session.step = 'adm_bc_img';
  ctx.editMessageText('🌍 Global Broadcast:\n1. ছবি পাঠান বা Skip।');
});

// ================= SERVER LAUNCH =================
// Set the bot webhook
const WEBHOOK_URL = process.env.RENDER_EXTERNAL_URL ? `${process.env.RENDER_EXTERNAL_URL}/bot${BOT_TOKEN}` : `/bot${BOT_TOKEN}`;

// Use Express middleware for the webhook
app.use(bot.webhookCallback(WEBHOOK_URL.substring(WEBHOOK_URL.lastIndexOf('/bot'))));

app.listen(PORT, () => {
  console.log(`🚀 Server listening on port ${PORT}`);
  if (process.env.RENDER_EXTERNAL_URL) {
    bot.telegram.setWebhook(WEBHOOK_URL).then(() => console.log(`✅ Webhook set: ${WEBHOOK_URL}`));
  } else {
    console.log('Running locally, webhook not set.');
  }
});

// Graceful shutdown
process.once('SIGINT', () => { db.close(); bot.stop('SIGINT'); });
process.once('SIGTERM', () => { db.close(); bot.stop('SIGTERM'); });
