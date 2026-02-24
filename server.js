/**
 * PROJECT: Bot Control Hub (SaaS) - Ultimate Fixed Version
 * AUTHOR: @lagatech
 * VERSION: 3.0.0 (Production Ready)
 * DATABASE: Firebase Realtime DB
 */

require('dotenv').config();
const { Telegraf, Markup, session } = require('telegraf');
const express = require('express');
const admin = require('firebase-admin');
const cors = require('cors');

// --- 1. INITIALIZATION & CONFIG ---
const app = express();
app.use(express.json());
app.use(cors());

const PORT = process.env.PORT || 3000;
const MAIN_BOT_TOKEN = process.env.MAIN_BOT_TOKEN;
const DATABASE_URL = process.env.DATABASE_URL || "https://bot-control-hub-eee53-default-rtdb.firebaseio.com";
const ADMIN_IDS = process.env.ADMIN_IDS ? process.env.ADMIN_IDS.split(',') : ['7605281774'];
const ADMIN_USERNAME = process.env.ADMIN_USERNAME || "lagatech"; // Admin Telegram Username without @

// Global Error Handlers
process.on('uncaughtException', (err) => console.error('CRITICAL ERROR (Uncaught):', err));
process.on('unhandledRejection', (reason, promise) => console.error('CRITICAL ERROR (Unhandled):', reason));

// --- 2. FIREBASE CONNECTION ---
let db, botsRef, usersRef, sessionsRef, subsRef;

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

    console.log("✅ Firebase Connected");
} catch (error) {
    console.error("❌ Firebase Init Failed:", error.message);
    process.exit(1);
}

// Memory storage for active bot instances
const activeBots = {};

// --- 3. MAIN CONTROLLER BOT ---
const mainBot = new Telegraf(MAIN_BOT_TOKEN);

mainBot.telegram.setMyCommands([
    { command: 'start', description: 'ড্যাশবোর্ড খুলুন' },
    { command: 'help', description: 'সাপোর্ট ও সাহায্য' }
]);

// Utility Keyboards
const mainKeyboard = Markup.keyboard([
    ['🤖 My Bots', '➕ New Bot'],
    ['📢 Broadcast', '📊 Statistics'],
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
        await sessionsRef.child(uid).remove(); // Clear session

        const welcomeMsg = 
            `👋 *স্বাগতম!* এটি বট কন্ট্রোল হাব।\n\n` +
            `এখান থেকে আপনি মাত্র কয়েক সেকেন্ডে টেলিগ্রাম বট তৈরি করতে পারবেন।\n\n` +
            `নিচের মেনু থেকে যেকোনো অপশন বেছে নিন 👇`;
        
        ctx.replyWithMarkdown(welcomeMsg, Markup.inlineKeyboard([
            [Markup.button.callback('🚀 শুরু করুন', 'start_menu')]
        ]));
    } catch (e) {
        console.error("Start Error:", e);
        ctx.reply("সিস্টেমে সাময়িক সমস্যা, কিছুক্ষণ পর আবার চেষ্টা করুন।");
    }
});

// --- HELP & CONTACT SUPPORT ---
mainBot.help(async (ctx) => {
    try {
        const supportMsg = 
            `🆘 *সাহায্য ও সাপোর্ট*\n\n` +
            `কোনো সমস্যা হলে বা কাস্টম বট তৈরি করতে চাইলে সরাসরি এডমিনের সাথে যোগাযোগ করুন।\n\n` +
            `🛠 অ্যাডমিন: @${ADMIN_USERNAME}`;
        
        ctx.replyWithMarkdown(supportMsg, Markup.inlineKeyboard([
            [Markup.button.url('💬 এডমিনের সাথে চ্যাট করুন', `https://t.me/${ADMIN_USERNAME}`)]
        ]));
    } catch (e) {
        console.error("Help Error:", e);
    }
});

