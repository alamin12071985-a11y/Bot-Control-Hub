/**
 * PROJECT: Bot Control Hub (SaaS)
 * AUTHOR: Rebuilt for @lagatech
 * VERSION: 2.0.0
 * DATABASE: Firebase Realtime DB
 */

require('dotenv').config();
const { Telegraf, Markup, session } = require('telegraf');
const express = require('express');
const admin = require('firebase-admin');
const cors = require('cors');

// --- 1. INITIALIZATION & SERVER SETUP ---
const app = express();
app.use(express.json());
app.use(cors());

const PORT = process.env.PORT || 3000;
const MAIN_BOT_TOKEN = process.env.MAIN_BOT_TOKEN;
const DATABASE_URL = "https://bot-control-hub-eee53-default-rtdb.firebaseio.com";

// Global Error Catching - Prevents the entire server from crashing on a single bot error
process.on('uncaughtException', (err) => {
    console.error('CRITICAL ERROR (Uncaught):', err);
});
process.on('unhandledRejection', (reason, promise) => {
    console.error('CRITICAL ERROR (Unhandled Rejection):', reason);
});

// --- 2. FIREBASE CONNECTION ---
let db, botsRef, usersRef, sessionsRef, subsRef, logsRef;

try {
    if (!process.env.FIREBASE_SERVICE_ACCOUNT) {
        throw new Error("Missing FIREBASE_SERVICE_ACCOUNT in Environment Variables!");
    }

    const serviceAccount = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT);
    admin.initializeApp({
        credential: admin.credential.cert(serviceAccount),
        databaseURL: DATABASE_URL
    });

    db = admin.database();
    botsRef = db.ref("bots");
    usersRef = db.ref("users");
    sessionsRef = db.ref("sessions");
    subsRef = db.ref("subscribers");
    logsRef = db.ref("system_logs");

    console.log("✅ Firebase Admin SDK Connected Successfully");
} catch (error) {
    console.error("❌ Firebase Connection Failed:", error.message);
    process.exit(1); 
}

// Memory storage for active Telegraf instances
let activeBots = {};

// --- 3. MAIN CONTROLLER BOT LOGIC ---
const mainBot = new Telegraf(MAIN_BOT_TOKEN);

// Set Menu Commands for Main Bot
mainBot.telegram.setMyCommands([
    { command: 'start', description: 'মূল ড্যাশবোর্ড চালু করুন' },
    { command: 'help', description: 'সহযোগিতা ও এডমিন কন্টাক্ট' },
    { command: 'stats', description: 'আপনার বটের পরিসংখ্যান' }
]);

// Utility Keyboard
const mainKeyboard = Markup.keyboard([
    ['🤖 My Bots', '➕ Add New Bot'],
    ['📊 Statistics', '❓ Help']
]).resize();

// --- START COMMAND ---
mainBot.start(async (ctx) => {
    try {
        const uid = ctx.from.id.toString();
        // Update user info in DB
        await usersRef.child(uid).update({
            username: ctx.from.username || "N/A",
            name: ctx.from.first_name,
            lastSeen: Date.now(),
            isPremium: false
        });

        // Clear any stuck setup session
        await sessionsRef.child(uid).remove();

        const welcomeMsg = 
            `👋 *স্বাগতম Bot Control Hub-এ!*\n\n` +
            `এখানে আপনি খুব সহজেই নিজের টেলিগ্রাম বট তৈরি এবং পরিচালনা করতে পারবেন।\n\n` +
            `🚀 *শুরু করতে নিচের বাটন ব্যবহার করুন:*`;
        
        ctx.replyWithMarkdownV2(welcomeMsg.replace(/[-]/g, '\\-').replace(/[!]/g, '\\!').replace(/[.]/g, '\\.'), mainKeyboard);
    } catch (e) {
        console.error("MainBot Start Error:", e);
    }
});

// --- HELP COMMAND ---
mainBot.help((ctx) => {
    ctx.reply(
        `❓ *সাহায্য প্রয়োজন?*\n\n` +
        `বট তৈরি করতে সমস্যা হলে বা কোনো ফিচারের জন্য আমাদের সাথে যোগাযোগ করুন।\n\n` +
        `👨‍💻 *এডমিন:* @lagatech\n` +
        `📢 *আপডেট চ্যানেল:* @lagatech_updates`,
        Markup.inlineKeyboard([
            [Markup.button.url('Message Admin', 'https://t.me/lagatech')],
            [Markup.button.url('Join Support Group', 'https://t.me/lagatech')]
        ])
    );
});

