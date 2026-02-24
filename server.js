/**
 * PROJECT: Bot Control Hub (SaaS) - Ultimate Fixed Version
 * AUTHOR: @lagatech
 * VERSION: 3.0.0 (Production Ready)
 * DATABASE: Firebase Realtime DB
 */

require('dotenv').config();
const { Telegraf, Markup, session, Scenes } = require('telegraf');
const express = require('express');
const admin = require('firebase-admin');
const cors = require('cors');

// --- 1. INITIALIZATION & CONFIGURATION ---
const app = express();
app.use(express.json());
app.use(cors());

const PORT = process.env.PORT || 3000;
const MAIN_BOT_TOKEN = process.env.MAIN_BOT_TOKEN;
const DATABASE_URL = process.env.DATABASE_URL || "https://bot-control-hub-eee53-default-rtdb.firebaseio.com";
const ADMIN_IDS = ['7605281774']; // Replace with your Telegram ID

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
    
    // Check if app is already initialized to prevent double initialization error
    if (admin.apps.length === 0) {
        admin.initializeApp({
            credential: admin.credential.cert(serviceAccount),
            databaseURL: DATABASE_URL
        });
    }

    db = admin.database();
    botsRef = db.ref("bots");
    usersRef = db.ref("users");
    sessionsRef = db.ref("sessions");
    subsRef = db.ref("subscribers");

    console.log("✅ Firebase Admin SDK Connected Successfully");
} catch (error) {
    console.error("❌ Firebase Connection Failed:", error.message);
    process.exit(1);
}

// Memory storage for active client bot instances
const activeBots = {};

// --- 3. MAIN CONTROLLER BOT SETUP ---
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
        
        // Save/Update User Info
        await usersRef.child(uid).update({
            username: ctx.from.username || "N/A",
            name: ctx.from.first_name,
            lastSeen: Date.now()
        });

        // Clear previous temporary sessions
        await sessionsRef.child(uid).remove();

        const welcomeMsg = 
            `👋 *হ্যালো বন্ধু!* স্বাগতম বট কন্ট্রোল হাবে!\n\n` +
            `এখানে তুমি নিজের খুব সহজেই টেলিগ্রাম বট বানাতে পারবে। একদম পানির মতো সহজ! 😄\n\n` +
            `নিচের বাটনে ক্লিক করে শুরু করো তো! 👇`;
        
        ctx.replyWithMarkdown(welcomeMsg, Markup.inlineKeyboard([
            [Markup.button.callback('🚀 Get Started', 'start_menu')]
        ]));
    } catch (e) {
        console.error("MainBot Start Error:", e);
        ctx.reply("⚠️ কিছু একটা সমস্যা হয়েছে, আবার চেষ্টা করো।");
    }
});

// --- HELP COMMAND (Support Only) ---
mainBot.help((ctx) => {
    ctx.reply(
        `❓ *সাহায্য চাই?*\n\n` +
        `বট বানাতে গেলে কোনো সমস্যা হলে বা কোনো বাগ পেলে এডমিনের সাথে যোগাযোগ করো।\n\n` +
        `👨‍💻 *এডমিন:* @lagatech`,
        Markup.inlineKeyboard([
            [Markup.button.url('💬 Message Admin', 'https://t.me/lagatech')]
        ])
    );
});

// --- CALLBACK HANDLERS ---
mainBot.action('start_menu', async (ctx) => {
    try {
        await ctx.answerCbQuery();
        await ctx.editMessageReplyMarkup(undefined);
        ctx.reply('🏠 মেনু থেকে যা ইচ্ছে তা করো!', mainKeyboard);
    } catch (e) {
        console.error(e);
    }
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
            const statusEmoji = b.status === 'RUN' ? '✅ চলছে' : '❌ বন্ধ';
            
            ctx.reply(
                `🤖 *বট:* ${b.botName}\n` +
                `🔗 *ইউজার:* @${b.botUsername}\n` +
                `📊 *স্ট্যাটাস:* ${statusEmoji}`,
                Markup.inlineKeyboard([
                    [Markup.button.callback('📝 Edit Welcome', `edit_${b.id}`)],
                    [Markup.button.callback('🗑 Delete Bot', `delete_${b.id}`)]
                ])
            );
        }
    } catch (e) {
        console.error("My Bots Error:", e);
        ctx.reply("বটের তালিকা আনতে সমস্যা হলো!");
    }
});

