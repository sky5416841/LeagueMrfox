import os
import re
import sys
import time
import json
import ssl
import base64
import asyncio
import threading

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
_augment_cache_loaded = False
_rank_emblem_cache: dict[str, str] = {}  # TIER_UPPER -> iconPath
_rank_emblem_loaded = False
_auto_pick         = False
_auto_pick_champ_id= 0
_last_pick_action_id = -1  # 防止對同一個 action 重複秒選
_champ_valid_ids: set[int] = set()  # 僅含有 roles 的正常可玩英雄，過濾 NPC

# 本地戰績快取路徑（data/ 已在 .gitignore，個人數據不上傳）
_MATCH_CACHE_FILE = os.path.join(os.path.dirname(__file__), "data", "match_history_cache.json")

# SGP 各區域 matchHistory base URL（來源：LeagueAkari/resources/builtin-config/sgp/league-servers.json）
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

# 在 initialize() 時填入
_platform_id       = ''   # 例如 "TW2"
_entitlement_token = ''   # Riot Entitlements JWT（SGP 認證用）

# ── Helper ─────────────────────────────────────────────────────────────
def _log(msg: str):
    try:
        eel.append_log(msg)()
    except Exception:
        print(f"[LOG] {msg}")


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
    """載入競技場 (KIWI) 增益資料快取。"""
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
            # 稀有度：0=Silver 1=Gold 2=Prismatic；嘗試多個欄位名
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
            _log(f"AUGMENT_CACHE >> 已載入 {len(_augment_cache)} 個競技場增益")
        else:
            _log("AUGMENT_CACHE_WARN >> cherry-augments.json 無資料")
    except Exception as e:
        _log(f"AUGMENT_CACHE_ERR >> {e}")


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
@eel.expose
def initialize():
    global _client, _puuid, _account_id, _platform_id, _entitlement_token
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

        _log(f"OPERATOR_PROFILE >> loaded: {full} // LVL {lvl} // ICON {icon_id}")
        _load_champ_summary()
        _start_ws()

        # ── 架構探勘報告（LeagueAkari 技術轉移藍圖）──────────────────────
        _log("═══════════════════════════════════════════════════════")
        _log("ARCH_REPORT >> LeagueAkari 核心功能探勘報告 v1.0")
        _log("═══════════════════════════════════════════════════════")
        _log("FEATURE_01 >> [自動符文套用] 原理：抓取 OP.GG / 遊戲內建")
        _log("             推薦符文 ID → DELETE 現有符文頁 →")
        _log("             POST /lol-perks/v1/pages 建立新符文頁")
        _log("             觸發時機：選角後確認英雄 / 手動觸發按鈕")
        _log("FEATURE_02 >> [選角大廳隊友查詢] 原理：champ-select session")
        _log("             events 已訂閱 → 解析 participants[].summonerId →")
        _log("             GET /lol-match-history/.../matches 抓近 5 場")
        _log("             顯示於側邊欄彈出視窗（勝率 / 常用英雄）")
        _log("FEATURE_03 >> [自動禁角 Auto-Ban] 原理：與 Auto-Pick 架構")
        _log("             完全相同 → 偵測 type==ban、isInProgress==True →")
        _log("             PATCH championId → POST complete 鎖定禁用")
        _log("             設定頁新增禁角 ID 輸入框即可直接移植")
        _log("═══════════════════════════════════════════════════════")

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


def _parse_one_game(game: dict, source: str) -> dict | None:
    """解析單場遊戲資料，相容 LCU 格式（stats 巢狀）與 SGP 格式（stats 攤平）。
    回傳解析好的 dict，找不到玩家或失敗時回傳 None。
    """
    _QUEUES_LOCAL = {
        420: "排位賽", 440: "彈性排位", 450: "大亂鬥",
        400: "一般對戰", 430: "一般對戰", 700: "衝突",
    }

    # ── 找玩家：SGP 可直接比 puuid；LCU 需透過 participantIdentities ────
    our_pid  = None
    our_puuid_matched = False

    # SGP / 新版 LCU：participants[].puuid 直接存在
    for p in game.get("participants", []):
        if p.get("puuid") == _puuid:
            our_pid = p.get("participantId")
            our_puuid_matched = True
            break

    # 舊版 LCU：透過 participantIdentities 查 participantId
    if not our_puuid_matched:
        for ident in game.get("participantIdentities", []):
            pl = ident.get("player", {})
            if (_puuid      and pl.get("puuid")            == _puuid) or \
               (_account_id and pl.get("accountId")        == _account_id) or \
               (_account_id and pl.get("currentAccountId") == _account_id):
                our_pid = ident.get("participantId")
                break

    if our_pid is None and not our_puuid_matched:
        return None

    for p in game.get("participants", []):
        # 用 puuid 或 participantId 定位自己
        matched = (p.get("puuid") == _puuid) if our_puuid_matched \
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
def set_auto_accept(enabled: bool):
    global _auto_accept
    _auto_accept = bool(enabled)
    _log(f"AUTO_ACCEPT_PROTOCOL >> {'ENGAGED' if _auto_accept else 'STANDBY'}")