// --- STATISTICS ---
mainBot.hears('📊 Statistics', async (ctx) => {
    try {
        const uid = ctx.from.id.toString();
        const botsSnap = await botsRef.orderByChild('ownerId').equalTo(ctx.from.id).once('value');
        const bots = botsSnap.val();
        
        if (!bots) return ctx.reply("আপনার কোনো একটিভ বট নেই।");

        let totalSubs = 0;
        let botCount = Object.keys(bots).length;

        for (let key in bots) {
            const sSnap = await subsRef.child(bots[key].id).once('value');
            if (sSnap.exists()) totalSubs += Object.keys(sSnap.val()).length;
        }

        ctx.reply(
            `📊 *আপনার অ্যাকাউন্টের তথ্য:*\n\n` +
            `🤖 মোট বট: ${botCount} টি\n` +
            `👥 মোট ইউজার (সকল বটে): ${totalSubs} জন`,
            { parse_mode: 'Markdown' }
        );
    } catch (e) {
        ctx.reply("পরিসংখ্যান লোড করতে সমস্যা হচ্ছে।");
    }
});

// --- ADD BOT WIZARD (STEP-BY-STEP) ---
mainBot.hears('➕ Add New Bot', async (ctx) => {
    const uid = ctx.from.id.toString();
    await sessionsRef.child(uid).set({ step: 'WAIT_TOKEN', startTime: Date.now() });
    
    ctx.reply(
        `✨ *ধাপ ১: বট টোকেন*\n\n` +
        `@BotFather থেকে পাওয়া আপনার বটের API Token-টি এখানে পাঠান।`,
        { parse_mode: 'Markdown' }
    );
});

// Logic Handler for Wizard Steps
mainBot.on('text', async (ctx) => {
    const uid = ctx.from.id.toString();
    const snap = await sessionsRef.child(uid).once('value');
    if (!snap.exists()) return;

    const session = snap.val();
    const input = ctx.message.text.trim();

    // Step 1: Token Validation
    if (session.step === 'WAIT_TOKEN') {
        try {
            ctx.reply("⏳ টোকেন যাচাই করা হচ্ছে...");
            const tempBot = new Telegraf(input);
            const info = await tempBot.telegram.getMe();

            await sessionsRef.child(uid).update({ 
                step: 'WAIT_IMAGE', 
                token: input, 
                botName: info.first_name, 
                botUsername: info.username 
            });

            ctx.reply(
                `✅ বট কানেক্ট হয়েছে: *@${info.username}*\n\n` +
                `✨ *ধাপ ২: ওয়েলকাম ছবি*\n` +
                `ইউজার যখন বটে /start দিবে, তখন কোন ছবি দেখাবে? সেটি পাঠান।\n` +
                `ছবি না দিতে চাইলে /skip লিখুন।`,
                { parse_mode: 'Markdown' }
            );
        } catch (e) {
            ctx.reply("❌ ভুল টোকেন! দয়া করে সঠিক টোকেনটি কপি করে পাঠান।");
        }
    } 
    // Step 3: Welcome Text
    else if (session.step === 'WAIT_TEXT') {
        await sessionsRef.child(uid).update({ step: 'WAIT_BTN_COUNT', welcomeText: input });
        ctx.reply("✨ *ধাপ ৪: বাটন সংখ্যা*\n\nবটে কয়টি বাটন রাখতে চান? (০ থেকে ৩ এর মধ্যে সংখ্যা লিখুন)");
    }
    // Step 4: Button Count
    else if (session.step === 'WAIT_BTN_COUNT') {
        const count = parseInt(input);
        if (isNaN(count) || count < 0 || count > 3) return ctx.reply("দয়া করে শুধু সংখ্যা লিখুন (0, 1, 2, 3)।");

        if (count === 0) {
            finalizeBotCreation(ctx, session, []);
        } else {
            await sessionsRef.child(uid).update({ step: 'WAIT_BTN_DATA', targetBtns: count, currentBtns: [] });
            ctx.reply(`বাটন ১ এর নাম এবং লিঙ্ক দিন।\n\n*ফরমেট:* নাম | লিঙ্ক\n*উদাহরণ:* Join Channel | https://t.me/lagatech`, { parse_mode: 'Markdown' });
        }
    }
    // Step 5: Button Data Collection
    else if (session.step === 'WAIT_BTN_DATA') {
        const parts = input.split('|');
        if (parts.length < 2) return ctx.reply("❌ ভুল ফরম্যাট! (নাম | লিঙ্ক) এভাবে লিখুন।");

        let btnList = session.currentBtns || [];
        btnList.push({ text: parts[0].trim(), url: parts[1].trim() });

        if (btnList.length >= session.targetBtns) {
            finalizeBotCreation(ctx, session, btnList);
        } else {
            await sessionsRef.child(uid).update({ currentBtns: btnList });
            ctx.reply(`বাটন ${btnList.length + 1} এর তথ্য দিন (নাম | লিঙ্ক)`);
        }
    }
});

