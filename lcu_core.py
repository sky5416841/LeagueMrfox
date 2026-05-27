import base64
import os
import psutil
import requests
import urllib3
import websockets

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_PROCESS_NAMES = ("LeagueClientUx.exe", "LeagueClientUx")


class LCUNotRunningError(Exception):
    pass


def _find_lcu_process():
    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            if proc.info["name"] in _PROCESS_NAMES:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    raise LCUNotRunningError("League Client process not found. Make sure the client is running.")


def _parse_lockfile(proc):
    try:
        exe_path = proc.exe()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        raise LCUNotRunningError(f"Cannot access process executable: {e}")

    install_dir = os.path.dirname(exe_path)
    lockfile_path = os.path.join(install_dir, "lockfile")

    if not os.path.exists(lockfile_path):
        raise LCUNotRunningError(f"lockfile not found at: {lockfile_path}")

    with open(lockfile_path, "r") as f:
        content = f.read().strip()

    # format: <name>:<pid>:<port>:<password>:<protocol>
    parts = content.split(":")
    if len(parts) != 5:
        raise LCUNotRunningError(f"Unexpected lockfile format: {content}")

    return {
        "name": parts[0],
        "pid": int(parts[1]),
        "port": int(parts[2]),
        "password": parts[3],
        "protocol": parts[4],
    }


class LCUClient:
    def __init__(self):
        proc = _find_lcu_process()
        info = _parse_lockfile(proc)

        self.port = info["port"]
        self.password = info["password"]
        self.protocol = info["protocol"]
        self._base_url = f"{self.protocol}://127.0.0.1:{self.port}"
        self._auth = ("riot", self.password)
        self._session = requests.Session()
        self._session.auth = self._auth
        self._session.verify = False

    def request(self, method: str, endpoint: str, **kwargs):
        url = self._base_url + endpoint
        response = self._session.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def get(self, endpoint: str, **kwargs):
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs):
        return self.request("POST", endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs):
        return self.request("PUT", endpoint, **kwargs)

    def patch(self, endpoint: str, **kwargs):
        return self.request("PATCH", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs):
        return self.request("DELETE", endpoint, **kwargs)

    def _ws_auth_header(self) -> dict:
        credentials = base64.b64encode(f"riot:{self.password}".encode()).decode()
        return {"Authorization": f"Basic {credentials}"}

    async def connect_websocket(self):
        uri = f"wss://127.0.0.1:{self.port}"
        ssl_context = __import__("ssl").create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = __import__("ssl").CERT_NONE
        return await websockets.connect(
            uri,
            additional_headers=self._ws_auth_header(),
            ssl=ssl_context,
        )
