require('dotenv').config();
const { Telegraf, Markup } = require('telegraf');
const express = require('express');
const admin = require('firebase-admin');
const cors = require('cors');

const app = express();
app.use(express.json());
app.use(cors());

// --- 1. FIREBASE SETUP ---
// Note: In Render, paste the entire Service Account JSON into the FIREBASE_SERVICE_ACCOUNT env var
const serviceAccount = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT);
const DATABASE_URL = process.env.DATABASE_URL;

admin.initializeApp({
    credential: admin.credential.cert(serviceAccount),
    databaseURL: DATABASE_URL
});

const db = admin.database();
const botsRef = db.ref("bots");
const usersRef = db.ref("users");
const sessionsRef = db.ref("sessions");
const subsRef = db.ref("subscribers");

let activeBots = {}; // Tracking running instances

// --- 2. MAIN CONTROLLER BOT ---
const MAIN_BOT_TOKEN = process.env.MAIN_BOT_TOKEN;
const mainBot = new Telegraf(MAIN_BOT_TOKEN);

// Dashboard Keyboard
const mainKeyboard = Markup.keyboard([
    ['🤖 My Bots', '➕ Add New Bot'],
    ['📢 Broadcast Setup', '❓ Help']
]).resize();

mainBot.start(async (ctx) => {
    const uid = ctx.from.id.toString();
    await usersRef.child(uid).update({
        username: ctx.from.username || "N/A",
        name: ctx.from.first_name,
        lastSeen: Date.now()
    });
    await sessionsRef.child(uid).remove(); // Clear stuck sessions
    ctx.reply(`👋 Welcome to Bot Control Hub!\n\nUse the menu below to manage your bots.`, mainKeyboard);
});

// --- ADD BOT WIZARD ---
mainBot.hears('➕ Add New Bot', async (ctx) => {
    await sessionsRef.child(ctx.from.id.toString()).set({ step: 'WAITING_TOKEN' });
    ctx.reply("✨ Step 1: Send me your Bot Token from @BotFather.");
});

mainBot.on('text', async (ctx) => {
    const uid = ctx.from.id.toString();
    const sessionSnap = await sessionsRef.child(uid).once('value');
    const session = sessionSnap.val();
    if (!session) return;

    const input = ctx.message.text.trim();

    if (session.step === 'WAITING_TOKEN') {
        try {
            const tempBot = new Telegraf(input);
            const info = await tempBot.telegram.getMe();
            await sessionsRef.child(uid).update({ 
                step: 'WAITING_IMAGE', token: input, botName: info.first_name, botUsername: info.username 
            });
            ctx.reply(`✅ Valid: @${info.username}\n\nStep 2: Send a Welcome Image (or send /skip).`);
        } catch (e) {
            ctx.reply("❌ Invalid Token! Please send a correct token.");
        }
    } 
    else if (session.step === 'WAITING_TEXT') {
        await sessionsRef.child(uid).update({ step: 'WAITING_BTN_COUNT', welcomeText: input });
        ctx.reply("Step 4: How many buttons do you want? (0-3)");
    }
    else if (session.step === 'WAITING_BTN_COUNT') {
        const count = parseInt(input);
        if (isNaN(count) || count < 0 || count > 3) return ctx.reply("Please enter a number between 0 and 3.");
        
        if (count === 0) {
            finalizeBot(ctx, session, []);
        } else {
            await sessionsRef.child(uid).update({ step: 'WAITING_BTN_DATA', btnCount: count, btns: [] });
            ctx.reply(`Send details for Button 1\nFormat: Button Name | URL`);
        }
    }
    else if (session.step === 'WAITING_BTN_DATA') {
        const parts = input.split('|');
        if (parts.length < 2) return ctx.reply("❌ Invalid format! Use: Name | URL");
        
        let btns = session.btns || [];
        btns.push({ text: parts[0].trim(), url: parts[1].trim() });
        
        if (btns.length >= session.btnCount) {
            finalizeBot(ctx, session, btns);
        } else {
            await sessionsRef.child(uid).update({ btns });
            ctx.reply(`Send details for Button ${btns.length + 1}\nFormat: Name | URL`);
        }
    }
});

mainBot.on(['photo', 'message'], async (ctx) => {
    const uid = ctx.from.id.toString();
    const sessionSnap = await sessionsRef.child(uid).once('value');
    const session = sessionSnap.val();

    if (session?.step === 'WAITING_IMAGE') {
        const fileId = ctx.message.photo ? ctx.message.photo[ctx.message.photo.length - 1].file_id : null;
        if (!fileId && ctx.message.text !== '/skip') return ctx.reply("Please send a photo or /skip.");
        
        await sessionsRef.child(uid).update({ step: 'WAITING_TEXT', welcomeImage: fileId || null });
        ctx.reply("Step 3: Send the Welcome Message text.");
    }
});