// --- CALLBACK HANDLERS ---
mainBot.action('start_menu', async (ctx) => {
    try {
        ctx.editMessageReplyMarkup(undefined);
        ctx.reply('🏠 মেনু সিলেক্ট করুন:', mainKeyboard);
    } catch (e) { console.error(e); }
});

mainBot.action('cancel_op', async (ctx) => {
    try {
        const uid = ctx.from.id.toString();
        await sessionsRef.child(uid).remove();
        ctx.editMessageText('❌ অপারেশন বাতিল করা হয়েছে।');
        ctx.answerCbQuery('বাতিল হয়েছে');
    } catch (e) { console.error(e); }
});

// --- MENU: MY BOTS ---
mainBot.hears('🤖 My Bots', async (ctx) => {
    try {
        const snap = await botsRef.orderByChild('ownerId').equalTo(ctx.from.id).once('value');
        const bots = snap.val();

        if (!bots) return ctx.reply("☹️ আপনার কোনো বট নেই। নতুন বট বানাতে '➕ New Bot' এ ক্লিক করুন।");

        ctx.reply("📦 আপনার বটের তালিকা:");

        for (let key in bots) {
            const b = bots[key];
            const statusEmoji = b.status === 'RUN' ? '✅' : '🛑';
            ctx.replyWithMarkdown(
                `🤖 *বট:* ${b.botName}\n` +
                `🔗 *ইউজার:* @${b.botUsername}\n` +
                `📊 *স্ট্যাটাস:* ${statusEmoji}`,
                Markup.inlineKeyboard([
                    [Markup.button.callback('📝 এডিট', `edit_${b.id}`), Markup.button.callback('🛑 স্টপ/স্টার্ট', `toggle_${b.id}`)],
                    [Markup.button.callback('🗑 ডিলিট', `delete_${b.id}`)]
                ])
            );
        }
    } catch (e) {
        console.error(e);
        ctx.reply("বটের তালিকা লোড করতে সমস্যা হয়েছে।");
    }
});

// --- MENU: NEW BOT WIZARD ---
mainBot.hears('➕ New Bot', async (ctx) => {
    try {
        const uid = ctx.from.id.toString();
        await sessionsRef.child(uid).set({ step: 'NEW_BOT_TOKEN', startTime: Date.now() });
        
        ctx.replyWithMarkdown(
            `✨ *ধাপ ১: বট টোকেন*\n\n` +
            `@BotFather থেকে আপনার বটের API Token নিয়ে এখানে পাঠান।\n\n` +
            `_⚠️ টোকেন কারো সাথে শেয়ার করবেন না!_`,
            Markup.inlineKeyboard([[Markup.button.callback('❌ বাতিল', 'cancel_op')]])
        );
    } catch (e) { console.error(e); }
});

// --- MENU: BROADCAST SELECT BOT ---
mainBot.hears('📢 Broadcast', async (ctx) => {
    try {
        const botsSnap = await botsRef.orderByChild('ownerId').equalTo(ctx.from.id).once('value');
        if (!botsSnap.exists()) return ctx.reply("☹️ আপনার কোনো বট নেই।");

        const bots = botsSnap.val();
        const btns = [];
        for (let key in bots) {
            btns.push([Markup.button.callback(`🤖 ${bots[key].botName}`, `bc_select_${bots[key].id}`)]);
        }
        
        ctx.reply("কোন বটে ব্রডকাস্ট পাঠাবেন?", Markup.inlineKeyboard(btns));
    } catch (e) { console.error(e); }
});

