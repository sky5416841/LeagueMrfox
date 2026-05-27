'use strict';

// Tailwind CDN 會在 body 注入浮水印徽章，偵測並移除非己方元素
(function removeCdnBadge() {
  const ours = new Set(['accept-flash', 'game-modal']);
  function sweep() {
    document.querySelectorAll('body > div').forEach(el => {
      if (ours.has(el.id) || el.classList.contains('scanlines')) return;
      el.remove();
    });
  }
  document.addEventListener('DOMContentLoaded', sweep);
  window.addEventListener('load', sweep);
  new MutationObserver(sweep).observe(document.body, { childList: true });
})();

let autoAcceptEnabled  = false;
let autoPickEnabled    = false;
let autoPickChampId    = 0;
let autoBanEnabled     = false;
let autoBanChampId     = 0;
let currentPage    = 1;
let itemsPerPage   = 20;
let _lastMatchCount = 0;
let _champList     = [];   // [{id, name}, ...]

// ── 共用圖片佔位符 ──────────────────────────────────────────────────────
const IMG_PH  = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E";
const IMG_ERR = "this.onerror=null;this.classList.add('img-err')";

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
  document.querySelectorAll('.tab-section').forEach(s => s.classList.add('hidden'));
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  document.getElementById(`tab-${tab}`).classList.remove('hidden');
  document.getElementById(`nav-${tab}`).classList.add('active');
  if (tab === 'analytics') loadAnalytics();
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

// ── 自動選角鎖定回調 ────────────────────────────────────────────────────
eel.expose(on_auto_pick_done);
function on_auto_pick_done(champId) {
  const name = _champNameById(champId);
  append_log(`AUTO_PICK ▶▶ ${name} 已秒選鎖定 ✓✓`, true);
  const flash = document.getElementById('accept-flash');
  flash.classList.remove('flashing');
  void flash.offsetWidth;
  flash.classList.add('flashing');
  setTimeout(() => flash.classList.remove('flashing'), 700);
}

// ── 自動禁角確認回調 ────────────────────────────────────────────────────
eel.expose(on_auto_ban_done);
function on_auto_ban_done(champId) {
  const name = _champNameById(champId);
  append_log(`AUTO_BAN ▶▶ ${name} 已禁用確認 ✓✓`, true);
  const flash = document.getElementById('accept-flash');
  flash.classList.remove('flashing');
  void flash.offsetWidth;
  flash.classList.add('flashing');
  setTimeout(() => flash.classList.remove('flashing'), 700);
}

// ── 大廳 X 光機回調 ────────────────────────────────────────────────────
eel.expose(on_lobby_scan_ready);
function on_lobby_scan_ready(players) {
  append_log(`LOBBY_SCAN ▶▶ 情報就緒 (${players.length} 位)`, true);

  const statusEl  = document.getElementById('live-status');
  const playersEl = document.getElementById('live-players');
  if (statusEl) statusEl.textContent = `掃描完成 · ${players.length} 位成員`;

  if (!playersEl) return;

  const allies  = players.filter(p => !p.isEnemy);
  const enemies = players.filter(p =>  p.isEnemy);

  if (enemies.length > 0) {
    // ARAM 模式：雙方選角均可見，用雙欄呈現完整情報
    playersEl.innerHTML = `
      <div class="ingame-panel">
        <div class="ingame-team-col">
          <div class="ingame-team-hdr ingame-team-hdr-blue">// 我方</div>
          ${allies.map(p => _renderLiveCard(p)).join('')}
        </div>
        <div class="ingame-divider"></div>
        <div class="ingame-team-col">
          <div class="ingame-team-hdr ingame-team-hdr-red">// 敵方 [ARAM]</div>
          ${enemies.map(p => _renderLiveCard(p)).join('')}
        </div>
      </div>`;
  } else {
    // 一般模式：單欄顯示隊友
    playersEl.innerHTML = players.map(p => _renderLiveCard(p)).join('');
  }

  switchTab('live');
}

eel.expose(on_champ_select_ended);
function on_champ_select_ended(phase) {
  const badge  = document.getElementById('live-phase-badge');
  const status = document.getElementById('live-status');
  if (phase === 'InProgress') {
    if (badge)  badge.textContent  = '[ 遊戲進行中 · 10人雷達啟動中... ]';
    if (status) status.textContent = '已進入遊戲，正在掃描全場 10 人戰力...';
  } else {
    if (badge)  badge.textContent  = '[ 對局結束 ]';
    if (status) status.textContent = '對局已結束，以下為本場情報紀錄。';
  }
  append_log(`GAMEFLOW ▶▶ ${phase}`, true);

  // EndOfGame = 玩家已離開結算畫面，此時 LCU 已完成戰績寫入，自動刷新第一頁
  if (phase === 'EndOfGame') {
    setTimeout(() => {
      append_log('AUTO_REFRESH ▶▶ 對局結束，自動刷新戰績第一頁...', true);
      currentPage = 1;
      loadMatchHistory();
    }, 4000);
  }
}

// ── 遊戲中 10 人雷達回調 ──────────────────────────────────────────────
eel.expose(on_ingame_scan_ready);
function on_ingame_scan_ready(data) {
  append_log(`INGAME_SCAN ▶▶ 10 人雷達就緒 (友方 ${data.myTeam.length} + 敵方 ${data.enemyTeam.length})`, true);

  const statusEl  = document.getElementById('live-status');
  const playersEl = document.getElementById('live-players');
  const badge     = document.getElementById('live-phase-badge');

  if (statusEl) statusEl.textContent = `遊戲進行中 · 友方 ${data.myTeam.length} 人 vs 敵方 ${data.enemyTeam.length} 人`;
  if (badge)    badge.textContent    = '[ 遊戲進行中 ]';

  if (!playersEl) return;

  playersEl.innerHTML = `
    <div class="ingame-panel">
      <div class="ingame-team-col">
        <div class="ingame-team-hdr ingame-team-hdr-blue">// 友方</div>
        ${data.myTeam.map(p => _renderLiveCard(p)).join('')}
      </div>
      <div class="ingame-divider"></div>
      <div class="ingame-team-col">
        <div class="ingame-team-hdr ingame-team-hdr-red">// 敵方</div>
        ${data.enemyTeam.map(p => _renderLiveCard(p)).join('')}
      </div>
    </div>`;

  // 非同步載入英雄頭像
  playersEl.querySelectorAll('[data-champid]').forEach(img => {
    _loadChampIcon(parseInt(img.dataset.champid), img);
  });

  switchTab('live');
}

