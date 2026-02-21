const express = require('express');
const { Telegraf, Markup, session } = require('telegraf');
const sqlite3 = require('sqlite3').verbose();
const axios = require('axios');
const path = require('path');

// ================= CONFIGURATION =================
const BOT_TOKEN = process.env.BOT_TOKEN || 'YOUR_BOT_TOKEN_HERE';
const ADMIN_IDS = process.env.ADMIN_IDS ? process.env.ADMIN_IDS.split(',').map(Number) : [123456789]; // Replace with your ID
const PORT = process.env.PORT || 3000;
const WEBHOOK_URL = process.env.RENDER_EXTERNAL_URL || `http://localhost:${PORT}`;

// ================= EXPRESS SERVER =================
const app = express();
app.use(express.json());
app.get('/', (req, res) => res.send('✅ Bot Control Hub Server is Running!'));
app.listen(PORT, () => console.log(`🚀 Server listening on port ${PORT}`));

// ================= DATABASE SETUP (SQLite) =================
const db = new sqlite3.Database('./botControlHub.db', (err) => {
  if (err) console.error('❌ Database opening error:', err.message);
  else console.log('✅ Connected to SQLite Database.');
});

// Initialize Tables
db.serialize(() => {
  // Main bot users
  db.run(`CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )`);

  // Force Join Channels
  db.run(`CREATE TABLE IF NOT EXISTS force_join (
    channel_id TEXT PRIMARY KEY,
    channel_title TEXT
  )`);

  // Client Bots added by users
  db.run(`CREATE TABLE IF NOT EXISTS client_bots (
    bot_id INTEGER PRIMARY KEY,
    owner_id INTEGER,
    token TEXT,
    username TEXT,
    welcome_text TEXT,
    welcome_image TEXT,
    buttons TEXT,
    broadcast_admins TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )`);

  // Users of Client Bots (for broadcast)
  db.run(`CREATE TABLE IF NOT EXISTS client_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER,
    user_id INTEGER,
    UNIQUE(bot_id, user_id)
  )`);
});

// ================= TELEGRAPH BOT SETUP =================
const bot = new Telegraf(BOT_TOKEN);

// Session Middleware
bot.use(session({
  defaultSession: () => ({
    step: null,
    data: {},
    tempBot: {}
  })
}));

// ================= HELPER FUNCTIONS =================
const isUserAdmin = (userId) => ADMIN_IDS.includes(userId);

const requireAdmin = async (ctx, next) => {
  if (!isUserAdmin(ctx.from.id)) {
    return ctx.reply('🚫 আপনি এডমিন নন! এই কমান্ডটি শুধুমাত্র এডমিনদের জন্য।');
  }
  return next();
};

// Check Force Join
const checkForceJoin = async (ctx, next) => {
  const userId = ctx.from.id;
  
  // Bypass for admins
  if (isUserAdmin(userId)) return next();

  const channels = await new Promise((resolve) => {
    db.all("SELECT * FROM force_join", [], (err, rows) => resolve(rows || []));
  });

  if (channels.length === 0) return next();

  let notJoined = [];
  for (const ch of channels) {
    try {
      const member = await ctx.telegram.getChatMember(ch.channel_id, userId);
      if (['left', 'kicked'].includes(member.status)) {
        notJoined.push(ch);
      }
    } catch (e) {
      // If bot can't check (bot not admin in channel), assume joined to avoid blocking
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
      { parse_mode: 'Markdown', ...Markup.inlineKeyboard(buttones) }
    );
  }
  return next();
};

