'use strict';

let autoAcceptEnabled = false;
let currentPage    = 1;
let itemsPerPage   = 20;
let _lastMatchCount = 0;

// ── 時鐘 ───────────────────────────────────────────────────────────────
(function tickClock() {
  const pad = n => String(n).padStart(2, '0');
  const el  = document.getElementById('clock');
  setInterval(() => {
    const n = new Date();
    el.textContent = `${pad(n.getHours())}:${pad(n.getMinutes())}:${pad(n.getSeconds())}`;
  }, 1000);
})();

// ── 頁籤切換 ────────────────────────────────────────────────────────────
function switchTab(tab) {
  // 隱藏所有 section
  document.querySelectorAll('.tab-section').forEach(s => s.classList.add('hidden'));
  // 移除所有 nav active
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));

  // 顯示目標 section
  document.getElementById(`tab-${tab}`).classList.remove('hidden');
  // 標記目標 nav
  document.getElementById(`nav-${tab}`).classList.add('active');
}

// ── 日誌 ───────────────────────────────────────────────────────────────
eel.expose(append_log);
function append_log(msg, highlight = false) {
  const container = document.getElementById('log');
  const n   = new Date();
  const pad = x => String(x).padStart(2, '0');
  const ts  = `${pad(n.getHours())}:${pad(n.getMinutes())}:${pad(n.getSeconds())}`;

  const row = document.createElement('div');
  row.className = 'log-line';
  row.innerHTML =
    `<span class="log-ts">[${ts}]</span>` +
    `<span class="log-arrow">▶</span>` +
    `<span class="log-msg${highlight ? ' highlight' : ''}">${msg}</span>`;
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
}

function clearLog() {
  document.getElementById('log').innerHTML = '';
}

// ── 配對接受閃光 ────────────────────────────────────────────────────────
eel.expose(on_match_accepted);
function on_match_accepted() {
  const flash = document.getElementById('accept-flash');
  flash.classList.remove('flashing');
  void flash.offsetWidth;
  flash.classList.add('flashing');
  append_log('自動接受 ▶▶ 配對已確認 ✓', true);
  setTimeout(() => flash.classList.remove('flashing'), 700);
}

// 安全取 DOM 元素，避免 null 炸掉整個 updateUI
function _el(id) {
  const el = document.getElementById(id);
  if (!el) console.error(`[LCU] 找不到 DOM 元素: #${id}`);
  return el;
}
function _setText(id, val)  { const e = _el(id); if (e) e.textContent = val; }
function _setHtml(id, val)  { const e = _el(id); if (e) e.innerHTML   = val; }
function _setStyle(id, prop, val) { const e = _el(id); if (e) e.style[prop] = val; }

// ── 更新 UI ────────────────────────────────────────────────────────────
function updateUI(data) {
  if (!data || !data.ok) {
    _setHtml('summoner-name', '<span style="color:#7f1d1d;font-size:13px;">── 離線 ──</span>');
    _setText('summoner-level', '---');
    _setText('lcu-port', '---');
    _setText('lcu-port-settings', '---');
    _setStyle('level-bar', 'width', '0%');
    setStatusOffline();
    return;
  }

  typewrite('summoner-name', data.name, 'text-lg text-cyan-300 glow-cyan tracking-wide');
  _setText('lcu-port', data.port);
  _setText('lcu-port-settings', data.port);
  _setText('summoner-level', data.level);

  requestAnimationFrame(() => {
    setTimeout(() => {
      document.getElementById('level-bar').style.width =
        Math.min((data.level / 1000) * 100, 100) + '%';
    }, 200);
  });

  setStatusOnline();

  const iconId = parseInt(data.iconId, 10);
  if (iconId > 0) {
    const avatarPath = '/lol-game-data/assets/v1/profile-icons/' + iconId + '.jpg';
    eel.get_lcu_image_base64(avatarPath)()
      .then(src => {
        if (src) document.getElementById('avatar-img').src = src;
        else append_log('AVATAR_WARN >> proxy empty for iconId=' + iconId);
      });
  }

  loadRankInfo();
  loadMatchHistory();
}

function setStatusOnline() {
  const st = document.getElementById('status-text');
  st.textContent = '連線正常';
  st.className   = 'text-[10px] glow-green transition-all duration-500';
  document.getElementById('status-dot').className = 'w-2 h-2 shrink-0 status-online';
  const lbl = document.getElementById('status-label');
  lbl.textContent = '已連線';
  lbl.className   = 'text-[10px] text-green-500';
}