function _renderLiveCard(p) {
  const isAnon   = p.anonymous;
  const isSelf   = p.isSelf;
  const isEnemy  = p.isEnemy;
  const noData   = p.total === 0;
  const wr       = p.winRate || 0;
  const hasChamp = p.championId && p.championId > 0;

  // 段位資訊
  const isUnranked = !p.tier || ['UNRANKED', 'NONE', 'NA', ''].includes(p.tier);
  const rankWrColor = (p.rankWinRate || 0) >= 60 ? '#4ade80'
    : (p.rankWinRate || 0) >= 50 ? '#a3e635'
    : (p.rankWinRate || 0) >= 40 ? '#fb923c' : '#f87171';
  const rankHtml = isUnranked
    ? '<div class="live-rank-row live-rank-unranked">未排位</div>'
    : `<div class="live-rank-row">
         <span class="live-rank-text">${p.tierText || ''}</span>
         <span class="live-rank-sep">·</span>
         <span class="live-rank-wr" style="color:${rankWrColor}">${p.rankWinRate || 0}%</span>
         <span class="live-rank-lp">${p.lp || 0} LP</span>
       </div>`;

  // 標籤
  let badge = '';
  if (isSelf) {
    badge = '<span class="live-badge live-badge-self">[ 你 ]</span>';
  } else if (!isAnon && !noData) {
    if (wr >= 60) badge = '<span class="live-badge live-badge-ace">[ ⭐ 絕活大腿 ]</span>';
    else if (wr < 40) badge = '<span class="live-badge live-badge-danger">[ 🚨 避雷警告 ]</span>';
  }

  // 勝率顏色
  const wrColor = wr >= 60 ? '#4ade80' : wr >= 50 ? '#a3e635' : wr >= 40 ? '#fb923c' : '#f87171';

  // 名稱 + 英雄名稱（遊戲中模式）
  const nameHtml = isAnon
    ? '<span class="text-slate-600 italic">匿名玩家</span>'
    : `<span class="text-slate-200 tracking-wide">${p.name}</span>`;
  const champTag = hasChamp && p.championName
    ? `<span class="text-[9px] text-slate-600 tracking-wider">[${p.championName}]</span>`
    : '';

  // 戰績區（匿名玩家只要有 PUUID 資料就照樣顯示，不隱藏）
  const statsHtml = (isAnon && noData) ? '<div class="text-[10px] text-slate-500 italic">— 匿名 · 無資料 —</div>'
    : noData
    ? `<div class="text-[10px] text-slate-700">${p.error ? '抓取失敗' : '無戰績資料'}</div>`
    : `<div class="flex items-center gap-4 mt-1">
         <div class="text-[10px]">
           <span class="text-slate-600">近${p.total}場</span>
           <span class="ml-1" style="color:${wrColor}">${wr}%</span>
           <span class="text-slate-700 ml-1">${p.wins}W ${p.total - p.wins}L</span>
         </div>
         <div class="text-[10px] text-slate-500">
           KDA <span class="text-slate-400">${p.kda}</span>
           <span class="text-slate-700 ml-2">${p.avgKills}/${p.avgDeaths}/${p.avgAssists}</span>
         </div>
       </div>
       <div class="live-wr-bar mt-1">
         <div class="live-wr-fill" style="width:${wr}%;background:${wrColor}"></div>
       </div>`;

  const selfClass  = isSelf  ? ' live-card-self'  : '';
  const enemyClass = isEnemy ? ' live-card-enemy' : '';

  // 左側圖示：有英雄時顯示頭像，選角大廳時顯示 cellId 數字
  const iconHtml = hasChamp
    ? `<div class="live-champ-icon">
         <img class="w-full h-full object-cover" src="${IMG_PH}" ${IMG_ERR}
              data-champid="${p.championId}" alt="${p.championName || ''}">
       </div>`
    : `<div class="live-cell-id">${p.cellId ?? ''}</div>`;

  return `
    <div class="live-card${selfClass}${enemyClass}">
      <div class="flex items-center gap-3">
        ${iconHtml}
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">${nameHtml}${champTag}${badge}</div>
          ${rankHtml}
          ${statsHtml}
        </div>
      </div>
    </div>`;
}

// ── 英雄選擇器 ─────────────────────────────────────────────────────────
function _champNameById(id) {
  const c = _champList.find(c => c.id === id);
  return c ? c.name : `ID=${id}`;
}

async function _loadChampionList() {
  try {
    _champList = await eel.get_champion_list()();
    append_log(`CHAMP_LIST >> 已載入 ${_champList.length} 位英雄至選擇器`);
  } catch (e) {
    append_log(`CHAMP_LIST_ERR >> ${e}`, true);
  }
}

