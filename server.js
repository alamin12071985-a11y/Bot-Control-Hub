/**
 * PROJECT: Bot Control Hub (SaaS) - Rebuilt & Fixed
 * AUTHOR: @lagatech
 * VERSION: 2.1.0 (Bangla Edition)
 * DATABASE: Firebase Realtime DB
 */

require('dotenv').config();
const { Telegraf, Markup, session, Scenes } = require('telegraf');
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
const ADMIN_IDS = ['YOUR_TELEGRAM_ID']; // এখানে আপনার টেলিগ্রাম ID বসান (স্ট্রিং আকারে)

// Global Error Catching
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

// Set Menu Commands
mainBot.telegram.setMyCommands([
    { command: 'start', description: 'মূল ড্যাশবোর্ড চালু করুন' },
    { command: 'help', description: 'সহযোগিতা ও এডমিন কন্টাক্ট' }
]);

// Utility Keyboards
const mainKeyboard = Markup.keyboard([
    ['🤖 My Bots', '➕ New Bot'],
    ['📢 Broadcast Setup', '📊 Statistics'],
    ['🛠 Admin Panel']
]).resize();

// --- START COMMAND ---
mainBot.start(async (ctx) => {
    try {
        const uid = ctx.from.id.toString();
        await usersRef.child(uid).update({
            username: ctx.from.username || "N/A",
            name: ctx.from.first_name,
            lastSeen: Date.now()
        });

        await sessionsRef.child(uid).remove(); // Clear previous sessions

        const welcomeMsg = 
            `👋 *হ্যালো বন্ধু!* স্বাগতম বট কন্ট্রোল হাবে!\n\n` +
            `এখানে তুমি নিজের খুব সহজেই টেলিগ্রাম বট বানাতে পারবে। একদম পানির মতো সহজ! 😄\n\n` +
            `নিচের বাটনে ক্লিক করে শুরু করো তো! 👇`;
        
        ctx.replyWithMarkdown(welcomeMsg, Markup.inlineKeyboard([
            [Markup.button.callback('🚀 Get Started', 'start_menu')]
        ]));
    } catch (e) {
        console.error("MainBot Start Error:", e);
    }
});

// --- HELP COMMAND ---
mainBot.help((ctx) => {
    ctx.reply(
        `❓ *সাহায্য চাই?*\n\n` +
        `বট বানাতে গেলে কোনো সমস্যা হলে বা মাথা খারাপ হয়ে গেলে এখানে এসো! 😂\n\n` +
        `👨‍💻 *এডমিন:* @lagatech\n` +
        `📢 *আপডেট চ্যানেল:* @lagatech_updates`,
        Markup.inlineKeyboard([
            [Markup.button.url('💬 Message Admin', 'https://t.me/lagatech')]
        ])
    );
});

// --- CALLBACK HANDLERS ---
mainBot.action('start_menu', async (ctx) => {
    ctx.editMessageReplyMarkup(undefined);
    ctx.reply('🏠 মেনু থেকে যা ইচ্ছে তা করো!', mainKeyboard);
});

// --- MAIN MENU HANDLERS ---

// 1. MY BOTS
mainBot.hears('🤖 My Bots', async (ctx) => {
    try {
        const snap = await botsRef.orderByChild('ownerId').equalTo(ctx.from.id).once('value');
        const bots = snap.val();

        if (!bots) return ctx.reply("☹️ তুমি এখনো কোনো বট বানাওনি! '➕ New Bot' বাটনে ক্লিক করো।");

        ctx.reply("📦 তোমার বটের তালিকা নিচে দেওয়া হলো:");

        for (let key in bots) {
            const b = bots[key];
            ctx.reply(
                `🤖 *বট:* ${b.botName}\n` +
                `🔗 *ইউজার:* @${b.botUsername}\n` +
                `📊 *স্ট্যাটাস:* ${b.status === 'RUN' ? '✅ চলছে' : '❌ বন্ধ'}`,
                Markup.inlineKeyboard([
                    [Markup.button.callback('📝 Edit Welcome', `edit_${b.id}`)],
                    [Markup.button.callback('🗑 Delete Bot', `delete_${b.id}`)]
                ], { parse_mode: 'Markdown' })
            );
        }
    } catch (e) {
        console.error(e);
        ctx.reply("বটের তালিকা আনতে সমস্যা হলো!");
    }
});

