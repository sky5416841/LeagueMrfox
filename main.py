import os
import re
import sys
import time
import json
import ssl
import socket
import base64
import asyncio
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor

import eel
import urllib3
import requests
import websockets

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from lcu_core import LCUClient, LCUNotRunningError

# ── State ──────────────────────────────────────────────────────────────
_client: LCUClient | None = None
_auto_accept = False
_ws_stop     = threading.Event()
_ws_thread: threading.Thread | None = None
_puuid       = ''
_account_id  = 0
_champ_cache: dict[int, str] = {}
_champ_summary_loaded = False
_item_cache: dict[int, str]  = {}   # item_id -> iconPath
_item_cache_loaded = False
_spell_cache: dict[int, str] = {}   # spell_id -> iconPath
_spell_cache_loaded = False
_perk_cache: dict[int, dict] = {}      # perk_id -> {iconPath, name, shortDesc}
_perk_cache_loaded = False
_perkstyle_cache: dict[int, str] = {}  # style_id -> iconPath（副系路徑圖示）
_perkstyle_cache_loaded = False
_augment_cache: dict[int, dict] = {}  # augment_id -> {iconPath, name}
_augment_cache_loaded = False          # cherry-augments 是否已載入
_kiwi_aug_cache_loaded = False         # kiwi-augments 是否已載入（需在遊戲中才能拿到）
_kiwi_aug_cache_failed = False         # 若 LCU 無此 endpoint 則不再重試
_rank_emblem_cache: dict[str, str] = {}  # TIER_UPPER -> iconPath
_rank_emblem_loaded = False
_auto_pick         = False
_auto_pick_champ_id= 0
_last_pick_action_id = -1  # 防止對同一個 action 重複秒選
_auto_ban          = False
_auto_ban_champ_id = 0
_last_ban_action_id = -1   # 防止對同一個 ban action 重複觸發
_champ_valid_ids: set[int] = set()  # 僅含有 roles 的正常可玩英雄，過濾 NPC

# 大廳 X 光機：掃描隊友戰力
_current_gameflow_phase = ''   # 由 WS gameflow 事件即時維護，掃描前用於 phase 守衛
_current_lobby_mode = 'ranked'  # 由大廳 queueId 推算：ranked / aram / arena
_last_scanned_team_key  = ''   # 防止對同一場大廳重複掃描
_lobby_scan_in_progress = False
_ingame_scan_in_progress = False  # 遊戲中 10 人雷達
_webview_window = None             # pywebview 原生視窗參考（自訂標題列控制用）
_hud_window = None                 # 遊戲中 HUD 浮窗（只有自己看得到，進遊戲顯示）
_hud_scan = {"my": [], "enemy": []}  # 最近一次全場雷達結果，供 HUD 合併顯示
_overlay_window = None             # 選角戰術常駐浮窗（always-on-top，選角時顯示）
_last_hovered_champ = 0             # 選角階段上次偵測到自己選的英雄（避免重複推播）
_last_champsel_key  = ''           # 選角戰術推播去重鍵（雙方已選英雄集合）
_EMPTY_PUUID = '00000000-0000-0000-0000-000000000000'  # 空位/匿名槽特徵 PUUID（LeagueAkari 過濾標準）

# 本地戰績快取路徑（data/ 已在 .gitignore，個人數據不上傳）
_MATCH_CACHE_FILE = os.path.join(os.path.dirname(__file__), "data", "match_history_cache.json")
# 玩家標記資料：puuid -> {tag, color, withWins, withLosses, vsWins, vsLosses, lastName}
_TAGGED_PLAYERS_FILE = os.path.join(os.path.dirname(__file__), "data", "tagged_players.json")
# 自動化偏好設定（自動接受/選角/禁角的開關與英雄）
_PREFS_FILE = os.path.join(os.path.dirname(__file__), "data", "prefs.json")
_tagged_players: dict = {}   # 啟動時載入，記憶體快取

# SGP 各區域 URL（來源：LeagueAkari/resources/builtin-config/sgp/league-servers.json）
_SGP_MATCH_HISTORY_URLS: dict[str, str] = {
    "TW2":  "https://apse1-red.pp.sgp.pvp.net",
    "SG2":  "https://apse1-red.pp.sgp.pvp.net",
    "PH2":  "https://apse1-red.pp.sgp.pvp.net",
    "VN2":  "https://apse1-red.pp.sgp.pvp.net",
    "TH2":  "https://apse1-red.pp.sgp.pvp.net",
    "OC1":  "https://apse1-red.pp.sgp.pvp.net",
    "KR":   "https://apne1-red.pp.sgp.pvp.net",
    "JP1":  "https://apne1-red.pp.sgp.pvp.net",
    "NA1":  "https://usw2-red.pp.sgp.pvp.net",
    "LA1":  "https://usw2-red.pp.sgp.pvp.net",
    "LA2":  "https://usw2-red.pp.sgp.pvp.net",
    "BR1":  "https://usw2-red.pp.sgp.pvp.net",
    "EUW1": "https://euc1-red.pp.sgp.pvp.net",
    "EUNE1":"https://euc1-red.pp.sgp.pvp.net",
    "RU":   "https://euc1-red.pp.sgp.pvp.net",
    "TR1":  "https://euc1-red.pp.sgp.pvp.net",
}

# summoner-ledge common URL（查匿名玩家名稱用）
_SGP_COMMON_URLS: dict[str, str] = {
    "TW2":  "https://tw2-red.lol.sgp.pvp.net",
    "SG2":  "https://sg2-red.lol.sgp.pvp.net",
    "PH2":  "https://ph2-red.lol.sgp.pvp.net",
    "VN2":  "https://vn2-red.lol.sgp.pvp.net",
    "TH2":  "https://th2-red.lol.sgp.pvp.net",
    "OC1":  "https://oc1-red.lol.sgp.pvp.net",
    "KR":   "https://kr-red.lol.sgp.pvp.net",
    "JP1":  "https://jp1-red.lol.sgp.pvp.net",
    "NA1":  "https://na1-red.lol.sgp.pvp.net",
    "LA1":  "https://la1-red.lol.sgp.pvp.net",
    "LA2":  "https://la2-red.lol.sgp.pvp.net",
    "BR1":  "https://br1-red.lol.sgp.pvp.net",
    "EUW1": "https://euw1-red.lol.sgp.pvp.net",
    "EUNE1":"https://eune1-red.lol.sgp.pvp.net",
    "RU":   "https://ru-red.lol.sgp.pvp.net",
    "TR1":  "https://tr1-red.lol.sgp.pvp.net",
}

# 在 initialize() 時填入
_platform_id          = ''   # 例如 "TW2"
_entitlement_token    = ''   # Riot Entitlements JWT（SGP matchHistory 用）
_league_session_token = ''   # League Session Token（SGP summoner-ledge 用）

# ── Helper ─────────────────────────────────────────────────────────────
_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.log")
_EEL_PORT = 8000   # eel HTTP/WebSocket server 埠號（亦用於單一實例偵測）


def _rotate_log(path: str, max_bytes: int = 2_000_000):
    """啟動時若 log 超過上限，轉存為 .1 備份後重新開始，避免無限增長。"""
    try:
        if os.path.exists(path) and os.path.getsize(path) > max_bytes:
            bak = path + ".1"
            if os.path.exists(bak):
                os.remove(bak)
            os.replace(path, bak)
    except Exception:
        pass


_rotate_log(_LOG_PATH)
_log_file = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)

def _log(msg: str):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        _log_file.write(line + "\n")
    except Exception:
        pass
    try:
        eel.append_log(msg)()
    except Exception:
        print(f"[LOG] {msg}")


def _sgp_get_summoner_names(puuids: list[str]) -> dict[str, str]:
    """[已廢棄] SGP summoner-ledge API 自 2026/6 起 unnamed=True，名稱欄位全空。
    保留函式供日後觀察，實際補名改由 summonerAPI fallback 處理。
    """
    pid = (_platform_id or "").upper()
    common_base = _SGP_COMMON_URLS.get(pid)
    if not common_base or not puuids:
        return {}
    # 每次使用前重新拿 token（避免過期）
    try:
        fresh_token = _client.get("/lol-league-session/v1/league-session-token") or ""
    except Exception:
        fresh_token = _league_session_token
    if not fresh_token:
        return {}
    region = pid.lower()
    url = f"{common_base}/summoner-ledge/v1/regions/{region}/summoners/puuids"
    try:
        resp = requests.post(
            url,
            json=puuids,
            headers={"Authorization": f"Bearer {fresh_token}"},
            verify=False,
            timeout=5,
        )
        resp.raise_for_status()
        raw_list = resp.json()
        # 記錄第一筆的欄位，方便追查格式變化
        if raw_list:
            s0 = raw_list[0]
            _log(f"SGP_SUMMONER >> 回傳欄位範例: name={s0.get('name')!r} "
                 f"internalName={s0.get('internalName')!r} "
                 f"unnamed={s0.get('unnamed')!r} privacy={s0.get('privacy')!r}")
        result = {}
        for s in raw_list:
            pu   = s.get("puuid", "")
            # SgpSummoner 的名稱欄位；internalName 是帳號原始名稱（非 Riot ID）
            name = (s.get("name") or s.get("internalName") or
                    s.get("gameName") or s.get("displayName") or "").strip()
            if pu and name:
                result[pu] = name
        _log(f"SGP_SUMMONER >> {len(result)}/{len(puuids)} 筆名稱查回")
        return result
    except Exception as e:
        _log(f"SGP_SUMMONER >> 失敗: {e}")
        return {}


# ── OP.GG 英雄攻略 API ─────────────────────────────────────────────────
_OPGG_BASE = "https://lol-api-champion.op.gg"
_OPGG_UA   = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36")
_opgg_cache: dict = {}   # key: f"{mode}/{champ_id}/{position}" -> data

# ── 大混戰增幅（騰訊 gtimg CDN，全量 kiwi augments，含名稱/稀有度）──────
_KIWI_AUGMENTS_URL = "https://game.gtimg.cn/images/lol/act/img/js/kiwi/kiwi_augments.json"
_kiwi_augments_cache: list = []
_kiwi_augments_loaded = False


def _load_kiwi_augments():
    global _kiwi_augments_cache, _kiwi_augments_loaded
    if _kiwi_augments_loaded:
        return
    try:
        resp = requests.get(_KIWI_AUGMENTS_URL, timeout=10)
        resp.raise_for_status()
        _kiwi_augments_cache = resp.json() or []
        _kiwi_augments_loaded = True
        _log(f"KIWI_AUGMENTS >> 載入 {len(_kiwi_augments_cache)} 個增幅")
    except Exception as e:
        _log(f"KIWI_AUGMENTS_ERR >> {e}")


@eel.expose
def get_kiwi_augments() -> list:
    """回傳大混戰全量增幅列表，供前端依稀有度分組顯示。
    格式：[{augmentID, name_cn, name_en, level(kSilver/kGold/kPrismatic), desc}, ...]
    """
    _load_kiwi_augments()
    return _kiwi_augments_cache


