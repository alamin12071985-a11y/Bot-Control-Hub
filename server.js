require('dotenv').config();
const { Telegraf, Markup } = require('telegraf');
const express = require('express');
const cors = require('cors');
const { MongoClient, ServerApiVersion, ObjectId } = require('mongodb');

const app = express();
app.use(express.json());
app.use(cors({ origin: '*' }));

// --- CONFIGURATION ---
const PORT = process.env.PORT || 3000;
const MONGO_URI = process.env.MONGODB_URI || "mongodb+srv://hellokaiiddo:0Mgb6Peq3UlsNpCD@cluster0.azbh81j.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0";
const MAIN_BOT_TOKEN = process.env.MAIN_BOT_TOKEN;

const client = new MongoClient(MONGO_URI, {
    serverApi: { version: ServerApiVersion.v1, strict: true, deprecationErrors: true }
});

let db, usersCol, botsCol, botSubscribersCol, sessionsCol;
let activeBots = {}; // Store running Telegraf instances

// --- DATABASE CONNECTION ---
async function connectDB() {
    try {
        await client.connect();
        db = client.db("BotControlHub");
        usersCol = db.collection("users");
        botsCol = db.collection("bots");
        botSubscribersCol = db.collection("bot_subscribers");
        sessionsCol = db.collection("sessions");
        console.log("✅ MongoDB Connected");
        
        initMainBot();
        resumeBots(); // Restart bots that were running
    } catch (err) {
        console.error("❌ MongoDB Error:", err);
    }
}

// --- MAIN CONTROLLER BOT LOGIC ---
const mainBot = new Telegraf(MAIN_BOT_TOKEN);