function _renderChampDropdown(query) {
  const dd = document.getElementById('champ-picker-dropdown');
  if (!dd) return;
  const q    = (query || '').trim().toLowerCase();
  const filtered = _champList.filter(c => {
    if (!c.name || c.id <= 0) return false;
    if (c.name.includes('末日')) return false;
    if (c.name.includes('NPC'))  return false;
    return true;
  });
  const list = q ? filtered.filter(c => c.name.toLowerCase().includes(q)) : filtered;
  const show = list.slice(0, 80);

  if (list.length === 0) {
    dd.innerHTML = '<div class="champ-picker-more">找不到符合的英雄</div>';
    return;
  }
  dd.innerHTML = show.map(c =>
    `<div class="champ-picker-item${autoPickChampId === c.id ? ' selected' : ''}"
          onclick="selectChamp(${c.id},'${c.name.replace(/'/g, "\\'")}')">
       ${c.name}
     </div>`
  ).join('');
  if (list.length > 80) {
    dd.innerHTML += `<div class="champ-picker-more">...還有 ${list.length - 80} 位，請輸入更精確名稱</div>`;
  }
}

function openChampPicker() {
  const dd = document.getElementById('champ-picker-dropdown');
  if (dd) dd.classList.remove('hidden');
  _renderChampDropdown(document.getElementById('ap-champ-search').value);
}

function filterChampPicker(query) {
  const dd = document.getElementById('champ-picker-dropdown');
  if (dd) dd.classList.remove('hidden');
  _renderChampDropdown(query);
}

function selectChamp(id, name) {
  autoPickChampId = id;
  const input = document.getElementById('ap-champ-search');
  if (input) input.value = name;
  const hint  = document.getElementById('ap-champ-hint');
  if (hint)  hint.textContent = `ID=${id}`;
  const dd = document.getElementById('champ-picker-dropdown');
  if (dd) dd.classList.add('hidden');
  if (autoPickEnabled) eel.set_auto_pick(autoPickEnabled, autoPickChampId);
}

// ── 禁角英雄選擇器 ─────────────────────────────────────────────────────
function _renderBanDropdown(query) {
  const dd = document.getElementById('ban-picker-dropdown');
  if (!dd) return;
  const q        = (query || '').trim().toLowerCase();
  const filtered = _champList.filter(c => c.name && c.id > 0 && !c.name.includes('末日') && !c.name.includes('NPC'));
  const list     = q ? filtered.filter(c => c.name.toLowerCase().includes(q)) : filtered;
  const show     = list.slice(0, 80);
  if (list.length === 0) {
    dd.innerHTML = '<div class="champ-picker-more">找不到符合的英雄</div>';
    return;
  }
  dd.innerHTML = show.map(c =>
    `<div class="champ-picker-item${autoBanChampId === c.id ? ' selected' : ''}"
          onclick="selectBanChamp(${c.id},'${c.name.replace(/'/g, "\\'")}')">
       ${c.name}
     </div>`
  ).join('');
  if (list.length > 80) {
    dd.innerHTML += `<div class="champ-picker-more">...還有 ${list.length - 80} 位，請輸入更精確名稱</div>`;
  }
}

function openBanPicker() {
  const dd = document.getElementById('ban-picker-dropdown');
  if (dd) dd.classList.remove('hidden');
  _renderBanDropdown(document.getElementById('ab-champ-search').value);
}

function filterBanPicker(query) {
  const dd = document.getElementById('ban-picker-dropdown');
  if (dd) dd.classList.remove('hidden');
  _renderBanDropdown(query);
}

function selectBanChamp(id, name) {
  autoBanChampId = id;
  const input = document.getElementById('ab-champ-search');
  if (input) input.value = name;
  const hint = document.getElementById('ab-champ-hint');
  if (hint) hint.textContent = `ID=${id}`;
  const dd = document.getElementById('ban-picker-dropdown');
  if (dd) dd.classList.add('hidden');
  if (autoBanEnabled) eel.set_auto_ban(autoBanEnabled, autoBanChampId);
}

// 點選選擇器外部時關閉下拉
document.addEventListener('click', (e) => {
  const wrap = document.getElementById('champ-picker-wrap');
  if (wrap && !wrap.contains(e.target)) {
    const dd = document.getElementById('champ-picker-dropdown');
    if (dd) dd.classList.add('hidden');
  }
  const banWrap = document.getElementById('ban-picker-wrap');
  if (banWrap && !banWrap.contains(e.target)) {
    const dd = document.getElementById('ban-picker-dropdown');
    if (dd) dd.classList.add('hidden');
  }
});

// ESC 同時關閉選擇器與 Modal
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  const dd = document.getElementById('champ-picker-dropdown');
  if (dd) dd.classList.add('hidden');
  closeGameModal();
});

// ── 自動選角開關 ────────────────────────────────────────────────────────
function toggleAutoPick() {
  autoPickEnabled = !autoPickEnabled;

  const btn  = document.getElementById('auto-pick-btn');
  const lbl  = document.getElementById('ap-label');
  const ind  = document.getElementById('ap-indicator');
  const desc = document.getElementById('ap-desc');

  if (autoPickEnabled) {
    btn.classList.add('engaged');
    lbl.innerHTML = '<span class="glow-orange">[ 自動選角：已啟動 ]</span>';
    ind.className = 'w-3 h-3 bg-orange-500 border-2 border-orange-400 transition-all duration-300 shadow-[0_0_8px_rgba(251,146,60,0.8)] shrink-0';
    desc.innerHTML = '<span style="color:rgba(251,146,60,0.55)">偵測到選角輪到行動時，自動秒選並鎖定。</span>';
  } else {
    btn.classList.remove('engaged');
    lbl.textContent = '[ 自動選角 ]';
    lbl.style       = '';
    ind.className   = 'w-3 h-3 border-2 border-slate-700 bg-transparent transition-all duration-300 shrink-0';
    desc.innerHTML  = '選角階段輪到行動時，自動秒選並鎖定指定英雄。';
  }

  eel.set_auto_pick(autoPickEnabled, autoPickChampId);
}