// --- MENU: STATISTICS ---
mainBot.hears('📊 Statistics', async (ctx) => {
    try {
        const botsSnap = await botsRef.orderByChild('ownerId').equalTo(ctx.from.id).once('value');
        const bots = botsSnap.val();
        
        if (!bots) return ctx.reply("তোমার কোনো একটিভ বট নেই।");

        let totalSubs = 0;
        let botCount = Object.keys(bots).length;

        for (let key in bots) {
            const sSnap = await subsRef.child(bots[key].id).once('value');
            if (sSnap.exists()) totalSubs += Object.keys(sSnap.val()).length;
        }

        ctx.replyWithMarkdown(
            `📊 *আপনার পরিসংখ্যান:*\n\n` +
            `🤖 মোট বট: *${botCount}* টি\n` +
            `👥 মোট ইউজার: *${totalSubs}* জন`
        );
    } catch (e) { console.error(e); ctx.reply("স্ট্যাটস লোড করতে সমস্যা হয়েছে।"); }
});

// --- MENU: ADMIN PANEL ---
mainBot.hears('🛠 Admin Panel', async (ctx) => {
    if (!ADMIN_IDS.includes(ctx.from.id.toString())) {
        return ctx.reply("🚫 এই প্যানেলটি শুধুমাত্র এডমিন দেখতে পারবে।");
    }
    ctx.replyWithMarkdown("🛠 *এডমিন প্যানেলে স্বাগতম বস!*", 
        Markup.inlineKeyboard([
            [Markup.button.callback('📊 সিস্টেম স্ট্যাটাস', 'admin_stats')],
            [Markup.button.callback('📢 গ্লোবাল ব্রডকাস্ট', 'admin_gb')]
        ])
    );
});

mainBot.action('admin_stats', async (ctx) => {
    try {
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
            `📊 *সিস্টেম রিপোর্ট:*\n\n` +
            `👥 হাব ইউজার: ${uSnap.exists() ? Object.keys(uSnap.val()).length : 0}\n` +
            `🤖 মোট ক্রিয়েটেড বট: ${bSnap.exists() ? Object.keys(bSnap.val()).length : 0}\n` +
            `🏴 মোট ক্লায়েন্ট ইউজার: ${totalClientUsers}`,
            { parse_mode: 'Markdown' }
        );
        ctx.answerCbQuery();
    } catch(e) { console.error(e); }
});

mainBot.action('admin_gb', async (ctx) => {
    await sessionsRef.child(ctx.from.id.toString()).set({ step: 'ADMIN_BC_WAIT_CONTENT' });
    ctx.editMessageText("📢 মেইন ব্রডকাস্ট মোড।\n\nছবি বা টেক্সট পাঠান।");
    ctx.answerCbQuery();
});


// --- DYNAMIC HANDLERS (WIZARD ENGINE) ---