@eel.expose
def set_auto_pick(enabled: bool, champ_id: int):
    global _auto_pick, _auto_pick_champ_id, _last_pick_action_id
    _auto_pick          = bool(enabled)
    _auto_pick_champ_id = int(champ_id) if champ_id else 0
    _last_pick_action_id = -1
    _log(f"AUTO_PICK_PROTOCOL >> {'ENGAGED' if _auto_pick else 'STANDBY'} // ChampID={_auto_pick_champ_id}")


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
    result = [{"id": cid, "name": name} for cid, name in _champ_cache.items() if cid > 0 and cid in _champ_valid_ids]
    result.sort(key=lambda x: x["name"])
    _log(f"CHAMP_LIST >> 回傳 {len(result)} 位英雄")
    return result


@eel.expose
def get_game_detail(game_id: int) -> dict:
    """取得完整 10 人對局資料，拆分為藍隊與紅隊。"""
    if not _client:
        return {}
    try:
        raw       = _client.get(f"/lol-match-history/v1/games/{game_id}")
        game_mode = raw.get("gameMode", "")
        is_arena  = game_mode in ("KIWI", "CHERRY")

        # participantId → 召喚師名稱
        id_map = {}
        for ident in raw.get("participantIdentities", []):
            pid  = ident.get("participantId")
            p    = ident.get("player", {})
            name = (p.get("gameName") or p.get("summonerName") or "---").strip()
            tag  = (p.get("tagLine") or "").strip()
            id_map[pid] = f"{name}#{tag}" if tag else name

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


def _ws_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_ws_listen_with_retry())
    except Exception as e:
        _log(f"WS_WORKER_ERR >> {e}")
    finally:
        loop.close()


async def _ws_listen_with_retry():
    backoff = 5
    while not _ws_stop.is_set():
        connected = await _ws_listen()
        if _ws_stop.is_set():
            break
        if connected:
            backoff = 5   # reset on clean disconnect
        else:
            backoff = min(backoff * 2, 60)
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
            additional_headers={"Authorization": f"Basic {creds}"},
            ssl=ssl_ctx,
            ping_interval=20,
            ping_timeout=10,
        ) as ws:
            _log("WS_STREAM >> ACTIVE // 訂閱配對與選角事件")
            # 訂閱配對就緒確認
            await ws.send(json.dumps([5, "OnJsonApiEvent_lol-matchmaking_v1_ready-check"]))
            # 訂閱英雄選擇階段（LeagueAkari 核心技術：監聽 champ-select session）
            await ws.send(json.dumps([5, "OnJsonApiEvent_lol-champ-select_v1_session"]))
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


async def _handle_champ_select(data: dict):
    """
    LeagueAkari 核心技術：英雄選擇階段自動秒選。
    參考架構：localPlayerCellId 比對 actorCellId，
    找到 type==pick、isInProgress==True、completed==False 的 action，
    PATCH championId 後 POST complete 鎖定。
    """
    global _last_pick_action_id
    if not isinstance(data, dict):
        return
    if not _auto_pick or not _auto_pick_champ_id:
        return

    local_cell = data.get("localPlayerCellId", -1)
    # actions 是二維陣列（每個選角階段一個子陣列）
    all_actions = []
    for phase in data.get("actions", []):
        if isinstance(phase, list):
            all_actions.extend(phase)
        elif isinstance(phase, dict):
            all_actions.append(phase)

    for action in all_actions:
        if (action.get("actorCellId") == local_cell
                and action.get("type", "").lower() == "pick"
                and action.get("isInProgress", False)
                and not action.get("completed", True)):

            action_id = action.get("id")
            if action_id == _last_pick_action_id:
                return  # 同一個 action 已處理，防止重複觸發
            _last_pick_action_id = action_id

            _log(f"CHAMP_SELECT >> 輪到我！actionId={action_id} 秒選 champId={_auto_pick_champ_id}")
            try:
                # Step 1：Hover（intent）英雄
                _client.patch(
                    f"/lol-champ-select/v1/session/actions/{action_id}",
                    json={"championId": _auto_pick_champ_id, "type": "pick"}
                )
                _log(f"AUTO_PICK >> PATCH champId={_auto_pick_champ_id} ✓")
                # Step 2：Lock In（完成選角）
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
            return


# ── Launch ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    eel.init(web_dir)

    launch_opts = dict(size=(1280, 800), close_callback=lambda p, s: sys.exit(0))
    for mode in ("edge", "chrome", "default"):
        try:
            eel.start("index.html", mode=mode, **launch_opts)
            break
        except (SystemError, OSError, EnvironmentError):
            continue