// Start Client Bot
const launchClientBot = (token, botId) => {
  if (!token) return;
  
  // Prevent duplicate launches
  if (global.activeBots && global.activeBots[botId]) return;

  const clientBot = new Telegraf(token);
  
  clientBot.start(async (ctx) => {
    const userId = ctx.from.id;
    const botInfo = ctx.botInfo;

    // Save user to client_users table
    db.run(`INSERT OR IGNORE INTO client_users (bot_id, user_id) VALUES (?, ?)`, [botId, userId]);

    // Fetch welcome config
    db.get(`SELECT * FROM client_bots WHERE bot_id = ?`, [botId], async (err, row) => {
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
  });

  // Client Bot Broadcast Command
  clientBot.command('broadcast', async (ctx) => {
    const userId = ctx.from.id;
    
    // Check if this user is a broadcast admin
    db.get(`SELECT broadcast_admins FROM client_bots WHERE bot_id = ?`, [botId], async (err, row) => {
      if (!row) return;
      
      const admins = row.broadcast_admins ? row.broadcast_admins.split(',').map(Number) : [];
      if (!admins.includes(userId)) return ctx.reply('🚫 আপনার এই কমান্ড ব্যবহার করার অনুমতি নেই।');

      // Start Broadcast Flow
      ctx.session = ctx.session || {};
      ctx.session.step = 'client_broadcast_image';
      ctx.session.data = { botId };
      ctx.reply('📢 **ব্রডকাস্ট শুরু করছি!**\n\nপ্রথমে একটি ছবি পাঠান অথবা "Skip" লিখুন।', { parse_mode: 'Markdown' });
    });
  });

  // Client Bot Session & Handlers
  clientBot.use(session());
  clientBot.on('text', async (ctx) => {
    if (!ctx.session || !ctx.session.step) return;

    const step = ctx.session.step;
    const text = ctx.message.text;

    if (step === 'client_broadcast_image') {
      if (text.toLowerCase() === 'skip') {
        ctx.session.step = 'client_broadcast_text';
        return ctx.reply('✅ ছবি স্কিপ করা হলো। এখন টেক্সট লিখুন অথবা Skip করুন।');
      }
      ctx.reply('⚠️ দয়া করে একটি ছবি পাঠান অথবা "Skip" লিখুন।');
    } 
    else if (step === 'client_broadcast_text') {
      ctx.session.data.text = text.toLowerCase() === 'skip' ? null : text;
      ctx.session.step = 'client_broadcast_button';
      ctx.reply('🔘 বাটন যোগ করতে চান?\nফরম্যাট: `নাম - url`\nঅথবা "Skip" লিখুন।', { parse_mode: 'Markdown' });
    }
    else if (step === 'client_broadcast_button') {
      ctx.session.data.button = text.toLowerCase() === 'skip' ? null : text;
      ctx.session.step = 'client_broadcast_confirm';
      
      let preview = "📢 **কনফার্মেশন:**\n\n";
      if (ctx.session.data.image) preview += "🖼 ছবি আছে\n";
      if (ctx.session.data.text) preview += `📝 টেক্সট: ${ctx.session.data.text}\n`;
      if (ctx.session.data.button) preview += `🔘 বাটন: ${ctx.session.data.button}\n`;
      
      preview += "\n✅ পাঠাতে হলে 'Yes' লিখুন। বাতিল করতে 'No' লিখুন।";
      ctx.reply(preview, { parse_mode: 'Markdown' });
    }
    else if (step === 'client_broadcast_confirm') {
      if (text.toLowerCase() !== 'yes') {
        ctx.session = null;
        return ctx.reply('❌ ব্রডকাস্ট বাতিল করা হয়েছে।');
      }

      const { botId, text: msgText, button } = ctx.session.data;
      
      // Get users
      db.all(`SELECT user_id FROM client_users WHERE bot_id = ?`, [botId], async (err, users) => {
        if (!users || users.length === 0) return ctx.reply('😢 কোনো ইউজার পাওয়া যায়নি।');
        
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
          } catch (e) { /* Skip blocked users */ }
        }
        ctx.reply(`✅ সফলভাবে ${count} জনকে ব্রডকাস্ট পাঠানো হয়েছে।`);
        ctx.session = null;
      });
    }
  });

  clientBot.on('photo', (ctx) => {
    if (ctx.session && ctx.session.step === 'client_broadcast_image') {
      ctx.session.data.image = ctx.message.photo[ctx.message.photo.length - 1].file_id;
      ctx.session.step = 'client_broadcast_text';
      ctx.reply('✅ ছবি সেভ হলো। এখন টেক্সট লিখুন অথবা Skip করুন।');
    }
  });

  clientBot.launch().then(() => {
    if (!global.activeBots) global.activeBots = {};
    global.activeBots[botId] = clientBot;
    console.log(`🤖 Client Bot Started: ${botId}`);
  }).catch(e => console.error(`Failed to start bot ${botId}:`, e.message));
};

