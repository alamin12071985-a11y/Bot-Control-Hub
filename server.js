require("dotenv").config();
const { Telegraf, Markup, session } = require("telegraf");
const express = require("express");
const SQLite = require("better-sqlite3");
const axios = require("axios");

const app = express();
app.get("/", (_, res) => res.send("Bot Control Hub Running ✅"));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log("Server running on " + PORT));

const ADMIN_IDS = (process.env.ADMIN_IDS || "").split(",").map(x => Number(x.trim()));

const db = new SQLite("database.db");

db.exec(`
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY,
 name TEXT,
 joined INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS force_channels(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 channel TEXT
);

CREATE TABLE IF NOT EXISTS client_bots(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 owner_id INTEGER,
 token TEXT,
 bot_id TEXT,
 username TEXT,
 welcome_text TEXT,
 welcome_image TEXT,
 buttons TEXT
);

CREATE TABLE IF NOT EXISTS client_bot_users(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 bot_id TEXT,
 user_id INTEGER
);

CREATE TABLE IF NOT EXISTS broadcast_admins(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 bot_id TEXT,
 user_id INTEGER
);
`);

const controller = new Telegraf(process.env.BOT_TOKEN);
controller.use(session());

async function checkForceJoin(ctx) {
  const channels = db.prepare("SELECT * FROM force_channels").all();
  if (!channels.length) return true;

  let notJoined = [];

  for (let ch of channels) {
    try {
      const res = await ctx.telegram.getChatMember(ch.channel, ctx.from.id);
      if (!["creator", "administrator", "member"].includes(res.status)) {
        notJoined.push(ch.channel);
      }
    } catch {
      notJoined.push(ch.channel);
    }
  }

  if (notJoined.length) {
    const buttons = notJoined.map(c => [Markup.button.url("চ্যানেল জয়েন করুন", `https://t.me/${c.replace("@","")}`)]);
    buttons.push([Markup.button.callback("আমি জয়েন করেছি ✅", "recheck")]);

    await ctx.reply("দেখছি আপনি এখনো সব চ্যানেলে জয়েন করেননি 😅 আগে জয়েন করুন প্লিজ।",
      Markup.inlineKeyboard(buttons)
    );
    return false;
  }

  return true;
}

controller.start(async ctx => {
  db.prepare("INSERT OR IGNORE INTO users(id,name) VALUES(?,?)")
    .run(ctx.from.id, ctx.from.first_name);

  if (!(await checkForceJoin(ctx))) return;

  await ctx.reply(
    "স্বাগতম Bot Control Hub এ 🤖\nচলুন নিজের বট বানাই!",
    Markup.inlineKeyboard([
      [Markup.button.callback("🚀 Get Started", "get_started")]
    ])
  );
});

controller.action("recheck", async ctx => {
  if (await checkForceJoin(ctx)) {
    await ctx.reply("সব ঠিক আছে 😎 এখন ব্যবহার করতে পারেন।");
  }
});

controller.action("get_started", async ctx => {
  ctx.session.step = "token";
  await ctx.reply("আপনার বটের টোকেন দিন 👇");
});

controller.on("text", async ctx => {

  if (!(await checkForceJoin(ctx))) return;

  if (!ctx.session.step) return;

  if (ctx.session.step === "token") {
    try {
      const token = ctx.message.text.trim();
      const res = await axios.get(`https://api.telegram.org/bot${token}/getMe`);
      if (!res.data.ok) throw new Error();

      const botInfo = res.data.result;

      db.prepare(`
        INSERT INTO client_bots(owner_id,token,bot_id,username)
        VALUES(?,?,?,?)
      `).run(ctx.from.id, token, botInfo.id, botInfo.username);

      ctx.session.botToken = token;
      ctx.session.botId = botInfo.id;
      ctx.session.step = "welcome_image";

      await ctx.reply("ওয়েলকাম ইমেজ দিবেন?\nছবি পাঠান অথবা /skip লিখুন");
      
      notifyAdmin(ctx, botInfo);

    } catch {
      await ctx.reply("এই টোকেন কাজ করছে না 😑 আবার চেষ্টা করুন।");
    }
  }

  else if (ctx.session.step === "welcome_text") {
    db.prepare(`
      UPDATE client_bots SET welcome_text=?
      WHERE bot_id=?
    `).run(ctx.message.text, ctx.session.botId);

    ctx.session.step = null;
    await ctx.reply("বট সেটআপ সম্পূর্ণ হয়েছে 🎉");
    launchClientBot(ctx.session.botToken);
  }
});

controller.on("photo", async ctx => {
  if (ctx.session.step === "welcome_image") {
    const fileId = ctx.message.photo.pop().file_id;
    db.prepare(`
      UPDATE client_bots SET welcome_image=?
      WHERE bot_id=?
    `).run(fileId, ctx.session.botId);

    ctx.session.step = "welcome_text";
    await ctx.reply("এবার ওয়েলকাম টেক্সট লিখুন ✍️");
  }
});

controller.command("skip", async ctx => {
  if (ctx.session.step === "welcome_image") {
    ctx.session.step = "welcome_text";
    await ctx.reply("ঠিক আছে 😄 এবার ওয়েলকাম টেক্সট লিখুন।");
  }
});

function notifyAdmin(ctx, botInfo) {
  ADMIN_IDS.forEach(id => {
    controller.telegram.sendMessage(id,
      `নতুন বট যুক্ত হয়েছে 🚀
User: ${ctx.from.first_name}
User ID: ${ctx.from.id}
Bot: @${botInfo.username}
Bot ID: ${botInfo.id}
সময়: ${new Date().toLocaleString()}`
    );
  });
}

function launchClientBot(token) {
  const bot = new Telegraf(token);

  bot.start(async ctx => {
    const data = db.prepare("SELECT * FROM client_bots WHERE bot_id=?")
      .get(ctx.botInfo.id);

    db.prepare(`
      INSERT INTO client_bot_users(bot_id,user_id)
      VALUES(?,?)
    `).run(ctx.botInfo.id, ctx.from.id);

    const buttons = data.buttons ? JSON.parse(data.buttons) : [];
    const keyboard = buttons.length ? Markup.inlineKeyboard(buttons) : undefined;

    if (data.welcome_image) {
      await ctx.replyWithPhoto(data.welcome_image, {
        caption: data.welcome_text || "স্বাগতম 😄",
        ...keyboard
      });
    } else {
      await ctx.reply(data.welcome_text || "স্বাগতম 😄", keyboard);
    }
  });

  bot.command("broadcast", async ctx => {
    const allowed = db.prepare(`
      SELECT * FROM broadcast_admins
      WHERE bot_id=? AND user_id=?
    `).get(ctx.botInfo.id, ctx.from.id);

    if (!allowed) return ctx.reply("আপনি ব্রডকাস্ট করতে পারবেন না 😶");

    ctx.session = { broadcast: true };
    await ctx.reply("ব্রডকাস্ট মেসেজ পাঠান এখন 👇");
  });

  bot.on("text", async ctx => {
    if (ctx.session?.broadcast) {
      const users = db.prepare(`
        SELECT user_id FROM client_bot_users
        WHERE bot_id=?
      `).all(ctx.botInfo.id);

      for (let u of users) {
        try {
          await ctx.telegram.sendMessage(u.user_id, ctx.message.text);
        } catch {}
      }

      ctx.session = null;
      await ctx.reply("ব্রডকাস্ট পাঠানো সম্পূর্ণ হয়েছে 📢");
    }
  });

  bot.launch();
}

controller.launch();