// 2. NEW BOT WIZARD (Step-by-Step)
mainBot.hears('➕ New Bot', async (ctx) => {
    const uid = ctx.from.id.toString();
    await sessionsRef.child(uid).set({ step: 'WAIT_TOKEN', startTime: Date.now() });
    ctx.reply(
        `✨ *ধাপ ১: বট টোকেন*\n\n` +
        `@BotFather থেকে তোমার বটের API Token টা নিয়ে এখানে পাঠাও।\n` +
        `(টোকেনটা কাউকে দিবে না কিন্তু! 🤫)`,
        { parse_mode: 'Markdown' }
    );
});

// 3. BROADCAST SETUP
mainBot.hears('📢 Broadcast Setup', async (ctx) => {
    const botsSnap = await botsRef.orderByChild('ownerId').equalTo(ctx.from.id).once('value');
    if (!botsSnap.exists()) return ctx.reply("☹️ তুমি কোনো বট বানাওনি!");

    const bots = botsSnap.val();
    const btns = [];
    for (let key in bots) {
        btns.push([Markup.button.callback(`🤖 ${bots[key].botName}`, `bc_setup_${bots[key].id}`)]);
    }
    
    ctx.reply("কোন বটের জন্য ব্রডকাস্ট সেটআপ করতে চাও?", Markup.inlineKeyboard(btns));
});

mainBot.action(/bc_setup_(.+)/, async (ctx) => {
    const bid = ctx.match[1];
    const uid = ctx.from.id.toString();
    
    await sessionsRef.child(uid).update({ step: 'BC_SET_ADMINS', botId: bid });
    ctx.editMessageText(
        `📢 *ব্রডকাস্ট এডমিন সেটআপ*\n\n` +
        `এখন তুমি যাদেরকে এই বটে ব্রডকাস্ট পাঠানোর অনুমতি দিতে চাও, তাদের *টেলিগ্রাম ID* পাঠাও।\n\n` +
        `একাধিক ID হলে কমা (,) দিয়ে আলাদা করো।\n` +
        `উদাহরণ: 12345678, 98765432`,
        { parse_mode: 'Markdown' }
    );
    ctx.answerCbQuery();
});

// 4. STATISTICS
mainBot.hears('📊 Statistics', async (ctx) => {
    try {
        const uid = ctx.from.id.toString();
        const botsSnap = await botsRef.orderByChild('ownerId').equalTo(ctx.from.id).once('value');
        const bots = botsSnap.val();
        
        if (!bots) return ctx.reply("তোমার কোনো একটিভ বট নেই।");

        let totalSubs = 0;
        let botCount = Object.keys(bots).length;

        for (let key in bots) {
            const sSnap = await subsRef.child(bots[key].id).once('value');
            if (sSnap.exists()) totalSubs += Object.keys(sSnap.val()).length;
        }

        ctx.reply(
            `📊 *তোমার হিসাব-নিকাশ:*\n\n` +
            `🤖 মোট বট: ${botCount} টি\n` +
            `👥 মোট ইউজার: ${totalSubs} জন\n\n` +
            `খুব ভালো! আরো বট বানাও! 😄`,
            { parse_mode: 'Markdown' }
        );
    } catch (e) {
        ctx.reply("পরিসংখ্যান লোড করতে সমস্যা হচ্ছে।");
    }
});

// 5. ADMIN PANEL
mainBot.hears('🛠 Admin Panel', async (ctx) => {
    if (!ADMIN_IDS.includes(ctx.from.id.toString())) {
        return ctx.reply("🚫 মাফ করবে, এই প্যানেলটি শুধু বস দেখতে পারবে! 😎");
    }

    ctx.reply("🛠 *এডমিন প্যানেলে স্বাগতম বস!*", 
        Markup.inlineKeyboard([
            [Markup.button.callback('📊 ওভারভিউ স্ট্যাটস', 'admin_stats')],
            [Markup.button.callback('📢 মেইন ব্রডকাস্ট', 'admin_broadcast')]
        ])
    );
});