// Load all existing client bots on startup
db.all(`SELECT bot_id, token FROM client_bots`, [], (err, rows) => {
  if (rows) rows.forEach(r => launchClientBot(r.token, r.bot_id));
});

// ================= MAIN BOT HANDLERS =================

bot.start(async (ctx) => {
  const user = ctx.from;
  
  // Register User
  db.run(`INSERT OR REPLACE INTO users (user_id, first_name, username) VALUES (?, ?, ?)`, 
    [user.id, user.first_name, user.username]);

  const buttons = Markup.inlineKeyboard([
    [Markup.button.callback('🚀 Get Started', 'start_menu')]
  ]);

  ctx.reply(
    `👋 হ্যালো *${user.first_name}*!\n\nআমি *Bot Control Hub*। এখান থেকে আপনি আপনার নিজের টেলিগ্রাম বট তৈরি ও পরিচালনা করতে পারবেন।\n\nনিচের বাটমে ক্লিক করে শুরু করুন! 👇`,
    { parse_mode: 'Markdown', ...buttons }
  );
});

bot.action('check_join', async (ctx) => {
  await ctx.deleteMessage();
  // Re-check logic or just restart
  ctx.reply('🔄 আপনার স্ট্যাটাস চেক করা হচ্ছে...');
  // Ideally, trigger the start handler again or middleware will handle on next action
});

// ================= USER MENUS =================

bot.action('start_menu', async (ctx) => {
  const isAdmin = isUserAdmin(ctx.from.id);
  const buttons = [
    [Markup.button.callback('🤖 My Bots', 'my_bots')],
    [Markup.button.callback('➕ New Bot', 'new_bot_start')],
    [Markup.button.callback('📢 Broadcast Setup', 'broadcast_setup_menu')]
  ];
  if (isAdmin) {
    buttons.push([Markup.button.callback('🛠️ Admin Panel', 'admin_panel')]);
  }
  
  ctx.editMessageText('🏠 **মূল মেনু**\n\nআপনি কী করতে চান?', {
    parse_mode: 'Markdown',
    ...Markup.inlineKeyboard(buttons)
  });
});

bot.action('back_home', (ctx) => ctx.editMessageText('🏠 মূল মেনুতে ফিরে এলেন।', 
  Markup.inlineKeyboard([[Markup.button.callback('🚀 Get Started', 'start_menu')]]))
);

// ================= NEW BOT FLOW =================

bot.action('new_bot_start', (ctx) => {
  ctx.session.step = 'new_bot_token';
  ctx.editMessageText('1️⃣ **নতুন বট সেটআপ**\n\nপ্রথমে আপনার বট টোকেন পাঠান।\n(@BotFather থেকে নিন)', { parse_mode: 'Markdown' });
});