function initMainBot() {
    // Middleware to track/create user
    mainBot.use(async (ctx, next) => {
        if (ctx.from) {
            await usersCol.updateOne(
                { userId: ctx.from.id },
                { $set: { username: ctx.from.username, lastSeen: new Date() } },
                { upsert: true }
            );
        }
        return next();
    });

    mainBot.start(async (ctx) => {
        await sessionsCol.deleteOne({ userId: ctx.from.id }); // Clear any stuck setup
        ctx.reply(`👋 Welcome to Bot Control Hub!\n\nManage your Telegram bot empire from here.`, 
            Markup.keyboard([
                ['🤖 My Bots', '➕ Add New Bot'],
                ['📢 Broadcast Setup', '❓ Help']
            ]).resize()
        );
    });

    mainBot.hears('❓ Help', (ctx) => {
        ctx.reply("Need assistance? Contact our admin.", Markup.inlineKeyboard([
            [Markup.button.url('Contact Admin', 'https://t.me/your_admin_username')]
        ]));
    });

    // --- ADD BOT WIZARD ---
    mainBot.hears('➕ Add New Bot', async (ctx) => {
        await sessionsCol.updateOne(
            { userId: ctx.from.id },
            { $set: { step: 'WAITING_TOKEN' } },
            { upsert: true }
        );
        ctx.reply("Step 1: Please send me your Bot Token from @BotFather.");
    });

    mainBot.on('text', async (ctx) => {
        const session = await sessionsCol.findOne({ userId: ctx.from.id });
        if (!session) return;

        if (session.step === 'WAITING_TOKEN') {
            const token = ctx.message.text.trim();
            try {
                const tempBot = new Telegraf(token);
                const botInfo = await tempBot.telegram.getMe();
                await sessionsCol.updateOne({ userId: ctx.from.id }, { 
                    $set: { step: 'WAITING_IMAGE', token, botName: botInfo.first_name, botUsername: botInfo.username } 
                });
                ctx.reply(`✅ Token valid for @${botInfo.username}\n\nStep 2: Send a Welcome Image (or send /skip).`);
            } catch (e) {
                ctx.reply("❌ Invalid token. Please try again.");
            }
        } 
        else if (session.step === 'WAITING_TEXT') {
            await sessionsCol.updateOne({ userId: ctx.from.id }, { 
                $set: { step: 'WAITING_BUTTON_COUNT', welcomeText: ctx.message.text } 
            });
            ctx.reply("Step 4: How many buttons do you want? (Enter 0-3)");
        }
        else if (session.step === 'WAITING_BUTTON_COUNT') {
            const count = parseInt(ctx.message.text);
            if (isNaN(count) || count < 0 || count > 3) return ctx.reply("Please enter a number between 0 and 3.");
            
            if (count === 0) {
                await finalizeBotCreation(ctx, session, []);
            } else {
                await sessionsCol.updateOne({ userId: ctx.from.id }, { 
                    $set: { step: 'WAITING_BUTTON_DATA', btnCount: count, btns: [], currentBtn: 1 } 
                });
                ctx.reply(`Send Name and URL for Button 1 (Format: Name | URL)`);
            }
        }
        else if (session.step === 'WAITING_BUTTON_DATA') {
            const parts = ctx.message.text.split('|');
            if (parts.length < 2) return ctx.reply("Format: Name | URL");
            
            const btns = session.btns || [];
            btns.push({ text: parts[0].trim(), url: parts[1].trim() });
            
            if (btns.length >= session.btnCount) {
                await finalizeBotCreation(ctx, session, btns);
            } else {
                const nextNum = btns.length + 1;
                await sessionsCol.updateOne({ userId: ctx.from.id }, { $set: { btns } });
                ctx.reply(`Send Name and URL for Button ${nextNum} (Format: Name | URL)`);
            }
        }
    });

    mainBot.on(['photo', 'message'], async (ctx) => {
        const session = await sessionsCol.findOne({ userId: ctx.from.id });
        if (session?.step === 'WAITING_IMAGE') {
            const fileId = ctx.message.photo ? ctx.message.photo[ctx.message.photo.length - 1].file_id : null;
            if (ctx.message.text === '/skip') {
                await sessionsCol.updateOne({ userId: ctx.from.id }, { $set: { step: 'WAITING_TEXT', welcomeImage: null } });
            } else if (fileId) {
                await sessionsCol.updateOne({ userId: ctx.from.id }, { $set: { step: 'WAITING_TEXT', welcomeImage: fileId } });
            } else {
                return ctx.reply("Please send a photo or /skip.");
            }
            ctx.reply("Step 3: Send the Welcome Message text.");
        }
    });

    // --- MY BOTS PANEL ---
    mainBot.hears('🤖 My Bots', async (ctx) => {
        const userBots = await botsCol.find({ ownerId: ctx.from.id }).toArray();
        if (userBots.length === 0) return ctx.reply("You haven't added any bots yet.");

        userBots.forEach(bot => {
            ctx.reply(`Bot: ${bot.botName} (@${bot.botUsername})\nStatus: ${bot.status}`, 
                Markup.inlineKeyboard([
                    [Markup.button.callback('Start', `start_${bot._id}`), Markup.button.callback('Stop', `stop_${bot._id}`)],
                    [Markup.button.callback('Delete', `del_${bot._id}`)]
                ])
            );
        });
    });

    // --- ACTIONS ---
    mainBot.action(/start_(.+)/, async (ctx) => {
        const botId = ctx.match[1];
        await launchClientBot(botId);
        ctx.answerCbQuery("Bot Started");
        ctx.editMessageText("Status: RUNNING");
    });

    mainBot.action(/stop_(.+)/, async (ctx) => {
        const botId = ctx.match[1];
        await stopClientBot(botId);
        ctx.answerCbQuery("Bot Stopped");
        ctx.editMessageText("Status: STOPPED");
    });

    mainBot.action(/del_(.+)/, async (ctx) => {
        const botId = ctx.match[1];
        await stopClientBot(botId);
        await botsCol.deleteOne({ _id: new ObjectId(botId) });
        ctx.answerCbQuery("Bot Deleted");
        ctx.deleteMessage();
    });

    mainBot.launch();
}