mainBot.action('admin_stats', async (ctx) => {
    const uSnap = await usersRef.once('value');
    const bSnap = await botsRef.once('value');
    
    let totalClientUsers = 0;
    const allBots = bSnap.val();
    if (allBots) {
        for (let key in allBots) {
            const sSnap = await subsRef.child(allBots[key].id).once('value');
            if (sSnap.exists()) totalClientUsers += Object.keys(sSnap.val()).length;
        }
    }

    ctx.editMessageText(
        `📊 *সিস্টেম ওভারভিউ:*\n\n` +
        `👥 হাব ইউজার: ${uSnap.exists() ? Object.keys(uSnap.val()).length : 0}\n` +
        `🤖 মোট ক্রিয়েটেড বট: ${bSnap.exists() ? Object.keys(bSnap.val()).length : 0}\n` +
        `🏴 মোট ক্লায়েন্ট ইউজার: ${totalClientUsers}`,
        { parse_mode: 'Markdown' }
    );
    ctx.answerCbQuery();
});

mainBot.action('admin_broadcast', async (ctx) => {
    await sessionsRef.child(ctx.from.id.toString()).set({ step: 'ADMIN_BC_WAIT_CONTENT' });
    ctx.editMessageText("📢 বস, মেইন ব্রডকাস্ট মেসেজটি পাঠাও (ছবি বা টেক্সট)।");
    ctx.answerCbQuery();
});

// --- DYNAMIC TEXT HANDLER (WIZARD ENGINE) ---
mainBot.on('text', async (ctx) => {
    const uid = ctx.from.id.toString();
    const snap = await sessionsRef.child(uid).once('value');
    if (!snap.exists()) return;

    const session = snap.val();
    const input = ctx.message.text.trim();

    // --- NEW BOT CREATION LOGIC ---
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
    else if (session.step === 'WAIT_TEXT') {
        await sessionsRef.child(uid).update({ step: 'WAIT_BTN_COUNT', welcomeText: input });
        ctx.reply("✨ *ধাপ ৪: বাটন সংখ্যা*\n\nবটে কয়টি বাটন রাখতে চান? (০ থেকে ৩ এর মধ্যে সংখ্যা লিখুন)");
    }
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
    // --- BROADCAST SETUP LOGIC ---
    else if (session.step === 'BC_SET_ADMINS') {
        const botId = session.botId;
        const ids = input.split(',').map(id => id.trim());
        
        await botsRef.child(botId).child('broadcastAdmins').set(ids);
        await sessionsRef.child(uid).remove();
        
        ctx.reply(`✅ সফল! এই বটের ব্রডকাস্ট এডমিন সেট করা হয়েছে। এখন তারা বটে গিয়ে /broadcast কমান্ড ব্যবহার করতে পারবে।`);
    }
    // --- ADMIN MAIN BROADCAST LOGIC ---
    else if (session.step === 'ADMIN_BC_BTN') {
        const parts = input.split('|');
        if (parts.length < 2) return ctx.reply("❌ ভুল ফরম্যাট! (নাম | লিঙ্ক) এভাবে লিখুন।");

        await performMainBroadcast(ctx, session, [{ text: parts[0].trim(), url: parts[1].trim() }]);
    }
});

// --- DYNAMIC IMAGE HANDLER ---
mainBot.on('photo', async (ctx) => {
    const uid = ctx.from.id.toString();
    const snap = await sessionsRef.child(uid).once('value');
    if (!snap.exists()) return;
    const session = snap.val();

    // NEW BOT CREATION IMAGE STEP
    if (session.step === 'WAIT_IMAGE') {
        const fileId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
        await sessionsRef.child(uid).update({ step: 'WAIT_TEXT', welcomeImage: fileId });
        
        ctx.reply(
            "🖼 ছবি ঠিক আছে! বেশ সুন্দর হয়েছে!\n\n" +
            "✨ *ধাপ ৩: ওয়েলকাম মেসেজ*\n\n" +
            "বট স্টার্ট করলে কি লেখা দেখাবে? সেটি লিখুন।", 
            { parse_mode: 'Markdown' }
        );
    }
    // ADMIN MAIN BROADCAST IMAGE
    else if (session.step === 'ADMIN_BC_WAIT_CONTENT') {
        const fileId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
        const caption = ctx.message.caption || "";
        
        await sessionsRef.child(uid).update({ step: 'ADMIN_BC_BTN', bcImage: fileId, bcText: caption });
        ctx.reply("📢 ছবি পেয়েছি। এখন একটি বাটন দিতে চাইলে লিখুন (নাম | লিঙ্ক), অথবা /skip করুন।");
    }
});