// ── 自動禁角開關 ────────────────────────────────────────────────────────
function toggleAutoBan() {
  autoBanEnabled = !autoBanEnabled;

  const btn  = document.getElementById('auto-ban-btn');
  const lbl  = document.getElementById('ab-label');
  const ind  = document.getElementById('ab-indicator');
  const desc = document.getElementById('ab-desc');

  if (autoBanEnabled) {
    btn.classList.add('engaged');
    lbl.innerHTML = '<span class="glow-red">[ 自動禁角：已啟動 ]</span>';
    ind.className = 'w-3 h-3 bg-red-500 border-2 border-red-400 transition-all duration-300 shadow-[0_0_8px_rgba(239,68,68,0.8)] shrink-0';
    desc.innerHTML = '<span style="color:rgba(239,68,68,0.55)">偵測到禁角輪到行動時，自動禁用目標英雄。</span>';
  } else {
    btn.classList.remove('engaged');
    lbl.textContent = '[ 自動禁角 ]';
    lbl.style       = '';
    ind.className   = 'w-3 h-3 border-2 border-slate-700 bg-transparent transition-all duration-300 shrink-0';
    desc.innerHTML  = '禁角階段輪到行動時，自動禁用指定英雄。';
  }

  eel.set_auto_ban(autoBanEnabled, autoBanChampId);
}

// ── 英雄分析 ────────────────────────────────────────────────────────────
async function loadAnalytics() {
  const statusEl  = document.getElementById('analytics-status');
  const aceEl     = document.getElementById('analytics-ace');
  const dangerEl  = document.getElementById('analytics-danger');
  if (!statusEl) return;

  statusEl.textContent = '資料載入中，最多取回 200 場...';
  aceEl.innerHTML    = '<div class="text-[10px] text-slate-700 tracking-widest">載入中...</div>';
  dangerEl.innerHTML = '<div class="text-[10px] text-slate-700 tracking-widest">載入中...</div>';

  try {
    const data = await eel.get_champion_analytics(200)();
    if (!data || data.length === 0) {
      statusEl.textContent = '暫無資料（需至少 3 場同英雄戰績）';
      aceEl.innerHTML    = '<div class="text-[10px] text-slate-700">— 無資料 —</div>';
      dangerEl.innerHTML = '<div class="text-[10px] text-slate-700">— 無資料 —</div>';
      return;
    }

    statusEl.textContent = `共統計 ${data.length} 位英雄（≥3 場）`;

    const ace    = data.slice(0, 5);
    const danger = data.slice().sort((a, b) => a.winRate - b.winRate).slice(0, 3);
    const maxDmg = Math.max(...data.map(d => d.avgDamage), 1);

    function renderCard(champ, glowClass) {
      const wrColor = champ.winRate >= 60 ? '#4ade80'
                    : champ.winRate >= 50 ? '#a3e635'
                    : champ.winRate >= 40 ? '#fb923c'
                    : '#f87171';
      const barPct  = Math.round(champ.winRate);
      const dmgPct  = Math.round(champ.avgDamage / maxDmg * 100);
      return `
        <div class="analytics-card ${glowClass}">
          <div class="flex items-center gap-3 mb-2">
            <div class="analytics-champ-icon">
              <img class="w-full h-full object-cover rounded"
                   src="${IMG_PH}" ${IMG_ERR}
                   data-champid="${champ.championId}"
                   alt="${champ.name}">
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-xs tracking-widest text-slate-300 truncate">${champ.name}</div>
              <div class="text-[10px] text-slate-600 mt-0.5">${champ.games} 場 · KDA ${champ.avgKDA}</div>
            </div>
            <div class="text-right shrink-0">
              <div class="text-base font-bold" style="color:${wrColor}">${champ.winRate}%</div>
              <div class="text-[9px] text-slate-700">${champ.wins}W ${champ.games - champ.wins}L</div>
            </div>
          </div>
          <div class="analytics-bar-wrap">
            <div class="analytics-bar-label">勝率</div>
            <div class="analytics-bar-track">
              <div class="analytics-bar-fill" style="width:${barPct}%;background:${wrColor}"></div>
            </div>
            <div class="analytics-bar-label text-right" style="color:${wrColor}">${barPct}%</div>
          </div>
          <div class="analytics-bar-wrap mt-1">
            <div class="analytics-bar-label">均傷</div>
            <div class="analytics-bar-track">
              <div class="analytics-bar-fill" style="width:${dmgPct}%;background:#06b6d4"></div>
            </div>
            <div class="analytics-bar-label text-right text-cyan-800">${(champ.avgDamage/1000).toFixed(1)}k</div>
          </div>
        </div>`;
    }

    aceEl.innerHTML    = ace.map(c => renderCard(c, 'glow-card-ace')).join('');
    dangerEl.innerHTML = danger.map(c => renderCard(c, 'glow-card-danger')).join('');

    // 非同步載入英雄頭像
    aceEl.querySelectorAll('[data-champid]').forEach(img => {
      _loadChampIcon(parseInt(img.dataset.champid), img);
    });
    dangerEl.querySelectorAll('[data-champid]').forEach(img => {
      _loadChampIcon(parseInt(img.dataset.champid), img);
    });

  } catch (e) {
    statusEl.textContent = `載入失敗：${e}`;
    append_log(`ANALYTICS_ERR >> ${e}`, true);
  }
}

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

  const startIndex  = (currentPage - 1) * itemsPerPage;
  const targetCount = itemsPerPage;

  list.innerHTML =
    `<div class="py-6 text-center text-[10px] text-slate-700 tracking-widest">` +
    `<span class="placeholder-block">██████████████████████</span>` +
    `<span class="blink text-cyan-800 ml-1">▮</span>` +
    `<div class="mt-1 text-slate-600">// 載入第 ${currentPage} 頁，共 ${targetCount} 筆 (offset=${startIndex})...</div></div>`;

  _updatePaginationUI(true);
  append_log(`MATCH_HISTORY_REQ >> 第 ${currentPage} 頁，startIndex=${startIndex} targetCount=${targetCount}`);

  let matches = [];
  try {
    matches = await eel.get_match_history(startIndex, targetCount)();
  } catch (err) {
    append_log(`MATCH_ERR >> 後端通訊失敗: ${err}`, true);
    matches = [];
  }

  list.innerHTML = '';
  _lastMatchCount = Array.isArray(matches) ? matches.length : 0;
  _updatePaginationUI(false);
  append_log(`MATCH_HISTORY >> loaded ${_lastMatchCount} 筆對局 (第 ${currentPage} 頁，每頁 ${itemsPerPage} 筆)`);

  // ── 前端備援符文解析 ──────────────────────────────────────────────────
  // 若後端三格式解析仍回傳全零（部分版本 LCU 資料結構不同），
  // 直接在前端解析 perksRaw.styles[].selections[].perk 作為保底。
  for (const m of (matches || [])) {
    if (m.isArena || !m.perksRaw) continue;
    const hasRunes = (m.runes || []).some(id => id > 0);
    if (!hasRunes) {
      const parsed = [];
      for (const style of (m.perksRaw.styles || [])) {
        for (const sel of (style.selections || [])) {
          if (sel.perk) parsed.push(sel.perk);
        }
      }
      if (parsed.length === 0 && (m.perksRaw.perkIds || []).length > 0) {
        parsed.push(...m.perksRaw.perkIds.slice(0, 6));
      }
      if (parsed.length > 0) {
        m.runes = parsed.slice(0, 6);
        append_log(`PERK_FALLBACK >> gameId=${m.gameId} 前端解析出 ${parsed.length} 個符文 ID`);
      }
    }
    const hasStatPerks = (m.statPerks || []).some(id => id > 0);
    if (!hasStatPerks) {
      const sp   = m.perksRaw.statPerks || {};
      const pids = m.perksRaw.perkIds   || [];
      if (sp.offense || sp.flex || sp.defense) {
        m.statPerks = [sp.offense || 0, sp.flex || 0, sp.defense || 0];
      } else if (pids.length >= 9) {
        m.statPerks = pids.slice(6, 9);
      }
    }
  }

  if (!matches || matches.length === 0) {
    const isFirstPage = currentPage === 1;
    list.innerHTML = isFirstPage
      ? '<div class="no-more-records">── 尚無作戰紀錄 ──</div>'
      : '<div class="no-more-records">' +
          '<span class="no-more-bracket">[ EOF ]</span>' +
          ' // 查無更多作戰紀錄' +
          '<span class="no-more-hint">已抵達本地快取底部</span>' +
        '</div>';
    return;
  }

  for (const m of matches) {
    const card = _buildMatchCard(m);
    list.appendChild(card);
    _loadChampIcon(m.championId, card.querySelector('.champ-img'));
    _loadItemIcons(m.items || [], card.querySelectorAll('.item-icon'));
    _loadSpellIcons([m.spell1Id, m.spell2Id], card.querySelectorAll('.spell-icon'));
    if (m.isArena) {
      const validAugs = (m.augments || []).filter(a => a && a.id > 0);
      _loadAugmentIcons(validAugs.map(a => a.id), card.querySelectorAll('.mc-aug-icon'));
    } else {
      _loadRuneIcons((m.runes || []).filter(x => x > 0), card.querySelectorAll('.mc-rune-icon'));
    }
  }
}

