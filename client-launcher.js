require("dotenv").config();
const { Telegraf, Markup } = require("telegraf");
const { MongoClient } = require("mongodb");

const mongo = new MongoClient(process.env.MONGO_URI);

let db;
const activeBots = {};

// INIT
async function init() {
 await mongo.connect();
 db = mongo.db("BotControlHub");

 console.log("Launcher Connected");

 startAllBots();
 autoReloadBots();
}

// START ALL
async function startAllBots() {
 const bots = await db.collection("bots").find().toArray();

 for (const b of bots) {
  launchBot(b);
 }
}

// LAUNCH BOT
async function launchBot(data) {
 if (activeBots[data.botId]) return;

 const bot = new Telegraf(data.token);

 bot.start(async (ctx) => {
  await db.collection("bots").updateOne(
   { botId: data.botId },
   { $addToSet: { users: ctx.from.id } }
  );

  const buttons = data.buttons.map(b =>
   [Markup.button.url(b.text, b.url)]
  );

  if (data.welcomeImage) {
   return ctx.replyWithPhoto(data.welcomeImage, {
    caption: data.welcomeText,
    reply_markup: { inline_keyboard: buttons }
   });
  }

  ctx.reply(data.welcomeText, {
   reply_markup: { inline_keyboard: buttons }
  });
 });

 bot.command("broadcast", async (ctx) => {
  const botData = await db.collection("bots").findOne({
   botId: data.botId
  });

  if (!botData.broadcastAdmins.includes(ctx.from.id))
   return ctx.reply("Not allowed");

  ctx.reply("Send broadcast message");

  bot.once("text", async (msgCtx) => {
   const users = botData.users;

   let sent = 0;
   let failed = 0;

   for (const user of users) {
    try {
     await bot.telegram.sendMessage(user, msgCtx.message.text);
     sent++;
    } catch {
     failed++;
    }
   }

   msgCtx.reply(
    `Broadcast Done

Sent: ${sent}
Failed: ${failed}`
   );
  });
 });

 bot.launch();
 activeBots[data.botId] = bot;

 console.log("Launched", data.username);
}

// AUTO RELOAD NEW BOTS
async function autoReloadBots() {
 setInterval(async () => {
  const bots = await db.collection("bots").find().toArray();

  for (const b of bots) {
   if (!activeBots[b.botId]) {
    launchBot(b);
   }
  }
 }, 10000);
}

init();