bot.on('text', async (ctx) => {
  const step = ctx.session.step;
  const text = ctx.message.text;

  // --- New Bot Flow ---
  if (step === 'new_bot_token') {
    if (!text.includes(':')) return ctx.reply('❌ এটি সঠিক টোকেন নয়। আবার চেষ্টা করুন।');
    
    ctx.reply('🔄 টোকেন ভ্যালিডেট করা হচ্ছে...');
    try {
      const tempBot = new Telegraf(text);
      const botInfo = await tempBot.telegram.getMe();
      
      ctx.session.tempBot = {
        token: text,
        username: botInfo.username,
        id: botInfo.id
      };
      ctx.session.step = 'new_bot_image';
      ctx.reply(`✅ বট পাওয়া গেছে: @${botInfo.username}\n\n2️⃣ আপনি কি ওয়েলকাম ইমেজ চান?\nএকটি ছবি পাঠান অথবা "Skip" লিখুন।`);
    } catch (e) {
      ctx.reply('❌ ভুল টোকেন বা বট এক্টিভ নেই।');
    }
  }
  else if (step === 'new_bot_image') {
    if (text.toLowerCase() === 'skip') {
      ctx.session.tempBot.image = null;
      ctx.session.step = 'new_bot_text';
      return ctx.reply('✅ ছবি স্কিপ করা হলো।\n\n3️⃣ এখন ওয়েলকাম টেক্সট লিখুন। (HTML ব্যবহার করতে পারবেন)');
    }
    ctx.reply('⚠️ একটি ছবি ফাইল পাঠান বা "Skip" লিখুন।');
  }
  else if (step === 'new_bot_text') {
    ctx.session.tempBot.text = text;
    ctx.session.step = 'new_bot_button_count';
    ctx.reply('✅ টেক্সট সেভ হলো।\n\n4️⃣ কতগুলো বাটন চান? (1-3 এর মধ্যে সংখ্যা লিখুন)');
  }
  else if (step === 'new_bot_button_count') {
    const count = parseInt(text);
    if (isNaN(count) || count < 1 || count > 3) return ctx.reply('⚠️ দয়া করে 1 থেকে 3 এর মধ্যে একটি সংখ্যা দিন।');
    
    ctx.session.tempBot.buttons = [];
    ctx.session.tempBot.buttonCount = count;
    ctx.session.tempBot.currentButton = 1;
    ctx.session.step = 'new_button_details';
    ctx.reply(`🔘 বাটন 1:\n\nনাম এবং URL দিন। ফরম্যাট:\nনাম - URL`);
  }
  else if (step === 'new_button_details') {
    if (!text.includes('-')) return ctx.reply('⚠️ ফরম্যাট ঠিক নেই। নাম - URL এভাবে দিন।');
    
    const parts = text.split('-');
    ctx.session.tempBot.buttons.push([Markup.button.url(parts[0].trim(), parts[1].trim())]);
    
    const next = ctx.session.tempBot.currentButton + 1;
    const total = ctx.session.tempBot.buttonCount;

    if (next <= total) {
      ctx.session.tempBot.currentButton = next;
      ctx.reply(`✅ বাটন ${next-1} সেট হলো।\n\n🔘 বাটন ${next} এর তথ্য দিন:`);
    } else {
      // Finish Setup
      const b = ctx.session.tempBot;
      const buttonsJson = JSON.stringify(b.buttons);
      
      db.run(`INSERT INTO client_bots (owner_id, token, username, welcome_text, welcome_image, buttons) VALUES (?, ?, ?, ?, ?, ?)`,
        [ctx.from.id, b.token, b.username, b.text, b.image, buttonsJson],
        function(err) {
          if (err) return ctx.reply('❌ ডাটাবেসে সেভ করতে সমস্যা হয়েছে।');
          
          const botDbId = this.lastID;
          
          // Launch the bot immediately
          launchClientBot(b.token, botDbId);
          
          // Alert Admin
          const alertMsg = `🆕 **নতুন বট যোগ হয়েছে!**\n\n👤 User: ${ctx.from.first_name} (${ctx.from.id})\n🤖 Bot: @${b.username}\n🆔 ID: ${b.id}\n🗓 Time: ${new Date().toLocaleString()}`;
          ADMIN_IDS.forEach(id => bot.telegram.sendMessage(id, alertMsg, { parse_mode: 'Markdown' }));
          
          ctx.session = {};
          ctx.reply(`🎉 **সফলভাবে বট তৈরি হয়েছে!**\n\nআপনার বট: @${b.username}\nএখন থেকে এটি কাজ করবে।`, { parse_mode: 'Markdown' });
        });
    }
  }
});

bot.on('photo', (ctx) => {
  const step = ctx.session.step;
  if (step === 'new_bot_image') {
    ctx.session.tempBot.image = ctx.message.photo[ctx.message.photo.length - 1].file_id;
    ctx.session.step = 'new_bot_text';
    ctx.reply('✅ ছবি সেভ হলো।\n\n3️⃣ এখন ওয়েলকাম টেক্সট লিখুন।');
  }
});

// ================= MY BOTS =================

bot.action('my_bots', (ctx) => {
  db.all(`SELECT * FROM client_bots WHERE owner_id = ?`, [ctx.from.id], (err, rows) => {
    if (!rows || rows.length === 0) {
      return ctx.editMessageText('😢 আপনি এখনও কোনো বট যোগ করেননি।', 
        Markup.inlineKeyboard([[Markup.button.callback('➕ নতুন বট যোগ করুন', 'new_bot_start')]]));
    }

    let buttons = [];
    rows.forEach(r => {
      buttons.push([Markup.button.callback(`🤖 @${r.username}`, `manage_bot_${r.bot_id}`)]);
    });
    buttons.push([Markup.button.callback('🔙 ব্যাক', 'start_menu')]);

    ctx.editMessageText('🤖 **আপনার বট তালিকা:**', { parse_mode: 'Markdown', ...Markup.inlineKeyboard(buttons) });
  });
});