function _updatePaginationUI(loading) {
  const pageEl  = document.getElementById('current-page');
  const prevBtn = document.getElementById('prev-page');
  const nextBtn = document.getElementById('next-page');
  if (pageEl)  pageEl.textContent  = currentPage;
  if (prevBtn) prevBtn.disabled    = loading || currentPage <= 1;
  if (nextBtn) nextBtn.disabled    = loading || _lastMatchCount < itemsPerPage;
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
    if (src) { iconEls[i].src = src; iconEls[i].classList.remove('empty'); }
  }
}

async function _loadRuneIcons(ids, iconEls) {
  for (let i = 0; i < iconEls.length; i++) {
    const id = ids[i] || 0;
    if (!id) continue;
    const src = await eel.get_perk_image_base64_by_id(id)();
    if (src) { iconEls[i].src = src; iconEls[i].classList.remove('empty'); }
  }
}

async function _loadAugmentIcons(ids, iconEls) {
  for (let i = 0; i < iconEls.length; i++) {
    const id = ids[i] || 0;
    if (!id) continue;
    const src = await eel.get_augment_image_base64_by_id(id)();
    if (src) {
      iconEls[i].src = src;
      iconEls[i].classList.remove('empty');
      iconEls[i].classList.add('augment-icon');
    }
  }
}

async function _loadPerkStyleIcon(styleId, imgEl) {
  if (!styleId || !imgEl) return;
  const src = await eel.get_perkstyle_image_base64_by_id(styleId)();
  if (src) { imgEl.src = src; imgEl.classList.remove('empty'); }
}

async function _loadSpellIcons(spells, iconEls) {
  for (let i = 0; i < iconEls.length; i++) {
    const id = spells[i] || 0;
    if (!id) continue;
    const src = await eel.get_spell_image_base64_by_id(id)();
    if (src) { iconEls[i].src = src; iconEls[i].classList.remove('empty'); }
  }
}

// ── 隊列名稱對照表 ──────────────────────────────────────────────────────
const queueMap = {
  420: '單雙積分',  440: '彈性積分',  450: '大亂鬥',
  430: '盲選模式',  400: '一般對戰',  490: '快速對戰',
  1700: '競技場',   700: '衝突',      900: 'URF',
  1020: '克隆模式', 1010: '雪球URF',  325: '輪替模式',
  1300: '節日模式', 830: 'AI對戰',    840: 'AI對戰',
  850: 'AI對戰',   1090: '鬥魂競技', 1100: '鬥魂競技',
  1111: '鬥魂競技', 2400: '隨機單中 : 大混戰',
};

