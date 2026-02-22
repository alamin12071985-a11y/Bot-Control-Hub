require("dotenv").config();
const { Telegraf, Markup, session } = require("telegraf");
const { MongoClient } = require("mongodb");

const bot = new Telegraf(process.env.MAIN_BOT_TOKEN);
const mongo = new MongoClient(process.env.MONGO_URI);

let db;

const activeLaunchRequests = {};

// CONNECT DB
async function initDB() {
 await mongo.connect();
 db = mongo.db("BotControlHub");
 console.log("MongoDB Connected");
}
initDB();

// COLLECTIONS
const Users = () => db.collection("users");
const Bots = () => db.collection("bots");

// SESSION
bot.use(session());

// START
bot.start(async (ctx) => {
 const id = ctx.from.id;

 await Users().updateOne(
  { id },
  { $set: { id } },
  { upsert: true }
 );

 ctx.reply(
  `🚀 Welcome to Bot Control Hub

Create and control unlimited Telegram bots easily.`,
  Markup.keyboard([
   ["🤖 My Bots", "➕ Add New Bot"],
   ["📢 Broadcast Setup"]
  ]).resize()
 );
});

// HELP
bot.command("help", async (ctx) => {
 ctx.reply(
  `Bot Control Hub Help

1. Connect your bot
2. Configure welcome message
3. Setup broadcast
4. Control bots easily`,
  Markup.inlineKeyboard([
   [Markup.button.url("Contact Admin", "https://t.me/admin")]
  ])
 );
});

// ADD BOT
bot.hears("➕ Add New Bot", async (ctx) => {
 ctx.session = { step: "token" };
 ctx.reply("Send your bot token");
});

// TOKEN STEP
bot.on("text", async (ctx) => {
 if (!ctx.session) return;

 if (ctx.session.step === "token") {
  const token = ctx.message.text;

  try {
   const testBot = new Telegraf(token);
   const info = await testBot.telegram.getMe();

   ctx.session.token = token;
   ctx.session.username = info.username;
   ctx.session.step = "image";

   return ctx.reply("Send welcome image or type skip");
  } catch {
   return ctx.reply("Invalid token");
  }
 }

 if (ctx.session.step === "image") {
  if (ctx.message.text === "skip") {
   ctx.session.image = null;
   ctx.session.step = "text";
   return ctx.reply("Send welcome text");
  }
 }

 if (ctx.session.step === "text") {
  ctx.session.text = ctx.message.text;
  ctx.session.step = "btnCount";
  return ctx.reply("How many buttons? (1-3)");
 }

 if (ctx.session.step === "btnCount") {
  const count = Number(ctx.message.text);
  if (count > 3 || count < 1)
   return ctx.reply("Send between 1 and 3");

  ctx.session.btnCount = count;
  ctx.session.buttons = [];
  ctx.session.step = "btnName";

  return ctx.reply("Send button name");
 }

 if (ctx.session.step === "btnName") {
  ctx.session.currentName = ctx.message.text;
  ctx.session.step = "btnUrl";
  return ctx.reply("Send button url");
 }

 if (ctx.session.step === "btnUrl") {
  ctx.session.buttons.push({
   text: ctx.session.currentName,
   url: ctx.message.text
  });

  if (ctx.session.buttons.length >= ctx.session.btnCount) {
   const botId = Date.now().toString();

   await Bots().insertOne({
    botId,
    owner: ctx.from.id,
    token: ctx.session.token,
    username: ctx.session.username,
    welcomeText: ctx.session.text,
    welcomeImage: ctx.session.image,
    buttons: ctx.session.buttons,
    users: [],
    broadcastAdmins: []
   });

   ctx.session = null;

   return ctx.reply("✅ Bot Connected Successfully");
  }

  ctx.session.step = "btnName";
  return ctx.reply("Next button name");
 }
});

// IMAGE
bot.on("photo", async (ctx) => {
 if (!ctx.session) return;
 if (ctx.session.step !== "image") return;

 ctx.session.image = ctx.message.photo.at(-1).file_id;
 ctx.session.step = "text";

 ctx.reply("Send welcome text");
});

// MY BOTS
bot.hears("🤖 My Bots", async (ctx) => {
 const list = await Bots().find({ owner: ctx.from.id }).toArray();

 if (!list.length)
  return ctx.reply("No bots added yet");

 for (const b of list) {
  await ctx.reply(
   `🤖 @${b.username}`,
   Markup.inlineKeyboard([
    [
     Markup.button.callback("View Info", `info_${b.botId}`),
     Markup.button.callback("Delete", `delete_${b.botId}`)
    ]
   ])
  );
 }
});

// INFO
bot.action(/info_(.+)/, async (ctx) => {
 const botId = ctx.match[1];
 const data = await Bots().findOne({ botId });

 ctx.editMessageText(
  `Bot Info

Username: @${data.username}
Users: ${data.users.length}`
 );
});

// DELETE
bot.action(/delete_(.+)/, async (ctx) => {
 const botId = ctx.match[1];
 await Bots().deleteOne({ botId });
 ctx.editMessageText("Bot deleted");
});

// BROADCAST SETUP
bot.hears("📢 Broadcast Setup", async (ctx) => {
 ctx.session = { step: "broadcastBot" };
 ctx.reply("Send bot username");
});

bot.launch();
console.log("Main Bot Running");
