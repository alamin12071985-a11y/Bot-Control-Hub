/* ═══════════════════════════════════════════════
   main.js — Earn Coins Mini App
   libtl.com SDK + Vercel API Integration
═══════════════════════════════════════════════ */

/* ── CONFIG ─────────────────────────────────── */
const CONFIG = {
  COINS_PER_AD:      10,
  CONVERT_THRESHOLD: 100,
  DAILY_LIMIT:       15,
  COOLDOWN_SEC:      30,          // seconds between ads
  API_BASE:          'https://myadspage.vercel.app/API/req/100coins', // Vercel endpoint
  BOT_USERNAME:      'YourBotUsername',
};

/* ── TELEGRAM INIT ───────────────────────────── */
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

/* ── USER ID ─────────────────────────────────── */
// Priority: URL param → Telegram WebApp → fallback '0'
const urlParams = new URLSearchParams(window.location.search);
const USER_ID   = urlParams.get('user_id')
               || tg?.initDataUnsafe?.user?.id?.toString()
               || '0';
const tgUser    = tg?.initDataUnsafe?.user || null;

/* ── STATE ───────────────────────────────────── */
// sessionStorage — resets every new session (safe, no server needed)
const STORE_KEY = 'earn_state_' + USER_ID;

const DEFAULT_STATE = {
  session_coins: 0,     // coins this session (not yet converted)
  total_ads:     0,     // all-time ads watched
  today_ads:     0,     // ads watched today
  converted:     0,     // total coins converted
  last_date:     null,  // for daily reset
  cooldown_until: null, // ISO string
};

let state = { ...DEFAULT_STATE };

function loadState() {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    if (raw) state = { ...DEFAULT_STATE, ...JSON.parse(raw) };
  } catch(e) { /* ignore */ }
}

