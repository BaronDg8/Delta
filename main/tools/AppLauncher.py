import os, glob, subprocess
from difflib import get_close_matches

class AppLauncher:
    """
    Builds a quick index of Start Menu shortcuts (.lnk) and PATH executables,
    then fuzzy-matches 'open <app>' requests and launches them.
    """
    START_MENU_DIRS = [
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("APPDATA",     os.path.expanduser(r"~\AppData\Roaming")), r"Microsoft\Windows\Start Menu\Programs"),
    ]

    # simple alias map so common nicknames work
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
                # don't overwrite .lnk if we already have that name
                idx.setdefault(name, exe)

        self.index = idx

    def _ensure_index(self):
        if self.index is None:
            self._build_index()

    def _normalize_query(self, q: str) -> str:
        q = q.strip().lower()
        return self.ALIASES.get(q, q)

    def find(self, query: str) -> str | None:
        """Return a filesystem path (.lnk or .exe) for the best match."""
        self._ensure_index()
        q = self._normalize_query(query)
        if q in self.index:
            return self.index[q]

        # fuzzy match on names
        names = list(self.index.keys())
        match = get_close_matches(q, names, n=1, cutoff=0.6)
        if match:
            return self.index[match[0]]
        return None

    def launch(self, query: str) -> tuple[bool, str]:
        target = self.find(query)
        if not target:
            return False, f"I couldn't find {query}."

        try:
            # .lnk / .url via ShellExecute
            if target.lower().endswith((".lnk", ".url")):
                os.startfile(target)
            else:
                # Run .exe directly (no shell), use its folder as cwd
                cwd = os.path.dirname(target) or None
                subprocess.Popen([target], cwd=cwd, shell=False)
            name = os.path.splitext(os.path.basename(target))[0]
            return True, f"Opening {name}."
        except Exception as e:
            return False, f"Sorry, I couldn’t open {query}: {e}"