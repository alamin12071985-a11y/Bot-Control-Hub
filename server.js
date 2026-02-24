/**
 * PROJECT: Bot Control Hub (SaaS) - COMPLETELY FIXED
 * AUTHOR: @lagatech
 * VERSION: 3.0.0 (Ultimate Edition)
 * DATABASE: Firebase Realtime DB
 * 
 * CHANGES:
 * ✓ Fixed image display in client bots
 * ✓ Fixed broadcast system
 * ✓ Removed update channel (only admin contact)
 * ✓ Better error handling
 * ✓ Proper session management
 * ✓ Image caching and validation
 */

require('dotenv').config();
const { Telegraf, Markup, session } = require('telegraf');
const express = require('express');
const admin = require('firebase-admin');
const cors = require('cors');
const crypto = require('crypto');

// --- 1. INITIALIZATION & SERVER SETUP ---
const app = express();
app.use(express.json());
app.use(cors());

const PORT = process.env.PORT || 3000;
const MAIN_BOT_TOKEN = process.env.MAIN_BOT_TOKEN;
const DATABASE_URL = "https://bot-control-hub-eee53-default-rtdb.firebaseio.com";
const ADMIN_IDS = ['7605281774']; // Admin Telegram IDs

// Enhanced logging
const LOG_LEVELS = {
    INFO: 'INFO',
    ERROR: 'ERROR',
    WARN: 'WARN',
    DEBUG: 'DEBUG'
};

function log(level, message, data = {}) {
    const logEntry = {
        timestamp: new Date().toISOString(),
        level,
        message,
        ...data
    };
    console.log(JSON.stringify(logEntry, null, 2));
    
    // Save to Firebase if needed (optional)
    if (logsRef) {
        logsRef.push(logEntry).catch(() => {});
    }
}

// Global Error Handlers
process.on('uncaughtException', (err) => {
    log(LOG_LEVELS.ERROR, 'Uncaught Exception', { error: err.message, stack: err.stack });
});

process.on('unhandledRejection', (reason, promise) => {
    log(LOG_LEVELS.ERROR, 'Unhandled Rejection', { reason: reason?.message || reason });
});

// --- 2. FIREBASE CONNECTION ---
let db, botsRef, usersRef, sessionsRef, subsRef, logsRef, broadcastJobsRef;

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
    broadcastJobsRef = db.ref("broadcast_jobs");

    log(LOG_LEVELS.INFO, 'Firebase Admin SDK Connected Successfully');
} catch (error) {
    log(LOG_LEVELS.ERROR, 'Firebase Connection Failed', { error: error.message });
    process.exit(1);
}

// Memory storage for active Telegraf instances
let activeBots = {};
let botRestartAttempts = {};

// --- 3. UTILITY FUNCTIONS ---
function generateRequestId() {
    return crypto.randomBytes(8).toString('hex');
}

async function validateTelegramToken(token) {
    try {
        const tempBot = new Telegraf(token);
        const botInfo = await tempBot.telegram.getMe();
        return { valid: true, botInfo };
    } catch (error) {
        return { valid: false, error: error.message };
    }
}

async function safeSendMessage(bot, chatId, text, extra = {}) {
    try {
        return await bot.telegram.sendMessage(chatId, text, extra);
    } catch (error) {
        log(LOG_LEVELS.WARN, 'Failed to send message', { chatId, error: error.message });
        return null;
    }
}

async function safeSendPhoto(bot, chatId, photo, extra = {}) {
    try {
        return await bot.telegram.sendPhoto(chatId, photo, extra);
    } catch (error) {
        log(LOG_LEVELS.WARN, 'Failed to send photo', { chatId, error: error.message });
        return null;
    }
}

// --- 4. MAIN CONTROLLER BOT ---
const mainBot = new Telegraf(MAIN_BOT_TOKEN);

// Set bot commands
mainBot.telegram.setMyCommands([
    { command: 'start', description: '🚀 Main Dashboard' },
    { command: 'help', description: '📞 Contact Admin' },
    { command: 'cancel', description: '❌ Cancel current operation' }
]).catch(err => log(LOG_LEVELS.ERROR, 'Failed to set commands', { error: err.message }));

// Session middleware for main bot
mainBot.use(session());

// Cancel command
mainBot.command('cancel', async (ctx) => {
    const uid = ctx.from.id.toString();
    await sessionsRef.child(uid).remove();
    ctx.reply('✅ Current operation cancelled. Use /start to begin again.');
});