// ── 戰績卡片 ────────────────────────────────────────────────────────────
function _buildMatchCard(m) {
  const card = document.createElement('div');
  const gr = m.gameResult || (m.win ? 'WIN' : 'LOSS');
  card.className = `match-card ${gr === 'REMAKE' ? 'remake' : m.win ? 'win' : 'loss'}`;

  // 有 gameId 則支援點擊展開 10 人詳細
  if (m.gameId) {
    card.style.cursor = 'pointer';
    card.title = '點擊查看 10 人完整戰績';
    card.addEventListener('click', () => openGameModal(m.gameId));
  }

  const kdaVal    = m.deaths === 0
    ? '<span style="color:#fbbf24">完美</span>'
    : ((m.kills + m.assists) / m.deaths).toFixed(2);
  const mins      = Math.floor(m.duration / 60);
  const secs      = String(m.duration % 60).padStart(2, '0');
  const queueName = queueMap[m.queueId] || `隊列(${m.queueId})`;
  const dmgStr    = m.damage ? m.damage.toLocaleString() + '傷' : '---';

  const itemsHtml = (m.items || [0,0,0,0,0,0]).slice(0, 6).map(() =>
    `<img src="${IMG_PH}" class="item-icon empty" alt="" onerror="${IMG_ERR}">`
  ).join('');

  // 稀有度邊框（與 Modal 一致）
  const _border = r => r >= 2 ? '1px solid #d946ef' : r === 1 ? '1px solid #eab308' : '1px solid #9ca3af';

  // 增幅裝置優先，無增幅才顯示符文，完全無資料留空
  let perkHtml = '';
  if (m.isArena) {
    const validAugs = (m.augments || []).filter(a => a && a.id > 0);
    perkHtml = validAugs.map(a =>
      `<img src="${IMG_PH}" class="mc-perk-img mc-aug-icon empty"
            style="border:${_border(a.rarity)}" alt=""
            onerror="this.onerror=null;this.style.display='none'">`
    ).join('');
  } else {
    const allPerks = (m.runes || []).filter(x => x > 0);
    perkHtml = allPerks.map(() =>
      `<img src="${IMG_PH}" class="mc-perk-img mc-rune-icon empty"
            alt="" onerror="this.onerror=null;this.style.display='none'">`
    ).join('');
  }

  card.innerHTML = `
    <div class="mc-left">
      <img src="${IMG_PH}" class="champ-img" alt="${m.championName}" title="${m.championName}" onerror="${IMG_ERR}">
      <div class="mc-spells">
        <img src="${IMG_PH}" class="spell-icon empty" alt="" onerror="${IMG_ERR}">
        <img src="${IMG_PH}" class="spell-icon empty" alt="" onerror="${IMG_ERR}">
      </div>
      <div class="mc-perk-wrap">${perkHtml}</div>
      <div class="mc-name">
        <span class="champ-name" title="${m.championName}">${m.championName}</span>
        <span class="game-mode">${queueName}</span>
      </div>
    </div>
    <div class="mc-mid">
      <div class="kda-block">
        <span class="k">${m.kills}</span><span class="sep">/</span>
        <span class="d">${m.deaths}</span><span class="sep">/</span>
        <span class="a">${m.assists}</span>
      </div>
      <span class="kda-ratio">${kdaVal} KDA</span>
      <span class="damage-val" style="margin-top:3px">${dmgStr}</span>
    </div>
    <div class="mc-right">
      <div class="mc-items">${itemsHtml}</div>
      <div class="mc-meta">
        <span class="duration">${mins}:${secs}</span>
        ${gr === 'REMAKE'
            ? '<div class="result remake-badge">[ 重開 ]</div>'
            : gr === 'SURRENDER_WIN'
              ? '<div class="result win-badge surrender-badge">[ 投降勝 ]</div>'
              : gr === 'SURRENDER_LOSS'
                ? '<div class="result loss-badge surrender-badge">[ 投降 ]</div>'
                : m.win
                  ? '<div class="result win-badge">[ 勝利 ]</div>'
                  : '<div class="result loss-badge">[ 失敗 ]</div>'
        }
      </div>
    </div>`;

  return card;
}

// ── 對局詳細 Modal ──────────────────────────────────────────────────────
async function openGameModal(gameId) {
  if (!gameId) return;
  const modal = document.getElementById('game-modal');
  modal.style.display = 'flex';

  document.getElementById('modal-meta').textContent    = `#${gameId}  //  資料載入中...`;
  document.getElementById('modal-blue-list').innerHTML = '<div class="modal-loading">▮ 藍隊資料載入中...</div>';
  document.getElementById('modal-red-list').innerHTML  = '<div class="modal-loading">▮ 紅隊資料載入中...</div>';

  try {
    const data = await eel.get_game_detail(gameId)();
    if (!data || (!data.blue && !data.red)) {
      document.getElementById('modal-meta').textContent    = `#${gameId}  //  載入失敗`;
      document.getElementById('modal-blue-list').innerHTML = '<div class="modal-loading">// 無法取得資料</div>';
      document.getElementById('modal-red-list').innerHTML  = '';
      return;
    }
    const mins = Math.floor((data.duration || 0) / 60);
    const secs = String((data.duration || 0) % 60).padStart(2, '0');
    document.getElementById('modal-meta').textContent = `#${gameId}  //  時長 ${mins}:${secs}`;

    // 計算全場最高傷害，用來繪製相對傷害長條圖
    const allPlayers    = [...(data.blue || []), ...(data.red || [])];
    const maxDamage     = Math.max(1, ...allPlayers.map(p => p.damage      || 0));
    const maxDamageTaken = Math.max(1, ...allPlayers.map(p => p.damageTaken || 0));

    try {
      const objs = data.objectives || {};
      _renderModalTeam('modal-blue-list', data.blue || [], maxDamage, maxDamageTaken, 'blue', objs[100] || objs['100'] || {});
      _renderModalTeam('modal-red-list',  data.red  || [], maxDamage, maxDamageTaken, 'red',  objs[200] || objs['200'] || {});
    } catch (renderErr) {
      console.error('Modal Render Error:', renderErr);
      document.getElementById('modal-blue-list').innerHTML = `<div class="modal-loading">// 渲染失敗: ${renderErr.message}</div>`;
      document.getElementById('modal-red-list').innerHTML  = '';
    }
  } catch (e) {
    console.error('Modal Load Error:', e);
    append_log(`MODAL_ERR >> ${e}`, true);
    document.getElementById('modal-meta').textContent     = `#${gameId}  //  連線錯誤`;
    document.getElementById('modal-blue-list').innerHTML  = '<div class="modal-loading">// 資料取得失敗，請查看 Console</div>';
    document.getElementById('modal-red-list').innerHTML   = '';
  }
}