// 2. NEW BOT WIZARD (Step-by-Step)
mainBot.hears('➕ New Bot', async (ctx) => {
    const uid = ctx.from.id.toString();
    await sessionsRef.child(uid).set({ step: 'NEW_BOT_TOKEN', startTime: Date.now() });
    
    ctx.reply(
        `✨ *ধাপ ১: বট টোকেন*\n\n` +
        `@BotFather থেকে তোমার বটের API Token টা নিয়ে এখানে পাঠাও।\n` +
        `(টোকেনটা কাউকে দিবে না কিন্তু! 🤫)`,
        { parse_mode: 'Markdown' }
    );
});

// 3. BROADCAST SETUP (Select Bot)
mainBot.hears('📢 Broadcast Setup', async (ctx) => {
    try {
        const botsSnap = await botsRef.orderByChild('ownerId').equalTo(ctx.from.id).once('value');
        if (!botsSnap.exists()) return ctx.reply("☹️ তুমি কোনো বট বানাওনি!");

        const bots = botsSnap.val();
        const btns = [];
        for (let key in bots) {
            btns.push([Markup.button.callback(`🤖 ${bots[key].botName}`, `bc_select_${bots[key].id}`)]);
        }
        
        ctx.reply("📢 কোন বটে ব্রডকাস্ট পাঠাতে চাও?", Markup.inlineKeyboard(btns));
    } catch (e) {
        console.error(e);
        ctx.reply("সেটআপে সমস্যা হচ্ছে।");
    }
});

// 4. STATISTICS
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

        ctx.reply(
            `📊 *তোমার হিসাব-নিকাশ:*\n\n` +
            `🤖 মোট বট: ${botCount} টি\n` +
            `👥 মোট ইউজার: ${totalSubs} জন\n\n` +
            `খুব ভালো! আরো বট বানাও! 😄`,
            { parse_mode: 'Markdown' }
        );
    } catch (e) {
        console.error(e);
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

        await ctx.editMessageText(
            `📊 *সিস্টেম ওভারভিউ:*\n\n` +
            `👥 হাব ইউজার: ${uSnap.exists() ? Object.keys(uSnap.val()).length : 0}\n` +
            `🤖 মোট ক্রিয়েটেড বট: ${bSnap.exists() ? Object.keys(bSnap.val()).length : 0}\n` +
            `🏴 মোট ক্লায়েন্ট ইউজার: ${totalClientUsers}`,
            { parse_mode: 'Markdown' }
        );
        await ctx.answerCbQuery();
    } catch (e) {
        console.error(e);
    }
});

mainBot.action('admin_broadcast', async (ctx) => {
    try {
        await sessionsRef.child(ctx.from.id.toString()).set({ step: 'ADMIN_BC_START' });
        await ctx.editMessageText("📢 বস, মেইন ব্রডকাস্ট শুরু করো। প্রথমে ছবি পাঠাও, অথবা টেক্সট পাঠাতে চাইলে /skip করো।");
        await ctx.answerCbQuery();
    } catch(e) {
        console.error(e);
    }
});

// --- INLINE ACTION HANDLERS (EDIT/DELETE) ---
mainBot.action(/edit_(.+)/, async (ctx) => {
    try {
        const bid = ctx.match[1];
        await sessionsRef.child(ctx.from.id.toString()).set({ step: 'EDIT_TEXT', editingBotId: bid });
        await ctx.answerCbQuery("এডিট মোড অন!");
        ctx.reply("এডিট করার জন্য নতুন ওয়েলকাম টেক্সট পাঠান। ছবি আগেরটাই থাকবে।");
    } catch(e) {
        console.error(e);
    }
});