// --- COMMAND HANDLERS FOR WIZARD SKIPS ---
mainBot.command('skip', async (ctx) => {
    const uid = ctx.from.id.toString();
    const snap = await sessionsRef.child(uid).once('value');
    if (!snap.exists()) return;
    const session = snap.val();

    if (session.step === 'WAIT_IMAGE') {
        await sessionsRef.child(uid).update({ step: 'WAIT_TEXT', welcomeImage: null });
        ctx.reply("👌 ঠিক আছে, ছবি ছাড়াই চলবে।\n\n✨ *ধাপ ৩: ওয়েলকাম মেসেজ*\n\nএখন টেক্সট লিখুন।", { parse_mode: 'Markdown' });
    } 
    else if (session.step === 'ADMIN_BC_BTN') {
        await performMainBroadcast(ctx, session, []);
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
            admins: [ctx.from.id],
            broadcastAdmins: [ctx.from.id] // Default owner is broadcast admin
        };

        await botsRef.child(botId).set(botData);
        await sessionsRef.child(ctx.from.id.toString()).remove();
        
        ctx.reply(`🎉 *অভিনন্দন!*\n\nতোমার বট *@${session.botUsername}* এখন লাইভ! আয় বস আয় দেখে যাই! 😍`, { parse_mode: 'Markdown' });
        
        initiateClientBot(botData);
    } catch (e) {
        ctx.reply("❌ সেভ করার সময় সমস্যা হয়েছে।");
    }
}

