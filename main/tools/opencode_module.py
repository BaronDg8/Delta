# opencode_module.py
import os, sys, time, platform, shutil, subprocess, requests

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4096

class OpenCodeModule:
    """
    Bridge Delta <-> OpenCode.
    mode="run":   fire-and-forget via `opencode run`
    mode="serve": ensure `opencode serve` is up, then call HTTP API.
    """
    def __init__(self, mode="run", binary="opencode", host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.mode   = mode
        self.binary = binary
        self.host   = host
        self.port   = port
        self.proc   = None  # server process when mode="serve"
        self.session_id = None

    # ---------- shared ----------
    def _which(self):
        path = shutil.which(self.binary)
        if not path:
            # allow hardcoding a full path in self.binary
            if os.path.exists(self.binary):
                return self.binary
            raise FileNotFoundError("opencode binary not found on PATH")
        return path

    # ---------- run mode ----------
    def ask_run(self, prompt: str, model: str|None=None, cwd: str|None=None) -> str:
        exe = self._which()
        cmd = [exe, "run", prompt]
        if model:
            cmd += ["--model", model]  # accepts provider/model per docs
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=cwd or os.getcwd()
        )
        out, err = p.communicate()
        if p.returncode != 0 and not out:
            raise RuntimeError(err.strip() or "opencode run failed")
        return out.strip()

    # ---------- serve mode ----------
    def _server_url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    def _ping(self) -> bool:
        try:
            r = requests.get(self._server_url("/app"), timeout=0.4)
            return r.ok
        except Exception:
            return False

    def ensure_server(self, cwd: str|None=None, quiet=True):
        if self._ping():
            return
        exe = self._which()
        flags = 0
        if platform.system() == "Windows":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        self.proc = subprocess.Popen(
            [exe, "serve", "--port", str(self.port), "--hostname", self.host],
            stdout=(subprocess.DEVNULL if quiet else None),
            stderr=(subprocess.DEVNULL if quiet else None),
            cwd=cwd or os.getcwd(),
            creationflags=flags
        )
        # wait for readiness
        for _ in range(60):
            time.sleep(0.1)
            if self._ping():
                return
        raise RuntimeError("Failed to start opencode server")

    def ensure_session(self):
        if self.session_id:
            return self.session_id
        r = requests.post(self._server_url("/session"), json={}, timeout=5)
        r.raise_for_status()
        data = r.json()
        # server returns a Session object; prefer `id` top-level or info.id
        self.session_id = (data.get("id")
                            or data.get("info", {}).get("id"))
        if not self.session_id:
            raise RuntimeError("Could not obtain session id")
        return self.session_id

    def ask_serve(self, prompt: str, model: str|None=None, agent: str|None=None) -> str:
        sid = self.ensure_session()
        body = {"parts": [{"type": "text", "text": prompt}]}
        if model: body["modelID"] = model
        if agent: body["agentID"] = agent
        r = requests.post(self._server_url(f"/session/{sid}/message"), json=body, timeout=120)
        r.raise_for_status()
        msg = r.json()
        # Extract text from `parts` if present (API returns Message object)
        parts = msg.get("parts") or []
        texts = []
        for p in parts:
            # some implementations use {type:"text", content:"..."} or {type:"text", text:"..."}
            if isinstance(p, dict) and p.get("type") == "text":
                texts.append(p.get("text") or p.get("content") or "")
        return "\n".join(t for t in texts if t)