function saveState() {
  try { sessionStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch(e) {}
}

function dailyReset() {
  const today = new Date().toDateString();
  if (state.last_date !== today) {
    state.today_ads    = 0;
    state.last_date    = today;
    state.cooldown_until = null;
    saveState();
  }
}

/* ── DOM REFS ────────────────────────────────── */
const watchBtn     = document.getElementById('watch-btn');
const btnIcon      = document.getElementById('btn-icon');
const btnLabel     = document.getElementById('btn-label');
const watchCaption = document.getElementById('watch-caption');
const balDisplay   = document.getElementById('bal-display');
const pctDisplay   = document.getElementById('pct-display');
const progFill     = document.getElementById('prog-fill');
const progHint     = document.getElementById('prog-hint');
const convertBtn   = document.getElementById('convert-btn');
const convertIcon  = document.getElementById('convert-icon');
const convertLabel = document.getElementById('convert-label');
const convertHint  = document.getElementById('convert-hint');
const coinsLeft    = document.getElementById('coins-left');
const statTotal    = document.getElementById('stat-total');
const statToday    = document.getElementById('stat-today');
const statConverted= document.getElementById('stat-converted');
const cooldownWrap = document.getElementById('cooldown-wrap');
const cooldownFill = document.getElementById('cooldown-fill');
const cooldownText = document.getElementById('cooldown-text');

/* ── RENDER UI ───────────────────────────────── */
function renderUI() {
  const coins = state.session_coins;
  const pct   = Math.min(100, Math.round((coins / CONFIG.CONVERT_THRESHOLD) * 100));
  const left  = Math.max(0, CONFIG.CONVERT_THRESHOLD - coins);

  // Balance
  balDisplay.textContent = coins;

  // Progress
  pctDisplay.textContent       = pct + '%';
  progFill.style.width         = pct + '%';
  progHint.textContent         = left > 0
    ? `${left} more Coins needed to convert`
    : '✅ Ready to convert!';

  // Stats
  statTotal.textContent     = state.total_ads;
  statToday.textContent     = state.today_ads;
  statConverted.textContent = state.converted;

  // Convert button
  if (coins >= CONFIG.CONVERT_THRESHOLD) {
    convertBtn.className       = 'convert-btn unlocked';
    convertIcon.className      = 'fas fa-bolt';
    convertLabel.textContent   = 'Convert to Bot Wallet';
    convertHint.innerHTML      = `🎯 Convert now! You have <strong>${coins}</strong> coins`;
    convertHint.style.color    = 'var(--gold)';
  } else {
    convertBtn.className       = 'convert-btn locked';
    convertIcon.className      = 'fas fa-lock';
    convertLabel.textContent   = 'Convert to Bot Wallet';
    convertHint.innerHTML      = `Need 100 Coins • <span id="coins-left">${left}</span> more to go`;
    convertHint.style.color    = '';
  }

  // Daily limit check
  if (state.today_ads >= CONFIG.DAILY_LIMIT) {
    setWatchDisabled('Daily limit reached! Come back tomorrow.');
  }
}

/* ── libtl.com AD SYSTEM ─────────────────────── */
let adWatching    = false;
let cooldownTimer = null;

function watchAd() {
  if (adWatching) return;

  // Daily limit
  if (state.today_ads >= CONFIG.DAILY_LIMIT) {
    showToast('⛔ Daily limit reached! Come back tomorrow.', 'warn');
    return;
  }

  // Active cooldown
  if (state.cooldown_until && new Date() < new Date(state.cooldown_until)) {
    const secs = Math.ceil((new Date(state.cooldown_until) - new Date()) / 1000);
    showToast(`⏳ Wait ${secs}s before next ad`, 'warn');
    return;
  }

  adWatching = true;
  setWatchLoading(true);
  if (tg) tg.HapticFeedback?.impactOccurred('light');

  /* ── libtl.com inApp Interstitial ── */
  let adDone = false;

  function giveReward() {
    if (adDone) return;
    adDone = true;
    onAdComplete();
  }

  try {
    if (typeof show_11007747 === 'function') {
      // SDK loaded — show real ad
      show_11007747({
        type: 'inApp',
        inAppSettings: {
          frequency: 1,
          capping: 0,
          interval: 0,
          timeout: 3,
          everyPage: true,
        }
      });

      // Detect when user returns from ad (tab/visibility restore)
      const onVisible = () => {
        if (document.visibilityState === 'visible') {
          document.removeEventListener('visibilitychange', onVisible);
          clearTimeout(fallback);
          setTimeout(giveReward, 600);
        }
      };
      document.addEventListener('visibilitychange', onVisible);

      // Fallback: reward after 8s if visibility never triggered
      const fallback = setTimeout(() => {
        document.removeEventListener('visibilitychange', onVisible);
        giveReward();
      }, 8000);

    } else {
      // SDK not yet loaded — demo mode (3s simulate)
      console.warn('[AdSystem] show_11007747 not ready, using demo mode');
      setTimeout(giveReward, 3000);
    }
  } catch(e) {
    // Any SDK error — still reward after 3s
    setTimeout(giveReward, 3000);
  }
}

function onAdComplete() {
  adWatching = false;

  // Add coins
  state.session_coins += CONFIG.COINS_PER_AD;
  state.total_ads     += 1;
  state.today_ads     += 1;

  // Set cooldown
  const cd = new Date();
  cd.setSeconds(cd.getSeconds() + CONFIG.COOLDOWN_SEC);
  state.cooldown_until = cd.toISOString();

  saveState();
  renderUI();
  setWatchLoading(false);
  spawnCoinFloat();
  showToast(`+${CONFIG.COINS_PER_AD} Coins earned! 🪙`, 'success');
  bumpBalance();
  if (tg) tg.HapticFeedback?.notificationOccurred('success');

  startCooldown(CONFIG.COOLDOWN_SEC);
}

/* ── COOLDOWN UI ─────────────────────────────── */
function startCooldown(seconds) {
  let remaining = seconds;

  watchBtn.disabled = true;
  cooldownWrap.style.display = 'block';
  cooldownFill.style.width   = '100%';
  cooldownFill.style.transition = 'none';
  watchCaption.textContent   = `Next ad in ${remaining}s...`;
  cooldownText.textContent   = '';

  // Force reflow so transition works
  void cooldownFill.offsetWidth;
  cooldownFill.style.transition = `width ${seconds}s linear`;
  cooldownFill.style.width      = '0%';

  clearInterval(cooldownTimer);
  cooldownTimer = setInterval(() => {
    remaining--;
    watchCaption.textContent = `Next ad in ${remaining}s...`;

    if (remaining <= 0) {
      clearInterval(cooldownTimer);
      cooldownWrap.style.display = 'none';

      if (state.today_ads >= CONFIG.DAILY_LIMIT) {
        setWatchDisabled('Daily limit reached!');
      } else {
        resetWatchBtn();
      }
    }
  }, 1000);
}

/* ── CONVERT COINS → Vercel API ──────────────── */
function convertCoins() {
  if (state.session_coins < CONFIG.CONVERT_THRESHOLD) return;
  if (convertBtn.classList.contains('converting')) return;

  const toConvert = Math.floor(state.session_coins / CONFIG.CONVERT_THRESHOLD) * CONFIG.CONVERT_THRESHOLD;

  convertBtn.classList.add('converting');
  convertLabel.textContent = 'Converting...';
  convertIcon.className    = 'fas fa-spinner fa-spin';

  const apiUrl = `${CONFIG.API_BASE}/${USER_ID}`;

  fetch(apiUrl, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  })
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then(data => {
      // Success
      state.session_coins -= toConvert;
      state.converted     += toConvert;

      saveState();
      renderUI();

      convertBtn.classList.remove('converting');
      convertIcon.className  = 'fas fa-lock';
      convertLabel.textContent = 'Convert to Bot Wallet';

      document.getElementById('modal-coins').textContent = toConvert;
      document.getElementById('modal').classList.add('open');

      if (tg) tg.HapticFeedback?.notificationOccurred('success');
    })
    .catch(err => {
      convertBtn.classList.remove('converting');
      renderUI(); // restore button state
      showToast('❌ Failed! Check connection & try again.', 'error');
      console.error('[Convert] API error:', err);
    });
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
}