// Text Handler
mainBot.on('text', async (ctx) => {
    const uid = ctx.from.id.toString();
    const snap = await sessionsRef.child(uid).once('value');
    if (!snap.exists()) return;

    const session = snap.val();
    const input = ctx.message.text.trim();

    // --- NEW BOT CREATION STEPS ---
    if (session.step === 'NEW_BOT_TOKEN') {
        try {
            ctx.reply("⏳ টোকেন যাচাই করা হচ্ছে...");
            const tempBot = new Telegraf(input);
            const info = await tempBot.telegram.getMe();

            await sessionsRef.child(uid).update({ 
                step: 'NEW_BOT_IMAGE', 
                token: input, 
                botName: info.first_name, 
                botUsername: info.username 
            });

            ctx.replyWithMarkdown(
                `✅ বট কানেক্ট হয়েছে: *@${info.username}*\n\n` +
                `✨ *ধাপ ২: ওয়েলকাম ছবি*\n` +
                `বট স্টার্ট করলে কোন ছবি দেখাবে? সেটি পাঠান।\n\n` +
                `ছবি না চাইলে /skip লিখুন।`,
                Markup.inlineKeyboard([[Markup.button.callback('❌ বাতিল', 'cancel_op')]])
            );
        } catch (e) {
            ctx.reply("❌ ভুল টোকেন! আবার সঠিক টোকেন পাঠান।");
        }
    } 
    else if (session.step === 'NEW_BOT_TEXT') {
        await sessionsRef.child(uid).update({ step: 'NEW_BOT_BUTTONS', welcomeText: input });
        ctx.replyWithMarkdown(
            `✨ *ধাপ ৪: বাটন সেটআপ*\n\n` +
            `কয়টি বাটন রাখবেন? (০ থেকে ৫ এর মধ্যে সংখ্যা লিখুন)\n` +
            `বাটন না চাইলে ০ লিখুন।`
        );
    }
    else if (session.step === 'NEW_BOT_BUTTONS') {
        const count = parseInt(input);
        if (isNaN(count) || count < 0 || count > 5) return ctx.reply("০ থেকে ৫ এর মধ্যে একটি সংখ্যা লিখুন।");
        
        if (count === 0) {
            await finalizeBotCreation(ctx, session, []);
        } else {
            await sessionsRef.child(uid).update({ step: 'NEW_BOT_BTN_DATA', targetBtns: count, currentBtns: [] });
            ctx.replyWithMarkdown(
                `বাটন ১ এর তথ্য দিন:\n\n*ফরমেট:* নাম | লিঙ্ক\n*উদাহরণ:* Join Channel | https://t.me/lagatech`
            );
        }
    }
    else if (session.step === 'NEW_BOT_BTN_DATA') {
        const parts = input.split('|');
        if (parts.length < 2) return ctx.reply("❌ ভুল ফরম্যাট! (নাম | লিঙ্ক) এভাবে লিখুন।");

        let btnList = session.currentBtns || [];
        btnList.push({ text: parts[0].trim(), url: parts[1].trim() });

        if (btnList.length >= session.targetBtns) {
            await finalizeBotCreation(ctx, session, btnList);
        } else {
            await sessionsRef.child(uid).update({ currentBtns: btnList });
            ctx.reply(`বাটন ${btnList.length + 1} এর তথ্য দিন (নাম | লিঙ্ক)`);
        }
    }
    
    // --- BROADCAST FLOW (MAIN BOT & CLIENT BOT) ---
    else if (session.step === 'BC_WAIT_TEXT') {
        if (!input) return ctx.reply("টেক্সট খালি রাখা যাবে না। অথবা /skip করুন।");
        await sessionsRef.child(uid).update({ step: 'BC_WAIT_BUTTON', bcText: input });
        ctx.reply("✅ টেক্সট সেভ হয়েছে।\n\nএখন বাটন দিন (নাম | লিঙ্ক) অথবা /skip করুন।");
    }
    else if (session.step === 'BC_WAIT_BUTTON') {
        const parts = input.split('|');
        if (parts.length < 2) return ctx.reply("❌ ভুল ফরম্যাট! (নাম | লিঙ্ক) এভাবে লিখুন।");
        
        await sessionsRef.child(uid).update({ step: 'BC_CONFIRM', bcButton: { text: parts[0].trim(), url: parts[1].trim() } });
        ctx.replyWithMarkdown(
            `✅ বাটন যোগ হয়েছে।\n\n` +
            `সব তথ্য ঠিক আছে? ব্রডকাস্ট পাঠাতে /confirm লিখুন।`,
            Markup.inlineKeyboard([[Markup.button.callback('✅ কনফার্ম', 'bc_send')]]),
        );
    }
    // Global Broadcast Admin
    else if (session.step === 'ADMIN_BC_WAIT_TEXT') {
        await sessionsRef.child(uid).update({ step: 'ADMIN_BC_WAIT_BUTTON', bcText: input });
        ctx.reply("✅ টেক্সট সেভ হয়েছে। বাটন দিন (নাম | লিঙ্ক) অথবা /skip করুন।");
    }
    else if (session.step === 'ADMIN_BC_WAIT_BUTTON') {
        const parts = input.split('|');
        if (parts.length < 2) return ctx.reply("❌ ভুল ফরম্যাট!");
        await sessionsRef.child(uid).update({ step: 'ADMIN_BC_CONFIRM', bcButton: { text: parts[0].trim(), url: parts[1].trim() } });
        ctx.reply("সব ঠিক আছে? /confirm লিখুন।");
    }
});