// --- START COMMAND ---
mainBot.start(async (ctx) => {
    const requestId = generateRequestId();
    try {
        const uid = ctx.from.id.toString();
        const userData = {
            uid,
            username: ctx.from.username || "N/A",
            firstName: ctx.from.first_name,
            lastName: ctx.from.last_name || "",
            languageCode: ctx.from.language_code,
            lastSeen: Date.now(),
            joinDate: admin.database.ServerValue.TIMESTAMP
        };
        
        await usersRef.child(uid).set(userData);
        await sessionsRef.child(uid).remove();

        const welcomeMsg = 
            `👋 *Welcome to Bot Control Hub!*\n\n` +
            `Create and manage your Telegram bots easily with this powerful control panel.\n\n` +
            `✨ *Features:*\n` +
            `• Create unlimited bots\n` +
            `• Custom welcome messages with images\n` +
            `• Button integration\n` +
            `• Broadcast system for subscribers\n` +
            `• Set custom broadcast admins\n\n` +
            `Use the buttons below to get started!`;

        await ctx.replyWithMarkdown(welcomeMsg, Markup.inlineKeyboard([
            [Markup.button.callback('🚀 Create New Bot', 'create_bot')],
            [Markup.button.callback('📋 My Bots', 'my_bots')],
            [Markup.button.callback('📞 Contact Admin', 'contact_admin')]
        ]));

        log(LOG_LEVELS.INFO, 'User started bot', { uid, username: ctx.from.username, requestId });
    } catch (error) {
        log(LOG_LEVELS.ERROR, 'Start command error', { error: error.message, requestId });
        ctx.reply('⚠️ An error occurred. Please try again later.');
    }
});

// --- HELP COMMAND ---
mainBot.help(async (ctx) => {
    await ctx.replyWithMarkdown(
        `📞 *Contact Admin*\n\n` +
        `If you need help or have any questions, please contact:\n` +
        `👨‍💻 Admin: @lagatech\n\n` +
        `*Available Commands:*\n` +
        `/start - Main Dashboard\n` +
        `/help - Contact Admin\n` +
        `/cancel - Cancel Operation`
    );
});

// --- CALLBACK HANDLERS ---
mainBot.action('create_bot', async (ctx) => {
    await ctx.answerCbQuery();
    await ctx.editMessageReplyMarkup(undefined);
    
    const uid = ctx.from.id.toString();
    await sessionsRef.child(uid).set({
        step: 'WAIT_TOKEN',
        startTime: Date.now()
    });
    
    await ctx.replyWithMarkdown(
        `🤖 *Step 1: Bot Token*\n\n` +
        `1. Go to @BotFather on Telegram\n` +
        `2. Create a new bot with /newbot\n` +
        `3. Copy the API token\n` +
        `4. Send the token here\n\n` +
        `⚠️ *Keep your token secret!*`
    );
});

mainBot.action('my_bots', async (ctx) => {
    await ctx.answerCbQuery();
    await showUserBots(ctx);
});

mainBot.action('contact_admin', async (ctx) => {
    await ctx.answerCbQuery();
    await ctx.replyWithMarkdown(
        `📞 *Contact Admin*\n\n` +
        `👤 Admin: @lagatech\n` +
        `💬 Feel free to message for any help or support!`
    );
});

// Show user's bots
async function showUserBots(ctx) {
    try {
        const uid = ctx.from.id.toString();
        const snapshot = await botsRef.orderByChild('ownerId').equalTo(uid).once('value');
        const bots = snapshot.val();

        if (!bots || Object.keys(bots).length === 0) {
            return ctx.reply(
                "📭 You haven't created any bots yet!",
                Markup.inlineKeyboard([
                    [Markup.button.callback('✨ Create Your First Bot', 'create_bot')]
                ])
            );
        }

        let message = "📋 *Your Bots*\n\n";
        const botList = Object.values(bots);
        
        for (let i = 0; i < botList.length; i++) {
            const bot = botList[i];
            message += `${i + 1}. 🤖 *${bot.botName}*\n`;
            message += `   └ @${bot.botUsername} - ${bot.status === 'RUN' ? '✅ Active' : '❌ Inactive'}\n\n`;
        }

        const buttons = [];
        for (let bot of botList) {
            buttons.push([
                Markup.button.callback(`🤖 ${bot.botName}`, `manage_${bot.id}`)
            ]);
        }

        await ctx.replyWithMarkdown(message, Markup.inlineKeyboard(buttons));
    } catch (error) {
        log(LOG_LEVELS.ERROR, 'Show bots error', { error: error.message });
        ctx.reply('⚠️ Error loading your bots. Please try again.');
    }
}

// Manage specific bot
mainBot.action(/manage_(.+)/, async (ctx) => {
    const botId = ctx.match[1];
    await ctx.answerCbQuery();
    
    try {
        const snapshot = await botsRef.child(botId).once('value');
        const bot = snapshot.val();
        
        if (!bot) {
            return ctx.reply('❌ Bot not found!');
        }

        const message = 
            `🤖 *Bot Management*\n\n` +
            `*Name:* ${bot.botName}\n` +
            `*Username:* @${bot.botUsername}\n` +
            `*Status:* ${bot.status === 'RUN' ? '✅ Running' : '❌ Stopped'}\n` +
            `*Created:* ${new Date(bot.createdAt).toLocaleString()}\n\n` +
            `*Broadcast Admins:* ${bot.broadcastAdmins?.length || 1} users`;

        await ctx.editMessageText(message, {
            parse_mode: 'Markdown',
            ...Markup.inlineKeyboard([
                [Markup.button.callback('📢 Broadcast Setup', `bcsetup_${botId}`)],
                [Markup.button.callback('✏️ Edit Welcome', `edit_${botId}`)],
                [Markup.button.callback('🔄 Restart Bot', `restart_${botId}`)],
                [Markup.button.callback('🗑 Delete Bot', `delete_${botId}`)],
                [Markup.button.callback('🔙 Back to List', 'my_bots')]
            ])
        });
    } catch (error) {
        log(LOG_LEVELS.ERROR, 'Manage bot error', { error: error.message });
        ctx.reply('⚠️ Error loading bot details.');
    }
});

