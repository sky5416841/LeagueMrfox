import os
_py_dir = os.path.dirname(os.path.abspath(__file__))
_tcl_base = r"C:\Users\user\AppData\Local\Programs\Python\Python313\tcl"
os.environ.setdefault("TCL_LIBRARY", os.path.join(_tcl_base, "tcl8.6"))
os.environ.setdefault("TK_LIBRARY",  os.path.join(_tcl_base, "tk8.6"))

import asyncio
import base64
import json
import ssl
import threading
from datetime import datetime

import customtkinter as ctk
import websockets

from lcu_core import LCUClient, LCUNotRunningError

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SIDEBAR_W = 220


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("League Dashboard")
        self.geometry("920x560")
        self.minsize(920, 560)

        self.client: LCUClient | None = None
        self.auto_accept_enabled = False
        self._ws_thread: threading.Thread | None = None
        self._stop_ws = threading.Event()

        self._build_ui()
        self.after(200, self._connect)

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=SIDEBAR_W, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(9, weight=1)

        ctk.CTkLabel(
            sb, text="League\nDashboard",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=(32, 24))

        ctk.CTkLabel(
            sb, text="C O N N E C T I O N",
            font=ctk.CTkFont(size=9), text_color="gray",
        ).grid(row=1, column=0, padx=22, sticky="w")

        # Status pill
        pill = ctk.CTkFrame(sb, fg_color=("gray20", "gray17"))
        pill.grid(row=2, column=0, padx=14, pady=(6, 16), sticky="ew")

        self._dot = ctk.CTkLabel(
            pill, text="●", font=ctk.CTkFont(size=18), text_color="#ff4d4d"
        )
        self._dot.grid(row=0, column=0, padx=(12, 6), pady=10)

        self._status_lbl = ctk.CTkLabel(
            pill, text="未連接", font=ctk.CTkFont(size=13)
        )
        self._status_lbl.grid(row=0, column=1, padx=(0, 12), pady=10, sticky="w")

        ctk.CTkButton(
            sb, text="重新連線", width=SIDEBAR_W - 40, command=self._connect,
        ).grid(row=3, column=0, padx=20, pady=4)

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        main.grid_columnconfigure((0, 1), weight=1)
        main.grid_rowconfigure(2, weight=1)

        # Summoner name card
        nc = ctk.CTkFrame(main)
        nc.grid(row=0, column=0, padx=(0, 8), pady=(0, 12), sticky="nsew")
        ctk.CTkLabel(nc, text="召喚師名稱",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(16, 4))
        self._name_lbl = ctk.CTkLabel(nc, text="—",
                                       font=ctk.CTkFont(size=17, weight="bold"))
        self._name_lbl.pack(pady=(0, 16))

        # Level card
        lc = ctk.CTkFrame(main)
        lc.grid(row=0, column=1, padx=(8, 0), pady=(0, 12), sticky="nsew")
        ctk.CTkLabel(lc, text="召喚師等級",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(16, 4))
        self._level_lbl = ctk.CTkLabel(lc, text="—",
                                        font=ctk.CTkFont(size=17, weight="bold"))
        self._level_lbl.pack(pady=(0, 16))

        # Features card
        fc = ctk.CTkFrame(main)
        fc.grid(row=1, column=0, columnspan=2, pady=(0, 12), sticky="nsew")
        fc.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(fc, text="自動化功能",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=2, padx=20, pady=(14, 4), sticky="w")

        ctk.CTkLabel(fc, text="自動接受對局",
                     font=ctk.CTkFont(size=13)).grid(
            row=1, column=0, padx=20, pady=(4, 14), sticky="w")

        self._auto_sw = ctk.CTkSwitch(
            fc, text="", onvalue=True, offvalue=False,
            command=self._toggle_auto_accept,
        )
        self._auto_sw.grid(row=1, column=1, padx=20, pady=(4, 14), sticky="e")

        # Log card
        lcard = ctk.CTkFrame(main)
        lcard.grid(row=2, column=0, columnspan=2, sticky="nsew")
        lcard.grid_columnconfigure(0, weight=1)
        lcard.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(lcard, text="活動記錄",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, padx=20, pady=(14, 4), sticky="w")

        self._log_box = ctk.CTkTextbox(lcard, state="disabled",
                                        font=ctk.CTkFont(family="Consolas", size=12))
        self._log_box.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")

    # ── Helpers ───────────────────────────────────────────────────────

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_box.configure(state="normal")
        self._log_box.insert("end", f"[{ts}]  {msg}\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _set_connected(self, ok: bool):
        self._dot.configure(text_color="#44dd77" if ok else "#ff4d4d")
        self._status_lbl.configure(text="已連接" if ok else "未連接")

    # ── Connect / Summoner ────────────────────────────────────────────

    def _connect(self):
        self._log("正在連線至 League Client…")
        try:
            self.client = LCUClient()
            self._set_connected(True)
            self._log(f"連線成功 (port={self.client.port})")
            self._fetch_summoner()
            self._start_ws()
        except LCUNotRunningError as e:
            self._set_connected(False)
            self._log(f"連線失敗：{e}")

    def _fetch_summoner(self):
        try:
            s = self.client.get("/lol-summoner/v1/current-summoner")
            name = s.get("gameName") or s.get("displayName") or "—"
            tag = s.get("tagLine", "")
            self._name_lbl.configure(text=f"{name}#{tag}" if tag else name)
            self._level_lbl.configure(text=str(s.get("summonerLevel", "—")))
            self._log(f"召喚師：{name}#{tag}，等級 {s.get('summonerLevel', '—')}")
        except Exception as e:
            self._log(f"取得召喚師資料失敗：{e}")

    # ── Auto-Accept ───────────────────────────────────────────────────

    def _toggle_auto_accept(self):
        self.auto_accept_enabled = bool(self._auto_sw.get())
        self._log("自動接受對局：" + ("開啟 ✓" if self.auto_accept_enabled else "關閉"))

    # ── WebSocket ─────────────────────────────────────────────────────

    def _start_ws(self):
        if self._ws_thread and self._ws_thread.is_alive():
            return
        self._stop_ws.clear()
        self._ws_thread = threading.Thread(target=self._ws_worker, daemon=True)
        self._ws_thread.start()

    def _ws_worker(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._ws_listen())
        except Exception as e:
            self.after(0, self._log, f"WebSocket 執行緒錯誤：{e}")
        finally:
            loop.close()

    async def _ws_listen(self):
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        creds = base64.b64encode(f"riot:{self.client.password}".encode()).decode()
        uri = f"wss://127.0.0.1:{self.client.port}"

        try:
            async with websockets.connect(
                uri,
                additional_headers={"Authorization": f"Basic {creds}"},
                ssl=ssl_ctx,
            ) as ws:
                self.after(0, self._log, "WebSocket 已連線，訂閱配對事件…")
                await ws.send(
                    json.dumps([5, "OnJsonApiEvent_lol-matchmaking_v1_ready-check"])
                )

                while not self._stop_ws.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        if not raw:
                            continue
                        msg = json.loads(raw)
                        # WAMP event: [8, topic, payload]
                        if len(msg) >= 3 and msg[0] == 8:
                            await self._on_ready_check(msg[2])
                    except asyncio.TimeoutError:
                        continue
                    except json.JSONDecodeError:
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        self.after(0, self._log, "WebSocket 連線中斷")
                        break
        except Exception as e:
            self.after(0, self._log, f"WebSocket 連線失敗：{e}")

    async def _on_ready_check(self, event: dict):
        data = event.get("data") or {}
        if not isinstance(data, dict):
            return

        state = data.get("state")
        player_resp = data.get("playerResponse", "None")

        if state == "InProgress" and player_resp == "None":
            self.after(0, self._log, "偵測到配對邀請！")
            if self.auto_accept_enabled:
                try:
                    self.client.post("/lol-matchmaking/v1/ready-check/accept")
                    self.after(0, self._log, "已自動接受對局 ✓")
                except Exception as e:
                    self.after(0, self._log, f"接受對局失敗：{e}")
        elif state == "EveryoneReady":
            self.after(0, self._log, "所有玩家已就緒，載入遊戲中…")

    # ── Lifecycle ─────────────────────────────────────────────────────

    def on_close(self):
        self._stop_ws.set()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
