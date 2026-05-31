// ════════════════════════════════════════════════════
// 📁 api/req/100coins/[userid].js
// Vercel Serverless API → Telebot Creator
// Route: GET /api/req/100coins/:userid
// ════════════════════════════════════════════════════

// ✅ Replace with your Telebot Creator Bot Username
const BOT_USERNAME = "lagasmmbot"; // ← শুধু এইটা পরিবর্তন করো

const TELEBOT_API  = `https://api.telebot.pro/${BOT_USERNAME}/runCommand`;

// Optional: Secret key for security (same key Mini App te dite hobe)
const SECRET_KEY   = "my_secret_key_2025"; // ← optional security

export default async function handler(req, res) {

  // ── CORS Headers ──
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  // ── Get user_id from URL ──
  const { userid } = req.query;

  // ── Validate user_id ──
  if (!userid || isNaN(userid)) {
    return res.status(400).json({
      success: false,
      error: "Invalid user_id"
    });
  }

  // ── Optional secret check ──
  const secret = req.query.secret || req.headers['x-secret'];
  if (secret && secret !== SECRET_KEY) {
    return res.status(403).json({
      success: false,
      error: "Unauthorized"
    });
  }

  try {
    // ── Call Telebot Creator API ──
    const response = await fetch(TELEBOT_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        command: "/addcoins_api",   // ← Telebot Creator command name
        user_id: parseInt(userid),
        params:  "100"              // ← amount to add
      })
    });

    const data = await response.json();

    if (response.ok) {
      return res.status(200).json({
        success: true,
        message: "100 coins added to user " + userid,
        telebot_response: data
      });
    } else {
      return res.status(500).json({
        success: false,
        error: "Telebot API error",
        details: data
      });
    }

  } catch (err) {
    return res.status(500).json({
      success: false,
      error: "Server error",
      details: err.message
    });
  }
}