// Handle Image Upload for Step 2
mainBot.on(['photo', 'message'], async (ctx) => {
    const uid = ctx.from.id.toString();
    const snap = await sessionsRef.child(uid).once('value');
    if (!snap.exists()) return;
    const session = snap.val();

    if (session.step === 'WAIT_IMAGE') {
        const fileId = ctx.message.photo ? ctx.message.photo[ctx.message.photo.length - 1].file_id : null;
        
        if (!fileId && ctx.message.text !== '/skip') {
            return ctx.reply("দয়া করে ছবি পাঠান অথবা /skip লিখুন।");
        }

        await sessionsRef.child(uid).update({ step: 'WAIT_TEXT', welcomeImage: fileId || null });
        ctx.reply("✨ *ধাপ ৩: ওয়েলকাম মেসেজ*\n\nবট স্টার্ট করলে কি লেখা দেখাবে? সেটি লিখুন।");
    }
});

async function finalizeBotCreation(ctx, session, buttons) {
    try {
        const botId = botsRef.push().key;
        const botData = {
            id: botId,
            ownerId: ctx.from.id,
            token: session.token,
            botName: session.botName,
            botUsername: session.botUsername,
            welcomeImage: session.welcomeImage || null,
            welcomeText: session.welcomeText,
            buttons: buttons,
            status: 'RUN',
            createdAt: Date.now(),
            admins: [ctx.from.id]
        };

        await botsRef.child(botId).set(botData);
        await sessionsRef.child(ctx.from.id.toString()).remove();
        
        ctx.reply(`🎉 *অভিনন্দন!*\n\nআপনার বট *@${session.botUsername}* এখন লাইভ এবং ব্যবহারের জন্য প্রস্তুত।`, { parse_mode: 'Markdown' });
        
        // Launch the bot instance immediately
        initiateClientBot(botData);
    } catch (e) {
        ctx.reply("❌ সেভ করার সময় সমস্যা হয়েছে। আবার চেষ্টা করুন।");
    }
}

// --- 4. MY BOTS MANAGEMENT PANEL ---
mainBot.hears('🤖 My Bots', async (ctx) => {
    try {
        const snap = await botsRef.orderByChild('ownerId').equalTo(ctx.from.id).once('value');
        const bots = snap.val();

        if (!bots) return ctx.reply("আপনি কোনো বট যুক্ত করেননি।");

        ctx.reply("📦 আপনার তৈরি করা বটগুলোর তালিকা:");

        for (let key in bots) {
            const b = bots[key];
            const btnLabel = b.status === 'RUN' ? '⏹ Stop Bot' : '▶️ Start Bot';
            
            ctx.reply(
                `🤖 *বট:* ${b.botName}\n` +
                `🔗 *ইউজার:* @${b.botUsername}\n` +
                `📊 *স্ট্যাটাস:* ${b.status === 'RUN' ? '✅ Active' : '❌ Stopped'}`,
                Markup.inlineKeyboard([
                    [Markup.button.callback(btnLabel, `toggle_${b.id}`)],
                    [Markup.button.callback('🗑 Delete Bot', `delete_${b.id}`)]
                ], { parse_mode: 'Markdown' })
            );
        }
    } catch (e) {
        ctx.reply("বট লিস্ট লোড করতে সমস্যা হচ্ছে।");
    }
});

// Inline Actions for Bot Management
mainBot.action(/toggle_(.+)/, async (ctx) => {
    const bid = ctx.match[1];
    const snap = await botsRef.child(bid).once('value');
    if (!snap.exists()) return ctx.answerCbQuery("বট পাওয়া যায়নি।");

    const bot = snap.val();
    const newStatus = bot.status === 'RUN' ? 'STOP' : 'RUN';

    if (newStatus === 'STOP') {
        if (activeBots[bid]) {
            try { activeBots[bid].stop(); } catch (e) {}
            delete activeBots[bid];
        }
    } else {
        initiateClientBot(bot);
    }

    await botsRef.child(bid).update({ status: newStatus });
    ctx.editMessageText(`বটের স্ট্যাটাস আপডেট হয়েছে: ${newStatus}`);
    ctx.answerCbQuery(`বট ${newStatus === 'RUN' ? 'চালু' : 'বন্ধ'} হয়েছে।`);
});

