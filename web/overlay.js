// ── 選角戰術中樞 浮窗 ──────────────────────────────────────────────────
// 英雄方形圖示（Community Dragon，依數值 championId 取得，免 LCU 依賴）
const CHAMP_ICON = id =>
  `https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/champion-icons/${id}.png`;
const ICON_ERR = "this.onerror=null;this.parentElement.classList.add('img-err')";

function _champCell(id, name) {
  return `<div class="ov-champ" title="${name || ''}">
    <img src="${CHAMP_ICON(id)}" onerror="${ICON_ERR}" alt="">
    ${name ? `<div class="ov-champ-name">${name}</div>` : ''}
  </div>`;
}

function _renderTeam(a, side) {
  const cls   = side === 'ally' ? 'ov-team-ally' : 'ov-team-enemy';
  const label = side === 'ally' ? '我方' : '敵方';
  const adW = Math.max(a.adPct || 0, 0), apW = Math.max(a.apPct || 0, 0);
  const roleChips = Object.entries(a.roles || {})
    .map(([r, c]) => `<span class="ov-role-chip">${r}${c > 1 ? '×' + c : ''}</span>`).join('');
  return `
    <div class="ov-team ${cls}">
      <div class="ov-team-hdr">
        <span class="ov-team-name">${label}</span>
        <span class="ov-team-meta">已選 ${a.count || 0}/5</span>
      </div>
      <div class="ov-dmgbar">
        <div class="ov-dmg-ad" style="width:${adW}%">${adW >= 18 ? `<span>物 ${adW}%</span>` : ''}</div>
        <div class="ov-dmg-ap" style="width:${apW}%">${apW >= 18 ? `<span>魔 ${apW}%</span>` : ''}</div>
      </div>
      <div class="ov-team-stats">
        <span>前排 <b>${a.frontline || 0}</b></span>
        <span>開團 <b>${a.engage || 0}</b></span>
        <span>物理 <b>${a.ad || 0}</b> · 魔法 <b>${a.ap || 0}</b></span>
      </div>
      ${roleChips ? `<div class="ov-roles">${roleChips}</div>` : ''}
    </div>`;
}

eel.expose(on_champ_select_update);
function on_champ_select_update(state) {
  const comp = state.comp || {};
  const my = comp.myTeam || {}, en = comp.enemyTeam || {};
  const compEl = document.getElementById('ov-comp');

  if ((my.count || 0) === 0 && (en.count || 0) === 0) {
    compEl.innerHTML = '<div class="ov-empty">等待雙方選角中...</div>';
  } else {
    compEl.innerHTML = _renderTeam(my, 'ally') + _renderTeam(en, 'enemy');
  }

  // 戰術提示（合併雙方旗標，標註陣營）
  const flags = []
    .concat((my.flags || []).map(f => ({ ...f, who: '我方' })))
    .concat((en.flags || []).map(f => ({ ...f, who: '敵方' })));
  const flagsSec = document.getElementById('ov-flags-sec');
  const flagsEl  = document.getElementById('ov-flags');
  if (flags.length) {
    flagsSec.style.display = '';
    flagsEl.innerHTML = flags.map(f =>
      `<div class="ov-flag ov-flag-${f.level}">[${f.who}] ${f.text}</div>`).join('');
  } else {
    flagsSec.style.display = 'none';
  }

  // 本場禁用
  const bansSec = document.getElementById('ov-bans-sec');
  const bansEl  = document.getElementById('ov-bans');
  const bans = state.bans || [];
  if (bans.length) {
    bansSec.style.display = '';
    bansEl.innerHTML = bans.map(b => _champCell(b.championId, b.name)).join('');
  } else {
    bansSec.style.display = 'none';
  }
}

// 進入時載入 meta 推薦禁用（依線路分組）
const LANE_LABEL = { TOP: '上路', JUNGLE: '打野', MID: '中路', ADC: '下路', SUPPORT: '輔助' };
const LANE_ORDER = ['TOP', 'JUNGLE', 'MID', 'ADC', 'SUPPORT'];

async function _loadBanHelper() {
  const el = document.getElementById('ov-banhelp-lanes');
  try {
    const lanes = await eel.get_ban_helper_by_lane('ranked', 4)();
    if (!lanes || !LANE_ORDER.some(k => (lanes[k] || []).length)) {
      el.innerHTML = '<div class="ov-empty">暫無資料</div>';
      return;
    }
    el.innerHTML = LANE_ORDER.map(k => {
      const arr = lanes[k] || [];
      const cells = arr.map(c =>
        `<div class="ov-champ" title="${c.championName} · 勝率 ${c.winRate}%">
          <img src="${CHAMP_ICON(c.championId)}" onerror="${ICON_ERR}" alt="">
          <div class="ov-banhelp-wr">${c.winRate}%</div>
        </div>`).join('');
      return `<div class="ov-lane-row">
        <div class="ov-lane-label">${LANE_LABEL[k]}</div>
        <div class="ov-lane-champs">${cells || '<span class="ov-empty">—</span>'}</div>
      </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = '<div class="ov-empty">載入失敗</div>';
  }
}

window.addEventListener('load', () => {
  setTimeout(_loadBanHelper, 800);
});
