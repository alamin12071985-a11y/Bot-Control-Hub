require("dotenv").config();
const { Telegraf, Markup } = require("telegraf");
const express = require("express");
const cors = require("cors");
const { MongoClient } = require("mongodb");

const app = express();
app.use(express.json());
app.use(cors());

const mongo = new MongoClient(process.env.MONGO_URI);
let db;

let activeBots = {};
let setupState = {};
let broadcastState = {};
let editState = {};

function randomId() {
  return Math.random().toString(36).substring(2, 12);
}

async function initDB() {
  await mongo.connect();
  db = mongo.db("botControlHub");

  await db.collection("users").createIndex({ userId: 1 });
  await db.collection("bots").createIndex({ ownerId: 1 });
  await db.collection("client_users").createIndex({ botId: 1 });

  console.log("✅ Mongo Connected");
}

const mainBot = new Telegraf(process.env.MAIN_BOT_TOKEN);

/* ================= START ================= */

mainBot.start(async (ctx) => {
  await db.collection("users").updateOne(
    { userId: ctx.from.id },
    { $set: { userId: ctx.from.id } },
    { upsert: true }
  );

  ctx.reply(
    "🤖 Welcome to Bot Control Hub",
    Markup.inlineKeyboard([
      [Markup.button.callback("🤖 My Bots", "MYBOTS")],
      [Markup.button.callback("➕ Add New Bot", "ADDBOT")],
      [Markup.button.callback("📢 Broadcast Setup", "SETBROADCAST")]
    ])
  );
});

/* ================= ADD BOT FLOW ================= */

mainBot.action("ADDBOT", async (ctx) => {
  setupState[ctx.from.id] = { step: 1 };
  ctx.reply("Send your Bot Token:");
});

mainBot.on("photo", async (ctx) => {
  const state = setupState[ctx.from.id];
  if (state && state.step === 2) {
    state.image = ctx.message.photo.pop().file_id;
    state.step = 3;
    ctx.reply("Send Welcome Text:");
  }
});

mainBot.on("text", async (ctx) => {
  const userId = ctx.from.id;

  /* ====== BOT SETUP ====== */
  if (setupState[userId]) {
    const state = setupState[userId];

    if (state.step === 1) {
      try {
        const testBot = new Telegraf(ctx.message.text);
        await testBot.telegram.getMe();

        state.token = ctx.message.text;
        state.step = 2;
        ctx.reply("Send Welcome Image or type SKIP:");
      } catch {
        ctx.reply("❌ Invalid Token. Try again.");
      }
      return;
    }

    if (state.step === 2 && ctx.message.text === "SKIP") {
      state.image = null;
      state.step = 3;
      ctx.reply("Send Welcome Text:");
      return;
    }

    if (state.step === 3) {
      state.text = ctx.message.text;
      state.buttons = [];
      state.step = 4;
      ctx.reply("How many buttons? (1-3)");
      return;
    }

    if (state.step === 4) {
      state.total = parseInt(ctx.message.text);
      state.count = 0;
      state.step = 5;
      ctx.reply("Send Button Name:");
      return;
    }

    if (state.step === 5) {
      state.tempName = ctx.message.text;
      state.step = 6;
      ctx.reply("Send Button URL:");
      return;
    }

    if (state.step === 6) {
      state.buttons.push({
        name: state.tempName,
        url: ctx.message.text
      });

      state.count++;
      if (state.count < state.total) {
        state.step = 5;
        ctx.reply("Send Next Button Name:");
      } else {
        const botId = randomId();

        await db.collection("bots").insertOne({
          botId,
          ownerId: userId,
          token: state.token,
          welcomeImage: state.image,
          welcomeText: state.text,
          buttons: state.buttons,
          broadcastAdmins: [],
          createdAt: new Date()
        });

        await launchClientBot(botId);

        delete setupState[userId];
        ctx.reply("✅ Bot Connected & Running!");
      }
      return;
    }
  }

  /* ====== BROADCAST SETUP ====== */
  if (broadcastState[userId]) {
    const state = broadcastState[userId];

    if (state.step === 1) {
      state.botId = ctx.message.text;
      state.step = 2;
      ctx.reply("Send Admin User IDs (comma separated):");
      return;
    }

    if (state.step === 2) {
      const ids = ctx.message.text.split(",").map(id => parseInt(id.trim()));
      await db.collection("bots").updateOne(
        { botId: state.botId },
        { $set: { broadcastAdmins: ids } }
      );
      delete broadcastState[userId];
      ctx.reply("✅ Broadcast Admins Updated.");
      return;
    }
  }

  /* ====== EDIT WELCOME ====== */
  if (editState[userId]) {
    const state = editState[userId];
    await db.collection("bots").updateOne(
      { botId: state.botId },
      { $set: { welcomeText: ctx.message.text } }
    );
    await reloadBot(state.botId);
    delete editState[userId];
    ctx.reply("✅ Welcome Message Updated.");
    return;
  }
});

