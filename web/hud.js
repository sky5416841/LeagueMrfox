// ── 遊戲中 HUD：每秒輪詢後端，合併「遊戲內即時資料」與「全場雷達」──────────
// 注意：eel 會把後端推播廣播給所有視窗，這裡不需要處理，也不註冊任何 expose。
const CHAMP_ICON = id =>
  `https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/champion-icons/${id}.png`;

function _wrColor(wr) {
  return wr >= 60 ? '#4ade80' : wr >= 50 ? '#a3e635' : wr >= 40 ? '#fb923c' : '#f87171';
}
function _esc(t) {
  return String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function _fmtTime(sec) {
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function _scanHtml(sc) {
  if (!sc || !sc.total) return '<span class="hud-meta">—</span>';
  let badges = '';
  if (sc.streakType === 'win'  && sc.streakCount >= 3) badges += `<span class="hud-badge hud-b-hot" title="連勝">🔥${sc.streakCount}</span>`;
  if (sc.streakType === 'lose' && sc.streakCount >= 3) badges += `<span class="hud-badge hud-b-cold" title="連敗">⚠${sc.streakCount}</span>`;
  const enc = sc.encounter;
  if (enc && (enc.ally.games || enc.enemy.games)) {
    const t = enc.ally.games ? `同隊${enc.ally.games}場 ${enc.ally.wins}勝` : `對手${enc.enemy.games}場 我方${enc.enemy.wins}勝`;
    badges += `<span class="hud-badge hud-b-enc" title="${t}">遇過</span>`;
  }
  return `<span style="color:${_wrColor(sc.winRate)}">${sc.winRate}%</span>${badges}`;
}

function _rowHtml(p) {
  const icon = p.championId
    ? `<img class="hud-icon" src="${CHAMP_ICON(p.championId)}" onerror="this.style.visibility='hidden'" alt="">`
    : '<div class="hud-icon"></div>';
  const meta = p.scan && p.scan.tier ? `${_esc(p.name)} · ${_esc(p.scan.tier)}` : _esc(p.name);
  const kda = p.level || p.k || p.d || p.a
    ? `${p.k}/${p.d}/${p.a}<span class="hud-cs">Lv${p.level || '-'} · ${p.cs}補</span>` : '';
  return `<div class="hud-row${p.dead ? ' dead' : ''}">
    ${icon}
    <div class="hud-who"><div class="hud-champ">${_esc(p.champion || '')}</div><div class="hud-meta">${meta}</div></div>
    <div class="hud-kda">${kda}</div>
    <div class="hud-scan">${_scanHtml(p.scan)}</div>
    ${p.dead && p.respawn > 0 ? `<div class="hud-death">💀 ${p.respawn}s</div>` : ''}
  </div>`;
}

function _render(d) {
  const body = document.getElementById('hud-body');
  const note = document.getElementById('hud-note');
  document.getElementById('hud-time').textContent = d.live ? _fmtTime(d.gameTime) : '--:--';
  note.textContent = d.live ? '' : '載入中 · 僅顯示雷達資料（遊戲開始後加入即時戰況）';
  if (!d.players || d.players.length === 0) { body.innerHTML = ''; note.textContent = '等待遊戲資料...'; return; }
  const sec = (side, label, cls) => {
    const rows = d.players.filter(p => p.side === side);
    return rows.length ? `<div class="hud-team-hdr ${cls}">// ${label}</div>${rows.map(_rowHtml).join('')}` : '';
  };
  body.innerHTML = sec('my', '我方', 'hud-team-my') + sec('enemy', '敵方', 'hud-team-enemy');
}

// 依內容自動調整視窗高度（變化超過 8px 才通知後端，避免頻繁縮放）
let _lastH = 0;
function _fitHeight() {
  const body = document.getElementById('hud-body');
  const h = Math.ceil(
    document.getElementById('hud-titlebar').offsetHeight +
    document.getElementById('hud-note').offsetHeight +
    document.querySelector('.hud-keys').offsetHeight +
    Array.from(body.children).reduce((s, c) => s + c.offsetHeight + 3, 0) + 18);
  if (Math.abs(h - _lastH) > 8) { _lastH = h; eel.hud_resize(h); }
}

let _busy = false;
async function _tick() {
  if (_busy) return;
  _busy = true;
  try { _render(await eel.get_hud_data()()); _fitHeight(); } catch (e) { /* 後端尚未就緒，下一秒再試 */ }
  _busy = false;
}
setInterval(_tick, 1000);
_tick();