@eel.expose
def get_kiwi_champion_augments(champ_id: int) -> list:
    """回傳特定英雄在大混戰的增幅排行（OP.GG aram-augments endpoint）。
    格式：[{id, tier(0=S..6=F), performance, popular}, ...] 依 performance 降序。
    """
    if not champ_id:
        return []
    try:
        resp = requests.get(
            f"{_OPGG_BASE}/api/contents/stats/champions/{champ_id}/aram-augments",
            headers={"User-Agent": _OPGG_UA}, timeout=10
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return sorted(data, key=lambda x: x.get("performance", 0), reverse=True)
    except Exception as e:
        _log(f"KIWI_CHAMP_AUGMENTS_ERR >> champ={champ_id} >> {e}")
        return []


def _opgg_get(path: str, params: dict = None) -> dict:
    """呼叫 OP.GG API，回傳 data 欄位；失敗回傳空 dict。"""
    try:
        resp = requests.get(f"{_OPGG_BASE}{path}", params=params or {},
                            headers={"User-Agent": _OPGG_UA}, timeout=12)
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception as e:
        _log(f"OPGG_ERR >> {path}: {e}")
        return {}


@eel.expose
def opgg_get_champion(champ_id: int, mode: str = "ranked", position: str = "", tier: str = "all") -> dict:
    """取得單英雄 OP.GG 攻略（符文/出裝/召喚師技能/技能加點）。
    mode: ranked / aram / arena / kiwi；kiwi（大混戰）無 OP.GG 專屬資料，改用 ranked 攻略。
    """
    if not champ_id:
        return {}
    if mode == "kiwi":
        mode = "ranked"   # OP.GG 無大混戰資料，以 ranked 攻略替代
    if mode == "aram":
        position = "none"
    elif mode == "arena":
        position = ""
    pos = position or "none"
    cache_key = f"{mode}/{champ_id}/{pos}/{tier}"
    if cache_key in _opgg_cache:
        return _opgg_cache[cache_key]

    region = "kr"   # OP.GG 以 kr 樣本最大，作為全球參考
    if mode == "arena":
        data = _opgg_get(f"/api/{region}/champions/{mode}/{champ_id}", {"tier": tier})
    elif mode == "aram":
        data = _opgg_get(f"/api/{region}/champions/{mode}/{champ_id}/none", {"tier": tier})
    else:
        # ranked：位置不可為 none，未指定時依序嘗試常見位置
        positions = [position] if (position and position != "none") else ["mid", "top", "adc", "support", "jungle"]
        data = {}
        for pp in positions:
            data = _opgg_get(f"/api/{region}/champions/{mode}/{champ_id}/{pp}", {"tier": tier})
            if data:
                pos = pp
                break
    if data:
        _opgg_cache[cache_key] = data
        _log(f"OPGG >> 取得英雄 {champ_id} 攻略（{mode}/{pos}）")
    return data


@eel.expose
def opgg_get_tier(mode: str = "ranked", tier: str = "all") -> list:
    """取得英雄梯隊列表（強度排行）。"""
    region = "kr"
    data = _opgg_get(f"/api/{region}/champions/{mode}", {"tier": tier})
    return data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []


# ── 英雄 Metadata（Data Dragon）：傷害類型 / 職業，供選角戰術分析 ───────────
_DDRAGON_VER_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
_CHAMP_META_FILE = os.path.join(os.path.dirname(__file__), "data", "champ_meta.json")
_champ_meta: dict[int, dict] = {}   # championId -> {name, tags, attack, magic, defense, dmgType}
_champ_meta_loaded = False

# 職業中文對照
_ROLE_ZH = {
    "Tank": "坦克", "Fighter": "鬥士", "Mage": "法師",
    "Marksman": "射手", "Assassin": "刺客", "Support": "輔助",
}
# 強開團 / 硬控英雄（championId 白名單，補 Data Dragon tags 無法表達的開團資訊）
# 保守收錄公認的強開團英雄，作為「開團能力」啟發式提示。
_ENGAGE_CHAMPS = {
    54, 89, 111, 32, 113, 154, 516, 526, 12, 57, 59, 254, 120, 62, 85, 3,
    131, 497, 412, 22, 79, 14, 72, 518, 56, 164, 106, 127, 9, 19, 20, 154,
    875, 555, 200, 33, 421, 60, 102,
}


def _classify_dmg_type(attack: int, magic: int) -> str:
    """依 Data Dragon info.attack / info.magic 判斷主要傷害類型。"""
    if attack >= magic + 3:
        return "AD"
    if magic >= attack + 3:
        return "AP"
    return "Mixed"


def _fetch_champ_meta() -> dict:
    """從 Data Dragon 下載英雄 metadata 並寫入本地快取。失敗回傳現有 _champ_meta。"""
    global _champ_meta, _champ_meta_loaded
    try:
        ver  = requests.get(_DDRAGON_VER_URL, timeout=8).json()[0]
        url  = f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/zh_TW/championFull.json"
        data = requests.get(url, timeout=15).json().get("data", {})
        meta: dict[int, dict] = {}
        for c in data.values():
            cid = int(c.get("key", 0) or 0)
            if not cid:
                continue
            info = c.get("info", {}) or {}
            atk  = info.get("attack", 0); mag = info.get("magic", 0); dfn = info.get("defense", 0)
            meta[cid] = {
                "name":    c.get("name", ""),
                "tags":    c.get("tags", []) or [],
                "attack":  atk, "magic": mag, "defense": dfn,
                "dmgType": _classify_dmg_type(atk, mag),
            }
        if meta:
            _champ_meta = meta
            _champ_meta_loaded = True
            try:
                with open(_CHAMP_META_FILE, "w", encoding="utf-8") as f:
                    json.dump({"version": ver,
                               "champs": {str(k): v for k, v in meta.items()}},
                              f, ensure_ascii=False)
            except Exception:
                pass
            _log(f"CHAMP_META >> 從 Data Dragon 下載 {len(meta)} 位英雄 (patch {ver})")
    except Exception as e:
        _log(f"CHAMP_META >> 下載失敗: {e}")
    return _champ_meta


def _load_champ_meta(force: bool = False) -> dict:
    """載入英雄 metadata：優先讀本地快取，缺檔才從 Data Dragon 下載。"""
    global _champ_meta, _champ_meta_loaded
    if _champ_meta_loaded and not force:
        return _champ_meta
    try:
        if os.path.exists(_CHAMP_META_FILE):
            with open(_CHAMP_META_FILE, encoding="utf-8") as f:
                cached = json.load(f)
            _champ_meta = {int(k): v for k, v in (cached.get("champs") or {}).items()}
            if _champ_meta:
                _champ_meta_loaded = True
                _log(f"CHAMP_META >> 從快取載入 {len(_champ_meta)} 位英雄 "
                     f"(patch {cached.get('version', '?')})")
                return _champ_meta
    except Exception as e:
        _log(f"CHAMP_META >> 快取讀取失敗: {e}")
    return _fetch_champ_meta()


def _analyze_team_comp(champ_ids: list[int]) -> dict:
    """分析一支隊伍的陣容組成：傷害類型、職業分布、前排數、開團數。
    回傳含各項統計與旗標的 dict；champ_ids 為已選英雄（0 代表未選，忽略）。
    """
    meta = _load_champ_meta()
    picks = [c for c in champ_ids if c and c > 0]
    ad = ap = mixed = frontline = engage = 0
    roles: dict[str, int] = {}
    atk_sum = mag_sum = 0
    detail = []
    for cid in picks:
        m = meta.get(cid, {})
        dmg = m.get("dmgType", "")
        if   dmg == "AD":  ad += 1
        elif dmg == "AP":  ap += 1
        elif dmg == "Mixed": mixed += 1
        atk_sum += m.get("attack", 0)
        mag_sum += m.get("magic", 0)
        tags = m.get("tags", [])
        if "Tank" in tags or m.get("defense", 0) >= 7:
            frontline += 1
        if cid in _ENGAGE_CHAMPS:
            engage += 1
        primary = tags[0] if tags else ""
        if primary:
            roles[primary] = roles.get(primary, 0) + 1
        detail.append({"championId": cid, "name": m.get("name", f"#{cid}"),
                       "dmgType": dmg, "tags": tags})

    n = len(picks)
    tot_dmg = atk_sum + mag_sum
    ad_pct = round(atk_sum / tot_dmg * 100) if tot_dmg else 50
    ap_pct = 100 - ad_pct if tot_dmg else 50

    # ── 戰術旗標（缺口提示）──────────────────────────────────────────────
    flags = []
    if n >= 3:
        if frontline == 0:
            flags.append({"level": "warn", "text": "缺乏前排（無坦克）"})
        if ap == 0 and ad >= 2:
            flags.append({"level": "warn", "text": "全物理陣容，敵方易疊護甲"})
        elif ad == 0 and ap >= 2:
            flags.append({"level": "warn", "text": "全魔法陣容，敵方易疊魔抗"})
        if engage == 0:
            flags.append({"level": "info", "text": "缺乏強開團，偏被動陣容"})
        if frontline >= 2 and 30 <= ad_pct <= 70 and engage >= 1:
            flags.append({"level": "good", "text": "陣容均衡（前排/傷害/開團兼具）"})

    roles_zh = {_ROLE_ZH.get(k, k): v for k, v in roles.items()}
    return {
        "count":     n,
        "ad":        ad, "ap": ap, "mixed": mixed,
        "adPct":     ad_pct, "apPct": ap_pct,
        "frontline": frontline, "engage": engage,
        "roles":     roles_zh,
        "flags":     flags,
        "detail":    detail,
    }


@eel.expose
def get_comp_analysis(my_champ_ids: list = None, enemy_champ_ids: list = None) -> dict:
    """選角戰術分析：回傳我方與敵方陣容組成比較。"""
    my  = _analyze_team_comp(my_champ_ids or [])
    en  = _analyze_team_comp(enemy_champ_ids or [])
    return {"myTeam": my, "enemyTeam": en}


@eel.expose
def get_ban_helper(mode: str = "ranked", position: str = "", limit: int = 8) -> list:
    """選角禁用輔助：回傳當前 meta 強度最高的英雄（OP.GG 梯隊）作為 ban 建議。
    敵方身分在選角階段被 Riot 隱藏，故改以 meta 強勢英雄作為通用 ban 目標。
    """
    try:
        tier_list = opgg_get_tier(mode)
        rows = []
        for it in (tier_list or []):
            cid = it.get("id") or it.get("championId") or 0
            if not cid:
                continue
            st = it.get("average_stats") or it.get("stats") or it
            win = st.get("win_rate") or st.get("winRate") or st.get("win") or 0
            pick = st.get("pick_rate") or st.get("pickRate") or 0
            ban  = st.get("ban_rate")  or st.get("banRate")  or 0
            tier_rank = it.get("tier") or st.get("tier") or 0
            rows.append({
                "championId":   cid,
                "championName": _get_champ_name(cid),
                "winRate":  round(float(win) * 100, 1) if win and float(win) <= 1 else round(float(win or 0), 1),
                "pickRate": round(float(pick) * 100, 1) if pick and float(pick) <= 1 else round(float(pick or 0), 1),
                "banRate":  round(float(ban) * 100, 1) if ban and float(ban) <= 1 else round(float(ban or 0), 1),
                "tier":     tier_rank,
            })
        # 以勝率 + 禁用率排序，取前 limit 個作為 ban 建議
        rows.sort(key=lambda r: (r["winRate"] + r["banRate"]), reverse=True)
        return rows[:limit]
    except Exception as e:
        _log(f"BAN_HELPER_ERR >> {e}")
        return []


# OP.GG 位置代碼 → 內部統一鍵
_OPGG_POS_KEY = {
    "TOP": "TOP", "JUNGLE": "JUNGLE", "MID": "MID", "MIDDLE": "MID",
    "ADC": "ADC", "BOTTOM": "ADC", "BOT": "ADC",
    "SUPPORT": "SUPPORT", "UTILITY": "SUPPORT",
}


@eel.expose
def get_ban_helper_by_lane(mode: str = "ranked", per_lane: int = 4) -> dict:
    """依線路分組的建議禁用：每條線回傳當前 meta 最強的數個英雄。
    來源 OP.GG 各英雄 positions[] 的分線梯隊（tier/rank），依梯隊強度排序。
    """
    out = {"TOP": [], "JUNGLE": [], "MID": [], "ADC": [], "SUPPORT": []}
    try:
        tier_list = opgg_get_tier(mode)
        buckets = {k: [] for k in out}
        for it in (tier_list or []):
            cid = it.get("id") or it.get("championId") or 0
            if not cid:
                continue
            for pos in (it.get("positions") or []):
                pk = _OPGG_POS_KEY.get((pos.get("name") or "").upper())
                if not pk:
                    continue
                st = pos.get("stats") or {}
                td = st.get("tier_data") or {}
                win = float(st.get("win_rate", 0) or 0)
                ban = float(st.get("ban_rate", 0) or 0)
                buckets[pk].append({
                    "championId":   cid,
                    "championName": _get_champ_name(cid),
                    "winRate":  round(win * 100, 1) if win <= 1 else round(win, 1),
                    "banRate":  round(ban * 100, 1) if ban <= 1 else round(ban, 1),
                    "tier":     td.get("tier", 9),
                    "rank":     td.get("rank", 999),
                })
        for pk, arr in buckets.items():
            # 梯隊 tier 越小越強、同 tier 比 rank
            arr.sort(key=lambda r: (r["tier"], r["rank"]))
            out[pk] = arr[:per_lane]
        return out
    except Exception as e:
        _log(f"BAN_LANE_ERR >> {e}")
        return out


def _fetch_player_games_sgp(puuid: str, count: int = 20) -> list:
    """用本機帳號的 entitlement token 搭配目標玩家 PUUID 查詢 SGP 戰績。
    可查任意玩家（不限自己），突破 LCU 僅能看自己的 20 筆限制。
    回傳解包後的 game dict 列表；任何錯誤一律回傳空列表讓呼叫端降級。
    """
    sgp_base = _SGP_MATCH_HISTORY_URLS.get((_platform_id or "").upper())
    if not sgp_base or not _entitlement_token or not puuid:
        return []
    try:
        url  = f"{sgp_base}/match-history-query/v1/products/lol/player/{puuid}/SUMMARY"
        resp = requests.get(
            url,
            params={"startIndex": 0, "count": count},
            headers={"Authorization": f"Bearer {_entitlement_token}"},
            timeout=10,
            verify=False,
        )
        resp.raise_for_status()
        raw = resp.json().get("games", [])
        return [wrap.get("json") or wrap for wrap in raw if wrap]
    except Exception:
        return []


def _fetch_games(puuid: str, count: int = 20) -> list:
    """取玩家近 count 場原始對局（SGP 優先，LCU 備援）。"""
    games = _fetch_player_games_sgp(puuid, count)
    if games:
        return games
    try:
        raw = _client.get(
            f"/lol-match-history/v1/products/lol/{puuid}/matches"
            f"?begIndex=0&endIndex={count}"
        )
        return raw.get("games", {}).get("games", [])
    except Exception:
        return []


def _find_participant(game: dict, puuid: str) -> dict | None:
    """在單場對局中找出指定玩家的 participant（相容 SGP 與 LCU 兩種格式）。"""
    for p in game.get("participants", []):
        if p.get("puuid") == puuid:
            return p
    for ident in game.get("participantIdentities", []):
        if ident.get("player", {}).get("puuid") == puuid:
            pid = ident.get("participantId")
            return next((p for p in game.get("participants", [])
                         if p.get("participantId") == pid), None)
    return None


def _add_champ_game(champ_stats: dict, ch_id: int, won: bool, k: int, d: int, a: int):
    """累計單一英雄的場次、勝場與 KDA 總和。"""
    cs = champ_stats.setdefault(ch_id, {"games": 0, "wins": 0, "k": 0, "d": 0, "a": 0})
    cs["games"] += 1
    cs["wins"]  += 1 if won else 0
    cs["k"] += k; cs["d"] += d; cs["a"] += a


def _rank_champions(champ_stats: dict) -> list[dict]:
    """英雄池輸出：依場次→勝率排序，附平均 KDA 與場次佔比。"""
    total = sum(cs["games"] for cs in champ_stats.values()) or 1
    ranked = sorted(champ_stats.items(),
                    key=lambda kv: (kv[1]["games"], kv[1]["wins"] / kv[1]["games"]),
                    reverse=True)
    return [
        {
            "championId":   cid,
            "championName": _get_champ_name(cid),
            "games":        cs["games"],
            "wins":         cs["wins"],
            "winRate":      round(cs["wins"] / cs["games"] * 100, 1),
            "kda":          round((cs["k"] + cs["a"]) / max(cs["d"], 1), 2),
            "share":        round(cs["games"] / total * 100, 1),
        }
        for cid, cs in ranked
    ]


def _pool_summary(champions: list[dict]) -> dict:
    """依英雄池分佈判定類型：一招鮮 / 專精 / 廣泛 / 亂選。"""
    total = sum(c["games"] for c in champions)
    if total == 0:
        return {"poolSize": 0, "poolType": "", "topShare": 0.0}
    top_share = champions[0]["games"] / total * 100
    size = len(champions)
    if total >= 5 and top_share >= 50:
        ptype = "一招鮮"
    elif total >= 5 and sum(c["games"] for c in champions[:3]) / total >= 0.7:
        ptype = "專精"
    elif size >= max(8, total * 0.6):
        ptype = "廣泛"
    else:
        ptype = "均衡"
    return {"poolSize": size, "poolType": ptype, "topShare": round(top_share, 1)}


def _aggregate_player_stats(puuid: str, count: int = 20) -> dict:
    """取得玩家近 count 場戰績並統計聚合數據（SGP 優先，LCU 備援）。
    回傳 wins / total / winRate / avgKills / avgDeaths / avgAssists / kda；
    無法取得資料時回傳全零字典。
    """
    zero = {"wins": 0, "total": 0, "winRate": 0.0,
            "avgKills": 0.0, "avgDeaths": 0.0, "avgAssists": 0.0, "kda": 0.0,
            "topChampions": [], "allChampions": [], "poolSize": 0, "poolType": "",
            "topShare": 0.0, "streakType": "", "streakCount": 0,
            "recentGames": [], "mainPosition": "", "positionGames": 0,
            "killParticipation": 0.0, "damageShare": 0.0}
    if not puuid:
        return zero

    games = _fetch_games(puuid, count)

    wins = kills = deaths = assists = cnt = 0
    champ_stats: dict[int, dict] = {}  # championId -> {games, wins}
    results: list[bool] = []  # 勝負序列（最新在前），用於計算連勝/連敗
    recent_games: list[dict] = []  # 近期單場記錄（最新在前），用於趨勢小圖
    pos_stats: dict[str, int] = {}  # 位置 -> 場次
    sum_kp = sum_dmgshare = 0.0     # 參團率/傷害佔比累加
    for g in games:
        if g.get("gameDuration", 999) < 240:
            continue
        pdata = _find_participant(g, puuid)
        if not pdata:
            continue
        stats = pdata.get("stats") or pdata
        if stats.get("win") is None and stats.get("kills") is None:
            continue
        won      = bool(stats.get("win"))
        k = stats.get("kills", 0); d = stats.get("deaths", 0); a = stats.get("assists", 0)

        # 傷害佔比 / 參團率（需同隊總和）
        my_tid = pdata.get("teamId") or stats.get("teamId") or 0
        t_k = t_dmg = 0
        for pp in g.get("participants", []):
            ps = pp.get("stats") or pp
            if (pp.get("teamId") or ps.get("teamId") or 0) == my_tid:
                t_k   += ps.get("kills", 0)
                t_dmg += ps.get("totalDamageDealtToChampions", 0)
        my_dmg = stats.get("totalDamageDealtToChampions", 0)
        sum_kp       += (k + a) / t_k   if t_k   else 0
        sum_dmgshare += my_dmg / t_dmg  if t_dmg else 0
        cnt     += 1
        wins    += 1 if won else 0
        results.append(won)
        kills   += k
        deaths  += d
        assists += a
        # 近期單場記錄（最新在前），用於趨勢小圖
        recent_games.append({
            "win": won,
            "championId": pdata.get("championId") or stats.get("championId") or 0,
            "kda": round((k + a) / max(d, 1), 2),
            "k": k, "d": d, "a": a,
        })

        # 統計位置（teamPosition：TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY；ARAM 為空）
        pos = (pdata.get("teamPosition") or stats.get("teamPosition") or
               pdata.get("individualPosition") or "").upper()
        if pos and pos != "NONE":
            pos_stats[pos] = pos_stats.get(pos, 0) + 1

        # 統計每個英雄的場次與勝場（championId 在 pdata 頂層）
        ch_id = pdata.get("championId") or stats.get("championId") or 0
        if ch_id:
            _add_champ_game(champ_stats, ch_id, won, k, d, a)

    if cnt > 0:
        # 拿手英雄 Top3：≥2 場優先（場次→勝率排序），不足 3 個再用 1 場的補滿
        all_champs = _rank_champions(champ_stats)
        multi  = [c for c in all_champs if c["games"] >= 2]
        single = [c for c in all_champs if c["games"] < 2]
        top_champions = (multi + single)[:3]
        # 連勝/連敗：從最新一場往回數，相同結果連續幾場
        streak_type = ""
        streak_count = 0
        if results:
            first = results[0]
            for r in results:
                if r == first:
                    streak_count += 1
                else:
                    break
            streak_type = "win" if first else "lose"

        return {
            "wins":         wins,
            "total":        cnt,
            "winRate":      round(wins / cnt * 100, 1),
            "avgKills":     round(kills   / cnt, 1),
            "avgDeaths":    round(deaths  / cnt, 1),
            "avgAssists":   round(assists / cnt, 1),
            "kda":          round((kills + assists) / max(deaths, 1), 2),
            "topChampions": top_champions,
            "allChampions": all_champs,
            **_pool_summary(all_champs),
            "streakType":   streak_type,
            "streakCount":  streak_count,
            "recentGames":  recent_games[:5],
            "mainPosition": (max(pos_stats, key=pos_stats.get) if pos_stats else ""),
            "positionGames": (max(pos_stats.values()) if pos_stats else 0),
            "killParticipation": round(sum_kp / cnt * 100, 1),
            "damageShare":       round(sum_dmgshare / cnt * 100, 1),
        }
    return zero


@eel.expose
def get_player_detail(puuid: str, count: int = 20) -> dict:
    """點擊雷達玩家後，回傳該玩家的完整個人頁資料。
    含：聚合摘要、段位、完整拿手英雄列表、近期逐場戰績（附 gameId 供點擊看全場）。
    無法取得時回傳 ok=False。
    """
    if not _client or not puuid:
        return {"ok": False}

    games = _fetch_games(puuid, count)

    wins = kills = deaths = assists = cnt = 0
    champ_stats: dict[int, dict] = {}     # championId -> {games, wins}
    recent_games: list[dict] = []         # 逐場（最新在前）
    for g in games:
        if g.get("gameDuration", 999) < 240:
            continue
        pdata = _find_participant(g, puuid)
        if not pdata:
            continue
        stats = pdata.get("stats") or pdata
        if stats.get("win") is None and stats.get("kills") is None:
            continue
        won = bool(stats.get("win"))
        k = stats.get("kills", 0); d = stats.get("deaths", 0); a = stats.get("assists", 0)
        ch_id = pdata.get("championId") or stats.get("championId") or 0
        cnt     += 1
        wins    += 1 if won else 0
        kills   += k; deaths += d; assists += a
        if ch_id:
            _add_champ_game(champ_stats, ch_id, won, k, d, a)
        recent_games.append({
            "gameId":       g.get("gameId") or 0,
            "queueId":      g.get("queueId") or 0,
            "gameCreation": g.get("gameCreation") or 0,
            "duration":     g.get("gameDuration") or 0,
            "win":          won,
            "championId":   ch_id,
            "championName": _get_champ_name(ch_id) if ch_id else "",
            "k": k, "d": d, "a": a,
            "kda":          round((k + a) / max(d, 1), 2),
        })

    # 完整英雄池（依場次→勝率排序，附 KDA / 佔比）
    champions = _rank_champions(champ_stats)

    rank = {}
    try:
        rank = _fetch_ranked_stats(puuid)
    except Exception as e:
        _log(f"PLAYER_DETAIL >> 段位失敗: {e}")

    # ── 完整檔案頁所需的進階資料（沿用既有共用函式，免額外抓對局）──
    dual_rank = _fetch_ranked_dual(puuid)
    overview  = _compute_overview(games, puuid)

    # 逐場完整卡片（與儀表板 _buildMatchCard 相容；以該玩家視角解析）
    match_cards: list[dict] = []
    for g in games:
        try:
            card = _parse_one_game(g, "sgp", puuid)
            if card:
                match_cards.append(card)
        except Exception as ce:
            _log(f"PLAYER_DETAIL >> 卡片解析失敗 gameId={g.get('gameId','?')}: {ce}")

    # 召喚師基本資料（頭像 / 等級 / 顯示名稱）
    profile_icon = 0
    summoner_lv  = 0
    display_name = ""
    try:
        s = _client.get(f"/lol-summoner/v2/summoners/puuid/{puuid}")
        profile_icon = s.get("profileIconId", 0)
        summoner_lv  = s.get("summonerLevel", 0)
        gname        = (s.get("gameName") or s.get("displayName") or "").strip()
        gtag         = (s.get("tagLine") or "").strip()
        display_name = f"{gname}#{gtag}" if gtag else gname
    except Exception as e:
        _log(f"PLAYER_DETAIL >> 召喚師資料失敗: {e}")

    return {
        "ok":          cnt > 0,
        "puuid":       puuid,
        "wins":        wins,
        "total":       cnt,
        "winRate":     round(wins / cnt * 100, 1) if cnt else 0.0,
        "avgKills":    round(kills   / cnt, 1) if cnt else 0.0,
        "avgDeaths":   round(deaths  / cnt, 1) if cnt else 0.0,
        "avgAssists":  round(assists / cnt, 1) if cnt else 0.0,
        "kda":         round((kills + assists) / max(deaths, 1), 2) if cnt else 0.0,
        "champions":   champions,
        "pool":        _pool_summary(champions),
        "recentGames": recent_games,
        "rank":        rank,
        "rankSolo":    dual_rank["solo"],
        "rankFlex":    dual_rank["flex"],
        "overview":    overview,
        "matchCards":  match_cards,
        "profileIconId": profile_icon,
        "summonerLevel": summoner_lv,
        "displayName":   display_name,
        "tagInfo":     _get_tag(puuid),
    }


_last_recorded_game_id = None  # 防止同一場重複計入勝負記錄


def _record_game_result():
    """遊戲結束時呼叫：抓自己最新一場戰績，更新與已標記玩家的同隊/對敵勝負。"""
    global _last_recorded_game_id
    if not _tagged_players:
        return   # 沒有任何標記玩家，省略
    try:
        games = _fetch_player_games_sgp(_puuid, 1)
        if not games:
            raw = _client.get(
                f"/lol-match-history/v1/products/lol/{_puuid}/matches?begIndex=0&endIndex=0")
            games = raw.get("games", {}).get("games", [])
        if not games:
            _log("TAGGED >> 取不到最新對局，略過勝負記錄")
            return
        g = games[0]
        gid = g.get("gameId")
        if gid and gid == _last_recorded_game_id:
            return   # 已記錄過

        # 建立 puuid -> (teamId, win) 對照
        roster = []
        parts = g.get("participants", [])
        idents = {i.get("participantId"): i.get("player", {}).get("puuid", "")
                  for i in g.get("participantIdentities", [])}
        for p in parts:
            pu = p.get("puuid") or idents.get(p.get("participantId"), "")
            st = p.get("stats") or p
            tid = p.get("teamId") or st.get("teamId") or 0
            won = bool(st.get("win"))
            if pu:
                roster.append((pu, tid, won))

        me = next((r for r in roster if r[0] == _puuid), None)
        if not me:
            _log("TAGGED >> 最新對局找不到自己，略過")
            return
        my_tid, my_win = me[1], me[2]

        updated = 0
        for pu, tid, _ in roster:
            if pu == _puuid or pu not in _tagged_players:
                continue
            rec = _tagged_players[pu]
            same_team = (tid == my_tid)
            if same_team:
                key = "withWins" if my_win else "withLosses"
            else:
                key = "vsWins" if my_win else "vsLosses"
            rec[key] = rec.get(key, 0) + 1
            updated += 1

        if updated:
            _last_recorded_game_id = gid
            _save_tagged_players()
            _log(f"TAGGED >> 已更新 {updated} 位標記玩家的勝負記錄（本場{'勝' if my_win else '敗'}）")
    except Exception as e:
        _log(f"TAGGED_RECORD_ERR >> {e}")


_OVERVIEW_ZERO = {"games": 0, "wins": 0, "losses": 0, "winRate": 0.0, "kda": 0.0,
                  "avgKills": 0.0, "avgDeaths": 0.0, "avgAssists": 0.0,
                  "killParticipation": 0.0, "damageShare": 0.0,
                  "goldShare": 0.0, "csShare": 0.0}


def _compute_overview(games: list, puuid: str) -> dict:
    """從一批 SGP/LCU 原始 game 計算指定玩家的進階數據：
    參團率、傷害比、經濟比、補刀比等。可用於本人或任意玩家。
    games 取不到玩家或為空時回傳全零。
    """
    if not games or not puuid:
        return dict(_OVERVIEW_ZERO)
    n = wins = 0
    sumK = sumD = sumA = 0
    sumKP = sumDmgShare = sumGoldShare = sumCsShare = 0.0
    for g in games:
        if g.get("gameDuration", 999) < 240:
            continue
        parts = g.get("participants", [])
        idents = {i.get("participantId"): i.get("player", {}).get("puuid", "")
                  for i in g.get("participantIdentities", [])}
        # 找目標玩家
        me = None
        for p in parts:
            pu = p.get("puuid") or idents.get(p.get("participantId"), "")
            if pu == puuid:
                me = p; break
        if not me:
            continue
        ms = me.get("stats") or me
        my_tid = me.get("teamId") or ms.get("teamId") or 0

        # 同隊統計
        tK = tDmg = tGold = tCs = 0
        for p in parts:
            st = p.get("stats") or p
            tid = p.get("teamId") or st.get("teamId") or 0
            if tid != my_tid:
                continue
            tK   += st.get("kills", 0)
            tDmg += st.get("totalDamageDealtToChampions", 0)
            tGold+= st.get("goldEarned", 0)
            tCs  += st.get("totalMinionsKilled", 0) + st.get("neutralMinionsKilled", 0)

        mk = ms.get("kills", 0); md = ms.get("deaths", 0); ma = ms.get("assists", 0)
        myDmg = ms.get("totalDamageDealtToChampions", 0)
        myGold= ms.get("goldEarned", 0)
        myCs  = ms.get("totalMinionsKilled", 0) + ms.get("neutralMinionsKilled", 0)

        n += 1
        wins += 1 if ms.get("win") else 0
        sumK += mk; sumD += md; sumA += ma
        sumKP        += (mk + ma) / tK   if tK   else 0
        sumDmgShare  += myDmg / tDmg      if tDmg else 0
        sumGoldShare += myGold / tGold    if tGold else 0
        sumCsShare   += myCs / tCs        if tCs  else 0

    if n == 0:
        return dict(_OVERVIEW_ZERO)
    return {
        "games":   n,
        "wins":    wins,
        "losses":  n - wins,
        "winRate": round(wins / n * 100, 1),
        "kda":     round((sumK + sumA) / max(sumD, 1), 2),
        "avgKills":   round(sumK / n, 1),
        "avgDeaths":  round(sumD / n, 1),
        "avgAssists": round(sumA / n, 1),
        "killParticipation": round(sumKP / n * 100, 1),
        "damageShare":       round(sumDmgShare / n * 100, 1),
        "goldShare":         round(sumGoldShare / n * 100, 1),
        "csShare":           round(sumCsShare / n * 100, 1),
    }


@eel.expose
def get_personal_overview(count: int = 20) -> dict:
    """統計本人近 count 場的進階數據：參團率、傷害比、經濟比、補刀比等。"""
    if not _puuid:
        return dict(_OVERVIEW_ZERO)
    try:
        return _compute_overview(_fetch_player_games_sgp(_puuid, count), _puuid)
    except Exception as e:
        _log(f"OVERVIEW_ERR >> {e}")
        return dict(_OVERVIEW_ZERO)


@eel.expose
def get_match_dashboard(count: int = 50) -> dict:
    """戰績數據儀表板：聚合近 count 場做視覺化。
    回傳勝率累積走勢、近期手感、評級分布、佇列分布、KDA 趨勢、最佳/最差英雄。
    """
    empty = {"summary": {}, "winTrend": [], "recentForm": [], "gradeDist": [],
             "queueDist": [], "kdaTrend": [], "bestChamps": [], "worstChamps": []}
    if not _client or not _puuid:
        return empty
    try:
        games = get_match_history(0, count)
        games = [g for g in (games or []) if g.get("gameResult") != "REMAKE"]
        if not games:
            return empty

        n      = len(games)
        wins   = sum(1 for g in games if g.get("win"))
        sumK   = sum(g.get("kills", 0)   for g in games)
        sumD   = sum(g.get("deaths", 0)  for g in games)
        sumA   = sum(g.get("assists", 0) for g in games)
        sumDmg = sum(g.get("damage", 0)  for g in games)

        # get_match_history 最新在前；走勢圖需由舊到新
        chrono = list(reversed(games))

        # 勝率累積走勢（由舊到新）
        win_trend = []
        cw = 0
        for i, g in enumerate(chrono, 1):
            cw += 1 if g.get("win") else 0
            win_trend.append({"i": i, "winRate": round(cw / i * 100, 1)})

        # KDA 逐場趨勢（由舊到新）
        kda_trend = [
            {"i": i, "kda": round((g.get("kills", 0) + g.get("assists", 0)) /
                                  max(g.get("deaths", 0), 1), 2)}
            for i, g in enumerate(chrono, 1)
        ]

        # 近期手感（最新 12 場，最新在前）
        recent_form = [
            {"win": bool(g.get("win")),
             "championId":   g.get("championId", 0),
             "championName": g.get("championName", ""),
             "kda":   round((g.get("kills", 0) + g.get("assists", 0)) /
                            max(g.get("deaths", 0), 1), 2),
             "grade": g.get("grade", "")}
            for g in games[:12]
        ]

        # 評級分布（S/A/B/C/D，依首字母歸類）
        buckets = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
        for g in games:
            gr = (g.get("grade") or "").strip().upper()
            if gr and gr[0] in buckets:
                buckets[gr[0]] += 1
        grade_dist = [{"grade": k, "count": v} for k, v in buckets.items()]

        # 佇列分布（含各佇列勝率）
        q_stats: dict[str, dict] = {}
        for g in games:
            q = g.get("queue") or "其他"
            s = q_stats.setdefault(q, {"games": 0, "wins": 0})
            s["games"] += 1
            s["wins"]  += 1 if g.get("win") else 0
        queue_dist = [
            {"queue": k, "games": v["games"], "wins": v["wins"],
             "winRate": round(v["wins"] / v["games"] * 100, 1)}
            for k, v in sorted(q_stats.items(), key=lambda kv: -kv[1]["games"])
        ]

        # 英雄表現（≥2 場）→ 最佳 / 最差
        champ: dict[int, dict] = {}
        for g in games:
            cid = g.get("championId", 0)
            if not cid:
                continue
            c = champ.setdefault(cid, {"name": g.get("championName", f"#{cid}"),
                                       "games": 0, "wins": 0, "k": 0, "d": 0, "a": 0})
            c["games"] += 1
            c["wins"]  += 1 if g.get("win") else 0
            c["k"] += g.get("kills", 0); c["d"] += g.get("deaths", 0); c["a"] += g.get("assists", 0)
        champ_rows = [
            {"championId": cid, "name": c["name"], "games": c["games"], "wins": c["wins"],
             "winRate": round(c["wins"] / c["games"] * 100, 1),
             "kda": round((c["k"] + c["a"]) / max(c["d"], 1), 2)}
            for cid, c in champ.items() if c["games"] >= 2
        ]
        best  = sorted(champ_rows, key=lambda r: (-r["winRate"], -r["games"]))[:5]
        worst = sorted(champ_rows, key=lambda r: (r["winRate"], -r["games"]))[:5]

        return {
            "summary": {
                "games": n, "wins": wins, "losses": n - wins,
                "winRate": round(wins / n * 100, 1),
                "kda": round((sumK + sumA) / max(sumD, 1), 2),
                "avgKills": round(sumK / n, 1), "avgDeaths": round(sumD / n, 1),
                "avgAssists": round(sumA / n, 1), "avgDamage": int(sumDmg / n),
            },
            "winTrend":    win_trend,
            "kdaTrend":    kda_trend,
            "recentForm":  recent_form,
            "gradeDist":   grade_dist,
            "queueDist":   queue_dist,
            "bestChamps":  best,
            "worstChamps": worst,
        }
    except Exception as e:
        _log(f"DASHBOARD_ERR >> {e}")
        return empty


_TIER_ZH = {
    "IRON": "黑鐵", "BRONZE": "青銅", "SILVER": "白銀",
    "GOLD": "黃金", "PLATINUM": "白金", "EMERALD": "翡翠",
    "DIAMOND": "鑽石", "MASTER": "大師",
    "GRANDMASTER": "宗師", "CHALLENGER": "菁英",
}
_TIER_ICON = {
    "IRON": "⬛", "BRONZE": "🟫", "SILVER": "🩶",
    "GOLD": "🥇", "PLATINUM": "🔷", "EMERALD": "💚",
    "DIAMOND": "💎", "MASTER": "🔮",
    "GRANDMASTER": "👑", "CHALLENGER": "🏆",
}
_DIV_MAP = {"I": "Ⅰ", "II": "Ⅱ", "III": "Ⅲ", "IV": "Ⅳ"}
_NO_RANK = {"", "NONE", "UNRANKED", "NA"}


def _fetch_ranked_stats(puuid: str) -> dict:
    """查詢玩家積分段位（優先單雙，次選彈性）。
    回傳 tier / tierText / rankWins / rankLosses / rankWinRate / lp。
    無段位時 tier='UNRANKED'，tierText='未排位'。
    """
    zero = {"tier": "UNRANKED", "tierText": "未排位", "division": "",
            "rankWins": 0, "rankLosses": 0, "rankWinRate": 0.0, "lp": 0}
    if not puuid or not _client:
        return zero
    try:
        data   = _client.get(f"/lol-ranked/v1/ranked-stats/{puuid}")
        queues = data.get("queues") or list((data.get("queueMap") or {}).values())
        solo = next((q for q in queues if q.get("queueType") == "RANKED_SOLO_5x5"), None)
        flex = next((q for q in queues if q.get("queueType") == "RANKED_FLEX_SR"),  None)
        entry = solo or flex
        if not entry:
            return zero
        tier = (entry.get("tier") or "").upper()
        if tier in _NO_RANK:
            return zero
        division = (entry.get("division") or entry.get("rank") or "")
        wins     = entry.get("wins", 0)
        losses   = entry.get("losses", 0)
        lp       = entry.get("leaguePoints", 0)
        total    = wins + losses
        wr       = round(wins / total * 100, 1) if total > 0 else 0.0
        icon     = _TIER_ICON.get(tier, "")
        zh       = _TIER_ZH.get(tier, tier)
        if tier in ("MASTER", "GRANDMASTER", "CHALLENGER"):
            tier_text = f"{icon} {zh}"
        else:
            tier_text = f"{icon} {zh} {_DIV_MAP.get(division, division)}"
        return {
            "tier":        tier,
            "tierText":    tier_text,
            "division":    division,
            "rankWins":    wins,
            "rankLosses":  losses,
            "rankWinRate": wr,
            "lp":          lp,
        }
    except Exception as e:
        _log(f"RANKED_ERR >> {puuid[:8] if puuid else '?'}: {e}")
        return zero


def _format_ranked_queue(entry: dict | None) -> dict:
    """把單一隊列的段位原始資料格式化為前端可用結構。無段位回傳 UNRANKED。"""
    zero = {"tier": "UNRANKED", "tierText": "未排位", "division": "",
            "rankWins": 0, "rankLosses": 0, "rankWinRate": 0.0, "lp": 0}
    if not entry:
        return zero
    tier = (entry.get("tier") or "").upper()
    if tier in _NO_RANK:
        return zero
    division = (entry.get("division") or entry.get("rank") or "")
    wins     = entry.get("wins", 0)
    losses   = entry.get("losses", 0)
    lp       = entry.get("leaguePoints", 0)
    total    = wins + losses
    wr       = round(wins / total * 100, 1) if total > 0 else 0.0
    icon     = _TIER_ICON.get(tier, "")
    zh       = _TIER_ZH.get(tier, tier)
    if tier in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        tier_text = f"{icon} {zh}"
    else:
        tier_text = f"{icon} {zh} {_DIV_MAP.get(division, division)}"
    return {
        "tier":        tier,
        "tierText":    tier_text,
        "division":    division,
        "rankWins":    wins,
        "rankLosses":  losses,
        "rankWinRate": wr,
        "lp":          lp,
    }


def _fetch_ranked_dual(puuid: str) -> dict:
    """同時取得單雙排位與彈性排位段位，供玩家完整檔案頁顯示。
    回傳 {"solo": {...}, "flex": {...}}，各自為 _format_ranked_queue 結構。
    """
    zero = {"tier": "UNRANKED", "tierText": "未排位", "division": "",
            "rankWins": 0, "rankLosses": 0, "rankWinRate": 0.0, "lp": 0}
    if not puuid or not _client:
        return {"solo": dict(zero), "flex": dict(zero)}
    try:
        data   = _client.get(f"/lol-ranked/v1/ranked-stats/{puuid}")
        queues = data.get("queues") or list((data.get("queueMap") or {}).values())
        solo = next((q for q in queues if q.get("queueType") == "RANKED_SOLO_5x5"), None)
        flex = next((q for q in queues if q.get("queueType") == "RANKED_FLEX_SR"),  None)
        return {"solo": _format_ranked_queue(solo), "flex": _format_ranked_queue(flex)}
    except Exception as e:
        _log(f"RANKED_DUAL_ERR >> {puuid[:8] if puuid else '?'}: {e}")
        return {"solo": dict(zero), "flex": dict(zero)}


def _maybe_trigger_lobby_scan(my_team: list):
    """若大廳成員組合改變，啟動背景執行緒掃描所有隊友。
    嚴格守衛：只允許在 ChampSelect 階段觸發，其他任何狀態直接 return。
    """
    global _last_scanned_team_key, _lobby_scan_in_progress
    # Phase 守衛：Lobby / Matchmaking / ReadyCheck 等階段一律略過
    if _current_gameflow_phase != "ChampSelect":
        return
    if not my_team:
        return
    # 用 cellId 組成穩定的場次識別鍵（cellId 在同一場選角內固定）
    team_key = ",".join(sorted(str(p.get("cellId", -1)) for p in my_team))
    if not team_key or team_key == _last_scanned_team_key or _lobby_scan_in_progress:
        return
    _last_scanned_team_key  = team_key
    _lobby_scan_in_progress = True
    threading.Thread(target=_scan_lobby_sync, args=(list(my_team),), daemon=True).start()


def _participant_name(p: dict) -> str:
    """從對局 participant 盡量取出「名稱#Tag」（欄位因來源而異，找不到回傳空字串）。"""
    name = (p.get("riotIdGameName") or p.get("gameName") or p.get("summonerName") or "").strip()
    tag  = (p.get("riotIdTagline") or p.get("tagLine") or "").strip()
    if not name:
        pl = p.get("player") or {}
        name = (pl.get("gameName") or pl.get("summonerName") or "").strip()
        tag  = tag or (pl.get("tagLine") or "").strip()
    return f"{name}#{tag}" if name and tag else name


def _build_encounters(count: int = 50) -> dict:
    """掃描自己近 count 場，建立「puuid -> 同隊/對手遭遇紀錄」。
    回傳 {puuid: {"ally": {"games","wins"}, "enemy": {"games","wins"}}}；失敗回傳空字典。
    每次掃描只呼叫一次，再由各玩家查表，避免重複抓戰績。
    """
    out: dict[str, dict] = {}
    if not _puuid:
        return out
    try:
        for g in _fetch_games(_puuid, count):
            if g.get("gameDuration", 999) < 240:
                continue
            me = _find_participant(g, _puuid)
            if not me:
                continue
            my_stats = me.get("stats") or me
            if my_stats.get("win") is None:
                continue
            won    = bool(my_stats.get("win"))
            my_tid = me.get("teamId") or my_stats.get("teamId") or 0
            for p in g.get("participants", []):
                pid = p.get("puuid") or ""
                if not pid or pid == _puuid or pid == _EMPTY_PUUID:
                    continue
                tid  = p.get("teamId") or (p.get("stats") or {}).get("teamId") or 0
                side = "ally" if tid == my_tid else "enemy"
                rec  = out.setdefault(pid, {"ally": {"games": 0, "wins": 0},
                                            "enemy": {"games": 0, "wins": 0}, "name": ""})
                rec[side]["games"] += 1
                rec[side]["wins"]  += 1 if won else 0
                if not rec.get("name"):
                    rec["name"] = _participant_name(p)
    except Exception as e:
        _log(f"ENCOUNTERS_ERR >> {e}")
    return out


_LIVE_API = "https://127.0.0.1:2999/liveclientdata"


def _live_get(path: str):
    """讀取遊戲內即時資料 API（僅在對局進行中開放）；失敗回傳 None。"""
    try:
        r = requests.get(f"{_LIVE_API}/{path}", timeout=1.0, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _champ_id_by_name(name: str) -> int:
    """由（本地化）英雄名反查 championId，供 HUD 顯示頭像；查不到回傳 0。"""
    if not name:
        return 0
    for cid, n in _champ_cache.items():
        if n == name:
            return cid
    for cid, meta in _champ_meta.items():
        if (meta.get("name") or "") == name:
            return cid
    return 0


def _norm_name(n: str) -> str:
    return (n or "").split("#")[0].strip().lower()


# ── 敵方召喚師技能計時（遊戲 API 不提供敵方施放事件 → 靠全域快捷鍵手動標記）──────────
# 基礎冷卻秒數（依 rawDisplayName 內含的技能代碼比對）
SPELL_TRACKING_ENABLED = False   # 敵方召喚師技能手動計時（預設關閉；開啟後 HUD 顯示敵方編號/技能，快捷鍵 Ctrl+Alt+1~5 啟用）
_SPELL_BASE_CD = {
    "SummonerFlash": 300, "SummonerTeleport": 360, "SummonerDot": 180, "SummonerHeal": 240,
    "SummonerBarrier": 180, "SummonerExhaust": 210, "SummonerBoost": 210, "SummonerHaste": 210,
    "SummonerSmite": 90, "SummonerMana": 240, "SummonerSnowball": 80,
}
_IONIAN_BOOTS = 3158      # 神速之靴：+12 召喚師技能急速（星際洞悉符文無法由 API 得知，未計入）
_spell_used: dict = {}    # (玩家名, 欄位 1/2) -> 標記當下的遊戲時間（秒）
_hud_enemies: list = []   # 最近一次 HUD 資料中的敵方玩家（供快捷鍵對應 1~5 號）


def _spell_code(raw: str) -> str:
    for code in _SPELL_BASE_CD:
        if code in (raw or ""):
            return code
    return ""


def _spell_cd(code: str, items: list) -> float:
    base = _SPELL_BASE_CD.get(code, 0)
    items = items if isinstance(items, list) else []      # 機器人等情況欄位可能不是清單
    haste = 12 if any(isinstance(i, dict) and i.get("itemID") == _IONIAN_BOOTS for i in items) else 0
    return round(base * 100 / (100 + haste))


def _mark_enemy_spell(idx: int, other: bool):
    """快捷鍵觸發：把敵方第 idx 號（1~5）的閃現（other=False）或另一招（other=True）標記為剛使用。
    3 秒內再按同一個鍵 = 取消（按錯時的復原）。"""
    if not (1 <= idx <= len(_hud_enemies)):
        return
    e = _hud_enemies[idx - 1]
    spells = e.get("spells") or []
    flash = next((x for x in spells if x["code"] == "SummonerFlash"), None)
    if other:
        sp = next((x for x in spells if x is not flash), None)
    else:
        sp = flash or (spells[0] if spells else None)
    if not sp:
        return
    t = (_live_get("gamestats") or {}).get("gameTime")
    if t is None:
        return
    key = (e["name"], sp["slot"])
    last = _spell_used.get(key)
    if last is not None and t - last < 3:
        del _spell_used[key]                       # 復原
        _log(f"SPELL >> 取消標記 敵{idx} {sp['name']}")
    else:
        _spell_used[key] = t
        _log(f"SPELL >> 敵{idx} {e['champion']} {sp['name']} 已使用（冷卻 {sp['cd']}s）")


# ── 目標重生計時（來自遊戲內事件 API 的擊殺事件；只用「擊殺後重生」這類穩定規則）──
_DRAGON_RESPAWN = 300      # 小龍被擊殺後 5 分鐘重生
_ELDER_RESPAWN  = 360      # 遠古龍 6 分鐘
_BARON_RESPAWN  = 360      # 男爵 6 分鐘
_INHIB_RESPAWN  = 300      # 水晶被摧毀後 5 分鐘重生
_LANE_NAME = {"L": "上路", "C": "中路", "R": "下路"}   # Barracks_T1_L1 的 L/C/R


def _compute_objectives(events: list, now: float, my_team: str) -> list:
    """由事件列表算出各目標的重生倒數。回傳 [{key,label,remaining,side}]，只含倒數中的項目。"""
    out = []
    last_dragon = last_baron = None
    inhibs = {}
    for e in events or []:
        if not isinstance(e, dict):
            continue
        name, t = e.get("EventName"), e.get("EventTime")
        if not isinstance(t, (int, float)):
            continue
        if name == "DragonKill":
            last_dragon = e
        elif name == "BaronKill":
            last_baron = e
        elif name == "InhibKilled":
            inhibs[str(e.get("InhibKilled", ""))] = t        # 同一水晶以最新一次為準
    if last_dragon:
        cd = _ELDER_RESPAWN if last_dragon.get("DragonType") == "Elder" else _DRAGON_RESPAWN
        rem = round(cd - (now - last_dragon["EventTime"]))
        if rem > 0:
            out.append({"key": "dragon", "label": "遠古龍" if cd == _ELDER_RESPAWN else "小龍", "remaining": rem, "side": ""})
    if last_baron:
        rem = round(_BARON_RESPAWN - (now - last_baron["EventTime"]))
        if rem > 0:
            out.append({"key": "baron", "label": "男爵", "remaining": rem, "side": ""})
    for nm, t in inhibs.items():
        rem = round(_INHIB_RESPAWN - (now - t))
        if rem <= 0:
            continue
        parts = nm.split("_")                                  # Barracks_T1_L1
        team_tag = parts[1] if len(parts) > 1 else ""
        lane = _LANE_NAME.get(parts[2][:1], "") if len(parts) > 2 else ""
        mine = (team_tag == "T1") == (my_team in ("", "ORDER"))   # T1 = 藍方(ORDER)
        out.append({"key": "inhib", "label": f"{'我方' if mine else '敵方'}{lane}水晶", "remaining": rem,
                    "side": "my" if mine else "enemy"})
    return out


_obj_seen: set = set()


def _log_objective_events(events):
    """把龍/男爵/水晶事件原始內容寫進 debug.log（每筆只記一次），供賽後核對計時是否正確。"""
    for e in events or []:
        if not isinstance(e, dict) or e.get("EventName") not in ("DragonKill", "BaronKill", "InhibKilled", "InhibRespawned", "HeraldKill", "HordeKill"):
            continue
        key = (e.get("EventName"), e.get("EventTime"), e.get("InhibKilled"), e.get("DragonType"))
        if key in _obj_seen:
            continue
        _obj_seen.add(key)
        _log(f"OBJ_EVENT >> {json.dumps(e, ensure_ascii=False)}")


@eel.expose
def get_hud_data() -> dict:
    """遊戲中 HUD 輪詢：合併「遊戲內即時資料」與「全場雷達掃描結果」。
    即時資料不可用（載入畫面、非對局）時，只回傳掃描結果（live=False）。"""
    scan_by_name = {}
    for side, key in (("my", "my"), ("enemy", "enemy")):
        for e in _hud_scan.get(key, []):
            scan_by_name[_norm_name(e.get("name", ""))] = (side, e)

    def _brief(e: dict) -> dict:
        return {"winRate": e.get("winRate", 0), "kda": e.get("kda", 0), "total": e.get("total", 0),
                "streakType": e.get("streakType", ""), "streakCount": e.get("streakCount", 0),
                "poolType": e.get("poolType", ""), "tier": e.get("tierText", ""),
                "encounter": e.get("encounter")}

    players_raw = _live_get("playerlist")
    if not isinstance(players_raw, list):
        # 尚無即時資料：用掃描結果撐場面
        rows = []
        for side in ("my", "enemy"):
            for e in _hud_scan.get(side, []):
                rows.append({"side": side, "name": e.get("name", ""), "champion": e.get("championName", ""),
                             "championId": e.get("championId", 0), "k": 0, "d": 0, "a": 0, "cs": 0,
                             "dead": False, "respawn": 0, "level": 0, "scan": _brief(e)})
        return {"live": False, "gameTime": 0, "players": rows, "spellTracking": SPELL_TRACKING_ENABLED}

    active = _live_get("activeplayername")
    active_team = ""
    for p in players_raw:
        nm = (p.get("riotIdGameName") or p.get("summonerName") or "")
        if active and (p.get("riotId") == active or p.get("summonerName") == active
                       or _norm_name(nm) == _norm_name(str(active))):
            active_team = p.get("team", "")
            break
    stats = _live_get("gamestats") or {}
    now   = stats.get("gameTime", 0)
    ev    = (_live_get("eventdata") or {}).get("Events", [])
    _log_objective_events(ev)
    try:
        objectives = _compute_objectives(ev, now, active_team)
    except Exception as e:
        objectives = []
        _log(f"OBJ_ERR >> {e}")
    if _spell_used and any(t > now + 1 for t in _spell_used.values()):
        _spell_used.clear()                        # 遊戲時間倒退 = 新的一場

    rows = []
    for p in players_raw:
        nm   = (p.get("riotIdGameName") or p.get("summonerName") or "").strip()
        sc   = p.get("scores") or {}
        champ = p.get("championName", "")
        found = scan_by_name.get(_norm_name(nm))
        cid   = (found[1].get("championId") if found else 0) or _champ_id_by_name(champ)
        side = "my" if (not active_team or p.get("team") == active_team) else "enemy"
        spells = []
        if side == "enemy" and SPELL_TRACKING_ENABLED:
            ss = p.get("summonerSpells") if isinstance(p.get("summonerSpells"), dict) else {}
            for slot, k in ((1, "summonerSpellOne"), (2, "summonerSpellTwo")):
                sp = ss.get(k) if isinstance(ss.get(k), dict) else {}
                code = _spell_code(sp.get("rawDisplayName", ""))
                cd   = _spell_cd(code, p.get("items"))
                used = _spell_used.get((nm, slot))
                rem  = max(0, round(cd - (now - used))) if (used is not None and cd) else 0
                spells.append({"slot": slot, "code": code, "name": sp.get("displayName", ""),
                               "cd": cd, "remaining": rem})
        rows.append({
            "side": side, "spells": spells,
            "name": nm, "champion": champ, "championId": cid or 0,
            "k": sc.get("kills", 0), "d": sc.get("deaths", 0), "a": sc.get("assists", 0),
            "cs": sc.get("creepScore", 0), "level": p.get("level", 0),
            "dead": bool(p.get("isDead")), "respawn": round(p.get("respawnTimer", 0) or 0),
            "isBot": bool(p.get("isBot")),
            "scan": _brief(found[1]) if found else None,
        })
    global _hud_enemies
    enemies = [r for r in rows if r["side"] == "enemy"]
    if SPELL_TRACKING_ENABLED:
        for i, r in enumerate(enemies, 1):
            r["idx"] = i
    _hud_enemies = enemies
    return {"live": True, "gameTime": round(now), "players": rows, "spellTracking": SPELL_TRACKING_ENABLED,
            "objectives": objectives}


# ── HUD 視窗樣式（Windows）：置頂但不影響遊戲操作 ─────────────────────────
_HUD_TITLE = "LeagueMrfox 遊戲中 HUD"
_hud_state = {"click_through": True, "user_hidden": False, "visible": False}
_HUD_ALPHA = 225        # 0~255，約 88% 不透明


def _hud_hwnd():
    try:
        import ctypes
        return ctypes.windll.user32.FindWindowW(None, _HUD_TITLE) or 0
    except Exception:
        return 0


def _hud_apply_style(click_through: bool):
    """套用視窗樣式：分層半透明 + 工具視窗(不進工作列) + 不取得焦點 + 可選的點擊穿透。"""
    import ctypes
    from ctypes import wintypes
    hwnd = _hud_hwnd()
    if not hwnd:
        return False
    u = ctypes.windll.user32
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT, WS_EX_LAYERED = 0x20, 0x80000
    WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
    ex = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    ex = (ex | WS_EX_TRANSPARENT) if click_through else (ex & ~WS_EX_TRANSPARENT)
    u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)
    u.SetLayeredWindowAttributes(hwnd, 0, _HUD_ALPHA, 0x2)   # LWA_ALPHA
    return True


def _hud_show_noactivate():
    """顯示並置頂，但不搶走遊戲焦點（不使用 pywebview.show()，它會啟用視窗）。"""
    import ctypes
    hwnd = _hud_hwnd()
    if not hwnd:
        if _hud_window:
            _hud_window.show()      # 找不到 hwnd 的退路
        return
    _hud_apply_style(_hud_state["click_through"])     # 先套 NOACTIVATE，之後顯示才不會搶焦點
    if not _hud_state.get("inited") and _hud_window:
        # 第一次必須走 pywebview.show()，內嵌網頁引擎才會真正載入頁面（只用 ShowWindow 會是白板）
        _hud_window.show()
        time.sleep(1.2)
        _hud_state["inited"] = True
        _hud_apply_style(_hud_state["click_through"])
    u = ctypes.windll.user32
    u.ShowWindow(hwnd, 4)           # SW_SHOWNOACTIVATE
    # HWND_TOPMOST=-1；SWP_NOSIZE|SWP_NOMOVE|SWP_NOACTIVATE = 0x1|0x2|0x10
    u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x13)
    _hud_state["visible"] = True