bot.action(/manage_bot_(\d+)/, (ctx) => {
  const botId = ctx.match[1];
  ctx.session.data.activeBotId = botId;

  db.get(`SELECT * FROM client_bots WHERE bot_id = ?`, [botId], (err, row) => {
    if (!row) return ctx.reply('❌ বট পাওয়া যায়নি।');
    
    const buttons = [
      [Markup.button.callback('✏️ এডিট ওয়েলকাম', `edit_welcome_${botId}`)],
      [Markup.button.callback('🗑️ বট ডিলিট', `delete_bot_${botId}`)],
      [Markup.button.callback('⚙️ সেটিংস দেখুন', `view_settings_${botId}`)],
      [Markup.button.callback('🔙 ব্যাক', 'my_bots')]
    ];
    ctx.editMessageText(`🔧 **বট ম্যানেজমেন্ট**\n\n🆔 Bot: @${row.username}`, { 
      parse_mode: 'Markdown', 
      ...Markup.inlineKeyboard(buttons) 
    });
  });
});

bot.action(/delete_bot_(\d+)/, (ctx) => {
  const botId = ctx.match[1];
  
  // Stop instance
  if (global.activeBots && global.activeBots[botId]) {
    global.activeBots[botId].stop();
    delete global.activeBots[botId];
  }

  db.run(`DELETE FROM client_bots WHERE bot_id = ? AND owner_id = ?`, [botId, ctx.from.id], (err) => {
    if (err) return ctx.reply('❌ ডিলিট করতে সমস্যা হয়েছে।');
    db.run(`DELETE FROM client_users WHERE bot_id = ?`, [botId]); // Clean users
    ctx.editMessageText('✅ বট সফলভাবে ডিলিট করা হয়েছে।', Markup.inlineKeyboard([[Markup.button.callback('🔙 মেনু', 'start_menu')]]));
  });
});

// ================= BROADCAST SETUP (FOR CLIENT BOTS) =================

bot.action('broadcast_setup_menu', (ctx) => {
  db.all(`SELECT bot_id, username FROM client_bots WHERE owner_id = ?`, [ctx.from.id], (err, rows) => {
    if (!rows || rows.length === 0) {
      return ctx.editMessageText('😢 আপনার কোনো বট নেই। প্রথমে বট যোগ করুন।', 
        Markup.inlineKeyboard([[Markup.button.callback('🔙 ব্যাক', 'start_menu')]]));
    }

    let buttons = rows.map(r => [Markup.button.callback(`📢 @${r.username}`, `set_bc_admin_${r.bot_id}`)]);
    buttons.push([Markup.button.callback('🔙 ব্যাক', 'start_menu')]);

    ctx.editMessageText('📢 কোন বটের জন্য ব্রডকাস্ট এডমিন সেট করতে চান?', 
      Markup.inlineKeyboard(buttons));
  });
});

bot.action(/set_bc_admin_(\d+)/, (ctx) => {
  const botId = ctx.match[1];
  ctx.session.step = 'input_bc_admins';
  ctx.session.data.targetBotId = botId;
  ctx.editMessageText('👥 ব্রডকাস্ট এডমিনদের টেলিগ্রাম ID পাঠান।\n\nএকাধিক হলে কমা (,) দিয়ে আলাদা করুন।\nযেমন: 123456, 987654');
});

bot.on('text', (ctx) => {
  if (ctx.session.step === 'input_bc_admins') {
    const botId = ctx.session.data.targetBotId;
    db.run(`UPDATE client_bots SET broadcast_admins = ? WHERE bot_id = ?`, [ctx.message.text, botId], (err) => {
      if (err) return ctx.reply('❌ সেভ করতে সমস্যা হয়েছে।');
      ctx.reply('✅ ব্রডকাস্ট এডমিন সফলভাবে সেট হয়েছে!', Markup.inlineKeyboard([[Markup.button.callback('🔙 মেনু', 'start_menu')]]));
      ctx.session = {};
    });
  }
});