mainBot.action(/delete_(.+)/, async (ctx) => {
    const bid = ctx.match[1];
    if (activeBots[bid]) {
        try { activeBots[bid].stop(); } catch (e) {}
        delete activeBots[bid];
    }
    await botsRef.child(bid).remove();
    await subsRef.child(bid).remove();
    ctx.deleteMessage();
    ctx.answerCbQuery("বটটি ডিলিট করা হয়েছে।");
});

// --- 5. CLIENT BOT DYNAMIC ENGINE ---
function initiateClientBot(config) {
    if (activeBots[config.id]) return;

    try {
        const bot = new Telegraf(config.token);

        // Client Bot Start Logic
        bot.start(async (ctx) => {
            try {
                // Tracking Subscribers
                await subsRef.child(config.id).child(ctx.from.id.toString()).update({
                    n: ctx.from.first_name,
                    u: ctx.from.username || "N/A",
                    t: Date.now()
                });

                const kb = config.buttons ? config.buttons.map(b => [Markup.button.url(b.text, b.url)]) : [];
                const extra = kb.length > 0 ? Markup.inlineKeyboard(kb) : {};

                if (config.welcomeImage) {
                    try {
                        await ctx.replyWithPhoto(config.welcomeImage, { caption: config.welcomeText, ...extra });
                    } catch (err) {
                        // Fallback: If image fails (400 Bad Request), send text
                        await ctx.reply(config.welcomeText, extra);
                    }
                } else {
                    await ctx.reply(config.welcomeText, extra);
                }
            } catch (innerError) {
                console.error(`Error in Client Bot @${config.botUsername} start:`, innerError.message);
            }
        });

        // Broadcast Feature for Bot Owners
        bot.command('broadcast', async (ctx) => {
            if (!config.admins.includes(ctx.from.id)) return;
            ctx.reply("📢 ব্রডকাস্ট মেসেজটি ছবিসহ বা শুধু টেক্সট লিখে পাঠান।");

            const broadcastListener = async (bCtx) => {
                if (bCtx.from.id !== ctx.from.id) return;
                
                const sSnap = await subsRef.child(config.id).once('value');
                const users = sSnap.val();
                
                if (!users) return bCtx.reply("বটে কোনো ইউজার নেই।");
                
                let success = 0;
                let fail = 0;
                bCtx.reply("⏳ ব্রডকাস্ট শুরু হয়েছে...");

                for (let uid in users) {
                    try {
                        await bCtx.copyMessage(uid);
                        success++;
                    } catch (e) {
                        fail++;
                    }
                }
                bCtx.reply(`📢 ব্রডকাস্ট শেষ!\n✅ সফল: ${success}\n❌ ব্যর্থ: ${fail}`);
                bot.off('message', broadcastListener); // Stop listening after one broadcast
                bot.off('photo', broadcastListener);
            };

            bot.on(['message', 'photo'], broadcastListener);
        });

        bot.launch().then(() => {
            console.log(`[ENGINE] @${config.botUsername} is now running.`);
        }).catch(e => {
            console.error(`[ENGINE] Failed to launch @${config.botUsername}:`, e.message);
        });

        activeBots[config.id] = bot;

    } catch (err) {
        console.error(`[ENGINE] Critical init error for @${config.botUsername}:`, err.message);
    }
}

// --- 6. AUTO-RESUME ON SERVER START ---
const startup = async () => {
    console.log("🛠 Booting system and resuming bots...");
    try {
        const snap = await botsRef.once('value');
        const allBots = snap.val();
        
        if (allBots) {
            let count = 0;
            for (let key in allBots) {
                if (allBots[key].status === 'RUN') {
                    initiateClientBot(allBots[key]);
                    count++;
                }
            }
            console.log(`🛠 Total ${count} bots resumed.`);
        }

        mainBot.launch().then(() => console.log("🚀 Main Controller Hub is online!"));
    } catch (e) {
        console.error("Startup Failure:", e);
    }
};

startup();

// --- 7. WEB SERVER HEALTH CHECK ---
app.get('/', (req, res) => {
    res.status(200).json({
        status: "Online",
        service: "Bot Control Hub Pro",
        active_instances: Object.keys(activeBots).length,
        timestamp: new Date().toISOString()
    });
});

app.listen(PORT, () => {
    console.log(`⚡ API Health Check Server running on port ${PORT}`);
});

// Graceful Shutdown Logic
process.once('SIGINT', () => {
    mainBot.stop('SIGINT');
    Object.values(activeBots).forEach(b => b.stop('SIGINT'));
    process.exit(0);
});
process.once('SIGTERM', () => {
    mainBot.stop('SIGTERM');
    Object.values(activeBots).forEach(b => b.stop('SIGTERM'));
    process.exit(0);
});