def _hud_hide_native():
    import ctypes
    hwnd = _hud_hwnd()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0)    # SW_HIDE
    elif _hud_window:
        _hud_window.hide()
    _hud_state["visible"] = False


_hotkey_last: dict = {}


def _hotkey_action(action: int):
    """統一處理快捷鍵動作（RegisterHotKey 與按鍵輪詢兩條路徑共用，0.4 秒內重複觸發視為同一次）。
    1=顯示/隱藏 2=點擊穿透切換 11~15=敵方閃現 21~25=敵方另一招"""
    now = time.time()
    if now - _hotkey_last.get(action, 0) < 0.4:
        return
    _hotkey_last[action] = now
    try:
        if action == 1:
            if _hud_state["visible"]:
                _hud_state["user_hidden"] = True
                _hud_hide_native()
            else:
                _hud_state["user_hidden"] = False
                _hud_show_noactivate()
        elif action == 2:
            _hud_state["click_through"] = not _hud_state["click_through"]
            _hud_apply_style(_hud_state["click_through"])
            _log(f"HUD >> {'點擊穿透（不影響遊戲操作）' if _hud_state['click_through'] else '可拖動模式'}")
        elif 11 <= action <= 15:
            _mark_enemy_spell(action - 10, other=False)
        elif 21 <= action <= 25:
            _mark_enemy_spell(action - 20, other=True)
    except Exception as e:
        _log(f"HUD_HOTKEY_ERR >> {e}")