function setStatusOffline() {
  const st = document.getElementById('status-text');
  st.textContent = '未連線';
  st.className   = 'text-[10px] text-red-800 transition-all duration-500';
  document.getElementById('status-dot').className = 'w-2 h-2 shrink-0 bg-red-900';
  const lbl = document.getElementById('status-label');
  lbl.textContent = '離線';
  lbl.className   = 'text-[10px] text-red-900';
}

// ── 打字機效果 ──────────────────────────────────────────────────────────
function typewrite(id, text, className) {
  const el = document.getElementById(id);
  el.className   = className;
  el.textContent = '';
  let i = 0;
  const iv = setInterval(() => {
    if (i < text.length) { el.textContent += text[i++]; }
    else clearInterval(iv);
  }, 35);
}

// ── 牌位資訊載入 ────────────────────────────────────────────────────────
async function loadRankInfo() {
  const info = await eel.get_rank_info()();
  if (!info) return;
  _renderRank('solo', info.solo);
  _renderRank('flex', info.flex);
}

function _renderRank(type, rank) {
  if (!rank) return;
  _setText('rank-' + type + '-text', rank.text || '未定級');
  _setText('rank-' + type + '-lp',   rank.tier !== 'UNRANKED' ? (rank.lp || '') : '');
  if (rank.tier && rank.tier !== 'UNRANKED') {
    document.getElementById('rank-' + type + '-img').src =
      'https://opgg-static.akamaized.net/images/medals_new/' + rank.tier.toLowerCase() + '.png';
  }
}

// ── 作戰紀錄載入 ────────────────────────────────────────────────────────
async function loadMatchHistory() {
  const list = document.getElementById('match-list');

  list.innerHTML =
    '<div class="py-6 text-center text-[10px] text-slate-700 tracking-widest">' +
    '<span class="placeholder-block">██████████████████████</span>' +
    '<span class="blink text-cyan-800 ml-1">▮</span></div>';

  _updatePaginationUI(true);

  const begIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = currentPage * itemsPerPage;
  const matches  = await eel.get_match_history(begIndex, endIndex)();
  list.innerHTML = '';

  _lastMatchCount = matches ? matches.length : 0;
  _updatePaginationUI(false);

  if (!matches || matches.length === 0) {
    list.innerHTML =
      '<div class="py-8 text-center text-[10px] text-slate-700 tracking-[0.2em]">' +
      '── 尚無對局紀錄 ──</div>';
    return;
  }

  for (const m of matches) {
    const card = _buildMatchCard(m);
    list.appendChild(card);
    _loadChampIcon(m.championId, card.querySelector('.champ-img'));
    _loadItemIcons(m.items || [], card.querySelectorAll('.item-icon'));
  }
}

function _updatePaginationUI(loading) {
  const pageEl = document.getElementById('current-page');
  const prevBtn = document.getElementById('prev-page');
  const nextBtn = document.getElementById('next-page');
  if (pageEl) pageEl.textContent = currentPage;
  if (prevBtn) prevBtn.disabled = loading || currentPage <= 1;
  if (nextBtn) nextBtn.disabled = loading || _lastMatchCount < itemsPerPage;
}

async function _loadChampIcon(champId, imgEl) {
  const paths = [
    `/lol-game-data/assets/v1/champion-icons/${champId}.png`,
    `/lol-game-data/assets/v1/champions/${champId}.png`,
  ];
  for (const p of paths) {
    const src = await eel.get_lcu_image_base64(p)();
    if (src) { imgEl.src = src; return; }
  }
}

async function _loadItemIcons(items, iconEls) {
  for (let i = 0; i < iconEls.length; i++) {
    const id = items[i] || 0;
    if (!id) continue;
    const src = await eel.get_item_image_base64_by_id(id)();
    if (src) {
      iconEls[i].src = src;
      iconEls[i].classList.remove('empty');
    }
  }
}

const queueMap = {
  420: '單雙積分', 440: '彈性積分', 450: '隨機單中',
  430: '盲選模式', 400: '一般對戰', 490: '快速對戰', 1700: '競技場',
};