// --- INLINE ACTIONS ---
mainBot.action(/edit_(.+)/, async (ctx) => {
    const bid = ctx.match[1];
    await sessionsRef.child(ctx.from.id.toString()).set({ step: 'WAIT_TEXT', editingBotId: bid, editing: true });
    ctx.answerCbQuery("এডিট মোড অন!");
    ctx.reply("এডিট করার জন্য নতুন ওয়েলকাম টেক্সট পাঠান।");
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

async function performMainBroadcast(ctx, session, buttons) {
    const uSnap = await usersRef.once('value');
    const users = uSnap.val();
    const kb = buttons.length > 0 ? Markup.inlineKeyboard(buttons.map(b => [Markup.button.url(b.text, b.url)])) : {};

    let success = 0;
    ctx.reply("📢 মেইন ব্রডকাস্ট শুরু হচ্ছে...");

    for (let uid in users) {
        try {
            if (session.bcImage) {
                await mainBot.telegram.sendPhoto(uid, session.bcImage, { caption: session.bcText, ...kb });
            } else {
                await mainBot.telegram.sendMessage(uid, session.bcText, kb);
            }
            success++;
        } catch (e) { }
    }
    await sessionsRef.child(ctx.from.id.toString()).remove();
    ctx.reply(`📢 বস, কাজ শেষ! সফল হয়েছে ${success} জনের কাছে।`);
}

// --- 5. CLIENT BOT DYNAMIC ENGINE ---
function initiateClientBot(config) {
    if (activeBots[config.id]) return;

    try {
        const bot = new Telegraf(config.token);
        
        // Session for client bot broadcast wizard
        bot.use(session());

        // Client Bot Start
        bot.start(async (ctx) => {
            try {
                await subsRef.child(config.id).child(ctx.from.id.toString()).update({
                    n: ctx.from.first_name,
                    u: ctx.from.username || "N/A",
                    t: Date.now()
                });

                const kb = config.buttons && config.buttons.length > 0 
                    ? Markup.inlineKeyboard(config.buttons.map(b => [Markup.button.url(b.text, b.url)])) 
                    : {};

                // FIX: Image showing issue fixed here properly
                if (config.welcomeImage) {
                    try {
                        await ctx.replyWithPhoto(config.welcomeImage, { 
                            caption: config.welcomeText || " ", 
                            ...kb 
                        });
                    } catch (err) {
                        // If photo fails, send text only
                        await ctx.reply(config.welcomeText || "Welcome!", kb);
                    }
                } else {
                    await ctx.reply(config.welcomeText || "Welcome!", kb);
                }
            } catch (innerError) {
                console.error(`Error in Client Bot @${config.botUsername} start:`, innerError.message);
            }
        });

        // Client Bot Broadcast System
        bot.command('broadcast', async (ctx) => {
            const uid = ctx.from.id;
            // Check permission
            const botConfig = (await botsRef.child(config.id).once('value')).val();
            if (!botConfig.broadcastAdmins || !botConfig.broadcastAdmins.includes(uid.toString())) {
                return ctx.reply("🚫 দুঃখিত, তুমি ব্রডকাস্ট করতে পারবে না!");
            }

            ctx.session = ctx.session || {};
            ctx.session.bcStep = 'WAIT_CONTENT';
            ctx.reply("📢 *ব্রডকাস্ট মোড*\n\nযা পাঠাতে চাও (ছবি বা টেক্সট) পাঠাও।", { parse_mode: 'Markdown' });
        });

        bot.on(['photo', 'text'], async (ctx) => {
            if (!ctx.session || !ctx.session.bcStep) return;
            
            const step = ctx.session.bcStep;
            
            if (step === 'WAIT_CONTENT') {
                if (ctx.message.photo) {
                    ctx.session.type = 'photo';
                    ctx.session.fileId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
                    ctx.session.text = ctx.message.caption || "";
                } else {
                    ctx.session.type = 'text';
                    ctx.session.text = ctx.message.text;
                }
                
                ctx.session.bcStep = 'WAIT_BUTTON';
                ctx.reply("বাটন দিতে চাও? (নাম | লিঙ্ক) লিখো, অথবা /skip করো।");
            } 
            else if (step === 'WAIT_BUTTON') {
                const parts = ctx.message.text.split('|');
                if (parts.length < 2) return ctx.reply("ভুল ফরম্যাট! আবার চেষ্টা করো বা /skip করো।");
                
                ctx.session.button = { text: parts[0].trim(), url: parts[1].trim() };
                ctx.session.bcStep = 'CONFIRM';
                ctx.reply("সব ঠিক আছে? কন্ফার্ম করতে /confirm লিখো।");
            }
        });

        bot.command('skip', async (ctx) => {
            if (!ctx.session || !ctx.session.bcStep) return;
            if (ctx.session.bcStep === 'WAIT_BUTTON') {
                ctx.session.bcStep = 'CONFIRM';
                ctx.reply("বাটন ছাড়া পাঠাবে? কন্ফার্ম করতে /confirm লিখো।");
            }
        });

        bot.command('confirm', async (ctx) => {
            if (!ctx.session || ctx.session.bcStep !== 'CONFIRM') return;

            const sSnap = await subsRef.child(config.id).once('value');
            const users = sSnap.val();
            if (!users) return ctx.reply("কোনো ইউজার নেই!");

            let success = 0;
            const kb = ctx.session.button ? Markup.inlineKeyboard([[Markup.button.url(ctx.session.button.text, ctx.session.button.url)]]) : {};

            ctx.reply("⏳ পাঠানো হচ্ছে...");

            for (let uid in users) {
                try {
                    if (ctx.session.type === 'photo') {
                        await bot.telegram.sendPhoto(uid, ctx.session.fileId, { caption: ctx.session.text, ...kb });
                    } else {
                        await bot.telegram.sendMessage(uid, ctx.session.text, kb);
                    }
                    success++;
                } catch (e) { }
            }
            
            ctx.reply(`✅ ব্রডকাস্ট শেষ! সফল: ${success} জন।`);
            ctx.session = null; // Reset session
        });

        bot.launch().then(() => {
            console.log(`[ENGINE] @${config.botUsername} is running.`);
        }).catch(e => console.error(`[ENGINE] Failed @${config.botUsername}:`, e.message));

        activeBots[config.id] = bot;

    } catch (err) {
        console.error(`[ENGINE] Init error @${config.botUsername}:`, err.message);
    }
}

// --- 6. AUTO-RESUME ON SERVER START ---
const startup = async () => {
    console.log("🛠 Booting system...");
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
            console.log(`🛠 Resumed ${count} bots.`);
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