mainBot.action(/delete_(.+)/, async (ctx) => {
    try {
        const bid = ctx.match[1];
        
        // Stop bot instance if running
        if (activeBots[bid]) {
            try { activeBots[bid].stop(); } catch (e) {}
            delete activeBots[bid];
        }

        // Remove from Database
        await botsRef.child(bid).remove();
        await subsRef.child(bid).remove();

        await ctx.deleteMessage();
        await ctx.answerCbQuery("বটটি ডিলিট করা হয়েছে।");
    } catch(e) {
        console.error(e);
    }
});

// Broadcast Bot Selection Handler
mainBot.action(/bc_select_(.+)/, async (ctx) => {
    try {
        const bid = ctx.match[1];
        const uid = ctx.from.id.toString();
        
        await sessionsRef.child(uid).set({ step: 'CLIENT_BC_IMAGE', botId: bid });
        
        await ctx.editMessageText(
            `📢 *ব্রডকাস্ট সেটআপ*\n\n` +
            `ধাপ ১: ছবি পাঠাও (Optional)\n` +
            `ছবি ছাড়া পাঠাতে চাইলে /skip লিখো।`,
            { parse_mode: 'Markdown' }
        );
        await ctx.answerCbQuery();
    } catch(e) {
        console.error(e);
    }
});