function _buildMatchCard(m) {
  const card = document.createElement('div');
  card.className = `match-card ${m.win ? 'win' : 'loss'}`;

  const kda       = m.deaths === 0
    ? '<span style="color:#fbbf24">完美</span>'
    : ((m.kills + m.assists) / m.deaths).toFixed(2);
  const mins      = Math.floor(m.duration / 60);
  const secs      = String(m.duration % 60).padStart(2, '0');
  const queueName = queueMap[m.queueId] || m.queue || '一般對戰';

  const PLACEHOLDER = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E";

  const itemsHtml = (m.items || [0,0,0,0,0,0]).slice(0, 6).map(() =>
    `<img src="${PLACEHOLDER}" class="item-icon empty" alt="">`
  ).join('');

  card.innerHTML = `
    <img src="${PLACEHOLDER}" class="champ-img" alt="${m.championName}" title="${m.championName}">
    <div class="card-content">
      <div class="card-row">
        <span class="champ-name" style="width:90px;flex-shrink:0">${m.championName}</span>
        <div class="kda-block">
          <span class="k">${m.kills}</span><span class="sep">/</span>
          <span class="d">${m.deaths}</span><span class="sep">/</span>
          <span class="a">${m.assists}</span>
          <span class="ratio">比率 ${kda}</span>
        </div>
        <div class="flex-1"></div>
        <div class="result ${m.win ? 'win-badge' : 'loss-badge'}">${m.win ? '[ 勝利 ]' : '[ 失敗 ]'}</div>
      </div>
      <div class="card-row">
        <span class="game-mode" style="width:90px;flex-shrink:0">${queueName}</span>
        <div class="items-row">${itemsHtml}</div>
        <div class="flex-1"></div>
        <span class="duration">${mins}:${secs}</span>
      </div>
    </div>`;

  return card;
}

// ── 自動接受開關 ────────────────────────────────────────────────────────
function toggleAutoAccept() {
  autoAcceptEnabled = !autoAcceptEnabled;

  const btn  = document.getElementById('auto-accept-btn');
  const lbl  = document.getElementById('aa-label');
  const ind  = document.getElementById('aa-indicator');
  const desc = document.getElementById('aa-desc');

  if (autoAcceptEnabled) {
    btn.classList.add('engaged');
    lbl.innerHTML = '<span class="glow-orange">[ 自動接受對局：已啟動 ]</span>';
    ind.className = 'w-3 h-3 bg-orange-500 border-2 border-orange-400 transition-all duration-300 shadow-[0_0_8px_rgba(251,146,60,0.8)] shrink-0';
    desc.innerHTML = '<span style="color:rgba(251,146,60,0.55)">協議已啟動，偵測到配對時自動接受。</span>';
  } else {
    btn.classList.remove('engaged');
    lbl.textContent = '[ 自動接受對局 ]';
    lbl.style       = '';
    ind.className   = 'w-3 h-3 border-2 border-slate-700 bg-transparent transition-all duration-300 shrink-0';
    desc.innerHTML  =
      '偵測到 <span style="color:#475569">InProgress</span> 配對狀態時自動接受。';
  }

  eel.set_auto_accept(autoAcceptEnabled);
}

// ── 重新連線 ────────────────────────────────────────────────────────────
async function doReconnect() {
  document.getElementById('summoner-name').innerHTML =
    '<span class="placeholder-block">████████████</span><span class="blink text-cyan-700">▮</span>';
  document.getElementById('summoner-level').textContent = '---';
  document.getElementById('lcu-port').textContent        = '---';
  document.getElementById('lcu-port-settings').textContent = '---';
  document.getElementById('level-bar').style.width       = '0%';
  document.getElementById('avatar-img').src =
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E";

  const st = document.getElementById('status-text');
  st.textContent = '重新連線中...';
  st.className   = 'text-[10px] text-yellow-600 transition-all duration-500';

  const data = await eel.reconnect()();
  updateUI(data);
}

// ── 初始化 ─────────────────────────────────────────────────────────────
window.addEventListener('load', async () => {
  append_log('SYS >> 終端介面 V4 初始化完成');

  document.getElementById('items-per-page').addEventListener('change', function () {
    itemsPerPage = parseInt(this.value, 10);
    currentPage  = 1;
    loadMatchHistory();
  });

  document.getElementById('prev-page').addEventListener('click', () => {
    if (currentPage > 1) { currentPage--; loadMatchHistory(); }
  });

  document.getElementById('next-page').addEventListener('click', () => {
    if (_lastMatchCount >= itemsPerPage) { currentPage++; loadMatchHistory(); }
  });

  try {
    const data = await eel.initialize()();
    updateUI(data);
  } catch (err) {
    append_log(`JS_ERR >> ${err}`, true);
  }
});