// ================= ADMIN PANEL =================

bot.action('admin_panel', requireAdmin, (ctx) => {
  ctx.editMessageText('🛠️ **এডমিন প্যানেলে স্বাগতম!**', {
    parse_mode: 'Markdown',
    ...Markup.inlineKeyboard([
      [Markup.button.callback('📊 স্ট্যাটাস', 'admin_stats')],
      [Markup.button.callback('📢 মেইন ব্রডকাস্ট', 'admin_main_bc')],
      [Markup.button.callback('🌍 গ্লোবাল ব্রডকাস্ট', 'admin_global_bc')],
      [Markup.button.callback('🔒 ফোর্স জয়েন সেটিং', 'admin_force')],
      [Markup.button.callback('🔙 ব্যাক', 'start_menu')]
    ])
  });
});

bot.action('admin_stats', requireAdmin, (ctx) => {
  db.get(`SELECT count(*) as count FROM users`, [], (e, u) => {
    db.get(`SELECT count(*) as count FROM client_bots`, [], (e2, b) => {
      ctx.editMessageText(
        `📊 **হাব স্ট্যাটাস**\n\n👥 মোট ইউজার: ${u.count}\n🤖 মোট ক্লায়েন্ট বট: ${b.count}`,
        { parse_mode: 'Markdown', ...Markup.inlineKeyboard([[Markup.button.callback('🔙 ব্যাক', 'admin_panel')]]) }
      );
    });
  });
});

bot.action('admin_force', requireAdmin, (ctx) => {
  db.all(`SELECT * FROM force_join`, [], (err, rows) => {
    let msg = "🔒 **ফোর্স জয়েন চ্যানেল:**\n\n";
    let buttons = [];
    
    if (rows && rows.length > 0) {
      rows.forEach(r => msg += `• ${r.channel_title} (${r.channel_id})\n`);
      buttons.push([Markup.button.callback('➕ নতুন যোগ করুন', 'add_force')]);
      buttons.push([Markup.button.callback('🗑️ সব মুছে ফেলুন', 'clear_force')]);
    } else {
      msg += "কোনো চ্যানেল সেট করা হয়নি।";
      buttons.push([Markup.button.callback('➕ নতুন যোগ করুন', 'add_force')]);
    }
    buttons.push([Markup.button.callback('🔙 ব্যাক', 'admin_panel')]);

    ctx.editMessageText(msg, { parse_mode: 'Markdown', ...Markup.inlineKeyboard(buttons) });
  });
});

bot.action('add_force', (ctx) => {
  ctx.session.step = 'add_force_channel';
  ctx.editMessageText('➕ চ্যানেল যোগ করুন:\n\nফরম্যাট: `-100xxxxxxxxxx` (Channel ID) - `Channel Title`\n\nউদাহরণ: `-1001234567890 - My Channel`');
});

bot.action('clear_force', requireAdmin, (ctx) => {
  db.run(`DELETE FROM force_join`);
  ctx.editMessageText('✅ সব ফোর্স জয়েন মুছে ফেলা হয়েছে।', Markup.inlineKeyboard([[Markup.button.callback('🔙 ব্যাক', 'admin_force')]]));
});

// ================= ADMIN BROADCAST FLOWS =================

// Helper for generic broadcast steps
const handleAdminBroadcast = (ctx, nextStep, prompt) => {
  ctx.session.step = nextStep;
  ctx.reply(prompt);
};

bot.action('admin_main_bc', requireAdmin, (ctx) => {
  ctx.session.data.broadcastType = 'main';
  handleAdminBroadcast(ctx, 'adm_bc_img', '📢 **মেইন ব্রডকাস্ট**\n\n1. ছবি পাঠান অথবা "Skip" লিখুন।');
});

bot.action('admin_global_bc', requireAdmin, (ctx) => {
  ctx.session.data.broadcastType = 'global';
  handleAdminBroadcast(ctx, 'adm_bc_img', '🌍 **গ্লোবাল ব্রডকাস্ট**\n\n1. ছবি পাঠান অথবা "Skip" লিখুন।');
});