function closeGameModal() {
  const modal = document.getElementById('game-modal');
  if (modal) modal.style.display = 'none';
}

function _renderModalTeam(sectionId, players, maxDamage, maxDamageTaken, teamColor, objectives) {
  const section = document.getElementById(sectionId);
  section.innerHTML = '';
  const obj = objectives || {};

  // ── 隊伍標題（勝敗 + 總計 KDA + 地圖目標）──
  const teamName = teamColor === 'blue' ? '藍隊' : '紅隊';
  const teamWin  = players.length > 0 && players[0].win;
  const winLabel = teamWin ? '勝利' : '失敗';
  const winColor = teamWin ? (teamColor === 'blue' ? '#22d3ee' : '#34d399') : '#f87171';
  const totalK   = players.reduce((s, p) => s + (p.kills   || 0), 0);
  const totalD   = players.reduce((s, p) => s + (p.deaths  || 0), 0);
  const totalA   = players.reduce((s, p) => s + (p.assists || 0), 0);
  const hdr = document.createElement('div');
  hdr.className = `mt-team-hdr ${teamColor}-hdr`;
  hdr.innerHTML =
    `<span><span style="color:${winColor}">[ ${winLabel} ]</span>  ◈ ${teamName}</span>` +
    `<span class="mt-hdr-right">` +
      `<span class="mt-team-objs">` +
        `<span class="mt-obj">🐉 ${obj.dragon    || 0}</span>` +
        `<span class="mt-obj">👾 ${obj.baron     || 0}</span>` +
        `<span class="mt-obj">🗼 ${obj.tower     || 0}</span>` +
        `<span class="mt-obj">🏚 ${obj.inhibitor || 0}</span>` +
      `</span>` +
      `<span class="mt-team-total">${totalK} <span style="color:#475569">/</span> ` +
        `<span style="color:#f87171">${totalD}</span> <span style="color:#475569">/</span> ${totalA}</span>` +
    `</span>`;
  section.appendChild(hdr);

  // ── 表頭列（欄位需與玩家列固定寬度嚴格對齊）──
  const colHdr = document.createElement('div');
  colHdr.className = 'mt-col-hdr';
  colHdr.innerHTML =
    `<div class="mt-ch-identity">英雄</div>` +
    `<div class="mt-ch-kda">KDA</div>` +
    `<div class="mt-ch-aug"></div>` +
    `<div class="mt-ch-dmg">輸出 <span style="color:#1e293b">|</span> 承傷</div>` +
    `<div class="mt-ch-cs">金幣/CS</div>` +
    `<div class="mt-ch-items">裝備</div>`;
  section.appendChild(colHdr);

  // ── 玩家列 ──
  for (const p of players) {
    const row = document.createElement('div');
    row.className = `mt-row ${p.win ? 'modal-win' : 'modal-loss'}`;

    const dmgPct      = maxDamage      > 0 ? ((p.damage      || 0) / maxDamage      * 100).toFixed(1) : 0;
    const dmgTakenPct = maxDamageTaken > 0 ? ((p.damageTaken || 0) / maxDamageTaken * 100).toFixed(1) : 0;
    const lvl        = p.champLevel || 0;
    const minorPerks = p.minorPerks || [];
    const validAugs  = (p.augments || []).filter(a => a && a.id > 0);
    const validPerks = minorPerks.filter(x => x > 0);
    const hasAugs    = validAugs.length > 0;
    const kp         = Math.round(((p.kills || 0) + (p.assists || 0)) / Math.max(1, totalK) * 100);
    const goldStr    = p.gold ? (p.gold / 1000).toFixed(1) + 'k' : '—';

    // KDA 兩行：第一行 K/D/A (KP%)，第二行 ratio KDA
    const kdaRatio  = p.deaths === 0
      ? '完美 KDA'
      : (((p.kills || 0) + (p.assists || 0)) / Math.max(1, p.deaths || 0)).toFixed(2) + ' KDA';
    const killColor = p.deaths === 0 ? '#fbbf24' : '#cbd5e1';
    const ratioColor= p.deaths === 0 ? '#fbbf24' : '#475569';

    // 增幅裝置稀有度 → 邊框顏色
    const _augBorder = r => r >= 2 ? '1px solid #d946ef' : r === 1 ? '1px solid #eab308' : '1px solid #9ca3af';

    // 增幅優先，無增幅才顯示次級符文，完全無資料留空
    const augColHtml = hasAugs
      ? `<div style="display:flex;gap:3px;flex-wrap:wrap;align-items:center">` +
        validAugs.map(a =>
          `<img src="${IMG_PH}" class="mt-augment-icon empty" ` +
          `data-aug-id="${a.id}" style="border:${_augBorder(a.rarity)}" ` +
          `alt="" onerror="this.onerror=null;this.style.display='none'">`
        ).join('') +
        `</div>`
      : validPerks.length > 0
        ? `<div style="display:flex;gap:3px;flex-wrap:wrap;align-items:center">` +
          validPerks.map(rId =>
            `<img src="${IMG_PH}" class="mt-minor-rune empty" ` +
            `data-perk-id="${rId}" alt="" onerror="this.onerror=null;this.style.display='none'">`
          ).join('') +
          `</div>`
        : '';

    const itemsHtml = (p.items || [0,0,0,0,0,0,0]).slice(0, 7).map(() =>
      `<img src="${IMG_PH}" class="mt-item empty" alt="" onerror="${IMG_ERR}">`
    ).join('');

    row.innerHTML =
      `<div class="mt-identity">` +
        `<div class="mt-champ-wrap">` +
          `<img src="${IMG_PH}" class="mt-champ empty" title="${p.championName}" onerror="${IMG_ERR}">` +
          (lvl ? `<span class="mt-champ-level">${lvl}</span>` : '') +
        `</div>` +
        `<div class="mt-grid">` +
          `<img src="${IMG_PH}" class="mt-si mt-spell empty" onerror="${IMG_ERR}">` +
          `<img src="${IMG_PH}" class="mt-si mt-spell empty" onerror="${IMG_ERR}">` +
          `<img src="${IMG_PH}" class="mt-si mt-rune  empty" onerror="${IMG_ERR}">` +
          `<img src="${IMG_PH}" class="mt-si mt-rune  empty" onerror="${IMG_ERR}">` +
        `</div>` +
        `<div class="mt-names">` +
          `<span class="mt-summoner" title="${p.summonerName}">${p.summonerName}</span>` +
          `<span class="mt-champ-name">${p.championName}</span>` +
        `</div>` +
      `</div>` +
      `<div class="mt-kda">` +
        `<div class="mt-kda-nums">` +
          `<span class="mt-k" style="color:${killColor}">${p.kills}</span>` +
          `<span class="mt-sep">/</span>` +
          `<span class="mt-d">${p.deaths}</span>` +
          `<span class="mt-sep">/</span>` +
          `<span class="mt-a">${p.assists}</span>` +
          `<span class="mt-kp"> (${kp}%)</span>` +
        `</div>` +
        `<div class="mt-kda-ratio" style="color:${ratioColor}">${kdaRatio}</div>` +
      `</div>` +
      `<div class="mt-aug-col">${augColHtml}</div>` +
      `<div class="mt-dmg">` +
        `<div class="mt-dmg-half">` +
          `<span class="mt-dmg-num">${(p.damage || 0).toLocaleString()}</span>` +
          `<div class="mt-dmg-bar-wrap"><div class="mt-dmg-bar ${teamColor}" style="width:${dmgPct}%"></div></div>` +
        `</div>` +
        `<div class="mt-dmg-half">` +
          `<span class="mt-dmg-taken-num">${(p.damageTaken || 0).toLocaleString()}</span>` +
          `<div class="mt-dmg-bar-wrap"><div class="mt-dmg-bar-taken" style="width:${dmgTakenPct}%"></div></div>` +
        `</div>` +
      `</div>` +
      `<div class="mt-cs">` +
        `<span class="mt-gold">${goldStr}</span>` +
        `<span>${p.minions || 0}<span class="mt-cs-lbl"> CS</span></span>` +
      `</div>` +
      `<div class="mt-items">${itemsHtml}</div>`;

    section.appendChild(row);
    _loadChampIcon(p.championId,                        row.querySelector('.mt-champ'));
    _loadSpellIcons([p.spell1Id || 0, p.spell2Id || 0], row.querySelectorAll('.mt-spell'));
    // 2x2 下排：perk0 (主系核心) + perkSubStyle (副系路徑圖示)
    const runeEls = row.querySelectorAll('.mt-rune');
    _loadRuneIcons([p.perk0 || 0], runeEls);
    _loadPerkStyleIcon(p.perkSubStyle || 0, runeEls[1]);
    // 增幅裝置優先；無增幅才載入次級符文
    if (hasAugs) {
      _loadAugmentIcons(validAugs.map(a => a.id), row.querySelectorAll('.mt-augment-icon'));
    } else {
      const minorRunes = row.querySelectorAll('.mt-minor-rune');
      if (minorRunes.length > 0) _loadRuneIcons(validPerks, minorRunes);
    }
    _loadItemIcons(p.items || [],                        row.querySelectorAll('.mt-item'));
  }
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
    desc.innerHTML  = '偵測到 <span style="color:#475569">InProgress</span> 配對狀態時自動接受。';
  }

  eel.set_auto_accept(autoAcceptEnabled);
}