// Photo Handler
mainBot.on('photo', async (ctx) => {
    const uid = ctx.from.id.toString();
    const snap = await sessionsRef.child(uid).once('value');
    if (!snap.exists()) return;
    const session = snap.val();

    // New Bot Setup
    if (session.step === 'NEW_BOT_IMAGE') {
        const fileId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
        await sessionsRef.child(uid).update({ step: 'NEW_BOT_TEXT', welcomeImage: fileId });
        ctx.reply("🖼 ছবি সেট হয়েছে!\n\n✨ ধাপ ৩: ওয়েলকাম মেসেজ লিখুন।");
    } 
    // Broadcast Setup
    else if (session.step === 'BC_WAIT_CONTENT') {
        const fileId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
        await sessionsRef.child(uid).update({ step: 'BC_WAIT_TEXT', bcImage: fileId });
        ctx.reply("🖼 ছবি পেয়েছি। এখন ক্যাপশন/টেক্সট লিখুন অথবা /skip করুন।");
    }
    else if (session.step === 'ADMIN_BC_WAIT_CONTENT') {
        const fileId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
        await sessionsRef.child(uid).update({ step: 'ADMIN_BC_WAIT_TEXT', bcImage: fileId });
        ctx.reply("খুব ভালো। এখন ক্যাপশন লিখুন বা /skip করুন।");
    }
});

// Skip Handler
mainBot.command('skip', async (ctx) => {
    const uid = ctx.from.id.toString();
    const snap = await sessionsRef.child(uid).once('value');
    if (!snap.exists()) return;
    const session = snap.val();

    if (session.step === 'NEW_BOT_IMAGE') {
        await sessionsRef.child(uid).update({ step: 'NEW_BOT_TEXT', welcomeImage: null });
        ctx.reply("👌 ছবি ছাড়াই চলবে।\n\n✨ ধাপ ৩: ওয়েলকাম মেসেজ লিখুন।");
    }
    else if (session.step === 'BC_WAIT_TEXT') {
        await sessionsRef.child(uid).update({ step: 'BC_WAIT_BUTTON', bcText: null });
        ctx.reply("👌 টেক্সট ছাড়াই চলবে। এখন বাটন দিন বা /skip করুন।");
    }
    else if (session.step === 'BC_WAIT_BUTTON') {
        await sessionsRef.child(uid).update({ step: 'BC_CONFIRM', bcButton: null });
        ctx.replyWithMarkdown(
            `সব ঠিক আছে? ব্রডকাস্ট পাঠাতে /confirm লিখুন।`,
            Markup.inlineKeyboard([[Markup.button.callback('✅ কনফার্ম', 'bc_send')]])
        );
    }
    else if (session.step === 'ADMIN_BC_WAIT_TEXT') {
        await sessionsRef.child(uid).update({ step: 'ADMIN_BC_WAIT_BUTTON', bcText: null });
        ctx.reply("টেক্সট স্কিপ করা হলো। বাটন দিন বা /skip করুন।");
    }
    else if (session.step === 'ADMIN_BC_WAIT_BUTTON') {
        await sessionsRef.child(uid).update({ step: 'ADMIN_BC_CONFIRM', bcButton: null });
        ctx.reply("সব ঠিক আছে? /confirm লিখুন।");
    }
});

// Confirm Handler
mainBot.command('confirm', async (ctx) => {
    const uid = ctx.from.id.toString();
    const snap = await sessionsRef.child(uid).once('value');
    if (!snap.exists()) return;
    const session = snap.val();

    if (session.step === 'BC_CONFIRM') {
        await performBroadcast(ctx, session);
    }
    else if (session.step === 'ADMIN_BC_CONFIRM') {
        await performAdminBroadcast(ctx, session);
    }
});