// --- DYNAMIC MESSAGE HANDLER (WIZARD ENGINE) ---
mainBot.on(['text', 'photo'], async (ctx) => {
    const uid = ctx.from.id.toString();
    
    // Safety check: Ignore if no session
    const snap = await sessionsRef.child(uid).once('value');
    if (!snap.exists()) return;
    
    const session = snap.val();
    const step = session.step;

    // ---------------- NEW BOT CREATION ----------------
    if (step === 'NEW_BOT_TOKEN') {
        if (!ctx.message.text) return ctx.reply("টোকেন টেক্সট আকারে পাঠাও!");
        
        const token = ctx.message.text.trim();
        ctx.reply("⏳ টোকেন যাচাই করা হচ্ছে...");
        
        try {
            const tempBot = new Telegraf(token);
            const info = await tempBot.telegram.getMe();

            await sessionsRef.child(uid).update({ 
                step: 'NEW_BOT_IMAGE', 
                token: token, 
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
    else if (step === 'NEW_BOT_IMAGE') {
        let fileId = null;
        if (ctx.message.photo) {
            fileId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
        } else if (ctx.message.text && ctx.message.text === '/skip') {
            fileId = null;
        } else {
            return ctx.reply("ছবি পাঠাও অথবা /skip করো।");
        }

        await sessionsRef.child(uid).update({ step: 'NEW_BOT_TEXT', welcomeImage: fileId });
        
        ctx.reply(
            "✨ *ধাপ ৩: ওয়েলকাম মেসেজ*\n\n" +
            "বট স্টার্ট করলে কি লেখা দেখাবে? সেটি লিখুন।", 
            { parse_mode: 'Markdown' }
        );
    }
    else if (step === 'NEW_BOT_TEXT') {
        const text = ctx.message.text;
        if (!text) return ctx.reply("টেক্সট লিখতে হবে!");
        
        await sessionsRef.child(uid).update({ step: 'NEW_BOT_BUTTONS', welcomeText: text });
        ctx.reply("✨ *ধাপ ৪: বাটন*\n\nবাটন দিতে চাইলে ফরম্যাটে লিখো: `নাম | লিঙ্ক`\nবাটন লাগবে না এমন থাকলে /skip করো।", { parse_mode: 'Markdown' });
    }
    else if (step === 'NEW_BOT_BUTTONS') {
        let buttons = [];
        if (ctx.message.text && ctx.message.text !== '/skip') {
            const parts = ctx.message.text.split('|');
            if (parts.length === 2) {
                buttons.push([{ text: parts[0].trim(), url: parts[1].trim() }]);
            } else {
                return ctx.reply("ভুল ফরম্যাট! ঠিক করে লিখো অথবা /skip করো।");
            }
        }
        
        await finalizeBotCreation(ctx, session, buttons);
    }
    
    // ---------------- EDIT BOT ----------------
    else if (step === 'EDIT_TEXT') {
        const bid = session.editingBotId;
        const text = ctx.message.text;
        
        await botsRef.child(bid).update({ welcomeText: text });
        await sessionsRef.child(uid).remove();
        
        ctx.reply("✅ ওয়েলকাম টেক্সট আপডেট হয়েছে!");
    }

    // ---------------- CLIENT BOT BROADCAST ----------------
    else if (step === 'CLIENT_BC_IMAGE') {
        let fileId = null;
        if (ctx.message.photo) {
            fileId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
        } else if (ctx.message.text && ctx.message.text === '/skip') {
            fileId = null;
        } else {
            // Maybe user sent text instead of image? Ask clarification or assume skip
            return ctx.reply("ছবি পাঠাও অথবা /skip করো।");
        }

        await sessionsRef.child(uid).update({ step: 'CLIENT_BC_TEXT', bcImage: fileId });
        ctx.reply("📢 ধাপ ২: এখন টেক্সট লিখো (Optional)। টেক্সট ছাড়া পাঠাতে চাইলে /skip করো।");
    }
    else if (step === 'CLIENT_BC_TEXT') {
        let text = "";
        if (ctx.message.text && ctx.message.text !== '/skip') {
            text = ctx.message.text;
        }

        await sessionsRef.child(uid).update({ step: 'CLIENT_BC_BUTTON', bcText: text });
        ctx.reply("📢 ধাপ ৩: বাটন দিতে চাইলে `নাম | লিঙ্ক` লিখো, অথবা /skip করো।", { parse_mode: 'Markdown' });
    }
    else if (step === 'CLIENT_BC_BUTTON') {
        let button = null;
        if (ctx.message.text && ctx.message.text !== '/skip') {
            const parts = ctx.message.text.split('|');
            if (parts.length === 2) {
                button = { text: parts[0].trim(), url: parts[1].trim() };
            } else {
                return ctx.reply("ভুল ফরম্যাট! আবার লিখো বা /skip করো।");
            }
        }

        await sessionsRef.child(uid).update({ step: 'CLIENT_BC_CONFIRM', bcButton: button });
        
        // Preview Message
        let msg = "👀 *প্রিভিউ:*\n\n";
        if (session.bcImage) msg += "🖼 ছবি আছে\n";
        if (session.bcText) msg += `📝 টেক্সট: ${session.bcText}\n`;
        if (button) msg += `🔲 বাটন: ${button.text}\n`;
        
        ctx.reply(msg + "\n\nকনফার্ম করতে /confirm লিখো, বা বাতিল করতে /cancel লিখো।", { parse_mode: 'Markdown' });
    }
    else if (step === 'CLIENT_BC_CONFIRM') {
        if (ctx.message.text === '/confirm') {
            await performClientBroadcast(ctx, session);
        } else if (ctx.message.text === '/cancel') {
            await sessionsRef.child(uid).remove();
            ctx.reply("❌ ব্রডকাস্ট বাতিল করা হয়েছে।");
        } else {
            ctx.reply("কনফার্ম করতে /confirm লিখো, বাতিল করতে /cancel লিখো।");
        }
    }

    // ---------------- ADMIN MAIN BROADCAST ----------------
    else if (step === 'ADMIN_BC_START') {
        let fileId = null;
        let text = "";
        
        if (ctx.message.photo) {
            fileId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
            text = ctx.message.caption || "";
        } else if (ctx.message.text && ctx.message.text !== '/skip') {
            text = ctx.message.text;
        }

        await sessionsRef.child(uid).update({ step: 'ADMIN_BC_CONFIRM', bcImage: fileId, bcText: text });
        ctx.reply("📢 কনফার্ম করতে /confirm লিখো, বা বাতিল করতে /cancel লিখো।");
    }
    else if (step === 'ADMIN_BC_CONFIRM') {
        if (ctx.message.text === '/confirm') {
            await performMainBroadcast(ctx, session);
        } else if (ctx.message.text === '/cancel') {
            await sessionsRef.child(uid).remove();
            ctx.reply("❌ ব্রডকাস্ট বাতিল করা হয়েছে।");
        }
    }
});

// --- HELPER FUNCTIONS ---

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
            createdAt: Date.now()
        };

        await botsRef.child(botId).set(botData);
        await sessionsRef.child(ctx.from.id.toString()).remove();
        
        ctx.reply(`🎉 *অভিনন্দন!*\n\nতোমার বট *@${session.botUsername}* এখন লাইভ! আয় বস আয় দেখে যাই! 😍`, { parse_mode: 'Markdown' });
        
        initiateClientBot(botData);
    } catch (e) {
        console.error("Bot Creation Error:", e);
        ctx.reply("❌ সেভ করার সময় সমস্যা হয়েছে।");
    }
}

async function performClientBroadcast(ctx, session) {
    const uid = ctx.from.id.toString();
    const botId = session.botId;
    
    ctx.reply("⏳ ব্রডকাস্ট শুরু হচ্ছে...");
    
    const sSnap = await subsRef.child(botId).once('value');
    const users = sSnap.val();
    
    if (!users) {
        await sessionsRef.child(uid).remove();
        return ctx.reply("কোনো সাবস্ক্রাইবার নেই!");
    }

    let success = 0;
    let fail = 0;
    const kb = session.bcButton ? Markup.inlineKeyboard([[Markup.button.url(session.bcButton.text, session.bcButton.url)]]) : {};

    // Get the specific bot instance to send messages
    const botInstance = activeBots[botId];
    if (!botInstance) return ctx.reply("⚠️ বট চলছে না, প্রথমে বট স্টার্ট করুন।");

    for (let userId in users) {
        try {
            if (session.bcImage) {
                await botInstance.telegram.sendPhoto(userId, session.bcImage, { caption: session.bcText, ...kb });
            } else if (session.bcText) {
                await botInstance.telegram.sendMessage(userId, session.bcText, kb);
            }
            success++;
        } catch (e) {
            fail++;
        }
        // Prevent spam limits
        if ((success + fail) % 20 === 0) await new Promise(resolve => setTimeout(resolve, 500));
    }

    await sessionsRef.child(uid).remove();
    ctx.reply(`📢 ব্রডকাস্ট শেষ!\n✅ সফল: ${success}\n❌ ব্যর্থ: ${fail}`);
}

async function performMainBroadcast(ctx, session) {
    const uid = ctx.from.id.toString();
    ctx.reply("⏳ মেইন ব্রডকাস্ট শুরু হচ্ছে...");

    const uSnap = await usersRef.once('value');
    const users = uSnap.val();

    let success = 0;
    
    for (let userId in users) {
        try {
            if (session.bcImage) {
                await mainBot.telegram.sendPhoto(userId, session.bcImage, { caption: session.bcText });
            } else if (session.bcText) {
                await mainBot.telegram.sendMessage(userId, session.bcText);
            }
            success++;
        } catch (e) { }
        
        if (success % 20 === 0) await new Promise(resolve => setTimeout(resolve, 500));
    }

    await sessionsRef.child(uid).remove();
    ctx.reply(`📢 বস, কাজ শেষ! সফল হয়েছে ${success} জনের কাছে।`);
}

// --- 5. CLIENT BOT DYNAMIC ENGINE ---
function initiateClientBot(config) {
    // If bot is already running, stop it first (for restart/update)
    if (activeBots[config.id]) {
        try { activeBots[config.id].stop(); } catch (e) {}
        delete activeBots[config.id];
    }

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

                // Prepare Keyboard
                const kb = config.buttons && config.buttons.length > 0 
                    ? Markup.inlineKeyboard(config.buttons) 
                    : {};

                // Send Welcome
                if (config.welcomeImage) {
                    await ctx.replyWithPhoto(config.welcomeImage, { 
                        caption: config.welcomeText || " ", 
                        ...kb 
                    });
                } else {
                    await ctx.reply(config.welcomeText || "Welcome!", kb);
                }
            } catch (innerError) {
                console.error(`Error in Client Bot @${config.botUsername} start:`, innerError.message);
            }
        });

        bot.launch().then(() => {
            console.log(`[ENGINE] ✅ @${config.botUsername} is running.`);
            activeBots[config.id] = bot;
        }).catch(e => console.error(`[ENGINE] ❌ Failed @${config.botUsername}:`, e.message));

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
        service: "Bot Control Hub Pro v3.0",
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