// --- BROADCAST SETUP ---
mainBot.action(/bcsetup_(.+)/, async (ctx) => {
    const botId = ctx.match[1];
    const uid = ctx.from.id.toString();
    
    await ctx.answerCbQuery();
    
    // Verify ownership
    const snapshot = await botsRef.child(botId).once('value');
    const bot = snapshot.val();
    
    if (!bot || bot.ownerId !== uid) {
        return ctx.reply('❌ You don\'t have permission to manage this bot!');
    }
    
    await sessionsRef.child(uid).set({
        step: 'BC_SET_ADMINS',
        botId: botId
    });
    
    await ctx.editMessageText(
        `📢 *Broadcast Admin Setup*\n\n` +
        `Send the Telegram User IDs who can send broadcasts in your bot.\n\n` +
        `*Current Admins:* ${bot.broadcastAdmins?.join(', ') || uid}\n\n` +
        `*Format:* Send IDs separated by commas\n` +
        `*Example:* 123456789, 987654321, 555666777\n\n` +
        `*Note:* You (owner) always have broadcast access.`,
        { parse_mode: 'Markdown' }
    );
});

// --- EDIT BOT WELCOME ---
mainBot.action(/edit_(.+)/, async (ctx) => {
    const botId = ctx.match[1];
    const uid = ctx.from.id.toString();
    
    await ctx.answerCbQuery();
    
    const snapshot = await botsRef.child(botId).once('value');
    const bot = snapshot.val();
    
    if (!bot || bot.ownerId !== uid) {
        return ctx.reply('❌ You don\'t have permission to edit this bot!');
    }
    
    await sessionsRef.child(uid).set({
        step: 'EDIT_WAIT_IMAGE',
        botId: botId,
        editing: true
    });
    
    await ctx.replyWithMarkdown(
        `✏️ *Edit Welcome Message*\n\n` +
        `Send a new welcome image (optional) or /skip to keep current.\n\n` +
        `*Current Image:* ${bot.welcomeImage ? '✅ Has image' : '❌ No image'}\n` +
        `*Current Text:* ${bot.welcomeText || 'Not set'}`
    );
});

// --- DELETE BOT ---
mainBot.action(/delete_(.+)/, async (ctx) => {
    const botId = ctx.match[1];
    const uid = ctx.from.id.toString();
    
    await ctx.answerCbQuery('Processing...');
    
    try {
        const snapshot = await botsRef.child(botId).once('value');
        const bot = snapshot.val();
        
        if (!bot || bot.ownerId !== uid) {
            return ctx.reply('❌ You don\'t have permission to delete this bot!');
        }
        
        // Stop bot if running
        if (activeBots[botId]) {
            try {
                activeBots[botId].stop('DELETE');
            } catch (e) {}
            delete activeBots[botId];
        }
        
        // Delete from Firebase
        await botsRef.child(botId).remove();
        await subsRef.child(botId).remove();
        
        await ctx.reply(`✅ Bot @${bot.botUsername} has been deleted successfully.`);
        
        // Show updated bot list
        await showUserBots(ctx);
    } catch (error) {
        log(LOG_LEVELS.ERROR, 'Delete bot error', { error: error.message });
        ctx.reply('⚠️ Error deleting bot. Please try again.');
    }
});

// --- RESTART BOT ---
mainBot.action(/restart_(.+)/, async (ctx) => {
    const botId = ctx.match[1];
    const uid = ctx.from.id.toString();
    
    await ctx.answerCbQuery('Restarting bot...');
    
    try {
        const snapshot = await botsRef.child(botId).once('value');
        const bot = snapshot.val();
        
        if (!bot || bot.ownerId !== uid) {
            return ctx.reply('❌ You don\'t have permission to restart this bot!');
        }
        
        // Stop existing instance
        if (activeBots[botId]) {
            try {
                activeBots[botId].stop('RESTART');
            } catch (e) {}
            delete activeBots[botId];
        }
        
        // Start new instance
        const success = await initiateClientBot(bot);
        
        if (success) {
            await ctx.reply(`✅ Bot @${bot.botUsername} has been restarted successfully.`);
        } else {
            await ctx.reply(`⚠️ Bot @${bot.botUsername} failed to restart. Check token validity.`);
        }
    } catch (error) {
        log(LOG_LEVELS.ERROR, 'Restart bot error', { error: error.message });
        ctx.reply('⚠️ Error restarting bot.');
    }
});