// Unified Text Handler for Admin Broadcast
bot.on('text', async (ctx) => {
  if (!ctx.session || !ctx.session.step || !ctx.session.step.startsWith('adm_bc')) return;
  
  const step = ctx.session.step;
  const text = ctx.message.text;
  const type = ctx.session.data.broadcastType; // 'main' or 'global'

  if (step === 'adm_bc_img') {
    if (text.toLowerCase() === 'skip') ctx.session.data.img = null;
    ctx.session.step = 'adm_bc_text';
    return ctx.reply('✅ 2. এখন টেক্সট লিখুন বা "Skip" করুন।');
  }
  
  if (step === 'adm_bc_text') {
    if (text.toLowerCase() === 'skip') ctx.session.data.txt = null;
    ctx.session.step = 'adm_bc_btn';
    return ctx.reply('✅ 3. বাটন লিখুন (নাম - url) অথবা "Skip" করুন।');
  }
  
  if (step === 'adm_bc_btn') {
    if (text.toLowerCase() !== 'skip') {
      const parts = text.split('-');
      ctx.session.data.btn = [[Markup.button.url(parts[0].trim(), parts[1].trim())]];
    } else {
      ctx.session.data.btn = null;
    }
    ctx.session.step = 'adm_bc_confirm';
    return ctx.reply('🚀 কনফার্ম করতে "Yes" লিখুন।');
  }
  
  if (step === 'adm_bc_confirm') {
    if (text.toLowerCase() !== 'yes') {
      ctx.session = {};
      return ctx.reply('❌ বাতিল করা হয়েছে।');
    }

    const { img, txt, btn } = ctx.session.data;
    const opts = { parse_mode: 'HTML' };
    if (btn) opts.reply_markup = Markup.inlineKeyboard(btn).reply_markup;

    let targets = [];
    
    if (type === 'main') {
      // Broadcast to users of THIS control hub
      targets = await new Promise(res => db.all(`SELECT user_id FROM users`, [], (e, r) => res(r || [])));
    } else if (type === 'global') {
      // Broadcast to ALL users of ALL client bots
      targets = await new Promise(res => db.all(`SELECT user_id FROM client_users`, [], (e, r) => res(r || [])));
    }

    ctx.reply(`🚀 পাঠানো হচ্ছে ${targets.length} জনকে...`);
    
    let success = 0;
    for (const u of targets) {
      try {
        if (img) {
          await bot.telegram.sendPhoto(u.user_id, img, { caption: txt || '', ...opts });
        } else if (txt) {
          await bot.telegram.sendMessage(u.user_id, txt, opts);
        }
        success++;
      } catch (e) {}
    }
    
    ctx.reply(`✅ সম্পন্ন! সফল: ${success}`);
    ctx.session = {};
  }
});

bot.on('photo', (ctx) => {
  if (ctx.session.step === 'adm_bc_img') {
    ctx.session.data.img = ctx.message.photo[ctx.message.photo.length - 1].file_id;
    ctx.session.step = 'adm_bc_text';
    ctx.reply('✅ ছবি নেওয়া হলো। 2. টেক্সট লিখুন বা Skip করুন।');
  }
});

// Text Handler for Add Force Channel
bot.on('text', (ctx) => {
  if (ctx.session.step === 'add_force_channel') {
    if (ctx.message.text.includes('-')) {
      const parts = ctx.message.text.split('-');
      const id = parts[0].trim();
      const title = parts[1].trim();
      
      db.run(`INSERT INTO force_join (channel_id, channel_title) VALUES (?, ?)`, [id, title], (err) => {
        if (err) return ctx.reply('❌ সেভ করতে সমস্যা হলো। আইডি ঠিক আছে কিনা দেখুন।');
        ctx.reply(`✅ ${title} যোগ করা হয়েছে!`, Markup.inlineKeyboard([[Markup.button.callback('🔙 ব্যাক', 'admin_force')]]));
        ctx.session = {};
      });
    } else {
      ctx.reply('⚠️ ফরম্যাট ঠিক নেই। আবার চেষ্টা করুন।');
    }
  }
});

// ================= START BOT =================
bot.launch({
  webhook: {
    domain: WEBHOOK_URL,
    port: PORT
  }
}).then(() => console.log('✅ Bot Control Hub is Live!'));

// Enable graceful stop
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