async function finalizeBotCreation(ctx, session, buttons) {
    const newBot = {
        ownerId: ctx.from.id,
        token: session.token,
        botName: session.botName,
        botUsername: session.botUsername,
        welcomeImage: session.welcomeImage,
        welcomeText: session.welcomeText,
        buttons: buttons,
        status: 'RUN',
        createdAt: new Date(),
        admins: [ctx.from.id]
    };
    const res = await botsCol.insertOne(newBot);
    await sessionsCol.deleteOne({ userId: ctx.from.id });
    ctx.reply(`✅ Bot @${session.botUsername} created and launched!`);
    launchClientBot(res.insertedId.toString());
}

// --- CLIENT BOT ENGINE ---
async function launchClientBot(dbId) {
    const botCfg = await botsCol.findOne({ _id: new ObjectId(dbId) });
    if (!botCfg || activeBots[dbId]) return;

    const instance = new Telegraf(botCfg.token);

    instance.start(async (ctx) => {
        // Track subscribers
        await botSubscribersCol.updateOne(
            { botId: dbId, userId: ctx.from.id },
            { $set: { username: ctx.from.username, joinedAt: new Date() } },
            { upsert: true }
        );

        const keyboard = botCfg.buttons.length > 0 
            ? Markup.inlineKeyboard(botCfg.buttons.map(b => [Markup.button.url(b.text, b.url)]))
            : null;

        if (botCfg.welcomeImage) {
            await ctx.replyWithPhoto(botCfg.welcomeImage, { caption: botCfg.welcomeText, ...keyboard });
        } else {
            await ctx.reply(botCfg.welcomeText, keyboard);
        }
    });

    // Broadcast Command for Client Bot
    instance.command('broadcast', async (ctx) => {
        if (!botCfg.admins.includes(ctx.from.id)) return;
        ctx.reply("Please send the message you want to broadcast to ALL users.");
        // Simple broadcast listener implementation
        instance.on('message', async (bCtx) => {
            if (bCtx.from.id !== ctx.from.id) return;
            const subscribers = await botSubscribersCol.find({ botId: dbId }).toArray();
            let success = 0;
            for (const sub of subscribers) {
                try {
                    await bCtx.copyMessage(sub.userId);
                    success++;
                } catch (e) {}
            }
            bCtx.reply(`📢 Broadcast Finished!\nSent to: ${success} users.`);
            return; // Exit listener after one broadcast
        });
    });

    instance.launch().catch(err => console.error(`Error launching ${botCfg.botUsername}:`, err));
    activeBots[dbId] = instance;
    await botsCol.updateOne({ _id: new ObjectId(dbId) }, { $set: { status: 'RUN' } });
}

async function stopClientBot(dbId) {
    if (activeBots[dbId]) {
        activeBots[dbId].stop('SIGTERM');
        delete activeBots[dbId];
    }
    await botsCol.updateOne({ _id: new ObjectId(dbId) }, { $set: { status: 'STOP' } });
}

async function resumeBots() {
    const bots = await botsCol.find({ status: 'RUN' }).toArray();
    for (const b of bots) {
        await launchClientBot(b._id.toString());
    }
}

// --- SERVER & INITIALIZATION ---
app.get('/', (req, res) => res.send('Bot Control Hub API Running'));

connectDB().then(() => {
    app.listen(PORT, () => console.log(`⚡ Server listening on port ${PORT}`));
});

// Graceful shutdown
process.once('SIGINT', () => {
    mainBot.stop('SIGINT');
    Object.values(activeBots).forEach(b => b.stop('SIGINT'));
});
process.once('SIGTERM', () => {
    mainBot.stop('SIGTERM');
    Object.values(activeBots).forEach(b => b.stop('SIGTERM'));
});