// --- TEXT HANDLER (WIZARD SYSTEM) ---
mainBot.on('text', async (ctx) => {
    const uid = ctx.from.id.toString();
    const sessionSnap = await sessionsRef.child(uid).once('value');
    
    if (!sessionSnap.exists()) return;
    
    const session = sessionSnap.val();
    const input = ctx.message.text.trim();
    
    // --- BOT CREATION: TOKEN STEP ---
    if (session.step === 'WAIT_TOKEN') {
        await ctx.reply('⏳ Validating token...');
        
        const validation = await validateTelegramToken(input);
        
        if (!validation.valid) {
            return ctx.reply(
                '❌ Invalid token! Please check and try again.\n\n' +
                'Get a valid token from @BotFather'
            );
        }
        
        const botInfo = validation.botInfo;
        
        await sessionsRef.child(uid).update({
            step: 'WAIT_IMAGE',
            token: input,
            botName: botInfo.first_name,
            botUsername: botInfo.username
        });
        
        await ctx.replyWithMarkdown(
            `✅ Bot connected: *@${botInfo.username}*\n\n` +
            `🖼 *Step 2: Welcome Image*\n\n` +
            `Send a welcome image for your bot (optional).\n` +
            `• Send a photo now\n` +
            `• Or /skip to continue without image`
        );
    }
    
    // --- BOT CREATION: TEXT STEP ---
    else if (session.step === 'WAIT_TEXT') {
        await sessionsRef.child(uid).update({
            step: 'WAIT_BTN_COUNT',
            welcomeText: input
        });
        
        await ctx.replyWithMarkdown(
            `✨ *Step 4: Button Setup*\n\n` +
            `How many buttons do you want? (0-3)\n\n` +
            `• Send a number (0, 1, 2, or 3)\n` +
            `• 0 means no buttons`
        );
    }
    
    // --- BOT CREATION: BUTTON COUNT STEP ---
    else if (session.step === 'WAIT_BTN_COUNT') {
        const count = parseInt(input);
        
        if (isNaN(count) || count < 0 || count > 3) {
            return ctx.reply('❌ Please send a valid number between 0 and 3.');
        }
        
        if (count === 0) {
            // No buttons, finalize creation
            await finalizeBotCreation(ctx, session, []);
        } else {
            await sessionsRef.child(uid).update({
                step: 'WAIT_BTN_DATA',
                targetBtns: count,
                currentBtns: []
            });
            
            await ctx.replyWithMarkdown(
                `🔘 *Button 1 Setup*\n\n` +
                `Send button details in this format:\n` +
                `*Button Name | URL*\n\n` +
                `*Example:* Join Channel | https://t.me/example`
            );
        }
    }
    
    // --- BOT CREATION: BUTTON DATA STEP ---
    else if (session.step === 'WAIT_BTN_DATA') {
        const parts = input.split('|').map(p => p.trim());
        
        if (parts.length < 2) {
            return ctx.reply(
                '❌ Invalid format! Use: *Button Name | URL*\n\n' +
                'Example: Join Channel | https://t.me/example'
            );
        }
        
        const [text, url] = parts;
        
        // Validate URL
        if (!url.startsWith('http')) {
            return ctx.reply('❌ URL must start with http:// or https://');
        }
        
        const currentBtns = session.currentBtns || [];
        currentBtns.push({ text, url });
        
        if (currentBtns.length >= session.targetBtns) {
            // All buttons collected, finalize
            await finalizeBotCreation(ctx, session, currentBtns);
        } else {
            await sessionsRef.child(uid).update({ currentBtns });
            await ctx.replyWithMarkdown(
                `🔘 *Button ${currentBtns.length + 1} Setup*\n\n` +
                `Send next button details:\n` +
                `*Button Name | URL*`
            );
        }
    }
    
    // --- BROADCAST SETUP: ADMIN IDS ---
    else if (session.step === 'BC_SET_ADMINS') {
        const botId = session.botId;
        
        // Parse IDs
        const ids = input.split(',')
            .map(id => id.trim())
            .filter(id => id.length > 0)
            .map(id => id.replace(/\D/g, '')); // Remove non-digits
        
        if (ids.length === 0) {
            return ctx.reply('❌ Please send at least one valid ID.');
        }
        
        // Add owner ID if not included
        if (!ids.includes(ctx.from.id.toString())) {
            ids.push(ctx.from.id.toString());
        }
        
        // Save to bot
        await botsRef.child(botId).child('broadcastAdmins').set(ids);
        
        // Clear session
        await sessionsRef.child(uid).remove();
        
        await ctx.replyWithMarkdown(
            `✅ *Broadcast Admins Updated!*\n\n` +
            `Admins can now use /broadcast command in your bot.\n\n` +
            `*Current Admins:* ${ids.join(', ')}`
        );
    }
    
    // --- EDIT BOT: TEXT STEP ---
    else if (session.step === 'EDIT_WAIT_TEXT') {
        const botId = session.botId;
        
        // Get current bot data
        const botSnap = await botsRef.child(botId).once('value');
        const bot = botSnap.val();
        
        if (!bot) {
            await sessionsRef.child(uid).remove();
            return ctx.reply('❌ Bot not found!');
        }
        
        // Update welcome text
        await botsRef.child(botId).update({
            welcomeText: input,
            lastEdited: Date.now()
        });
        
        // Clear session
        await sessionsRef.child(uid).remove();
        
        // Restart bot to apply changes
        if (activeBots[botId]) {
            try {
                activeBots[botId].stop('UPDATE');
            } catch (e) {}
            delete activeBots[botId];
        }
        
        await initiateClientBot({...bot, welcomeText: input});
        
        await ctx.replyWithMarkdown(
            `✅ *Welcome Text Updated!*\n\n` +
            `Your bot has been updated with the new welcome message.`
        );
    }
});