// ── 重整戰績（強制回到第 1 頁並向 LCU 重新拉取）──────────────────────────
function refreshMatchHistory() {
  currentPage = 1;
  append_log('REFRESH >> 強制重新拉取最新戰績 (P.1)...');
  loadMatchHistory();
}

// ── 重新連線 ────────────────────────────────────────────────────────────
async function doReconnect() {
  document.getElementById('summoner-name').innerHTML =
    '<span class="placeholder-block">████████████</span><span class="blink text-cyan-700">▮</span>';
  document.getElementById('summoner-level').textContent    = '---';
  document.getElementById('lcu-port').textContent          = '---';
  document.getElementById('lcu-port-settings').textContent = '---';
  document.getElementById('level-bar').style.width         = '0%';
  document.getElementById('avatar-img').src = 'avatar.png';

  const st = document.getElementById('status-text');
  st.textContent = '重新連線中...';
  st.className   = 'text-[10px] text-yellow-600 transition-all duration-500';

  const data = await eel.reconnect()();
  updateUI(data);
  if (data && data.ok) await _loadChampionList();
}

// ── 初始化 ─────────────────────────────────────────────────────────────
window.addEventListener('load', async () => {
  append_log('SYS >> LeagueMrfox V1.0 初始化完成');

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
    if (data && data.ok) await _loadChampionList();
  } catch (err) {
    append_log(`JS_ERR >> ${err}`, true);
  }
});
