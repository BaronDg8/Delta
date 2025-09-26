# AppLauncher.py
from langchain.tools import tool
import os, glob, subprocess
from difflib import get_close_matches

class _Launcher:
    START_MENU_DIRS = [
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("APPDATA", os.path.expanduser(r"~\AppData\Roaming")), r"Microsoft\Windows\Start Menu\Programs"),
    ]

    ALIASES = {
        "vs code": "visual studio code",
        "vscode": "visual studio code",
        "edge": "microsoft edge",
        "chrome": "google chrome",
        "word": "microsoft word",
        "excel": "microsoft excel",
        "powerpoint": "microsoft powerpoint",
        "discord": "discord",
        "spotify": "spotify",
    }

    def __init__(self):
        self.index = None  # name(lower) -> path

    def _build_index(self):
        idx = {}
        # 1) Start Menu shortcuts (.lnk)
        for root in self.START_MENU_DIRS:
            if not os.path.isdir(root):
                continue
            for path in glob.glob(os.path.join(root, "**", "*.lnk"), recursive=True):
                name = os.path.splitext(os.path.basename(path))[0].lower()
                idx[name] = path
        # 2) Executables in PATH
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if not d or not os.path.isdir(d):
                continue
            for exe in glob.glob(os.path.join(d, "*.exe")):
                name = os.path.splitext(os.path.basename(exe))[0].lower()
                idx.setdefault(name, exe)  # prefer .lnk if it exists
        self.index = idx

    def _ensure_index(self):
        if self.index is None:
            self._build_index()

    def _normalize_query(self, q: str) -> str:
        q = q.strip().lower()
        if q.startswith("open "):
            q = q[5:]
        return self.ALIASES.get(q, q)

    def find(self, query: str):
        self._ensure_index()
        q = self._normalize_query(query)
        if q in self.index:
            return self.index[q]
        names = list(self.index.keys())
        match = get_close_matches(q, names, n=1, cutoff=0.6)
        return self.index[match[0]] if match else None

    def launch(self, query: str) -> tuple[bool, str]:
        target = self.find(query)
        if not target:
            return False, f"I couldn't find {query}."
        try:
            if target.lower().endswith((".lnk", ".url")):
                os.startfile(target)  # type: ignore[attr-defined]
            else:
                cwd = os.path.dirname(target) or None
                subprocess.Popen([target], cwd=cwd, shell=False)
            name = os.path.splitext(os.path.basename(target))[0]
            return True, f"Opening {name}."
        except Exception as e:
            return False, f"Sorry, I couldn’t open {query}: {e}"

# single cached instance for the tool
_LAUNCHER = _Launcher()

@tool("AppLauncher", return_direct=True)
def AppLauncher(query: str) -> str:
    """
    Open a Windows app by name. Natural inputs work:

    Examples:
    - "open chrome"
    - "open vs code"
    - "open microsoft word"
    """
    ok, msg = _LAUNCHER.launch(query)
    return msg