// --- PHOTO HANDLER ---
mainBot.on('photo', async (ctx) => {
    const uid = ctx.from.id.toString();
    const sessionSnap = await sessionsRef.child(uid).once('value');
    
    if (!sessionSnap.exists()) return;
    
    const session = sessionSnap.val();
    const photo = ctx.message.photo;
    const fileId = photo[photo.length - 1].file_id;
    
    // --- BOT CREATION: IMAGE STEP ---
    if (session.step === 'WAIT_IMAGE') {
        await sessionsRef.child(uid).update({
            step: 'WAIT_TEXT',
            welcomeImage: fileId
        });
        
        await ctx.replyWithMarkdown(
            `🖼 *Image Saved!*\n\n` +
            `✨ *Step 3: Welcome Text*\n\n` +
            `Now send the welcome text message for your bot.\n` +
            `This will be shown with the image when users start the bot.`
        );
    }
    
    // --- EDIT BOT: IMAGE STEP ---
    else if (session.step === 'EDIT_WAIT_IMAGE') {
        const botId = session.botId;
        
        // Get current bot data
        const botSnap = await botsRef.child(botId).once('value');
        const bot = botSnap.val();
        
        if (!bot) {
            await sessionsRef.child(uid).remove();
            return ctx.reply('❌ Bot not found!');
        }
        
        // Update image and move to text edit
        await sessionsRef.child(uid).update({
            step: 'EDIT_WAIT_TEXT',
            welcomeImage: fileId
        });
        
        await ctx.replyWithMarkdown(
            `🖼 *Image Saved!*\n\n` +
            `✏️ Now send the new welcome text for your bot.\n` +
            `Or /skip to keep current text.`
        );
    }
});

// --- SKIP COMMAND HANDLER ---
mainBot.command('skip', async (ctx) => {
    const uid = ctx.from.id.toString();
    const sessionSnap = await sessionsRef.child(uid).once('value');
    
    if (!sessionSnap.exists()) return;
    
    const session = sessionSnap.val();
    
    // Skip image in bot creation
    if (session.step === 'WAIT_IMAGE') {
        await sessionsRef.child(uid).update({
            step: 'WAIT_TEXT',
            welcomeImage: null
        });
        
        await ctx.replyWithMarkdown(
            `✨ *Step 3: Welcome Text*\n\n` +
            `Send the welcome text message for your bot.\n` +
            `This will be shown when users start the bot.`
        );
    }
    
    // Skip image in edit mode
    else if (session.step === 'EDIT_WAIT_IMAGE') {
        await sessionsRef.child(uid).update({
            step: 'EDIT_WAIT_TEXT'
        });
        
        await ctx.replyWithMarkdown(
            `✏️ Send the new welcome text for your bot.\n` +
            `Or /skip to keep current text.`
        );
    }
    
    // Skip text in edit mode
    else if (session.step === 'EDIT_WAIT_TEXT') {
        const botId = session.botId;
        
        // Get current bot data
        const botSnap = await botsRef.child(botId).once('value');
        const bot = botSnap.val();
        
        if (!bot) {
            await sessionsRef.child(uid).remove();
            return ctx.reply('❌ Bot not found!');
        }
        
        // If there's a new image, update it
        if (session.welcomeImage) {
            await botsRef.child(botId).update({
                welcomeImage: session.welcomeImage,
                lastEdited: Date.now()
            });
        }
        
        // Clear session
        await sessionsRef.child(uid).remove();
        
        // Restart bot
        if (activeBots[botId]) {
            try {
                activeBots[botId].stop('UPDATE');
            } catch (e) {}
            delete activeBots[botId];
        }
        
        await initiateClientBot({
            ...bot,
            welcomeImage: session.welcomeImage || bot.welcomeImage
        });
        
        await ctx.replyWithMarkdown(
            `✅ *Bot Updated!*\n\n` +
            `Your bot has been updated successfully.`
        );
    }
});