// --- CALLBACK ACTIONS FOR BUTTONS ---
mainBot.action(/bc_select_(.+)/, async (ctx) => {
    const bid = ctx.match[1];
    const uid = ctx.from.id.toString();
    
    // Verify ownership
    const botSnap = await botsRef.child(bid).once('value');
    if (!botSnap.exists() || botSnap.val().ownerId !== uid) return ctx.answerCbQuery("অনুমতি নেই!");
    
    await sessionsRef.child(uid).set({ step: 'BC_WAIT_CONTENT', botId: bid });
    ctx.editMessageText(
        `📢 *ব্রডকাস্ট সেটআপ*\n\n` +
        `ধাপ ১: এখন যা পাঠাবেন (ছবি বা টেক্সট) তা পাঠান।`,
        { parse_mode: 'Markdown' }
    );
});

mainBot.action('bc_send', async (ctx) => {
    const uid = ctx.from.id.toString();
    const snap = await sessionsRef.child(uid).once('value');
    if (!snap.exists() || snap.val().step !== 'BC_CONFIRM') return;
    await performBroadcast(ctx, snap.val());
});

mainBot.action(/edit_(.+)/, async (ctx) => {
    const bid = ctx.match[1];
    await sessionsRef.child(ctx.from.id.toString()).set({ step: 'EDIT_WAIT_TEXT', editingBotId: bid });
    ctx.answerCbQuery("এডিট মোড অন!");
    ctx.reply("নতুন ওয়েলকাম মেসেজ লিখুন। ছবি পরিবর্তন করতে চাইলে মেসেজের সাথে ছবি পাঠান।");
});

mainBot.action(/toggle_(.+)/, async (ctx) => {
    const bid = ctx.match[1];
    const botSnap = await botsRef.child(bid).once('value');
    const botData = botSnap.val();
    const newStatus = botData.status === 'RUN' ? 'STOP' : 'RUN';
    
    await botsRef.child(bid).update({ status: newStatus });
    
    if (newStatus === 'STOP' && activeBots[bid]) {
        activeBots[bid].stop();
        delete activeBots[bid];
    } else if (newStatus === 'RUN') {
        initiateClientBot(botData);
    }
    
    ctx.answerCbQuery(`বট স্ট্যাটাস: ${newStatus}`);
    ctx.editMessageReplyMarkup(undefined); // Refresh UI logic omitted for brevity, simple alert is enough
});

mainBot.action(/delete_(.+)/, async (ctx) => {
    const bid = ctx.match[1];
    if (activeBots[bid]) {
        activeBots[bid].stop();
        delete activeBots[bid];
    }
    await botsRef.child(bid).remove();
    await subsRef.child(bid).remove();
    ctx.answerCbQuery("ডিলিট হয়েছে!");
    ctx.deleteMessage();
});

// --- CORE FUNCTIONS ---

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
            welcomeText: session.welcomeText || "Welcome!",
            buttons: buttons,
            status: 'RUN',
            createdAt: Date.now()
        };

        await botsRef.child(botId).set(botData);
        await sessionsRef.child(ctx.from.id.toString()).remove();
        
        ctx.replyWithMarkdown(`🎉 *সফল!*\n\nআপনার বট *@${session.botUsername}* এখন লাইভ!`);
        
        initiateClientBot(botData);
    } catch (e) {
        console.error(e);
        ctx.reply("❌ বট তৈরি করতে সমস্যা হয়েছে।");
    }
}