async function finalizeBot(ctx, session, buttons) {
    const botRef = botsRef.push();
    const botData = {
        id: botRef.key,
        ownerId: ctx.from.id,
        token: session.token,
        botName: session.botName,
        botUsername: session.botUsername,
        welcomeImage: session.welcomeImage || null,
        welcomeText: session.welcomeText,
        buttons: buttons,
        status: 'RUN',
        admins: [ctx.from.id]
    };

    await botRef.set(botData);
    await sessionsRef.child(ctx.from.id.toString()).remove();
    ctx.reply(`🎉 Bot @${session.botUsername} successfully created and launched!`);
    startClientBot(botData);
}

// --- MY BOTS MANAGEMENT ---
mainBot.hears('🤖 My Bots', async (ctx) => {
    const snap = await botsRef.orderByChild('ownerId').equalTo(ctx.from.id).once('value');
    const bots = snap.val();
    if (!bots) return ctx.reply("You don't have any bots yet.");

    for (let key in bots) {
        const b = bots[key];
        ctx.reply(`Bot: ${b.botName}\nUser: @${b.botUsername}\nStatus: ${b.status}`, 
            Markup.inlineKeyboard([
                [Markup.button.callback('⏹ Stop', `stop_${b.id}`), Markup.button.callback('▶️ Start', `start_${b.id}`)],
                [Markup.button.callback('🗑 Delete', `del_${b.id}`)]
            ])
        );
    }
});

mainBot.action(/start_(.+)/, async (ctx) => {
    const bid = ctx.match[1];
    const snap = await botsRef.child(bid).once('value');
    startClientBot(snap.val());
    await botsRef.child(bid).update({ status: 'RUN' });
    ctx.answerCbQuery("Bot Started");
});

mainBot.action(/stop_(.+)/, async (ctx) => {
    const bid = ctx.match[1];
    if (activeBots[bid]) {
        activeBots[bid].stop();
        delete activeBots[bid];
    }
    await botsRef.child(bid).update({ status: 'STOP' });
    ctx.answerCbQuery("Bot Stopped");
});

mainBot.action(/del_(.+)/, async (ctx) => {
    const bid = ctx.match[1];
    if (activeBots[bid]) activeBots[bid].stop();
    await botsRef.child(bid).remove();
    ctx.deleteMessage();
});

// --- 3. CLIENT BOT LOGIC ---
function startClientBot(config) {
    if (activeBots[config.id]) return;

    const bot = new Telegraf(config.token);

    bot.start(async (ctx) => {
        // Log Subscriber
        await subsRef.child(config.id).child(ctx.from.id.toString()).set({
            name: ctx.from.first_name,
            username: ctx.from.username || "N/A"
        });

        const kb = config.buttons ? config.buttons.map(b => [Markup.button.url(b.text, b.url)]) : [];
        const extra = kb.length > 0 ? Markup.inlineKeyboard(kb) : {};

        if (config.welcomeImage) {
            ctx.replyWithPhoto(config.welcomeImage, { caption: config.welcomeText, ...extra });
        } else {
            ctx.reply(config.welcomeText, extra);
        }
    });

    // Broadcast Command
    bot.command('broadcast', (ctx) => {
        if (!config.admins.includes(ctx.from.id)) return;
        ctx.reply("Please reply to this message with the content you want to broadcast.");
        
        bot.on('message', async (msgCtx) => {
            if (msgCtx.from.id !== ctx.from.id) return;
            const usersSnap = await subsRef.child(config.id).once('value');
            const users = usersSnap.val();
            if (!users) return msgCtx.reply("No users found to broadcast to.");

            let sentCount = 0;
            for (let uid in users) {
                try {
                    await msgCtx.copyMessage(uid);
                    sentCount++;
                } catch (e) {}
            }
            msgCtx.reply(`📢 Broadcast Complete! Sent to ${sentCount} users.`);
        });
    });

    bot.launch().catch(err => console.error("Bot launch failed", err));
    activeBots[config.id] = bot;
}

// Auto-Resume Bots
const init = async () => {
    const snap = await botsRef.once('value');
    const bots = snap.val();
    if (bots) {
        for (let key in bots) {
            if (bots[key].status === 'RUN') startClientBot(bots[key]);
        }
    }
    mainBot.launch();
    console.log("🚀 Control Hub is Online");
};

init();

// --- 4. EXPRESS SERVER ---
app.get('/', (req, res) => res.send('Bot Control Hub is running...'));
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server listening on port ${PORT}`));