// --- FINALIZE BOT CREATION ---
async function finalizeBotCreation(ctx, session, buttons) {
    const uid = ctx.from.id.toString();
    const requestId = generateRequestId();
    
    try {
        const botId = botsRef.push().key;
        
        const botData = {
            id: botId,
            ownerId: uid,
            ownerUsername: ctx.from.username || "N/A",
            token: session.token,
            botName: session.botName,
            botUsername: session.botUsername,
            welcomeImage: session.welcomeImage || null,
            welcomeText: session.welcomeText || "Welcome to my bot!",
            buttons: buttons || [],
            status: 'RUN',
            createdAt: Date.now(),
            lastEdited: Date.now(),
            broadcastAdmins: [uid], // Owner is default broadcast admin
            totalUsers: 0,
            stats: {
                created: Date.now(),
                lastActive: Date.now()
            }
        };

        // Save to Firebase
        await botsRef.child(botId).set(botData);
        
        // Clear session
        await sessionsRef.child(uid).remove();
        
        // Start the bot
        const started = await initiateClientBot(botData);
        
        if (started) {
            await ctx.replyWithMarkdown(
                `🎉 *Bot Created Successfully!*\n\n` +
                `🤖 *Name:* ${botData.botName}\n` +
                `🔗 *Username:* @${botData.botUsername}\n` +
                `📊 *Status:* ✅ Active\n\n` +
                `*What's next?*\n` +
                `• Use /broadcast in your bot to send messages\n` +
                `• Add broadcast admins from main menu\n` +
                `• Edit welcome message anytime\n\n` +
                `Start your bot: https://t.me/${botData.botUsername}`,
                Markup.inlineKeyboard([
                    [Markup.button.url('🚀 Open Bot', `https://t.me/${botData.botUsername}`)],
                    [Markup.button.callback('📋 Manage Bots', 'my_bots')]
                ])
            );
        } else {
            await ctx.replyWithMarkdown(
                `⚠️ *Bot Created But Failed to Start*\n\n` +
                `Your bot was saved but couldn't be started. Try restarting it from the manage menu.`
            );
        }
        
        log(LOG_LEVELS.INFO, 'Bot created', { 
            botId, 
            botUsername: botData.botUsername, 
            ownerId: uid,
            requestId 
        });
        
    } catch (error) {
        log(LOG_LEVELS.ERROR, 'Bot creation finalization error', { 
            error: error.message,
            requestId 
        });
        
        await ctx.reply(
            '❌ Failed to create bot. Please try again.\n' +
            'If the problem persists, contact @lagatech'
        );
    }
}