def _hud_hotkeys():
    """路徑一：RegisterHotKey 全域快捷鍵。
    Ctrl+Alt+H 顯示/隱藏；Ctrl+Alt+J 切換點擊穿透/可拖動；Ctrl+Alt+1~5 敵方閃現；+Shift 另一招。"""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    MOD = 0x1 | 0x2 | 0x4000        # ALT | CTRL | NOREPEAT
    bad = []
    table = [(1, MOD, 0x48, "H"), (2, MOD, 0x4A, "J")]
    for n in range(1, 6):
        if not SPELL_TRACKING_ENABLED:
            break
        table.append((10 + n, MOD, 0x30 + n, f"{n}"))
        table.append((20 + n, MOD | 0x4, 0x30 + n, f"Shift+{n}"))
    for aid, mod, vk, nm in table:
        if not u.RegisterHotKey(None, aid, mod, vk):
            bad.append(nm)
    if bad:
        _log(f"HUD_HOTKEY >> RegisterHotKey 註冊失敗: {bad}（改由按鍵輪詢備援處理）")
    msg = wintypes.MSG()
    while u.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == 0x0312:                   # WM_HOTKEY
            _hotkey_action(int(msg.wParam))


def _hud_key_poll():
    """路徑二（備援）：輪詢實際按鍵狀態。反作弊/其他程式攔截 RegisterHotKey 時仍能運作。
    只在「Ctrl+Alt 同時按著」時才處理，且只在按下瞬間（邊緣）觸發一次。"""
    import ctypes
    gk = ctypes.windll.user32.GetAsyncKeyState
    keys = {0x48: 1, 0x4A: 2}
    for n in range(1, 6):
        if SPELL_TRACKING_ENABLED:
            keys[0x30 + n] = n
    prev = set()
    logged = False
    while True:
        time.sleep(0.03)
        try:
            ctrl = gk(0x11) & 0x8000
            alt  = gk(0x12) & 0x8000
            if not (ctrl and alt):
                prev.clear()
                continue
            shift = bool(gk(0x10) & 0x8000)
            for vk, n in keys.items():
                down = bool(gk(vk) & 0x8000)
                if down and vk not in prev:
                    prev.add(vk)
                    if not logged:
                        _log("HUD_KEYPOLL >> 已偵測到快捷鍵按下（輪詢通道運作中）")
                        logged = True
                    if vk in (0x48, 0x4A):
                        _hotkey_action(n)
                    else:
                        _hotkey_action((20 if shift else 10) + n)
                elif not down:
                    prev.discard(vk)
        except Exception as e:
            _log(f"HUD_KEYPOLL_ERR >> {e}")
            time.sleep(2)


def _safe_eel_call(name: str, *args):
    """呼叫前端函式；視窗尚未就緒或沒有該函式時靜默忽略。"""
    try:
        getattr(eel, name)(*args)()
    except Exception:
        pass


@eel.expose
def is_game_running() -> bool:
    """遊戲內即時資料 API 是否有回應（= 對局進行中）。"""
    return _live_get("gamestats") is not None


def _hud_watcher():
    """HUD 顯示由「遊戲內即時資料 API 是否可用」決定，不依賴 LCU：
    遊戲設定為「開局後關閉客戶端」、或本程式在遊戲中才啟動時也能正常顯示。"""
    visible = False
    miss = 0
    while True:
        time.sleep(2)
        up = _live_get("gamestats") is not None
        if up != _hud_state.get("game_up"):
            _hud_state["game_up"] = up
            threading.Thread(target=lambda u=up: _safe_eel_call("on_game_status", u), daemon=True).start()
        try:
            if up:
                miss = 0
                if not visible and _hud_window:
                    visible = True
                    if not _hud_state["user_hidden"]:
                        _hud_show_noactivate()
                        _log("HUD >> 偵測到遊戲進行中，顯示 HUD（置頂、點擊穿透）")
            else:
                miss += 1
                if visible and miss >= 5 and _hud_window:   # 連續 10 秒沒資料才視為遊戲結束
                    _hud_hide_native()
                    visible = False
                    _hud_state["user_hidden"] = False       # 下一場重新自動顯示
                    _hud_scan["my"], _hud_scan["enemy"] = [], []
                    _spell_used.clear()
                    _log("HUD >> 遊戲結束，隱藏 HUD")
        except Exception as e:
            _log(f"HUD_WATCH_ERR >> {e}")


@eel.expose
def hud_resize(height: int):
    """HUD 依內容高度自動縮放（避免下方空白擋住遊戲畫面）。"""
    try:
        if _hud_window:
            _hud_window.resize(330, max(90, min(int(height), 700)))
    except Exception as e:
        _log(f"HUD_RESIZE_ERR >> {e}")


@eel.expose
def hud_hide():
    """HUD 右上角關閉鈕：隱藏浮窗（下一場遊戲會再自動顯示）。"""
    try:
        _hud_state["user_hidden"] = True
        _hud_hide_native()
    except Exception as e:
        _log(f"HUD_HIDE_ERR >> {e}")


@eel.expose
def get_encounter_ranking(count: int = 100, min_games: int = 3, top: int = 5) -> dict:
    """福星／剋星榜：統計近 count 場中，同隊勝率最高（福星）與對戰時我方勝率最低（剋星）的玩家。
    需至少同場 min_games 場才列入，避免樣本過少。"""
    enc = _build_encounters(count)

    def _row(pid: str, rec: dict, side: str) -> dict:
        r = rec[side]
        return {"puuid": pid, "name": rec.get("name", ""), "games": r["games"],
                "wins": r["wins"], "winRate": round(r["wins"] / r["games"] * 100, 1)}

    lucky   = [_row(p, r, "ally")  for p, r in enc.items() if r["ally"]["games"]  >= min_games]
    nemesis = [_row(p, r, "enemy") for p, r in enc.items() if r["enemy"]["games"] >= max(2, min_games - 1)]  # 對手較難重複遇到，門檻少 1 場
    lucky   = sorted([x for x in lucky   if x["winRate"] >= 50], key=lambda x: (-x["winRate"], -x["games"]))[:top]
    nemesis = sorted([x for x in nemesis if x["winRate"] <  50], key=lambda x: ( x["winRate"], -x["games"]))[:top]

    for row in lucky + nemesis:          # 名稱缺漏時用 LCU 以 puuid 補查
        if not row["name"]:
            try:
                sm = _client.get(f"/lol-summoner/v2/summoners/puuid/{row['puuid']}")
                g, t = (sm.get("gameName") or "").strip(), (sm.get("tagLine") or "").strip()
                row["name"] = f"{g}#{t}" if g and t else g
            except Exception:
                pass
        row["name"] = row["name"] or "匿名玩家"
    return {"lucky": lucky, "nemesis": nemesis, "players": len(enc)}


def _with_progress(fn, total: int, kind: str):
    """包裝逐人掃描函式：每完成一人就推播進度（done/total）給前端。"""
    lock  = threading.Lock()
    state = {"done": 0}

    def wrapped(item):
        try:
            return fn(item)
        finally:
            with lock:
                state["done"] += 1
                done = state["done"]
            def _push():
                try:
                    eel.on_scan_progress(kind, done, total)()
                except Exception:
                    pass
            # 另開執行緒推送：不等前端回應，避免拖慢掃描
            threading.Thread(target=_push, daemon=True).start()
    return wrapped


def _scan_lobby_sync(my_team: list):
    """背景執行緒：逐一取得隊友召喚師名稱與近 20 場戰績，完成後推播至前端。"""
    global _lobby_scan_in_progress
    try:
        _log(f"LOBBY_SCAN >> 開始掃描 {len(my_team)} 位成員...")

        encounters = _build_encounters()

        def _scan_lobby_one(player: dict) -> dict:
            sid        = player.get("summonerId", 0)
            puuid      = player.get("puuid", "") or ""
            # 過濾空位 PUUID（Riot 以全零 UUID 代表未填入的槽位）
            if puuid == _EMPTY_PUUID:
                puuid = ""
            cell_id    = player.get("cellId", -1)
            visibility = player.get("nameVisibilityType", "VISIBLE")
            is_anon    = (visibility == "HIDDEN") or (not sid and not puuid)
            is_self    = (puuid == _puuid) if puuid else False
            is_enemy   = player.get("_teamSide", "ally") == "enemy"

            entry = {
                "cellId":      cell_id,
                "name":        "匿名玩家" if is_anon else "?",
                "anonymous":   is_anon,
                "isSelf":      is_self,
                "isEnemy":     is_enemy,
                "wins":        0, "total":      0,
                "winRate":     0.0,
                "avgKills":    0.0, "avgDeaths": 0.0, "avgAssists": 0.0,
                "kda":         0.0,
                "tier":        "UNRANKED",
                "tierText":    "未排位",
                "rankWins":    0, "rankLosses": 0,
                "rankWinRate": 0.0, "lp": 0,
                "topChampions": [],
                "streakType": "", "streakCount": 0,
                "recentGames": [],
                "error":       False,
            }

            if is_anon:
                return entry

            # ── 取召喚師名稱（v2 API）────────────────────────────────
            try:
                if sid:
                    s = _client.get(f"/lol-summoner/v1/summoners/{sid}")
                    entry["name"] = (s.get("displayName") or
                                     s.get("gameName")    or
                                     s.get("name")        or "?")
                    if not puuid:
                        puuid = s.get("puuid", "")
                elif puuid:
                    s = _client.get(f"/lol-summoner/v2/summoners/puuid/{puuid}")
                    entry["name"] = (s.get("displayName") or
                                     s.get("gameName")    or
                                     s.get("name")        or "?")
            except Exception as e:
                _log(f"LOBBY_SCAN >> 名稱失敗 sid={sid}: {e}")
                entry["error"] = True

            # ── 取近 20 場戰績（SGP 優先，LCU 備援）────────────────────
            if puuid:
                try:
                    entry.update(_aggregate_player_stats(puuid))
                except Exception as e:
                    _log(f"LOBBY_SCAN >> 戰績失敗 puuid={puuid[:8] if puuid else '?'}: {e}")
                    entry["error"] = True

            # ── 取積分段位 ────────────────────────────────────────────
            if puuid:
                try:
                    entry.update(_fetch_ranked_stats(puuid))
                except Exception as e:
                    _log(f"LOBBY_SCAN >> 段位失敗 puuid={puuid[:8] if puuid else '?'}: {e}")

            entry["puuid"] = puuid
            entry["tagInfo"] = _get_tag(puuid)
            entry["randomPick"] = _current_lobby_mode in ("aram", "kiwi", "arena")  # 隨機選角模式不顯示熟練度標籤
            if not is_self:
                entry["encounter"] = encounters.get(puuid)
            return entry

        _t0 = time.time()
        with ThreadPoolExecutor(max_workers=10) as _pool:
            results = list(_pool.map(_with_progress(_scan_lobby_one, len(my_team), "lobby"), my_team))

        _log(f"LOBBY_SCAN >> 完成！{len(results)} 位玩家情報就緒（耗時 {time.time()-_t0:.1f}s）")
        try:
            eel.on_lobby_scan_ready(results)()
        except Exception as e:
            _log(f"LOBBY_SCAN_EEL_ERR >> {e}")
    finally:
        _lobby_scan_in_progress = False


def _mark_premade_groups(team: list[dict]):
    """依 teamParticipantId 標記同隊開黑組。
    同一 teamParticipantId 且人數 >= 2 視為一組，依序給組別編號 1, 2, ...
    （LeagueAkari 技術：Riot 用 teamParticipantId 標記預組隊伍）
    """
    groups: dict = {}
    for p in team:
        tpid = p.get("teamParticipantId") or 0
        if tpid:
            groups.setdefault(tpid, []).append(p)
    group_no = 0
    for tpid, members in groups.items():
        if len(members) >= 2:        # 2 人以上才算開黑
            group_no += 1
            for p in members:
                p["premadeGroup"] = group_no


def _maybe_trigger_ingame_scan():
    """若遊戲中雷達未啟動，啟動背景執行緒掃描全場 10 人。"""
    global _ingame_scan_in_progress
    if _ingame_scan_in_progress:
        return
    _ingame_scan_in_progress = True
    threading.Thread(target=_scan_ingame_sync, daemon=True).start()