/* ── WATCH BTN STATES ────────────────────────── */
function setWatchLoading(on) {
  if (on) {
    watchBtn.classList.add('loading');
    watchBtn.disabled        = true;
    btnIcon.className        = 'fas fa-spinner btn-icon';
    btnLabel.textContent     = 'Loading...';
    watchCaption.textContent = 'Ad is loading...';
  } else {
    watchBtn.classList.remove('loading');
    btnIcon.className    = 'fas fa-play-circle btn-icon';
    btnLabel.textContent = 'Watch Ad';
  }
}

function resetWatchBtn() {
  watchBtn.disabled        = false;
  watchBtn.classList.remove('loading');
  btnIcon.className        = 'fas fa-play-circle btn-icon';
  btnLabel.textContent     = 'Watch Ad';
  watchCaption.textContent = 'Watch ads and earn coins';
}

function setWatchDisabled(msg) {
  watchBtn.disabled        = true;
  watchBtn.classList.remove('loading');
  btnIcon.className        = 'fas fa-check-circle btn-icon';
  btnIcon.style.color      = 'var(--success)';
  btnLabel.textContent     = 'Done';
  watchCaption.textContent = msg || 'Come back tomorrow!';
}

/* ── ANIMATIONS ──────────────────────────────── */
function spawnCoinFloat() {
  const el   = document.createElement('div');
  el.className = 'coin-float';
  el.textContent = `+${CONFIG.COINS_PER_AD} 🪙`;
  const btn  = document.getElementById('watch-btn');
  const rect = btn.getBoundingClientRect();
  el.style.left = (rect.left + rect.width / 2 - 30) + 'px';
  el.style.top  = (rect.top - 10 + window.scrollY) + 'px';
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 1300);
}

function bumpBalance() {
  balDisplay.style.transform = 'scale(1.3)';
  balDisplay.style.color     = '#FFD700';
  balDisplay.style.textShadow = '0 0 30px rgba(255,215,0,0.8)';
  setTimeout(() => {
    balDisplay.style.transform  = '';
    balDisplay.style.color      = '';
    balDisplay.style.textShadow = '';
  }, 500);
}

/* ── TOAST ───────────────────────────────────── */
let toastTimer;
function showToast(msg, type = '') {
  const t    = document.getElementById('toast');
  const icon = document.getElementById('toast-icon');
  const icons = {
    success: 'fa-check-circle',
    warn:    'fa-exclamation-circle',
    error:   'fa-times-circle',
    '':      'fa-info-circle',
  };
  icon.className       = `fas ${icons[type] || 'fa-info-circle'}`;
  document.getElementById('toast-msg').textContent = msg;
  t.className          = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3000);
}

/* ── INIT USER PROFILE ───────────────────────── */
function initProfile() {
  const name     = tgUser?.first_name || 'User';
  const uid      = tgUser?.id || USER_ID || '------';
  const photoUrl = tgUser?.photo_url || '';

  document.getElementById('u-name').textContent = name;
  document.getElementById('u-id').textContent   = `ID: #${uid}`;
  document.getElementById('u-fallback').textContent = name.charAt(0).toUpperCase();

  const img = document.getElementById('u-img');
  if (photoUrl) {
    img.src = photoUrl;
  } else {
    img.style.display = 'none';
    document.getElementById('u-fallback').style.display = 'flex';
  }
}

/* ── RESUME COOLDOWN ON RELOAD ───────────────── */
function resumeCooldown() {
  if (!state.cooldown_until) return;
  const remaining = Math.ceil((new Date(state.cooldown_until) - new Date()) / 1000);
  if (remaining > 0) {
    watchBtn.disabled = true;
    watchCaption.textContent = `Next ad in ${remaining}s...`;
    startCooldown(remaining);
  }
}

/* ── BOOT ────────────────────────────────────── */
window.addEventListener('DOMContentLoaded', () => {
  loadState();
  dailyReset();
  initProfile();
  renderUI();
  resumeCooldown();
});