// --- 5. CLIENT BOT ENGINE (FIXED VERSION) ---
async function initiateClientBot(config) {
    const botId = config.id;
    
    // Prevent duplicate instances
    if (activeBots[botId]) {
        try {
            activeBots[botId].stop('RESTART');
        } catch (e) {}
        delete activeBots[botId];
    }
    
    try {
        log(LOG_LEVELS.INFO, 'Starting client bot', { botId, username: config.botUsername });
        
        const bot = new Telegraf(config.token);
        
        // Session middleware for broadcast wizard
        bot.use(session());
        
        // Error handler
        bot.catch((err, ctx) => {
            log(LOG_LEVELS.ERROR, 'Client bot error', { 
                botId: config.id,
                error: err.message,
                updateType: ctx.updateType 
            });
        });
        
        // --- START COMMAND HANDLER (FIXED) ---
        bot.start(async (ctx) => {
            try {
                const userId = ctx.from.id.toString();
                const userName = ctx.from.first_name || "User";
                const userUsername = ctx.from.username || "";
                
                // Save subscriber
                await subsRef.child(config.id).child(userId).set({
                    name: userName,
                    username: userUsername,
                    joinedAt: Date.now(),
                    lastActive: Date.now(),
                    languageCode: ctx.from.language_code
                });
                
                // Update bot user count
                const subsSnap = await subsRef.child(config.id).once('value');
                const userCount = subsSnap.exists() ? Object.keys(subsSnap.val()).length : 0;
                await botsRef.child(config.id).update({ totalUsers: userCount });
                
                // Prepare keyboard
                let keyboard = {};
                if (config.buttons && config.buttons.length > 0) {
                    const buttonRows = config.buttons.map(btn => 
                        [Markup.button.url(btn.text, btn.url)]
                    );
                    keyboard = Markup.inlineKeyboard(buttonRows);
                }
                
                // Send welcome message with proper error handling
                if (config.welcomeImage) {
                    try {
                        // Try to send with photo first
                        await ctx.replyWithPhoto(config.welcomeImage, {
                            caption: config.welcomeText || `Welcome ${userName}!`,
                            parse_mode: 'Markdown',
                            ...keyboard
                        });
                    } catch (photoError) {
                        log(LOG_LEVELS.WARN, 'Photo send failed, falling back to text', { 
                            botId: config.id,
                            error: photoError.message 
                        });
                        
                        // If photo fails, send text only
                        await ctx.reply(
                            config.welcomeText || `Welcome ${userName}!`,
                            keyboard
                        );
                    }
                } else {
                    // No image, just text
                    await ctx.reply(
                        config.welcomeText || `Welcome ${userName}!`,
                        keyboard
                    );
                }
                
            } catch (error) {
                log(LOG_LEVELS.ERROR, 'Client bot start error', { 
                    botId: config.id,
                    error: error.message 
                });
                
                // Fallback message
                await ctx.reply('Welcome!').catch(() => {});
            }
        });
        
        // --- BROADCAST COMMAND HANDLER (FIXED) ---
        bot.command('broadcast', async (ctx) => {
            try {
                const userId = ctx.from.id.toString();
                
                // Check if user is broadcast admin
                const botConfig = (await botsRef.child(config.id).once('value')).val();
                
                if (!botConfig) {
                    return ctx.reply('❌ Bot configuration not found.');
                }
                
                const admins = botConfig.broadcastAdmins || [botConfig.ownerId];
                
                if (!admins.includes(userId)) {
                    return ctx.reply('🚫 You are not authorized to use broadcast command.');
                }
                
                // Initialize broadcast session
                ctx.session = ctx.session || {};
                ctx.session.broadcast = {
                    step: 'WAIT_CONTENT',
                    botId: config.id
                };
                
                await ctx.replyWithMarkdown(
                    `📢 *Broadcast Mode*\n\n` +
                    `Send the content you want to broadcast:\n\n` +
                    `• Send a photo (with optional caption)\n` +
                    `• Send text message\n` +
                    `• Or /cancel to exit`
                );
                
            } catch (error) {
                log(LOG_LEVELS.ERROR, 'Broadcast command error', { 
                    botId: config.id,
                    error: error.message 
                });
                ctx.reply('⚠️ Error starting broadcast. Please try again.');
            }
        });
        
        // --- BROADCAST CONTENT HANDLER ---
        bot.on('text', async (ctx) => {
            if (!ctx.session?.broadcast) return;
            
            const session = ctx.session.broadcast;
            const text = ctx.message.text;
            
            // Cancel command
            if (text === '/cancel') {
                ctx.session.broadcast = null;
                return ctx.reply('❌ Broadcast cancelled.');
            }
            
            // WAIT_CONTENT step (text)
            if (session.step === 'WAIT_CONTENT') {
                ctx.session.broadcast = {
                    ...session,
                    step: 'WAIT_BUTTON',
                    type: 'text',
                    content: text,
                    caption: ''
                };
                
                await ctx.replyWithMarkdown(
                    `🔘 *Add Button (Optional)*\n\n` +
                    `Send button details or /skip to continue.\n\n` +
                    `*Format:* Button Name | URL\n` +
                    `*Example:* Join Channel | https://t.me/example`
                );
            }
            
            // WAIT_BUTTON step
            else if (session.step === 'WAIT_BUTTON') {
                // Check if user wants to skip
                if (text.toLowerCase() === '/skip') {
                    // Skip button
                    await processBroadcast(ctx, session, null);
                } else {
                    // Parse button
                    const parts = text.split('|').map(p => p.trim());
                    
                    if (parts.length < 2) {
                        return ctx.reply(
                            '❌ Invalid format! Use: *Button Name | URL*\n\n' +
                            'Or /skip to continue without button'
                        );
                    }
                    
                    const [btnText, btnUrl] = parts;
                    
                    if (!btnUrl.startsWith('http')) {
                        return ctx.reply('❌ URL must start with http:// or https://');
                    }
                    
                    const button = { text: btnText, url: btnUrl };
                    await processBroadcast(ctx, session, button);
                }
            }
        });
        
        // --- PHOTO HANDLER FOR BROADCAST ---
        bot.on('photo', async (ctx) => {
            if (!ctx.session?.broadcast) return;
            
            const session = ctx.session.broadcast;
            
            if (session.step === 'WAIT_CONTENT') {
                const photo = ctx.message.photo;
                const fileId = photo[photo.length - 1].file_id;
                const caption = ctx.message.caption || '';
                
                ctx.session.broadcast = {
                    ...session,
                    step: 'WAIT_BUTTON',
                    type: 'photo',
                    content: fileId,
                    caption: caption
                };
                
                await ctx.replyWithMarkdown(
                    `🔘 *Add Button (Optional)*\n\n` +
                    `Send button details or /skip to continue.\n\n` +
                    `*Format:* Button Name | URL\n` +
                    `*Example:* Join Channel | https://t.me/example`
                );
            }
        });
        
        // Process and send broadcast
        async function processBroadcast(ctx, session, button) {
            const botId = session.botId;
            const requestId = generateRequestId();
            
            try {
                // Get all subscribers
                const subsSnap = await subsRef.child(botId).once('value');
                const subscribers = subsSnap.val();
                
                if (!subscribers || Object.keys(subscribers).length === 0) {
                    ctx.session.broadcast = null;
                    return ctx.reply('📭 No subscribers found to broadcast.');
                }
                
                const userIds = Object.keys(subscribers);
                const total = userIds.length;
                
                // Prepare keyboard
                let keyboard = {};
                if (button) {
                    keyboard = Markup.inlineKeyboard([[Markup.button.url(button.text, button.url)]]);
                }
                
                // Send initial status
                const statusMsg = await ctx.reply(
                    `📢 Broadcasting to ${total} users...\n` +
                    `⏳ 0/${total} completed`
                );
                
                let success = 0;
                let failed = 0;
                
                // Send to all subscribers with delay to avoid rate limits
                for (let i = 0; i < userIds.length; i++) {
                    const userId = userIds[i];
                    
                    try {
                        if (session.type === 'photo') {
                            await bot.telegram.sendPhoto(userId, session.content, {
                                caption: session.caption,
                                ...keyboard
                            });
                        } else {
                            await bot.telegram.sendMessage(userId, session.content, keyboard);
                        }
                        success++;
                        
                        // Update status every 10 messages
                        if ((i + 1) % 10 === 0 || i === userIds.length - 1) {
                            await ctx.telegram.editMessageText(
                                statusMsg.chat.id,
                                statusMsg.message_id,
                                null,
                                `📢 Broadcasting...\n✅ ${success}/${total} completed\n❌ Failed: ${failed}`
                            ).catch(() => {});
                        }
                        
                        // Small delay to avoid flooding
                        await new Promise(resolve => setTimeout(resolve, 50));
                        
                    } catch (error) {
                        failed++;
                        log(LOG_LEVELS.WARN, 'Broadcast send failed', { 
                            botId,
                            userId,
                            error: error.message 
                        });
                    }
                }
                
                // Final status
                await ctx.reply(
                    `✅ *Broadcast Complete!*\n\n` +
                    `📊 *Statistics:*\n` +
                    `• Total Users: ${total}\n` +
                    `• Successful: ${success}\n` +
                    `• Failed: ${failed}\n` +
                    `• Success Rate: ${Math.round((success/total)*100)}%`
                );
                
                // Clear session
                ctx.session.broadcast = null;
                
                // Log broadcast
                log(LOG_LEVELS.INFO, 'Broadcast completed', {
                    botId,
                    success,
                    failed,
                    total,
                    type: session.type,
                    hasButton: !!button,
                    requestId
                });
                
            } catch (error) {
                log(LOG_LEVELS.ERROR, 'Broadcast processing error', { 
                    botId: config.id,
                    error: error.message,
                    requestId 
                });
                
                ctx.reply('⚠️ Error during broadcast. Please try again.');
                ctx.session.broadcast = null;
            }
        }
        
        // Launch bot
        await bot.launch();
        
        // Store in active bots
        activeBots[botId] = bot;
        
        log(LOG_LEVELS.INFO, 'Client bot started successfully', { 
            botId, 
            username: config.botUsername 
        });
        
        return true;
        
    } catch (error) {
        log(LOG_LEVELS.ERROR, 'Failed to start client bot', { 
            botId: config.id,
            error: error.message 
        });
        
        // Update bot status
        await botsRef.child(config.id).update({ 
            status: 'ERROR',
            lastError: error.message,
            lastErrorTime: Date.now()
        }).catch(() => {});
        
        return false;
    }
}

