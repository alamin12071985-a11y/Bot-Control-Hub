// api/req/100coins/[userid].js
// Vercel Serverless Function
// Called by Mini App when user converts 100 coins
// URL: https://your-app.vercel.app/API/req/100coins/USER_ID

export default async function handler(req, res) {

  /* ── CORS ── */
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, x-api-key');

  if (req.method === 'OPTIONS') return res.status(200).end();

  /* ── CONFIG (set in Vercel Environment Variables) ── */
  const BOT_TOKEN = process.env.BOT_TOKEN;   // Your Telegram Bot Token
  const API_KEY   = process.env.API_KEY;     // Optional secret key for security
  const COINS     = 100;

  /* ── GET user_id from URL ── */
  const { userid } = req.query;

  if (!userid || isNaN(userid)) {
    return res.status(400).json({
      ok: false,
      error: 'Invalid or missing user_id',
    });
  }

  /* ── Optional API Key check ── */
  if (API_KEY) {
    const provided = req.headers['x-api-key'] || req.query.key;
    if (provided !== API_KEY) {
      return res.status(401).json({ ok: false, error: 'Unauthorized' });
    }
  }

  if (!BOT_TOKEN) {
    return res.status(500).json({ ok: false, error: 'BOT_TOKEN not configured' });
  }

  /* ── Send /addcoins command trigger to Bot ── */
  try {
    const telegramUrl = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;

    // Send a message to the user that triggers /addcoins in your TPY bot
    const payload = {
      chat_id:    userid,
      text:       `/addcoins ${userid}`,
      parse_mode: 'HTML',
    };

    const tgRes  = await fetch(telegramUrl, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });

    const tgData = await tgRes.json();

    if (!tgData.ok) {
      throw new Error(tgData.description || 'Telegram API error');
    }

    return res.status(200).json({
      ok:          true,
      user_id:     userid,
      coins_added: COINS,
      message:     'Signal sent to bot successfully',
    });

  } catch (err) {
    return res.status(500).json({
      ok:    false,
      error: err.message || 'Internal server error',
    });
  }
}