/* ================= MY BOTS ================= */

mainBot.action("MYBOTS", async (ctx) => {
  const bots = await db.collection("bots").find({ ownerId: ctx.from.id }).toArray();

  if (!bots.length) return ctx.reply("No Bots Found.");

  for (const bot of bots) {
    ctx.reply(
      `🤖 ${bot.botId}`,
      Markup.inlineKeyboard([
        [Markup.button.callback("Edit Welcome", `EDIT_${bot.botId}`)],
        [Markup.button.callback("Delete", `DEL_${bot.botId}`)]
      ])
    );
  }
});

mainBot.action(/EDIT_(.+)/, async (ctx) => {
  editState[ctx.from.id] = { botId: ctx.match[1] };
  ctx.reply("Send New Welcome Text:");
});

mainBot.action(/DEL_(.+)/, async (ctx) => {
  const botId = ctx.match[1];
  await db.collection("bots").deleteOne({ botId });
  if (activeBots[botId]) {
    await activeBots[botId].stop();
    delete activeBots[botId];
  }
  ctx.reply("Bot Deleted.");
});

/* ================= BROADCAST SETUP ================= */

mainBot.action("SETBROADCAST", async (ctx) => {
  broadcastState[ctx.from.id] = { step: 1 };
  ctx.reply("Send Bot ID:");
});

/* ================= CLIENT BOT ================= */

async function launchClientBot(botId) {
  const data = await db.collection("bots").findOne({ botId });
  if (!data) return;

  const bot = new Telegraf(data.token);

  bot.start(async (ctx) => {
    await db.collection("client_users").updateOne(
      { botId, userId: ctx.from.id },
      { $set: { botId, userId: ctx.from.id } },
      { upsert: true }
    );

    const buttons = data.buttons.map(b => [Markup.button.url(b.name, b.url)]);

    if (data.welcomeImage) {
      await ctx.replyWithPhoto(data.welcomeImage, {
        caption: data.welcomeText,
        reply_markup: { inline_keyboard: buttons }
      });
    } else {
      await ctx.reply(data.welcomeText, {
        reply_markup: { inline_keyboard: buttons }
      });
    }
  });

  bot.command("broadcast", async (ctx) => {
    if (!data.broadcastAdmins.includes(ctx.from.id))
      return ctx.reply("❌ Not Authorized");

    ctx.reply("Send Broadcast Message:");

    bot.once("text", async (msgCtx) => {
      const users = await db.collection("client_users").find({ botId }).toArray();
      for (const u of users) {
        try {
          await bot.telegram.sendMessage(u.userId, msgCtx.message.text);
        } catch {}
      }
      msgCtx.reply("✅ Broadcast Sent.");
    });
  });

  await bot.launch();
  activeBots[botId] = bot;
}

async function reloadBot(botId) {
  if (activeBots[botId]) {
    await activeBots[botId].stop();
    delete activeBots[botId];
  }
  await launchClientBot(botId);
}

/* ================= SERVER ================= */

app.get("/", (_, res) => res.send("Bot Control Hub Running"));

async function start() {
  await initDB();
  await mainBot.launch();
  app.listen(process.env.PORT || 3000);
}

start();