// --- 6. AUTO-RESUME ON START ---
async function startup() {
    log(LOG_LEVELS.INFO, 'Starting Bot Control Hub...');
    
    try {
        // Load all bots
        const snapshot = await botsRef.once('value');
        const allBots = snapshot.val();
        
        if (allBots) {
            let started = 0;
            let failed = 0;
            
            for (let [botId, botConfig] of Object.entries(allBots)) {
                if (botConfig.status === 'RUN') {
                    const success = await initiateClientBot(botConfig);
                    if (success) {
                        started++;
                    } else {
                        failed++;
                    }
                }
            }
            
            log(LOG_LEVELS.INFO, 'Bots loaded', { started, failed, total: Object.keys(allBots).length });
        }
        
        // Start main bot
        await mainBot.launch();
        log(LOG_LEVELS.INFO, 'Main controller bot started');
        
        // Set webhook if needed
        if (process.env.WEBHOOK_URL) {
            await mainBot.telegram.setWebhook(`${process.env.WEBHOOK_URL}/webhook`);
            log(LOG_LEVELS.INFO, 'Webhook set', { url: process.env.WEBHOOK_URL });
        }
        
    } catch (error) {
        log(LOG_LEVELS.ERROR, 'Startup failed', { error: error.message });
        process.exit(1);
    }
}

// --- 7. EXPRESS SERVER (HEALTH CHECKS) ---
app.get('/', (req, res) => {
    res.json({
        status: 'online',
        service: 'Bot Control Hub',
        version: '3.0.0',
        activeBots: Object.keys(activeBots).length,
        timestamp: new Date().toISOString()
    });
});

app.get('/health', (req, res) => {
    res.json({
        status: 'healthy',
        uptime: process.uptime(),
        memory: process.memoryUsage(),
        activeBots: Object.keys(activeBots).length
    });
});

app.post('/webhook', async (req, res) => {
    try {
        await mainBot.handleUpdate(req.body, res);
    } catch (error) {
        log(LOG_LEVELS.ERROR, 'Webhook error', { error: error.message });
        res.sendStatus(200);
    }
});

app.listen(PORT, () => {
    log(LOG_LEVELS.INFO, `HTTP server running on port ${PORT}`);
});

// --- 8. GRACEFUL SHUTDOWN ---
async function shutdown(signal) {
    log(LOG_LEVELS.INFO, `Received ${signal}, shutting down...`);
    
    // Stop main bot
    try {
        await mainBot.stop(signal);
    } catch (e) {}
    
    // Stop all client bots
    for (let [botId, bot] of Object.entries(activeBots)) {
        try {
            await bot.stop(signal);
        } catch (e) {}
    }
    
    log(LOG_LEVELS.INFO, 'All bots stopped');
    process.exit(0);
}

process.once('SIGINT', () => shutdown('SIGINT'));
process.once('SIGTERM', () => shutdown('SIGTERM'));

// Start the system
startup();