def _scan_ingame_sync():
    """背景執行緒：10 人雷達掃描。
    主要來源：gameflow session teamOne/teamTwo（已按隊伍分好，最可靠）。
    補充來源：coregame session（提供 championId 等額外欄位）。
    """
    global _ingame_scan_in_progress
    try:
        _log("INGAME_SCAN >> 啟動...")

        # ═══ 主要來源：gameflow（一次 API call，隊伍已分好）════════════════════
        t1_raw: list[dict] = []
        t2_raw: list[dict] = []
        _gf_name_cache: dict[str, str] = {}
        try:
            gf      = _client.get("/lol-gameflow/v1/session")
            gd      = gf.get("gameData", {})
            t1_raw  = [p for p in gd.get("teamOne", []) if p.get("puuid")]
            t2_raw  = [p for p in gd.get("teamTwo", []) if p.get("puuid")]
            _log(f"INGAME_SCAN >> [gameflow] teamOne={len(t1_raw)} teamTwo={len(t2_raw)}")

            # playerChampionSelections 補回 teamOne/teamTwo 漏掉的玩家
            # （CHERRY/大混戰等模式 teamOne/teamTwo 可能不完整）
            pcs = gd.get("playerChampionSelections", [])
            if pcs:
                known = {p["puuid"] for p in t1_raw + t2_raw if p.get("puuid")}
                extra = [p for p in pcs
                         if p.get("puuid") and p["puuid"] != _EMPTY_PUUID
                         and p["puuid"] not in known]
                if extra:
                    _log(f"INGAME_SCAN >> playerChampionSelections 補入 {len(extra)} 位缺漏玩家")
                    # 按隊伍人數平均分配
                    for p in extra:
                        if len(t1_raw) <= len(t2_raw):
                            t1_raw.append(p)
                        else:
                            t2_raw.append(p)
                    _log(f"INGAME_SCAN >> 補後 teamOne={len(t1_raw)} teamTwo={len(t2_raw)}")
            # 同步建立名稱快取（供後續 _scan_one 補名用，跳過空位槽）
            for gp in t1_raw + t2_raw:
                pu   = gp.get("puuid", "")
                if pu == _EMPTY_PUUID:
                    continue
                real = (gp.get("summonerName") or gp.get("gameName") or
                        gp.get("displayName")  or gp.get("riotId")   or
                        gp.get("name") or "").strip()
                if real:
                    _gf_name_cache[pu] = real
            _log(f"INGAME_SCAN >> 名稱快取 {len(_gf_name_cache)}/{len(t1_raw)+len(t2_raw)} 筆")

            # SGP summoner-ledge 已於 2026/6 被 Riot 端遮蔽（unnamed=True），
            # 名稱補齊改由各 _fetch_player 內的 summonerAPI fallback 處理
        except Exception as e:
            _log(f"INGAME_SCAN >> [gameflow] 失敗: {e}")

        if not t1_raw and not t2_raw:
            _log("INGAME_SCAN >> gameflow 無玩家資料，放棄掃描")
            return

        # ═══ 確認自己在哪隊 ═══════════════════════════════════════════════════
        my_tid = 0
        for p in t1_raw:
            if p.get("puuid") == _puuid:
                my_tid = 100; break
        if not my_tid:
            for p in t2_raw:
                if p.get("puuid") == _puuid:
                    my_tid = 200; break
        if not my_tid:
            my_tid = 100  # 保底

        if my_tid == 100:
            my_raw, enemy_raw = list(t1_raw), list(t2_raw)
        else:
            my_raw, enemy_raw = list(t2_raw), list(t1_raw)

        # ═══ 補充來源：coregame（補 championId，並補回 EMPTY_PUUID 的真實玩家）══
        def _fetch_coregame(retry: bool = False) -> dict:
            """回傳 puuid→player dict，失敗回傳空 dict。"""
            try:
                cg = _client.get("/lol-coregame/v1/session")
                result = {p["puuid"]: p for p in cg.get("players", [])
                          if p.get("puuid") and p["puuid"] != _EMPTY_PUUID}
                _log(f"INGAME_SCAN >> [coregame] {'重試' if retry else ''}補充資料 {len(result)} 筆")
                return result
            except Exception as e:
                _log(f"INGAME_SCAN >> [coregame] {'重試' if retry else ''}無回應: {e}")
                return {}

        cg_map = _fetch_coregame()

        # 若人數不足 10 且 coregame 沒資料（GameStart 時常見），最多等 15 秒
        total = len(my_raw) + len(enemy_raw)
        if total < 10 and not cg_map:
            for wait_sec in (3, 3, 3, 6):
                _log(f"INGAME_SCAN >> 人數不足，等待 coregame 就緒（{wait_sec}s）...")
                time.sleep(wait_sec)
                cg_map = _fetch_coregame(retry=True)
                if cg_map:
                    break

        # 用 coregame 補回 gameflow 中 EMPTY_PUUID 的真實玩家
        if cg_map:
            known_puuids = {p.get("puuid", "") for p in my_raw + enemy_raw
                            if p.get("puuid") and p["puuid"] != _EMPTY_PUUID}
            for pu, cg_p in cg_map.items():
                if pu not in known_puuids:
                    # 判斷補入哪隊（以目前人數較少的隊為準）
                    if len(my_raw) < 5:
                        my_raw.append(cg_p)
                    elif len(enemy_raw) < 5:
                        enemy_raw.append(cg_p)
                    known_puuids.add(pu)
                    _log(f"INGAME_SCAN >> coregame 補回缺漏玩家 puuid=...{pu[-6:]}")

        def _merge_cg(p: dict) -> dict:
            cg_p = cg_map.get(p.get("puuid", ""), {})
            if not cg_p:
                return p
            merged = dict(p)
            for k, v in cg_p.items():
                if k not in merged or not merged[k]:
                    merged[k] = v
            return merged

        my_raw    = [_merge_cg(p) for p in my_raw]
        enemy_raw = [_merge_cg(p) for p in enemy_raw]

        _log(f"INGAME_SCAN >> 我方 {len(my_raw)} + 敵方 {len(enemy_raw)}")

        encounters = _build_encounters()

        def _scan_one(p: dict) -> dict:
            puuid    = p.get("puuid", "") or ""
            if puuid == _EMPTY_PUUID:
                puuid = ""
            sid      = p.get("summonerId", 0)
            champ_id = p.get("championId", 0)
            champ_nm = _get_champ_name(champ_id) if champ_id else ""

            # 多欄位容錯取名（coregame: summonerName；gameflow: gameName/riotId）
            name = (
                p.get("summonerName") or p.get("gameName") or
                p.get("displayName")  or p.get("riotId")   or ""
            ).strip()

            # 若 coregame 名稱為空，優先從 gameflow 快取補回真實名稱
            if not name and puuid and puuid in _gf_name_cache:
                name = _gf_name_cache[puuid]
                _log(f"INGAME_SCAN >> GF快取補名 puuid=...{puuid[-6:]}")

            # 匿名玩家：有 PUUID 仍查戰績，名稱補英雄名作識別
            is_anon = not name
            if is_anon:
                raw_fields = {k: bool((p.get(k) or "").strip())
                              for k in ("summonerName","gameName","displayName","riotId","name")}
                _log(f"INGAME_SCAN >> 匿名玩家 puuid=...{puuid[-6:] if puuid else 'N/A'} sid={sid} CG欄位={raw_fields}")
                name = f"[匿名] {champ_nm}" if champ_nm else "[匿名]"

            entry = {
                "name":        name,
                "puuid":       puuid,
                "isSelf":      puuid == _puuid,
                "anonymous":   is_anon,
                "championId":  champ_id,
                "championName": champ_nm,
                "wins": 0, "total": 0, "winRate": 0.0,
                "avgKills": 0.0, "avgDeaths": 0.0, "avgAssists": 0.0,
                "kda": 0.0,
                "tier":        "UNRANKED",
                "tierText":    "未排位",
                "rankWins":    0, "rankLosses": 0,
                "rankWinRate": 0.0, "lp": 0,
                "topChampions": [],
                "streakType": "", "streakCount": 0,
                "recentGames": [],
                "teamParticipantId": p.get("teamParticipantId") or 0,
                "premadeGroup": 0,   # 0=單排；>0=同組編號（稍後分析填入）
                "error": False,
            }

            # 若仍匿名，最後嘗試 LCU summoner API（v1 by sid，v2 by puuid）
            if is_anon and (sid or puuid):
                try:
                    ep = (f"/lol-summoner/v1/summoners/{sid}" if sid
                          else f"/lol-summoner/v2/summoners/puuid/{puuid}")
                    s = _client.get(ep)
                    has2 = {k: bool((s.get(k) or "").strip())
                            for k in ("displayName","gameName","name","internalName")}
                    _log(f"INGAME_SCAN >> summonerAPI {ep[-30:]} 回傳欄位={has2}")
                    real = (s.get("displayName") or s.get("gameName") or
                            s.get("name") or s.get("internalName") or "").strip()
                    if real:
                        entry["name"]      = real
                        entry["anonymous"] = False
                        is_anon = False
                        _log(f"INGAME_SCAN >> summonerAPI 補名成功")
                    else:
                        _log(f"INGAME_SCAN >> summonerAPI 仍無名稱，所有欄位皆空")
                except Exception as e:
                    _log(f"INGAME_SCAN >> summonerAPI 失敗: {e}")

            # 戰績查詢：有 PUUID 就查，不論是否匿名
            if puuid:
                try:
                    player_stats = _aggregate_player_stats(puuid)
                    entry.update(player_stats)
                except Exception as e:
                    _log(f"INGAME_SCAN >> 戰績失敗 {puuid[:8]}: {e}")
                    entry["error"] = True

            # 段位查詢
            if puuid:
                try:
                    entry.update(_fetch_ranked_stats(puuid))
                except Exception as e:
                    _log(f"INGAME_SCAN >> 段位失敗 {puuid[:8]}: {e}")

            entry["tagInfo"] = _get_tag(puuid)
            entry["randomPick"] = _current_lobby_mode in ("aram", "kiwi", "arena")  # 隨機選角模式不顯示熟練度標籤
            if puuid != _puuid:
                entry["encounter"] = encounters.get(puuid)
            return entry

        # 並行查詢全場 10 人（每人查戰績+段位，序列太慢）
        _t0 = time.time()
        with ThreadPoolExecutor(max_workers=10) as _pool:
            _all = list(_pool.map(_with_progress(_scan_one, len(my_raw) + len(enemy_raw), "ingame"),
                                  my_raw + enemy_raw))
        my_team    = _all[:len(my_raw)]
        enemy_team = _all[len(my_raw):]
        _mark_premade_groups(my_team)
        _mark_premade_groups(enemy_team)
        _log(f"INGAME_SCAN >> 完成！{len(my_team)}+{len(enemy_team)} 人雷達就緒（耗時 {time.time()-_t0:.1f}s）")
        _hud_scan["my"], _hud_scan["enemy"] = my_team, enemy_team
        try:
            eel.on_ingame_scan_ready({"myTeam": my_team, "enemyTeam": enemy_team})()
        except Exception as e:
            _log(f"INGAME_SCAN_EEL_ERR >> {e}")
    except Exception as e:
        _log(f"INGAME_SCAN_ERR >> {e}")
    finally:
        _ingame_scan_in_progress = False


def _load_match_cache() -> dict:
    """從磁碟讀取本地戰績快取，key 為 str(gameId)。帳號不符時自動清空。"""
    try:
        if not os.path.exists(_MATCH_CACHE_FILE):
            return {}
        with open(_MATCH_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("puuid") != _puuid:   # 切換帳號時清空舊快取
            return {}
        return data.get("games", {})
    except Exception:
        return {}


def _save_match_cache(games_dict: dict):
    """將合併後的戰績快取寫回磁碟。"""
    try:
        os.makedirs(os.path.dirname(_MATCH_CACHE_FILE), exist_ok=True)
        with open(_MATCH_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"puuid": _puuid, "games": games_dict}, f, ensure_ascii=False)
    except Exception as e:
        _log(f"CACHE_WRITE_ERR >> {e}")


# ── 玩家標記儲存層 ─────────────────────────────────────────────────────
def _load_tagged_players():
    """啟動時從磁碟載入玩家標記到記憶體。"""
    global _tagged_players
    try:
        if os.path.exists(_TAGGED_PLAYERS_FILE):
            with open(_TAGGED_PLAYERS_FILE, "r", encoding="utf-8") as f:
                _tagged_players = json.load(f)
            _log(f"TAGGED >> 載入 {len(_tagged_players)} 筆玩家標記")
    except Exception as e:
        _log(f"TAGGED_LOAD_ERR >> {e}")
        _tagged_players = {}


def _save_tagged_players():
    """將標記寫回磁碟。"""
    try:
        os.makedirs(os.path.dirname(_TAGGED_PLAYERS_FILE), exist_ok=True)
        with open(_TAGGED_PLAYERS_FILE, "w", encoding="utf-8") as f:
            json.dump(_tagged_players, f, ensure_ascii=False)
    except Exception as e:
        _log(f"TAGGED_SAVE_ERR >> {e}")


# ── 自動化偏好儲存層 ───────────────────────────────────────────────────
def _save_prefs():
    """將自動化開關偏好寫回磁碟。"""
    try:
        os.makedirs(os.path.dirname(_PREFS_FILE), exist_ok=True)
        with open(_PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "autoAccept":     _auto_accept,
                "autoPick":       _auto_pick,
                "autoPickChamp":  _auto_pick_champ_id,
                "autoBan":        _auto_ban,
                "autoBanChamp":   _auto_ban_champ_id,
            }, f, ensure_ascii=False)
    except Exception as e:
        _log(f"PREFS_SAVE_ERR >> {e}")