async function performBroadcast(ctx, session) {
    const botId = session.botId;
    ctx.reply("⏳ ব্রডকাস্ট শুরু হচ্ছে...");
    
    const botRef = botsRef.child(botId);
    const botSnap = await botRef.once('value');
    const botInstance = activeBots[botId];
    
    if (!botInstance || !botSnap.exists()) return ctx.reply("বট চলছে না বা খুঁজে পাওয়া যায়নি।");

    const usersSnap = await subsRef.child(botId).once('value');
    const users = usersSnap.val();
    if (!users) return ctx.reply("কোনো ইউজার নেই।");

    let success = 0;
    const kb = session.bcButton ? Markup.inlineKeyboard([[Markup.button.url(session.bcButton.text, session.bcButton.url)]]) : {};
    
    // Optional parameters handling
    const image = session.bcImage;
    const text = session.bcText || " "; // Empty string causes error in some cases

    for (let uid in users) {
        try {
            if (image) {
                await botInstance.telegram.sendPhoto(uid, image, { caption: text, parse_mode: 'Markdown', ...kb });
            } else if (text && text !== " ") {
                await botInstance.telegram.sendMessage(uid, text, { parse_mode: 'Markdown', ...kb });
            }
            success++;
        } catch (e) { /* Ignore blocked users */ }
    }
    
    await sessionsRef.child(ctx.from.id.toString()).remove();
    ctx.reply(`✅ ব্রডকাস্ট শেষ!\nসফল: ${success} জন।`);
}

async function performAdminBroadcast(ctx, session) {
    ctx.reply("📢 গ্লোবাল ব্রডকাস্ট শুরু হচ্ছে...");
    const uSnap = await usersRef.once('value');
    const users = uSnap.val();
    
    const kb = session.bcButton ? Markup.inlineKeyboard([[Markup.button.url(session.bcButton.text, session.bcButton.url)]]) : {};
    let success = 0;

    for (let uid in users) {
        try {
            if (session.bcImage) {
                await mainBot.telegram.sendPhoto(uid, session.bcImage, { caption: session.bcText || " ", ...kb });
            } else {
                await mainBot.telegram.sendMessage(uid, session.bcText || " ", kb);
            }
            success++;
        } catch (e) {}
    }
    await sessionsRef.child(ctx.from.id.toString()).remove();
    ctx.reply(`📢 গ্লোবাল ব্রডকাস্ট শেষ। সফল: ${success}`);
}

// --- 5. CLIENT BOT ENGINE ---
function initiateClientBot(config) {
    if (activeBots[config.id]) return; // Already running

    try {
        const bot = new Telegraf(config.token);
        
        bot.start(async (ctx) => {
            try {
                // Save Subscriber
                await subsRef.child(config.id).child(ctx.from.id.toString()).update({
                    n: ctx.from.first_name,
                    u: ctx.from.username || "N/A",
                    t: Date.now()
                });

                // Prepare Buttons
                let inlineKeyboard = [];
                if (config.buttons && config.buttons.length > 0) {
                    config.buttons.forEach(btn => {
                        inlineKeyboard.push([Markup.button.url(btn.text, btn.url)]);
                    });
                }
                
                // Send Welcome - CRITICAL FIX
                const options = { parse_mode: 'Markdown' };
                if (inlineKeyboard.length > 0) options.reply_markup = Markup.inlineKeyboard(inlineKeyboard).reply_markup;

                if (config.welcomeImage) {
                    await ctx.replyWithPhoto(config.welcomeImage, { 
                        caption: config.welcomeText || " ", 
                        ...options 
                    });
                } else {
                    await ctx.reply(config.welcomeText || "Welcome!", options);
                }
            } catch (err) {
                console.error(`Client Bot @${config.botUsername} Start Error:`, err.message);
            }
        });

        bot.launch().then(() => {
            console.log(`[ENGINE] 🟢 @${config.botUsername} is running.`);
            activeBots[config.id] = bot;
        }).catch(e => console.error(`[ENGINE] 🔴 Failed @${config.botUsername}:`, e.message));

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

// --- WEB SERVER ---
app.get('/', (req, res) => {
    res.status(200).json({
        status: "Online",
        active_instances: Object.keys(activeBots).length,
        timestamp: new Date().toISOString()
    });
});

app.listen(PORT, () => console.log(`⚡ API running on port ${PORT}`));

// Graceful Shutdown
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