@eel.expose
def get_prefs() -> dict:
    """前端啟動時讀取已存偏好，用來恢復 UI 開關狀態。"""
    try:
        if os.path.exists(_PREFS_FILE):
            with open(_PREFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        _log(f"PREFS_LOAD_ERR >> {e}")
    return {}


def _restore_prefs():
    """啟動時把已存偏好恢復到記憶體（後端狀態，前端 UI 由 get_prefs 同步）。"""
    global _auto_accept, _auto_pick, _auto_pick_champ_id, _auto_ban, _auto_ban_champ_id
    p = get_prefs()
    if not p:
        return
    _auto_accept        = bool(p.get("autoAccept", False))
    _auto_pick          = bool(p.get("autoPick", False))
    _auto_pick_champ_id = int(p.get("autoPickChamp", 0) or 0)
    _auto_ban           = bool(p.get("autoBan", False))
    _auto_ban_champ_id  = int(p.get("autoBanChamp", 0) or 0)
    _log(f"PREFS >> 恢復偏好 accept={_auto_accept} pick={_auto_pick} ban={_auto_ban}")


def _get_tag(puuid: str) -> dict:
    """取得某玩家的標記資料，無則回傳空 dict。"""
    if not puuid:
        return {}
    return _tagged_players.get(puuid, {})


@eel.expose
def set_player_tag(puuid: str, tag: str, color: str = "yellow"):
    """設定/更新玩家標記文字與顏色（空字串=移除標記）。"""
    if not puuid:
        return False
    tag = (tag or "").strip()
    if not tag:
        _tagged_players.pop(puuid, None)
        _log(f"TAGGED >> 移除標記 ...{puuid[-6:]}")
    else:
        rec = _tagged_players.setdefault(puuid, {})
        rec["tag"] = tag
        rec["color"] = color or "yellow"
        _log(f"TAGGED >> 設定標記 ...{puuid[-6:]} = {tag}")
    _save_tagged_players()
    return True


@eel.expose
def get_player_tag(puuid: str):
    """前端查詢單一玩家標記。"""
    return _get_tag(puuid)


def _load_champ_summary():
    global _champ_summary_loaded
    if _champ_summary_loaded:
        return
    try:
        data = _client.get("/lol-game-data/v1/champion-summary", timeout=10)
        count = 0
        for c in data:
            cid   = int(c.get("id", -1))
            name  = (c.get("name") or "").strip() or (c.get("alias") or "").strip()
            roles = c.get("roles") or []
            if cid > 0 and name:
                _champ_cache[cid] = name   # 全部放入，供遊戲內查名
                count += 1
                if roles:
                    _champ_valid_ids.add(cid)  # 只有有 roles 的才進選擇器
        if count > 0:
            _champ_summary_loaded = True
            _log(f"CHAMP_CACHE >> 已載入 {count} 位（可選英雄 {len(_champ_valid_ids)} 位，NPC 已隔離）")
        else:
            _log(f"CHAMP_CACHE_WARN >> champion-summary 回傳 {len(data)} 筆但 name 全空，改用逐一查詢")
    except Exception as e:
        _log(f"CHAMP_SUMMARY_ERR >> {e}")


def _get_champ_name(champ_id: int) -> str:
    if champ_id in _champ_cache:
        return _champ_cache[champ_id]
    for ep in (
        f"/lol-game-data/v1/champions/{champ_id}",
        f"/lol-game-data/assets/v1/champions/{champ_id}.json",
    ):
        try:
            d    = _client.get(ep, timeout=5)
            name = (d.get("name") or "").strip() or (d.get("alias") or "").strip()
            if name:
                _champ_cache[champ_id] = name
                return name
        except Exception:
            continue
    # 備援：LCU champion-summary 偶爾 404，改用 Data Dragon metadata 的中文名
    meta_name = (_champ_meta.get(champ_id, {}).get("name") or "").strip()
    if meta_name:
        return meta_name
    return f"#{champ_id}"


def _load_item_cache():
    global _item_cache_loaded
    if _item_cache_loaded:
        return
    try:
        data = _client.get("/lol-game-data/assets/v1/items.json", timeout=15)
        for item in data:
            iid  = int(item.get("id", 0))
            path = (item.get("iconPath") or "").strip()
            if iid > 0 and path:
                _item_cache[iid] = path
        if _item_cache:
            _item_cache_loaded = True
            _log(f"ITEM_CACHE >> 已載入 {len(_item_cache)} 件裝備路徑")
        else:
            _log("ITEM_CACHE_WARN >> items.json 無 iconPath")
    except Exception as e:
        _log(f"ITEM_CACHE_ERR >> {e}")


def _load_spell_cache():
    global _spell_cache_loaded
    if _spell_cache_loaded:
        return
    try:
        data  = _client.get("/lol-game-data/assets/v1/summoner-spells.json", timeout=10)
        items = data if isinstance(data, list) else list(data.values())
        for sp in items:
            sid  = int(sp.get("id", 0))
            path = (sp.get("iconPath") or "").strip()
            if sid > 0 and path:
                _spell_cache[sid] = path
        if _spell_cache:
            _spell_cache_loaded = True
            _log(f"SPELL_CACHE >> 已載入 {len(_spell_cache)} 個召喚師技能路徑")
        else:
            _log("SPELL_CACHE_WARN >> summoner-spells.json 無 iconPath")
    except Exception as e:
        _log(f"SPELL_CACHE_ERR >> {e}")


def _load_perk_cache():
    global _perk_cache_loaded
    if _perk_cache_loaded:
        return
    try:
        data  = _client.get("/lol-game-data/assets/v1/perks.json", timeout=15)
        items = data if isinstance(data, list) else list(data.values())
        for p in items:
            pid = int(p.get("id", 0))
            if pid > 0:
                _perk_cache[pid] = {
                    "iconPath":  (p.get("iconPath")  or "").strip(),
                    "name":      (p.get("name")      or "").strip(),
                    "shortDesc": (p.get("shortDesc") or "").strip(),
                }
        if _perk_cache:
            _perk_cache_loaded = True
            _log(f"PERK_CACHE >> 已載入 {len(_perk_cache)} 個符文資料")
        else:
            _log("PERK_CACHE_WARN >> perks.json 無資料")
    except Exception as e:
        _log(f"PERK_CACHE_ERR >> {e}")


def _load_perkstyle_cache():
    global _perkstyle_cache_loaded
    if _perkstyle_cache_loaded:
        return
    try:
        data  = _client.get("/lol-game-data/assets/v1/perkstyles.json", timeout=10)
        items = data if isinstance(data, list) else data.get("styles", [])
        for s in (items or []):
            sid  = int(s.get("id", 0))
            path = (s.get("iconPath") or "").strip()
            if sid > 0 and path:
                _perkstyle_cache[sid] = path
        if _perkstyle_cache:
            _perkstyle_cache_loaded = True
            _log(f"PERKSTYLE_CACHE >> 已載入 {len(_perkstyle_cache)} 個副系路徑圖示")
        else:
            _log("PERKSTYLE_CACHE_WARN >> perkstyles.json 無資料")
    except Exception as e:
        _log(f"PERKSTYLE_CACHE_ERR >> {e}")


def _perk_tooltip(perk_id: int) -> str:
    """Return 'name — shortDesc' with HTML stripped, for use as title attribute."""
    p = _perk_cache.get(perk_id)
    if not p:
        return ""
    name = p.get("name", "")
    desc = re.sub(r"<[^>]+>", "", p.get("shortDesc", "")).strip()
    return f"{name} — {desc}" if desc else name


def _load_augment_cache():
    """載入競技場(cherry) 增幅快取。啟動時即可呼叫。"""
    global _augment_cache_loaded
    if _augment_cache_loaded:
        return
    try:
        data  = _client.get("/lol-game-data/assets/v1/cherry-augments.json", timeout=15)
        items = data if isinstance(data, list) else list(data.values())
        for aug in items:
            aid  = int(aug.get("id", 0))
            path = (aug.get("augmentSmallIconPath") or "").strip()
            name = (aug.get("nameTRA") or aug.get("name") or "").strip()
            rarity_raw = aug.get("rarity", aug.get("augmentType", aug.get("tier", 1)))
            try:
                rarity = int(rarity_raw)
            except (TypeError, ValueError):
                s = str(rarity_raw).lower()
                rarity = 2 if "prismatic" in s else (0 if "silver" in s else 1)
            if aid > 0 and path:
                _augment_cache[aid] = {"iconPath": path, "name": name, "rarity": rarity}
        if _augment_cache:
            _augment_cache_loaded = True
            _log(f"AUGMENT_CACHE >> cherry 載入 {len(_augment_cache)} 個增幅")
        else:
            _log("AUGMENT_CACHE_WARN >> cherry-augments.json 無資料")
    except Exception as e:
        _log(f"AUGMENT_CACHE_ERR >> cherry: {e}")


def _load_kiwi_aug_cache():
    """載入大混戰(kiwi) 增幅快取。需在選角/遊戲中 LCU 才有資料，lazy 呼叫。"""
    global _kiwi_aug_cache_loaded, _kiwi_aug_cache_failed
    if _kiwi_aug_cache_loaded or _kiwi_aug_cache_failed:
        return
    try:
        data  = _client.get("/lol-game-data/assets/v1/kiwi-augments.json", timeout=15)
        items = data if isinstance(data, list) else list(data.values())
        added = 0
        for aug in items:
            aid  = int(aug.get("id", 0))
            path = (aug.get("augmentSmallIconPath") or "").strip()
            name = (aug.get("nameTRA") or aug.get("name") or "").strip()
            rarity_raw = aug.get("rarity", aug.get("augmentType", aug.get("tier", 1)))
            try:
                rarity = int(rarity_raw)
            except (TypeError, ValueError):
                s = str(rarity_raw).lower()
                rarity = 2 if "prismatic" in s else (0 if "silver" in s else 1)
            if aid > 0 and path:
                _augment_cache[aid] = {"iconPath": path, "name": name, "rarity": rarity}
                added += 1
        if added:
            _kiwi_aug_cache_loaded = True
            _log(f"AUGMENT_CACHE >> kiwi 載入 {added} 個增幅，快取共 {len(_augment_cache)} 個")
        else:
            _log("AUGMENT_CACHE_WARN >> kiwi-augments.json 無資料，cherry 快取已涵蓋")
            _kiwi_aug_cache_failed = True   # 不再重試
    except Exception as e:
        _log(f"AUGMENT_CACHE_ERR >> kiwi: {e}")
        _kiwi_aug_cache_failed = True       # LCU 無此 endpoint，不再重試


def _load_rank_emblem_cache():
    global _rank_emblem_loaded
    if _rank_emblem_loaded:
        return
    try:
        data  = _client.get("/lol-game-data/assets/v1/ranked-emblems.json")
        items = data if isinstance(data, list) else list(data.values())
        for entry in items:
            tier = (entry.get("tier") or "").upper()
            path = (entry.get("emblem") or entry.get("iconPath") or
                    entry.get("mediumIconPath") or entry.get("smallIconPath") or "").strip()
            if tier and path:
                _rank_emblem_cache[tier] = path
        if _rank_emblem_cache:
            _rank_emblem_loaded = True
            _log(f"EMBLEM_CACHE >> 已載入 {len(_rank_emblem_cache)} 個牌位路徑")
        else:
            _log("EMBLEM_CACHE_WARN >> ranked-emblems.json 無可用路徑")
    except Exception as e:
        _log(f"EMBLEM_CACHE_ERR >> {e}")


# ── Exposed to JS ──────────────────────────────────────────────────────
_init_lock = threading.Lock()
_init_in_progress = False


@eel.expose
def initialize():
    global _last_init_ok
    res = _initialize_impl()
    _last_init_ok = bool((res or {}).get("ok"))
    return res


def _initialize_impl():
    global _client, _puuid, _account_id, _platform_id, _entitlement_token, _league_session_token
    global _init_in_progress
    # 重入防護：避免前端 load 與 reconnect 同時觸發造成重複初始化
    with _init_lock:
        if _init_in_progress:
            _log("SYS >> 初始化進行中，略過重複呼叫")
            return {"ok": bool(_client and _puuid)}
        _init_in_progress = True
    _log("SYS >> Initializing connection to League Client...")
    try:
        _client     = LCUClient()
        _log(f"LCU_LINK >> ESTABLISHED // port={_client.port}")

        s           = _client.get("/lol-summoner/v1/current-summoner")
        name        = s.get("gameName") or s.get("displayName") or "UNKNOWN"
        tag         = s.get("tagLine", "")
        full        = f"{name}#{tag}" if tag else name
        lvl         = s.get("summonerLevel", 0)
        icon_id     = s.get("profileIconId", 0)
        _puuid      = s.get("puuid", "")
        _account_id = s.get("accountId", 0)

        # ── SGP 認證資訊（用於突破 LCU 20 筆戰績限制）────────────────
        # platformId 從 /lol-login/v1/session 的 idToken JWT payload 解碼
        # Riot JWT claims 裡的 cpid 欄位即為 "TW2"、"NA1" 等格式
        _platform_id = ""
        try:
            login_data = _client.get("/lol-login/v1/session")
            id_token   = login_data.get("idToken", "")
            if id_token:
                parts = id_token.split(".")
                if len(parts) >= 2:
                    # base64url 解碼 JWT payload（補齊 padding）
                    padded = parts[1] + "=" * (-len(parts[1]) % 4)
                    claims = json.loads(base64.urlsafe_b64decode(padded))
                    # cpid 藏在 lol[0].cpid（不是頂層欄位）
                    lol_list     = claims.get("lol") or claims.get("lol_region") or []
                    _platform_id = (lol_list[0].get("cpid") or
                                    lol_list[0].get("pid")  or "") if lol_list else ""
        except Exception as ep_err:
            _log(f"SGP_REGION_ERR >> {ep_err}")
        _log(f"SGP_REGION >> platformId={_platform_id!r}")

        try:
            ent = _client.get("/entitlements/v1/token")
            _entitlement_token = ent.get("accessToken", "")
            _log(f"SGP_TOKEN >> {'OK' if _entitlement_token else 'EMPTY'} (len={len(_entitlement_token)})")
        except Exception:
            _entitlement_token = ""

        try:
            _league_session_token = _client.get("/lol-league-session/v1/league-session-token") or ""
            _log(f"SGP_SESSION_TOKEN >> {'OK' if _league_session_token else 'EMPTY'} (len={len(_league_session_token)})")
        except Exception:
            _league_session_token = ""

        _log(f"OPERATOR_PROFILE >> loaded: {full} // LVL {lvl} // ICON {icon_id}")
        _load_champ_summary()
        _load_tagged_players()
        _restore_prefs()
        _start_ws()

        # 啟動／重連時若已在選角或遊戲中，WS 不會補發事件 → 背景補掃一次
        def _catch_up():
            time.sleep(3)
            trigger_live_scan()
        threading.Thread(target=_catch_up, daemon=True).start()

        # 若啟動／重連時已在選角中，主動顯示戰術浮窗（WS 不會補發 phase 轉換事件）
        try:
            if _overlay_window and _client.get("/lol-gameflow/v1/gameflow-phase") == "ChampSelect":
                _overlay_window.show()
        except Exception:
            pass

        return {
            "ok":     True,
            "name":   full,
            "level":  lvl,
            "port":   _client.port,
            "iconId": icon_id,
        }

    except LCUNotRunningError as e:
        _log(f"ERR >> {e}")
        return {"ok": False, "error": str(e)}
    except Exception as e:
        _log(f"ERR >> {e}")
        return {"ok": False, "error": str(e)}
    finally:
        _init_in_progress = False


@eel.expose
def get_lcu_image_base64(endpoint: str) -> str:
    """Proxy an LCU image endpoint and return it as a base64 data-URI."""
    if not _client:
        return ''
    try:
        url  = f"{_client.protocol}://127.0.0.1:{_client.port}{endpoint}"
        resp = _client._session.get(url, timeout=8)
        if resp.status_code == 200:
            ct  = resp.headers.get('content-type', 'image/jpeg').split(';')[0].strip()
            b64 = base64.b64encode(resp.content).decode()
            return f'data:{ct};base64,{b64}'
        _log(f"IMG_PROXY >> {resp.status_code} {endpoint}")
        return ''
    except Exception as e:
        _log(f"IMG_PROXY_ERR >> {endpoint} >> {e}")
        return ''


@eel.expose
def get_item_image_base64_by_id(item_id: int) -> str:
    """Look up item iconPath from manifest then proxy as base64."""
    if not _client or not item_id:
        return ''
    _load_item_cache()
    path = _item_cache.get(int(item_id))
    if not path:
        _log(f"ITEM_MISS >> id={item_id}")
        return ''
    return get_lcu_image_base64(path)


@eel.expose
def get_spell_image_base64_by_id(spell_id: int) -> str:
    """Look up summoner spell iconPath from manifest then proxy as base64."""
    if not _client or not spell_id:
        return ''
    _load_spell_cache()
    path = _spell_cache.get(int(spell_id))
    if path:
        return get_lcu_image_base64(path)
    for attempt in (
        f"/lol-game-data/assets/v1/summoner-spells/summoner{spell_id}.png",
        f"/lol-game-data/assets/v1/summoner-spells/{spell_id}.png",
    ):
        result = get_lcu_image_base64(attempt)
        if result:
            return result
    return ''


@eel.expose
def get_perk_image_base64_by_id(perk_id: int) -> str:
    """Look up perk iconPath from manifest then proxy as base64."""
    if not _client or not perk_id:
        return ''
    _load_perk_cache()
    p = _perk_cache.get(int(perk_id))
    if not p:
        return ''
    path = p.get("iconPath", "")
    return get_lcu_image_base64(path) if path else ''


@eel.expose
def get_perkstyle_image_base64_by_id(style_id: int) -> str:
    """查詢副系符文路徑（Precision/Domination 等）圖示，透過 LCU 代理回傳 base64。"""
    if not _client or not style_id:
        return ''
    _load_perkstyle_cache()
    path = _perkstyle_cache.get(int(style_id), '')
    return get_lcu_image_base64(path) if path else ''


@eel.expose
def get_augment_image_base64_by_id(augment_id: int) -> str:
    """查詢競技場增益圖示路徑，透過 LCU 代理回傳 base64。"""
    if not _client or not augment_id:
        return ''
    try:
        _load_augment_cache()
        aug = _augment_cache.get(int(augment_id))
        if not aug:
            return ''
        path = aug.get("iconPath", "")
        return get_lcu_image_base64(path) if path else ''
    except Exception as e:
        _log(f"AUGMENT_IMG_ERR >> id={augment_id} >> {e}")
        return ''


_kiwi_balance_cache: dict = {}   # champion_id -> balance dict
_kiwi_balance_loaded = False


def _load_kiwi_balance():
    global _kiwi_balance_cache, _kiwi_balance_loaded
    if _kiwi_balance_loaded:
        return
    try:
        resp = requests.get(f"{_OPGG_BASE}/api/contents/aram-balance",
                            headers={"User-Agent": _OPGG_UA}, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        _kiwi_balance_cache = {str(e["champion_id"]): e for e in data if "champion_id" in e}
        _kiwi_balance_loaded = True
        _log(f"KIWI_BALANCE >> 載入 {len(_kiwi_balance_cache)} 位英雄平衡資料")
    except Exception as e:
        _log(f"KIWI_BALANCE_ERR >> {e}")


@eel.expose
def get_kiwi_balance(champ_id: int) -> dict:
    """回傳大混戰/大亂鬥英雄平衡調整（OP.GG aram-balance）。
    回傳 {damage_dealt, damage_taken, healing, shield_amount, energy_regen, ...}（以 100 為基準，非 100 才有意義）。
    """
    if not champ_id:
        return {}
    _load_kiwi_balance()
    entry = _kiwi_balance_cache.get(str(champ_id)) or {}
    if not entry or entry.get("default", False):
        return {}
    # 只回傳非預設值（值 != 100 且 != 0 的欄位）
    result = {}
    for k in ("damage_dealt", "damage_taken", "healing", "shield_amount",
              "energy_regen", "tenacity", "cooldown_reduction", "attack_speed",
              "area_of_effect_damage"):
        v = entry.get(k, 100)
        if v != 100 and v != 0:
            result[k] = round(v - 100, 1)   # 轉為 +/- 百分比
    return result


@eel.expose
def get_current_lobby_mode() -> str:
    """回傳目前大廳/佇列的模式：ranked / aram / arena / kiwi。"""
    return _current_lobby_mode


@eel.expose
def get_augment_names(augment_ids: list) -> dict:
    """批次回傳 {augmentId: name} dict，供前端增幅列表顯示名稱。"""
    if not augment_ids:
        return {}
    _load_augment_cache()
    _load_kiwi_aug_cache()   # kiwi 模式下 lazy load（在遊戲中 LCU 才有資料）
    return {str(aid): (_augment_cache.get(int(aid)) or {}).get("name", "") for aid in augment_ids}


@eel.expose
def get_arena_balance(champ_id: int) -> dict:
    """回傳競技場英雄平衡性調整（造成/承受傷害百分比）。
    從 LCU /lol-game-data/assets/v1/arena-champion-stats.json 取得。
    回傳 {dmg_dealt: float, dmg_taken: float}，查無時回 {}。
    """
    if not _client or not champ_id:
        return {}
    try:
        data = _client.get("/lol-game-data/assets/v1/arena-champion-stats.json", timeout=8)
        if not isinstance(data, list):
            return {}
        for entry in data:
            if entry.get("championId") == champ_id or entry.get("id") == champ_id:
                dmg_dealt = round((entry.get("damageDealtMod", 1.0) - 1.0) * 100, 1)
                dmg_taken = round((entry.get("damageTakenMod", 1.0) - 1.0) * 100, 1)
                return {"dmg_dealt": dmg_dealt, "dmg_taken": dmg_taken}
        return {}
    except Exception as e:
        _log(f"ARENA_BALANCE_ERR >> {e}")
        return {}


@eel.expose
def get_rank_info() -> dict | None:
    """Return solo and flex rank data separately."""
    if not _client or not _puuid:
        return None

    _TIER_ZH = {
        'IRON': '黑鐵', 'BRONZE': '青銅', 'SILVER': '白銀',
        'GOLD': '黃金', 'PLATINUM': '白金', 'EMERALD': '翡翠',
        'DIAMOND': '鑽石', 'MASTER': '大師',
        'GRANDMASTER': '宗師', 'CHALLENGER': '菁英',
    }
    _NO_RANK = {'NONE', 'UNRANKED', 'NA', ''}
    _DIV_MAP = {'I': 'Ⅰ', 'II': 'Ⅱ', 'III': 'Ⅲ', 'IV': 'Ⅳ'}

    def _parse(entry):
        if not entry:
            return {"tier": "UNRANKED", "text": "未定級", "lp": ""}
        tier = (entry.get('tier') or '').upper()
        if tier in _NO_RANK:
            return {"tier": "UNRANKED", "text": "未定級", "lp": ""}
        division = (entry.get('division') or entry.get('rank') or '')
        lp       = entry.get('leaguePoints', 0)
        tier_zh  = _TIER_ZH.get(tier, tier)
        if tier in ('MASTER', 'GRANDMASTER', 'CHALLENGER'):
            text = tier_zh
        else:
            text = f"{tier_zh} {_DIV_MAP.get(division, division)}"
        return {"tier": tier, "text": text, "lp": f"{lp} LP"}

    try:
        data   = _client.get(f"/lol-ranked/v1/ranked-stats/{_puuid}")
        queues = data.get("queues") or list((data.get("queueMap") or {}).values())

        solo = next((e for e in queues if e.get('queueType') == 'RANKED_SOLO_5x5'), None)
        flex = next((e for e in queues if e.get('queueType') == 'RANKED_FLEX_SR'),  None)

        result = {"solo": _parse(solo), "flex": _parse(flex)}
        _log(f"RANK_INFO >> solo={result['solo']['text']} flex={result['flex']['text']}")
        return result

    except Exception as e:
        _log(f"RANK_INFO_ERR >> {e}")
        return None


def _grade_game(game: dict, pdata: dict, stats: dict, win: bool, is_remake: bool) -> str:
    """依該場表現給評級 S/A/B/C/D（綜合 KDA、參團率、傷害佔比）。"""
    if is_remake:
        return ""
    try:
        k = stats.get("kills", 0); d = stats.get("deaths", 0); a = stats.get("assists", 0)
        kda = (k + a) / max(d, 1)
        my_tid = pdata.get("teamId") or stats.get("teamId") or 0
        t_k = t_dmg = 0
        for pp in game.get("participants", []):
            ps = pp.get("stats") or pp
            if (pp.get("teamId") or ps.get("teamId") or 0) == my_tid:
                t_k   += ps.get("kills", 0)
                t_dmg += ps.get("totalDamageDealtToChampions", 0)
        my_dmg = stats.get("totalDamageDealtToChampions", 0)
        kp        = (k + a) / t_k   if t_k   else 0
        dmg_share = my_dmg / t_dmg  if t_dmg else 0

        # 綜合評分（0~100）
        score = (min(kda, 6) / 6 * 45 +    # KDA 最高 45 分
                 min(kp, 0.8) / 0.8 * 30 +  # 參團率 最高 30 分
                 min(dmg_share, 0.35) / 0.35 * 25)  # 傷害佔比 最高 25 分
        if win:
            score += 5   # 勝利小加成
        if   score >= 80: return "S"
        elif score >= 65: return "A"
        elif score >= 48: return "B"
        elif score >= 32: return "C"
        else:             return "D"
    except Exception:
        return ""


def _parse_one_game(game: dict, source: str, target_puuid: str | None = None) -> dict | None:
    """解析單場遊戲資料，相容 LCU 格式（stats 巢狀）與 SGP 格式（stats 攤平）。
    target_puuid 預設為本人 _puuid；傳入其他 puuid 時改以該玩家視角解析（供玩家詳細頁沿用）。
    回傳解析好的 dict，找不到玩家或失敗時回傳 None。
    """
    tp     = target_puuid or _puuid
    is_self = (tp == _puuid)
    _QUEUES_LOCAL = {
        420: "排位賽", 440: "彈性排位", 450: "大亂鬥",
        400: "一般對戰", 430: "一般對戰", 700: "衝突",
    }

    # ── 找玩家：SGP 可直接比 puuid；LCU 需透過 participantIdentities ────
    our_pid  = None
    our_puuid_matched = False

    # SGP / 新版 LCU：participants[].puuid 直接存在
    for p in game.get("participants", []):
        if p.get("puuid") == tp:
            our_pid = p.get("participantId")
            our_puuid_matched = True
            break

    # 舊版 LCU：透過 participantIdentities 查 participantId（accountId 比對僅限本人）
    if not our_puuid_matched:
        for ident in game.get("participantIdentities", []):
            pl = ident.get("player", {})
            if (tp          and pl.get("puuid")            == tp) or \
               (is_self and _account_id and pl.get("accountId")        == _account_id) or \
               (is_self and _account_id and pl.get("currentAccountId") == _account_id):
                our_pid = ident.get("participantId")
                break

    if our_pid is None and not our_puuid_matched:
        return None

    for p in game.get("participants", []):
        # 用 puuid 或 participantId 定位目標玩家
        matched = (p.get("puuid") == tp) if our_puuid_matched \
                  else (p.get("participantId") == our_pid)
        if not matched:
            continue

        # SGP 格式：stats 攤平在 p；LCU 格式：stats 在 p["stats"]
        nested = p.get("stats") or {}
        stats  = nested if (nested.get("kills") is not None or nested.get("win") is not None) else p

        champ_id = p.get("championId", 0)
        q        = game.get("queueId") or game.get("gameQueueConfigId", 0)
        mode     = game.get("gameMode", "")
        is_arena = (mode in ("KIWI", "CHERRY"))
        duration = game.get("gameDuration", 0)

        win          = stats.get("win", False)
        is_remake    = 0 < duration < 240
        is_surrender = bool(
            stats.get("gameEndedInEarlySurrender") or
            stats.get("teamEarlySurrendered")      or
            stats.get("gameEndedInSurrender")
        )
        game_result = ("REMAKE" if is_remake else
                       ("SURRENDER_WIN" if win else "SURRENDER_LOSS") if is_surrender else
                       ("WIN" if win else "LOSS"))

        base = {
            "gameId":       game.get("gameId", 0),
            "championId":   champ_id,
            "championName": _get_champ_name(champ_id),
            "kills":        stats.get("kills",   0),
            "deaths":       stats.get("deaths",  0),
            "assists":      stats.get("assists", 0),
            "win":          bool(win),
            "duration":     duration,
            "queueId":      q,
            "queue":        _QUEUES_LOCAL.get(q, "一般對戰"),
            "items":        [stats.get(f"item{i}", 0) or p.get(f"item{i}", 0) for i in range(6)],
            "spell1Id":     p.get("spell1Id", 0),
            "spell2Id":     p.get("spell2Id", 0),
            "damage":       stats.get("totalDamageDealtToChampions", 0) or p.get("totalDamageDealtToChampions", 0),
            "grade":        _grade_game(game, p, stats, win, is_remake),
            "gameResult":   game_result,
            "isSurrender":  is_surrender,
            "source":       source,
        }

        if is_arena:
            _load_augment_cache()
            aug_ids = [stats.get(f"playerAugment{i}", 0) or p.get(f"playerAugment{i}", 0) for i in range(1, 7)]
            base.update({
                "augments":     [{"id": aid, "rarity": (_augment_cache.get(aid) or {}).get("rarity", 1)} for aid in aug_ids],
                "runes":        aug_ids,
                "statPerks":    [],
                "runeTooltips": [(_augment_cache.get(aid) or {}).get("name", "") for aid in aug_ids],
                "statPerkTooltips": [],
                "isArena":      True,
                "queue":        _QUEUES_LOCAL.get(q, "競技場"),
            })
        else:
            perks_obj = p.get("perks") or stats.get("perks") or {}
            rune_ids  = [stats.get(f"perk{i}", 0) for i in range(6)]
            if not any(rune_ids) and perks_obj.get("styles"):
                rune_ids = []
                for style in perks_obj["styles"]:
                    for sel in style.get("selections", []):
                        rune_ids.append(sel.get("perk", 0))
                rune_ids = (rune_ids + [0] * 6)[:6]
            if not any(rune_ids) and perks_obj.get("perkIds"):
                rune_ids = (list(perks_obj["perkIds"][:6]) + [0] * 6)[:6]

            stat_ids = [stats.get(f"statPerk{i}", 0) for i in range(3)]
            if not any(stat_ids):
                sp = perks_obj.get("statPerks") or {}
                if isinstance(sp, dict):
                    stat_ids = [sp.get("offense", 0), sp.get("flex", 0), sp.get("defense", 0)]
            if not any(stat_ids) and perks_obj.get("perkIds"):
                pids = perks_obj["perkIds"]
                stat_ids = (list(pids[6:9]) + [0] * 3)[:3]

            base.update({
                "runes":            rune_ids,
                "statPerks":        stat_ids,
                "runeTooltips":     [_perk_tooltip(pid) for pid in rune_ids],
                "statPerkTooltips": [_perk_tooltip(pid) for pid in stat_ids],
                "perksRaw": {
                    "styles":    perks_obj.get("styles")    or [],
                    "statPerks": perks_obj.get("statPerks") or {},
                    "perkIds":   perks_obj.get("perkIds")   or [],
                },
                "isArena": False,
            })

        return base
    return None


@eel.expose
def get_match_history(start_index: int = 0, target_count: int = 20) -> list:
    """優先使用 SGP API（無 20 筆限制）直接回傳 start_index~target_count 筆。
    SGP 失敗時降級為 LCU + 本地累加快取。
    """
    if not _client or not _puuid:
        return []
    try:
        _load_champ_summary()
        _load_perk_cache()

        # ══ 路徑 A：SGP API（無 20 筆限制，直接精確分頁）══════════════
        sgp_base = _SGP_MATCH_HISTORY_URLS.get(_platform_id.upper()) if _platform_id else None

        if sgp_base and _entitlement_token:
            url = f"{sgp_base}/match-history-query/v1/products/lol/player/{_puuid}/SUMMARY"
            _log(f"SGP_REQ >> {_platform_id} start={start_index} count={target_count}")
            try:
                resp = requests.get(
                    url,
                    params={"startIndex": start_index, "count": target_count},
                    headers={"Authorization": f"Bearer {_entitlement_token}"},
                    timeout=15,
                )
                resp.raise_for_status()
                sgp_data  = resp.json()
                raw_games = sgp_data.get("games", [])
                _log(f"SGP_RAW >> 回傳 {len(raw_games)} 筆原始資料")

                results = []
                for wrap in raw_games:
                    game = wrap.get("json") or wrap
                    if not game:
                        continue
                    try:
                        parsed = _parse_one_game(game, "sgp")
                        if parsed:
                            results.append(parsed)
                    except Exception as ge:
                        _log(f"SGP_PARSE_ERR >> gameId={game.get('gameId','?')} >> {ge}")

                if results:
                    _log(f"SGP_OK >> 成功解析 {len(results)} 筆，直接回傳")
                    return results
                _log("SGP_EMPTY >> SGP 回傳空結果，降級至 LCU 路徑")
            except Exception as sgp_err:
                _log(f"SGP_FAIL >> {sgp_err}，降級至 LCU 路徑")

        # ══ 路徑 B：LCU API（~20 筆）+ 本地累加快取 ═════════════════════
        _log(f"LCU_REQ >> 抓取最新戰績 (puuid={_puuid[:8]}...)")
        raw        = _client.get(
            f"/lol-match-history/v1/products/lol/{_puuid}/matches"
            f"?begIndex=0&endIndex=20",
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        fresh_games = raw.get("games", {}).get("games", [])
        _log(f"LCU_RAW >> 回傳 {len(fresh_games)} 筆")

        # ── 解析 LCU 回傳資料，使用共用 helper ─────────────────────────
        results = []
        for game in fresh_games:
            try:
                parsed = _parse_one_game(game, "lcu")
                if parsed:
                    results.append(parsed)
            except Exception as ge:
                _log(f"LCU_PARSE_ERR >> gameId={game.get('gameId','?')} >> {ge}")

        # ── 載入本地快取，合併並儲存 ─────────────────────────────────────
        cached = _load_match_cache()
        before = len(cached)
        for r in results:
            cached[str(r["gameId"])] = r
        after = len(cached)
        _save_match_cache(cached)
        _log(f"LCU_CACHE >> 新增 {after - before} 筆，快取共 {after} 筆")

        # ── 從合併快取依 gameId 降序排列後分頁回傳 ───────────────────────
        all_sorted = sorted(cached.values(), key=lambda x: x.get("gameId", 0), reverse=True)
        page_slice = all_sorted[start_index : start_index + target_count]
        _log(f"LCU_HISTORY >> 快取共 {len(all_sorted)} 筆，回傳 [{start_index}:{start_index+target_count}] 共 {len(page_slice)} 筆")
        return page_slice

    except Exception as e:
        _log(f"MATCH_HISTORY_ERR >> {e}")
        return []


@eel.expose
def js_log(msg):
    """供前端 JS 寫診斷訊息到 debug.log。"""
    _log(f"JS >> {msg}")


@eel.expose
def window_minimize():
    """最小化原生視窗（自訂標題列用）。"""
    if _webview_window:
        _webview_window.minimize()


_window_maximized = False


@eel.expose
def window_toggle_maximize():
    """切換最大化／還原。"""
    global _window_maximized
    if not _webview_window:
        return
    try:
        if _window_maximized:
            _webview_window.restore()
            _window_maximized = False
        else:
            _webview_window.maximize()
            _window_maximized = True
    except Exception as e:
        _log(f"WINDOW_MAX_ERR >> {e}")


@eel.expose
def window_close():
    """關閉原生視窗。"""
    if _webview_window:
        _webview_window.destroy()


@eel.expose
def set_auto_accept(enabled: bool):
    global _auto_accept
    _auto_accept = bool(enabled)
    _log(f"AUTO_ACCEPT_PROTOCOL >> {'ENGAGED' if _auto_accept else 'STANDBY'}")
    _save_prefs()


@eel.expose
def set_auto_pick(enabled: bool, champ_id: int):
    global _auto_pick, _auto_pick_champ_id, _last_pick_action_id
    _auto_pick          = bool(enabled)
    _auto_pick_champ_id = int(champ_id) if champ_id else 0
    _last_pick_action_id = -1
    _log(f"AUTO_PICK_PROTOCOL >> {'ENGAGED' if _auto_pick else 'STANDBY'} // ChampID={_auto_pick_champ_id}")
    _save_prefs()


@eel.expose
def set_auto_ban(enabled: bool, champ_id: int):
    global _auto_ban, _auto_ban_champ_id, _last_ban_action_id
    _auto_ban          = bool(enabled)
    _auto_ban_champ_id = int(champ_id) if champ_id else 0
    _last_ban_action_id = -1
    _log(f"AUTO_BAN_PROTOCOL >> {'ENGAGED' if _auto_ban else 'STANDBY'} // ChampID={_auto_ban_champ_id}")
    _save_prefs()


@eel.expose
def trigger_lobby_scan():
    """手動觸發大廳掃描。嚴格只在 ChampSelect 階段執行，其他狀態靜默略過。"""
    global _last_scanned_team_key
    if not _client:
        return
    # ── Phase 守衛 第一層：先查 Gameflow 確認真的在選角 ──────────────────
    try:
        phase = _client.get("/lol-gameflow/v1/gameflow-phase")
        if phase != "ChampSelect":
            _log(f"LOBBY_SCAN >> 略過，當前狀態為 [{phase}]（非 ChampSelect）")
            return
    except Exception as e:
        _log(f"LOBBY_SCAN >> 無法確認 Gameflow 狀態: {e}")
        return
    # ── 第二層：呼叫 champ-select session ────────────────────────────────
    try:
        session    = _client.get("/lol-champ-select/v1/session")
        my_team    = session.get("myTeam",    [])
        their_team = session.get("theirTeam", [])
        if not my_team:
            _log("LOBBY_SCAN >> myTeam 為空，略過掃描")
            return
        tagged_my  = [dict(p, _teamSide="ally")  for p in my_team]
        tagged_foe = [dict(p, _teamSide="enemy") for p in their_team
                      if p.get("puuid") and p.get("puuid") != _EMPTY_PUUID]
        combined = tagged_my + tagged_foe
        _last_scanned_team_key = ""  # 強制重新掃描
        _maybe_trigger_lobby_scan(combined)
    except requests.exceptions.HTTPError as he:
        if he.response is not None and he.response.status_code == 404:
            _log("LOBBY_SCAN >> 選角已結束，端點不存在 (404)")
        else:
            _log(f"LOBBY_SCAN >> 手動觸發失敗: {he}")
    except Exception as e:
        _log(f"LOBBY_SCAN >> 手動觸發失敗: {e}")


@eel.expose
def trigger_ingame_scan():
    """手動觸發遊戲中 10 人雷達。嚴格只在 InProgress 階段執行。"""
    global _ingame_scan_in_progress
    if not _client:
        return
    # Phase 守衛：確認真的在遊戲中（GameStart = 載入畫面，InProgress = 遊戲中）
    try:
        phase = _client.get("/lol-gameflow/v1/gameflow-phase")
        if phase not in ("GameStart", "InProgress"):
            _log(f"INGAME_SCAN >> 略過，當前狀態為 [{phase}]（非 GameStart/InProgress）")
            return
    except Exception as e:
        _log(f"INGAME_SCAN >> 無法確認 Gameflow 狀態: {e}")
        return
    _ingame_scan_in_progress = False  # 允許重複觸發（手動重整）
    _maybe_trigger_ingame_scan()


@eel.expose
def trigger_live_scan():
    """統一掃描入口：嚴格依 phase 路由，ChampSelect→大廳掃描，InProgress→10人雷達，其他→靜默。"""
    if not _client:
        return
    try:
        phase = _client.get("/lol-gameflow/v1/gameflow-phase")
        if not isinstance(phase, str):
            return
        if phase == "ChampSelect":
            trigger_lobby_scan()
        elif phase in ("GameStart", "InProgress"):
            trigger_ingame_scan()
        else:
            _log(f"LIVE_SCAN >> 當前狀態 [{phase}] 無可執行的掃描任務")
    except Exception as e:
        _log(f"LIVE_SCAN >> 觸發失敗: {e}")


@eel.expose
def get_champion_list() -> list:
    """回傳已排序的英雄清單 [{id, name}, ...]，嘗試多端點確保完整性。"""
    if not _client:
        return []
    _load_champ_summary()
    # 若主端點不足 160 個，依序嘗試備援端點補充
    if len(_champ_cache) < 160:
        for ep in (
            "/lol-game-data/assets/v1/champion-summary.json",
            "/lol-game-data/v1/champions",
        ):
            try:
                data  = _client.get(ep, timeout=10)
                items = data if isinstance(data, list) else list(data.values())
                added = 0
                for c in items:
                    cid   = int(c.get("id", -1))
                    name  = (c.get("name") or "").strip() or (c.get("alias") or "").strip()
                    roles = c.get("roles") or []
                    if cid > 0 and name and cid not in _champ_cache:
                        _champ_cache[cid] = name   # 全部放入，供遊戲內查名
                        added += 1
                        if roles:
                            _champ_valid_ids.add(cid)
                if added > 0:
                    _log(f"CHAMP_SUPPLEMENT >> {ep} 補充了 {added} 位英雄")
                if len(_champ_cache) >= 160:
                    break
            except Exception as e:
                _log(f"CHAMP_SUPPLEMENT_ERR >> {ep}: {e}")
    # 真實英雄 ID 皆 < 3000，過濾掉末日機兵等特殊高 ID 變體
    result = [{"id": cid, "name": name} for cid, name in _champ_cache.items()
              if 0 < cid < 3000 and cid in _champ_valid_ids]
    result.sort(key=lambda x: x["name"])
    _log(f"CHAMP_LIST >> 回傳 {len(result)} 位英雄")
    return result


@eel.expose
def get_champion_analytics(count: int = 200) -> list:
    """
    從最近 count 場戰績統計每位英雄的數據。
    篩選出場數 >= 3，按勝率降序排列。
    回傳: [{championId, name, games, wins, winRate, avgKDA, avgDamage}, ...]
    """
    if not _client or not _puuid:
        return []
    try:
        _log(f"ANALYTICS >> 開始統計最近 {count} 場英雄數據...")
        games = get_match_history(0, count)
        if not games:
            _log("ANALYTICS >> 無法取得戰績資料")
            return []

        stats: dict[int, dict] = {}
        for g in games:
            cid = g.get("championId", 0)
            if not cid:
                continue
            if g.get("gameResult") == "REMAKE":
                continue  # 排除重開場次
            if cid not in stats:
                stats[cid] = {"games": 0, "wins": 0, "kills": 0, "deaths": 0, "assists": 0, "damage": 0}
            s = stats[cid]
            s["games"]   += 1
            s["wins"]    += 1 if g.get("win") else 0
            s["kills"]   += g.get("kills", 0)
            s["deaths"]  += g.get("deaths", 0)
            s["assists"] += g.get("assists", 0)
            s["damage"]  += g.get("damage", 0)

        result = []
        for cid, s in stats.items():
            n = s["games"]
            if n < 3:
                continue
            deaths  = s["deaths"] or 1
            avg_kda = round((s["kills"] + s["assists"]) / deaths, 2)
            result.append({
                "championId": cid,
                "name":       _champ_cache.get(cid, f"#{cid}"),
                "games":      n,
                "wins":       s["wins"],
                "winRate":    round(s["wins"] / n * 100, 1),
                "avgKDA":     avg_kda,
                "avgDamage":  int(s["damage"] / n),
            })

        result.sort(key=lambda x: (-x["winRate"], -x["games"]))
        _log(f"ANALYTICS >> 統計完成，共 {len(result)} 位英雄（≥3 場）")
        return result
    except Exception as e:
        _log(f"ANALYTICS_ERR >> {e}")
        return []


@eel.expose
def get_game_detail(game_id: int) -> dict:
    """取得完整 10 人對局資料，拆分為藍隊與紅隊。"""
    if not _client:
        return {}
    try:
        raw       = _client.get(f"/lol-match-history/v1/games/{game_id}")
        game_mode = raw.get("gameMode", "")
        is_arena  = game_mode in ("KIWI", "CHERRY")

        # participantId → 召喚師名稱 / puuid
        id_map = {}
        puuid_map = {}
        for ident in raw.get("participantIdentities", []):
            pid  = ident.get("participantId")
            p    = ident.get("player", {})
            name = (p.get("gameName") or p.get("summonerName") or "---").strip()
            tag  = (p.get("tagLine") or "").strip()
            id_map[pid] = f"{name}#{tag}" if tag else name
            puuid_map[pid] = p.get("puuid", "") or ""

        # 提取隊伍目標資料 (baron/dragon/tower/inhibitor)
        objectives: dict[int, dict] = {}
        for team in raw.get("teams", []):
            tid  = int(team.get("teamId", 0))
            objs = team.get("objectives", {})
            objectives[tid] = {
                "baron":     (objs.get("baron")     or {}).get("kills", 0),
                "dragon":    (objs.get("dragon")    or {}).get("kills", 0),
                "tower":     (objs.get("tower")     or {}).get("kills", 0),
                "inhibitor": (objs.get("inhibitor") or {}).get("kills", 0),
            }

        _load_augment_cache()   # 確保稀有度資料已就緒
        blue, red = [], []
        for p in raw.get("participants", []):
            pid      = p.get("participantId")
            stats    = p.get("stats", {})
            champ_id = p.get("championId", 0)

            # 解析符文（三格式容錯）
            perks_obj     = p.get("perks") or stats.get("perks") or {}
            styles        = perks_obj.get("styles") or []
            perk_ids      = perks_obj.get("perkIds") or []
            perk0         = stats.get("perk0", 0)
            perk_sub_style = 0  # 副系路徑 ID，用於 2x2 格右下角

            if styles:
                if not perk0 and styles[0].get("selections"):
                    perk0 = styles[0]["selections"][0].get("perk", 0)
                if len(styles) > 1:
                    perk_sub_style = int(styles[1].get("style", 0) or styles[1].get("id", 0))
            if not perk0 and perk_ids:
                perk0 = perk_ids[0]

            # 次級符文：遞迴暴力掃描整個玩家 JSON，找出所有 8000~9999 範圍的符文 ID
            def _scan_rune_ids(obj, found: set):
                if isinstance(obj, dict):
                    for v in obj.values():
                        _scan_rune_ids(v, found)
                elif isinstance(obj, list):
                    for v in obj:
                        _scan_rune_ids(v, found)
                else:
                    try:
                        v = int(obj)
                        if 5000 <= v <= 9999:
                            found.add(v)
                    except (TypeError, ValueError):
                        pass

            scanned: set[int] = set()
            _scan_rune_ids(p, scanned)
            print(f"DEBUG 掃描結果 PID={pid}: {sorted(scanned)}")

            # 扣除 keystone (perk0)，剩下即次級符文，取前 5，不足補 0
            minor_perks = [x for x in sorted(scanned) if x != perk0][:5]
            while len(minor_perks) < 5:
                minor_perks.append(0)

            entry = {
                "summonerName": id_map.get(pid, f"Player{pid}"),
                "puuid":        puuid_map.get(pid, "") or (p.get("puuid", "") or ""),
                "championId":   champ_id,
                "championName": _get_champ_name(champ_id),
                "champLevel":   stats.get("champLevel", 0),
                "spell1Id":     p.get("spell1Id", 0),
                "spell2Id":     p.get("spell2Id", 0),
                "kills":        stats.get("kills",   0),
                "deaths":       stats.get("deaths",  0),
                "assists":      stats.get("assists", 0),
                "minions":      stats.get("totalMinionsKilled", 0) + stats.get("neutralMinionsKilled", 0),
                "items":        [stats.get(f"item{i}", 0) for i in range(7)],  # item6 = 飾品
                "augments":     [
                    {
                        "id":     (aid := stats.get(f"playerAugment{i}", 0)),
                        "rarity": (_augment_cache.get(aid) or {}).get("rarity", 1),
                    }
                    for i in range(1, 5)
                ],
                "damage":       stats.get("totalDamageDealtToChampions", 0),
                "damageTaken":  stats.get("totalDamageTaken", 0),
                "gold":         stats.get("goldEarned", 0),
                "perk0":        perk0,
                "perkSubStyle": perk_sub_style,
                "minorPerks":   minor_perks,
                "win":          stats.get("win", False),
            }
            (blue if p.get("teamId", 100) == 100 else red).append(entry)

        _log(f"GAME_DETAIL >> gameId={game_id} blue={len(blue)} red={len(red)}")
        return {"gameId": game_id, "duration": raw.get("gameDuration", 0),
                "blue": blue, "red": red, "objectives": objectives}
    except Exception as e:
        _log(f"GAME_DETAIL_ERR >> gameId={game_id} >> {e}")
        return {}


@eel.expose
def reconnect():
    _ws_stop.set()
    time.sleep(0.3)
    _ws_stop.clear()
    return initialize()


# ── WebSocket ──────────────────────────────────────────────────────────
def _start_ws():
    global _ws_thread
    if _ws_thread and _ws_thread.is_alive():
        return
    _ws_stop.clear()
    _ws_thread = threading.Thread(target=_ws_worker, daemon=True)
    _ws_thread.start()


# websockets 14+ 改名為 additional_headers；13.x 以下仍是 extra_headers（相容兩者）
try:
    _WS_HEADERS_KW = ("additional_headers"
                      if int(websockets.__version__.split(".")[0]) >= 14 else "extra_headers")
except Exception:
    _WS_HEADERS_KW = "additional_headers"


def _ws_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_ws_listen_with_retry())
    except Exception as e:
        _log(f"WS_WORKER_ERR >> {e}")
    finally:
        loop.close()


_last_pushed_ok = None  # 最近一次推播給前端的連線狀態（避免重複推播）


def _push_status(res: dict):
    """把連線狀態變化推給前端（僅在狀態改變時）。"""
    global _last_pushed_ok
    ok = bool((res or {}).get("ok"))
    if ok == _last_pushed_ok:
        return
    _last_pushed_ok = ok
    try:
        eel.on_lcu_status(res)()
    except Exception as e:
        _log(f"LCU_STATUS_PUSH_ERR >> {e}")


_last_init_ok = False   # 最近一次 initialize() 是否成功（供斷線後自動重連判斷）


async def _ws_listen_with_retry():
    backoff = 5
    while not _ws_stop.is_set():
        connected = await _ws_listen()
        if _ws_stop.is_set():
            break
        if connected:
            backoff = 5   # reset on clean disconnect
        else:
            backoff = min(backoff * 2, 20)
        # 客戶端重開後 port/密碼會變：偵測到憑證改變就自動重新初始化（免手動按重新連線）
        try:
            fresh = LCUClient()
            if (_client is None or not _last_init_ok
                    or (fresh.port, fresh.password) != (_client.port, _client.password)):
                _log(f"WS_STREAM >> 偵測到新的客戶端連線 (port={fresh.port})，自動重新初始化")
                res = await asyncio.get_running_loop().run_in_executor(None, initialize)
                backoff = 2
                if (res or {}).get("ok"):
                    _push_status(res)       # 讓畫面從「離線」切回已連線並刷新帳號資料
                else:
                    _log(f"WS_STREAM >> 重新初始化未完成（客戶端可能仍在登入）: {(res or {}).get('error','')}")
        except LCUNotRunningError:
            _push_status({"ok": False})     # 客戶端關閉 → 畫面顯示離線
        except Exception as e:
            _log(f"WS_STREAM >> 自動重新初始化失敗: {e}")
        _log(f"WS_STREAM >> reconnecting in {backoff}s...")
        for _ in range(backoff * 2):
            if _ws_stop.is_set():
                return
            await asyncio.sleep(0.5)


async def _ws_listen() -> bool:
    """Connect, subscribe, and pump events. Returns True if we connected at least once."""
    if not _client:
        return False
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode   = ssl.CERT_NONE
    creds = base64.b64encode(f"riot:{_client.password}".encode()).decode()
    uri   = f"wss://127.0.0.1:{_client.port}"

    try:
        async with websockets.connect(
            uri,
            **{_WS_HEADERS_KW: {"Authorization": f"Basic {creds}"}},
            ssl=ssl_ctx,
            ping_interval=20,
            ping_timeout=10,
        ) as ws:
            _log("WS_STREAM >> ACTIVE // 訂閱配對、選角、Gameflow、Lobby 事件")
            # 訂閱配對就緒確認
            await ws.send(json.dumps([5, "OnJsonApiEvent_lol-matchmaking_v1_ready-check"]))
            # 訂閱英雄選擇階段（LeagueAkari 核心技術：監聽 champ-select session）
            await ws.send(json.dumps([5, "OnJsonApiEvent_lol-champ-select_v1_session"]))
            # 訂閱 Gameflow 狀態變更（偵測選角結束以重置掃描鍵）
            await ws.send(json.dumps([5, "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase"]))
            # 訂閱大廳設定變更（切換遊戲模式時即時偵測 queueId）
            await ws.send(json.dumps([5, "OnJsonApiEvent_lol-lobby_v2_lobby"]))
            while not _ws_stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    if not raw:
                        continue
                    msg = json.loads(raw)
                    if len(msg) >= 3 and msg[0] == 8:
                        await _handle_event(msg[2])
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    _log("WS_STREAM >> server closed connection")
                    break
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    _log(f"WS_LOOP_ERR >> {e}")
                    break
        return True
    except Exception as e:
        _log(f"WS_CONN_ERR >> {e}")
        return False


async def _handle_event(event: dict):
    """依 URI 路由至對應的事件處理器。"""
    uri  = event.get("uri", "")
    data = event.get("data")

    if "ready-check" in uri:
        await _handle_ready_check(data or {})
    elif "champ-select" in uri:
        await _handle_champ_select(data or {})
    elif "gameflow-phase" in uri:
        _handle_gameflow_phase(data)
    elif "lol-lobby" in uri and isinstance(data, dict):
        _handle_lobby_update(data)


def _handle_lobby_update(data: dict):
    """大廳設定變更時（切換遊戲模式）重新偵測 queue 模式並推播前端。"""
    global _current_lobby_mode
    try:
        q_obj  = data.get("gameConfig", {}).get("queueId", 0)
        q_id   = q_obj if isinstance(q_obj, int) else 0
        if q_id == 0:   # 忽略 LCU 在模式切換間夾帶的空事件
            return
        q_name = data.get("gameConfig", {}).get("gameMode", "")
        if q_id == 450:
            new_mode = "aram"
        elif q_id == 2400 or "KIWI" in q_name.upper() or "大混戰" in q_name:
            new_mode = "kiwi"
        elif q_id in (1700, 1710) or "CHERRY" in q_name.upper():
            new_mode = "arena"
        else:
            new_mode = "ranked"
        if new_mode != _current_lobby_mode:
            _current_lobby_mode = new_mode
            _log(f"LOBBY_UPDATE >> queueId={q_id} gameMode={q_name!r} → {new_mode}")
            try:
                eel.on_lobby_mode_change(new_mode)()
            except Exception:
                pass
    except Exception as e:
        _log(f"LOBBY_UPDATE_ERR >> {e}")


async def _handle_ready_check(data: dict):
    if not isinstance(data, dict):
        return
    state = data.get("state")
    resp  = data.get("playerResponse")
    unanswered = resp in ("None", "none", None, "")

    if state == "InProgress" and unanswered:
        _log("MATCH_FOUND >> ready check InProgress — player has not responded")
        if _auto_accept:
            try:
                _client.post("/lol-matchmaking/v1/ready-check/accept", json={})
                _log("AUTO_ACCEPT >> match ACCEPTED ✓")
                try:
                    eel.on_match_accepted()()
                except Exception:
                    pass
            except Exception as e:
                _log(f"ACCEPT_ERR >> {e}")
        else:
            _log("AUTO_ACCEPT >> STANDBY (功能未啟動)")
    elif state == "EveryoneReady":
        _log("ALL_PLAYERS_READY >> loading into game...")
    elif state:
        _log(f"READY_CHECK >> state={state} response={resp}")


def _handle_gameflow_phase(phase):
    """WS Gameflow 事件：更新全域 phase 快取，並嚴格依階段路由各掃描任務。"""
    global _current_gameflow_phase, _last_scanned_team_key, _ingame_scan_in_progress
    if not isinstance(phase, str):
        return

    # 即時同步全域 phase（供所有掃描函式使用，無需額外 API 呼叫）
    _current_gameflow_phase = phase
    _log(f"GAMEFLOW >> 狀態 → {phase}")

    # 進大廳/配對時偵測 queue 模式，推播給前端更新攻略頁下拉選單
    if phase in ("Lobby", "Matchmaking", "ReadyCheck", "ChampSelect"):
        try:
            global _current_lobby_mode
            q_obj  = _client.get("/lol-gameflow/v1/session").get("gameData", {}).get("queue", {})
            q_id   = q_obj.get("id", 0)
            q_type = q_obj.get("type", "")
            q_name = q_obj.get("shortName", q_obj.get("name", ""))
            if q_id == 450:
                _current_lobby_mode = "aram"
            elif q_id == 2400 or "KIWI" in q_type.upper() or "大混戰" in q_name:
                _current_lobby_mode = "kiwi"
            elif q_id in (1700, 1710) or "CHERRY" in q_type.upper():
                _current_lobby_mode = "arena"
            else:
                _current_lobby_mode = "ranked"
            _log(f"LOBBY_MODE >> queueId={q_id} type={q_type!r} → {_current_lobby_mode}")
            try:
                eel.on_lobby_mode_change(_current_lobby_mode)()
            except Exception:
                pass
        except Exception:
            pass

    # 離開選角大廳：重置掃描鍵，讓下次進入選角時重新掃描
    if phase != "ChampSelect":
        global _last_hovered_champ, _last_champsel_key
        _last_scanned_team_key = ""
        _last_hovered_champ = 0
        _last_champsel_key = ""

    # ── 選角戰術浮窗：進入選角顯示，離開隱藏（always-on-top）──────────────
    try:
        if _overlay_window:
            if phase == "ChampSelect":
                _overlay_window.show()
            else:
                _overlay_window.hide()
    except Exception as e:
        _log(f"OVERLAY_TOGGLE_ERR >> {e}")

    # ── 遊戲中 HUD：進入遊戲顯示，離開隱藏並清空掃描快取 ──────────────────
    if phase not in ("GameStart", "InProgress", "Reconnect"):
        _hud_scan["my"], _hud_scan["enemy"] = [], []   # 離開遊戲：清空雷達快取（視窗顯示由 _hud_watcher 決定）

    # ── 嚴格 phase 路由 ──────────────────────────────────────────────────
    if phase == "ReadyCheck":
        # gameflow 進入 ReadyCheck 即直接嘗試接受（比 matchmaking WS 事件更可靠）
        if _auto_accept:
            try:
                _client.post("/lol-matchmaking/v1/ready-check/accept", json={})
                _log("AUTO_ACCEPT >> match ACCEPTED via gameflow phase ✓")
                try:
                    eel.on_match_accepted()()
                except Exception:
                    pass
            except Exception as e:
                _log(f"ACCEPT_ERR >> {e}")

    elif phase in ("GameStart", "InProgress"):
        # GameStart = 遊戲載入畫面；InProgress = 遊戲進行中；兩者皆可啟動雷達
        # （GameStart 時 gameflow session 已有完整 10 人資料，可提前掃描）
        try:
            eel.on_champ_select_ended("InProgress")()
        except Exception:
            pass
        _maybe_trigger_ingame_scan()

    elif phase in ("EndOfGame", "PreEndOfGame", "WaitingForStats", "Reconnect"):
        # 遊戲結束：重置雷達旗標、通知前端封存
        _ingame_scan_in_progress = False
        try:
            eel.on_champ_select_ended(phase)()
        except Exception:
            pass
        # 結算時更新與標記玩家的勝負記錄（延遲幾秒等戰績寫入）
        if phase == "EndOfGame":
            def _delayed_record():
                time.sleep(5)
                _record_game_result()
            threading.Thread(target=_delayed_record, daemon=True).start()
    # Lobby / Matchmaking / ReadyCheck / ChampSelect 等其他狀態
    # 不主動觸發任何掃描（大廳掃描由 WS champ-select session 事件驅動）


async def _handle_champ_select(data: dict):
    """
    LeagueAkari 核心技術：英雄選擇階段自動秒選／禁角。
    localPlayerCellId 比對 actorCellId，
    依 type 分別處理 ban（禁角）與 pick（選角）。
    """
    global _last_pick_action_id, _last_ban_action_id
    if not isinstance(data, dict):
        return

    local_cell = data.get("localPlayerCellId", -1)
    all_actions = []
    for phase in data.get("actions", []):
        if isinstance(phase, list):
            all_actions.extend(phase)
        elif isinstance(phase, dict):
            all_actions.append(phase)

    # 大廳 X 光機：每次 session 更新時嘗試觸發（內部有重複觸發防護）
    # ARAM 模式中 theirTeam 同樣帶有真實 PUUID，一併掃描以呈現完整 10 人情報
    my_team    = data.get("myTeam",    [])
    their_team = data.get("theirTeam", [])
    tagged_my  = [dict(p, _teamSide="ally")  for p in my_team]
    tagged_foe = [dict(p, _teamSide="enemy") for p in their_team
                  if p.get("puuid") and p.get("puuid") != _EMPTY_PUUID]
    combined = tagged_my + tagged_foe
    if combined:
        _maybe_trigger_lobby_scan(combined)

    # ── 偵測佇列模式（ARAM=450, Arena 各版本, 其餘=ranked）─────────────────
    try:
        gf_session = _client.get("/lol-gameflow/v1/session")
        queue_obj  = gf_session.get("gameData", {}).get("queue", {})
        _q         = queue_obj.get("id", 0)
        _q_type    = queue_obj.get("type", "")
        _q_name    = queue_obj.get("shortName", queue_obj.get("name", ""))
        _log(f"CHAMPSEL_QUEUE >> id={_q} type={_q_type!r} name={_q_name!r}")
    except Exception as e:
        _q = 0; _q_type = ""; _q_name = ""
        _log(f"CHAMPSEL_QUEUE >> 取佇列失敗: {e}")
    if _q == 450:
        _queue_mode = "aram"
    elif _q == 2400 or "KIWI" in _q_type.upper() or "KIWI" in _q_name.upper() or "大混戰" in _q_name:
        _queue_mode = "kiwi"
        threading.Thread(target=_load_kiwi_aug_cache, daemon=True).start()  # 進入 kiwi 選角即 lazy load
    elif _q in (1700, 1710) or "CHERRY" in _q_type.upper() or "CHERRY" in _q_name.upper():
        _queue_mode = "arena"
    else:
        _queue_mode = "ranked"
    _log(f"CHAMPSEL_QUEUE >> 模式={_queue_mode}")

    # ── 選角戰術中樞：解析雙方已選英雄 + 禁用，推播戰術分析給浮窗/主視窗 ──
    global _last_champsel_key
    try:
        my_ids    = [p.get("championId") or 0 for p in my_team]
        my_ids    = [c for c in my_ids if c > 0]
        enemy_ids = [p.get("championId") or 0 for p in their_team]
        enemy_ids = [c for c in enemy_ids if c > 0]
        ban_ids   = [a.get("championId") for a in all_actions
                     if a.get("type") == "ban" and a.get("completed")
                     and (a.get("championId") or 0) > 0]
        key = f"{sorted(my_ids)}|{sorted(enemy_ids)}|{sorted(ban_ids)}"
        if key != _last_champsel_key:
            _last_champsel_key = key
            comp = get_comp_analysis(my_ids, enemy_ids)
            eel.on_champ_select_update({
                "myChampIds":    my_ids,
                "enemyChampIds": enemy_ids,
                "bans": [{"championId": c, "name": _get_champ_name(c)} for c in ban_ids],
                "comp": comp,
                "queueMode": _queue_mode,   # 供浮窗顯示標題 & 選正確 ban 模式
            })()
    except Exception as e:
        _log(f"CHAMPSEL_PUSH_ERR >> {e}")

    # ── 偵測自己選/預選的英雄，推播給前端自動載入 OP.GG 攻略 ──────────
    global _last_hovered_champ
    me = next((p for p in my_team if p.get("cellId") == local_cell), None)
    if me:
        cid = me.get("championId") or me.get("championPickIntent") or 0
        pos = (me.get("assignedPosition") or "").lower()
        if cid and cid != _last_hovered_champ:
            _last_hovered_champ = cid
            mode = _queue_mode  # 已由上方偵測好（ranked/aram/arena）
            _log(f"OPGG ▶▶ 偵測到選角英雄 {cid}（{mode}），推播前端載入攻略")
            try:
                eel.on_my_champion_select(cid, mode, pos)()  # () 才會真正觸發；內部已無阻塞呼叫
            except Exception as e:
                _log(f"OPGG_PUSH_ERR >> {e}")

    for action in all_actions:
        if action.get("actorCellId") != local_cell:
            continue
        if not action.get("isInProgress", False):
            continue
        if action.get("completed", True):
            continue

        action_type = action.get("type", "").lower()
        action_id   = action.get("id")

        # ── 自動禁角 ───────────────────────────────────────────────────
        if action_type == "ban" and _auto_ban and _auto_ban_champ_id:
            if action_id == _last_ban_action_id:
                continue
            _last_ban_action_id = action_id
            _log(f"AUTO_BAN >> 禁角輪到我！actionId={action_id} 禁用 champId={_auto_ban_champ_id}")
            try:
                _client.patch(
                    f"/lol-champ-select/v1/session/actions/{action_id}",
                    json={"championId": _auto_ban_champ_id, "type": "ban"}
                )
                _log(f"AUTO_BAN >> PATCH champId={_auto_ban_champ_id} ✓")
                _client.post(
                    f"/lol-champ-select/v1/session/actions/{action_id}/complete",
                    json={}
                )
                _log(f"AUTO_BAN >> CONFIRMED ✓✓")
                try:
                    eel.on_auto_ban_done(_auto_ban_champ_id)()
                except Exception:
                    pass
            except Exception as e:
                _log(f"AUTO_BAN_ERR >> {e}")

        # ── 自動選角 ───────────────────────────────────────────────────
        elif action_type == "pick" and _auto_pick and _auto_pick_champ_id:
            if action_id == _last_pick_action_id:
                continue
            _last_pick_action_id = action_id
            _log(f"AUTO_PICK >> 選角輪到我！actionId={action_id} 秒選 champId={_auto_pick_champ_id}")
            try:
                _client.patch(
                    f"/lol-champ-select/v1/session/actions/{action_id}",
                    json={"championId": _auto_pick_champ_id, "type": "pick"}
                )
                _log(f"AUTO_PICK >> PATCH champId={_auto_pick_champ_id} ✓")
                _client.post(
                    f"/lol-champ-select/v1/session/actions/{action_id}/complete",
                    json={}
                )
                _log(f"AUTO_PICK >> LOCKED IN ✓✓")
                try:
                    eel.on_auto_pick_done(_auto_pick_champ_id)()
                except Exception:
                    pass
            except Exception as e:
                _log(f"AUTO_PICK_ERR >> {e}")


# ── Launch ─────────────────────────────────────────────────────────────
def _port_in_use(port: int) -> bool:
    """偵測 port 是否已被占用（用於單一實例防護）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_server_ready(port: int, timeout: float = 10.0) -> bool:
    """輪詢直到 eel server 接受連線，或逾時。比固定 sleep 更可靠。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_in_use(port):
            return True
        time.sleep(0.1)
    return False


if __name__ == "__main__":
    # ── 單一實例防護 ───────────────────────────────────────────────────
    # port 已被占用 → 已有一個實例在執行；直接結束，避免 eel server
    # 在背景 thread 噴 WinError 10048，並防止開出指向舊實例的重複視窗。
    if _port_in_use(_EEL_PORT):
        _log("SYS >> 偵測到 LeagueMrfox 已在執行中，結束本次啟動")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, "LeagueMrfox 已經在執行中。", "LeagueMrfox", 0x40)
        except Exception:
            pass
        sys.exit(0)

    # 打包成 .exe 時 PyInstaller 解壓至 sys._MEIPASS；開發模式使用腳本所在目錄
    if getattr(sys, "frozen", False):
        web_dir = os.path.join(sys._MEIPASS, "web")
    else:
        web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    eel.init(web_dir)

    import webview

    # 背景執行緒：只啟動 eel 的 HTTP + WebSocket server，不開瀏覽器
    def _eel_server():
        try:
            eel.start("index.html", mode=None, block=True, port=_EEL_PORT,
                      close_callback=lambda p, s: None)
        except Exception as e:
            _log(f"EEL_SERVER_ERR >> {e}")

    t = threading.Thread(target=_eel_server, daemon=True)
    t.start()

    # 輪詢等待 server 就緒，而非固定 sleep（避免視窗先於 server 開啟）
    if not _wait_server_ready(_EEL_PORT, timeout=10.0):
        _log("SYS >> eel server 啟動逾時，仍嘗試開啟視窗")

    # 用 pywebview 開啟原生視窗（無邊框，自訂標題列）
    # URL 帶時間戳避免 WebView2 快取舊頁面
    _cache_bust = int(time.time())
    _webview_window = webview.create_window(
        "LeagueMrfox",
        f"http://localhost:{_EEL_PORT}/index.html?v={_cache_bust}",
        width=1440,
        height=860,
        min_size=(900, 600),
        frameless=True,
        easy_drag=False,
        resizable=True,
    )

    # 選角戰術常駐浮窗：always-on-top、初始隱藏，由 gameflow phase 控制顯示。
    # 以 try/except 隔離，任何多視窗/置頂相容性問題都不影響主程式。
    try:
        _overlay_window = webview.create_window(
            "LeagueMrfox 選角戰術",
            f"http://localhost:{_EEL_PORT}/overlay.html?v={_cache_bust}",
            width=480,
            height=860,
            frameless=True,
            on_top=True,
            resizable=True,
            hidden=True,
            x=40, y=40,
        )
    except Exception as e:
        _overlay_window = None
        _log(f"OVERLAY_CREATE_ERR >> {e}")

    # 遊戲中 HUD 浮窗：預設放螢幕右上角，進入對局才顯示
    try:
        try:
            _sw = webview.screens[0].width
        except Exception:
            _sw = 1920
        _hud_window = webview.create_window(
            "LeagueMrfox 遊戲中 HUD",
            f"http://localhost:{_EEL_PORT}/hud.html?v={_cache_bust}",
            width=330, height=470,
            frameless=True, on_top=True, resizable=True, hidden=True,
            x=max(0, _sw - 350), y=90,
        )
    except Exception as e:
        _hud_window = None
        _log(f"HUD_CREATE_ERR >> {e}")

    if _hud_window:
        threading.Thread(target=_hud_watcher, daemon=True).start()
        threading.Thread(target=_hud_hotkeys, daemon=True).start()
        threading.Thread(target=_hud_key_poll, daemon=True).start()

    try:
        webview.start()
    except Exception as e:
        _log(f"WEBVIEW_ERR >> {e}")
    sys.exit(0)
