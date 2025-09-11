"""
Cortana Manager Executable
 "pyinstaller --noconsole  manager.py" to update the executable
 "pyinstaller --noconsole  manager.py --icon=cortana.png" to update the executable with an icon
 # pyinstaller --noconsole manager.py --icon=cortana.png --add-data "voice_activation.py;." --add-data "resource_notifier.py;." --add-data "Delta.py;." --add-data "chat_room.py;." --add-data "mic_system.py;." --add-data "mouth.py;." --add-data "commands.json;." --add-data "settings.json;." --add-data "ignore_config.json;." --add-data "cortana.png;."
"""

import sys
import subprocess
import os
import socket
import json
import datetime
import glob

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QMessageBox, QComboBox, QTabWidget, QLineEdit, QLabel, QFormLayout, QScrollArea,
    QSystemTrayIcon, QMenu, QAction, QStyle, QPlainTextEdit, QFileDialog, QAction, qApp
)
from PyQt5.QtGui import QIcon, QFont, QColor, QTextCursor, QGuiApplication, QPainter
from PyQt5.QtCore import Qt, QProcess, QTimer, QProcessEnvironment, pyqtSignal

# --- CONFIG SUPPORT ---
CONFIG_PATH = os.path.join("main", "config", "terminal_config.json")

def load_config():
    if not os.path.exists(CONFIG_PATH):
        # Default config if missing
        return {
            "interpreter": sys.executable,
            "default_shell": "cmd",
            "script_directory": "scripts",
            "last_script": "",
            "auto_run_chain": False,
            "script_chain": []
        }
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

class IntegratedTerminal(QWidget):
    # a widget providing an integrated terminal shell using QProcess.
    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.shell_type = "cmd"
        self.history = []
        self.history_index = -1
        self.env = os.environ.copy()
        self.initUI()
        self.load_history()
        self.start_shell(self.shell_type)

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Shell selector and control buttons
        top_bar = QHBoxLayout()
        self.shell_selector = QComboBox()
        self.shell_selector.addItems(["cmd", "powershell", "bash", "python"])
        self.shell_selector.currentTextChanged.connect(self.change_shell)
        top_bar.addWidget(QLabel("Shell:"))
        top_bar.addWidget(self.shell_selector)

        self.btn_run_file = QPushButton("Run File")
        self.btn_run_file.clicked.connect(self.run_script_file)
        top_bar.addWidget(self.btn_run_file)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.clear_output)
        top_bar.addWidget(self.btn_clear)

        self.btn_kill = QPushButton("Kill")
        self.btn_kill.clicked.connect(self.kill_process)
        top_bar.addWidget(self.btn_kill)

        self.status_label = QLabel("Idle")
        top_bar.addWidget(self.status_label)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Output area
        self.terminal_output = QPlainTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setFont(QFont("Consolas", 10))
        self.terminal_output.setStyleSheet("background-color: #181818; color: #e0e0e0; border-radius: 10px;")
        layout.addWidget(self.terminal_output)

        # Input area
        self.terminal_input = QLineEdit()
        self.terminal_input.setPlaceholderText("Type a command and press Enter...")
        self.terminal_input.setFont(QFont("Consolas", 10))
        self.terminal_input.setStyleSheet("background-color: #232323; color: #e0e0e0; border-radius: 8px;")
        self.terminal_input.returnPressed.connect(self.run_command)
        self.terminal_input.installEventFilter(self)
        layout.addWidget(self.terminal_input)

        self.setLayout(layout)

    def start_shell(self, shell_type="cmd"):
        # kill old
        if self.process:
            self.process.kill()
            self.process.deleteLater()

        # create and store on self.process
        self.process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        self.process.setProcessEnvironment(env)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.setWorkingDirectory(os.getcwd())

        if shell_type.lower().startswith("powershell"):
            prog, args = "powershell.exe", ["-NoExit", "-Command", f"Set-Location \"{os.getcwd()}\""]
        else:
            prog, args = "cmd.exe", ["/K"]

        self.process.setProgram(prog)
        self.process.setArguments(args)
        self.process.start()
        self.terminal_output.appendPlainText(f"[Launched {prog} in {os.getcwd()}]")

    def run_command(self):
        cmd = self.terminal_input.text().strip()
        # ← now this will actually see the QProcess you just started
        if not cmd or not self.process or self.process.state() != QProcess.Running:
            self.terminal_output.appendPlainText("[No persistent shell process running!]")
            return

        self.terminal_output.appendPlainText(f">>> {cmd}")
        self.terminal_input.clear()
        self.process.write((cmd + "\n").encode("utf-8"))

    def run_command(self):
        command = self.terminal_input.text().strip()
        if not command:
            return

        # ---- handle cd locally ----
        parts = command.split(maxsplit=1)
        if parts[0].lower() == "cd":
            target = parts[1] if len(parts) > 1 else os.path.expanduser("~")
            try:
                os.chdir(target)
                self.terminal_output.appendPlainText(f"Changed directory to {os.getcwd()}")
            except Exception as e:
                self.terminal_output.appendPlainText(f"cd {e}")
            self.terminal_input.clear()
            return

        # your existing subprocess.run code
        shell = self.config.get("default_shell", "cmd")
        if shell == "cmd":
            shell_cmd = ["cmd.exe", "/C", command]
        # … other shells …
        completed = subprocess.run(shell_cmd, capture_output=True, text=True)
        if completed.stdout:
            self.terminal_output.appendPlainText(completed.stdout)
        if completed.stderr:
            self.terminal_output.appendPlainText(f"[stderr] {completed.stderr}")
        self.terminal_output.appendPlainText(f"--- Script exited with code {completed.returncode} ---")
        self.terminal_input.clear()

    def handle_stdout(self):
        if self.process:
            data = self.process.readAllStandardOutput()
            text = bytes(data).decode(errors="replace")
            self.terminal_output.appendPlainText(text.rstrip())
            self.terminal_output.moveCursor(QTextCursor.End)

    def handle_stderr(self):
        if self.process:
            data = self.process.readAllStandardError()
            text = bytes(data).decode(errors="replace")
            self.terminal_output.appendPlainText(f"[stderr] {text.rstrip()}")
            self.terminal_output.moveCursor(QTextCursor.End)

    def clear_output(self):
        self.terminal_output.clear()

    def kill_process(self):
        if self.process and self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.set_status("Killed")
            self.terminal_output.appendPlainText("[Process killed]")

    def set_status(self, status):
        if hasattr(self, "status_label") and self.status_label:
            try:
                self.status_label.setText(status)
            except RuntimeError:
                pass

    def change_shell(self, shell_type):
        self.shell_type = shell_type
        self.start_shell(shell_type)

    def run_script_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Script File", "", 
            "All Scripts (*.py *.js *.sh *.ps1);;Python (*.py);;JavaScript (*.js);;Shell (*.sh);;PowerShell (*.ps1)")
        if not file_path:
            return
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".py":
            cmd = f'python "{file_path}"'
        elif ext == ".js":
            cmd = f'node "{file_path}"'
        elif ext == ".sh":
            cmd = f'bash "{file_path}"'
        elif ext == ".ps1":
            cmd = f'powershell -ExecutionPolicy ByPass -File "{file_path}"'
        else:
            self.terminal_output.appendPlainText("[Unsupported script type]")
            return
        self.terminal_input.setText(cmd)
        self.run_command()

    def eventFilter(self, obj, event):
        # Up/Down arrow for history navigation
        if obj == self.terminal_input and event.type() == event.KeyPress:
            if event.key() == Qt.Key_Up:
                if self.history and self.history_index > 0:
                    self.history_index -= 1
                    self.terminal_input.setText(self.history[self.history_index])
                    return True
            elif event.key() == Qt.Key_Down:
                if self.history and self.history_index < len(self.history) - 1:
                    self.history_index += 1
                    self.terminal_input.setText(self.history[self.history_index])
                    return True
                elif self.history_index == len(self.history) - 1:
                    self.history_index += 1
                    self.terminal_input.clear()
                    return True
        return super().eventFilter(obj, event)

    def save_history(self):
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2)
        except Exception:
            pass

    def load_history(self):
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                self.history = json.load(f)
            self.history_index = len(self.history)
        except Exception:
            self.history = []
            self.history_index = 0

class Terminal(QWidget):
    """IDE-style terminal and script launcher with config support."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = load_config()
        self.env = os.environ.copy()
        
        # **HOOK UP** to the manager’s persistent cmd_process
        if parent and hasattr(parent, "cmd_process"):
            self.process = parent.cmd_process
        else:
            self.process = None

        self.scripts_folder = self.config.get("script_directory", "scripts")
        self.last_script    = self.config.get("last_script", "")
        self.initUI()
        self.refresh_scripts_list()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Top bar: interpreter & shell selectors, script selector, run, chain, reload, clear ---
        top_bar = QHBoxLayout()

        # Interpreter selector
        self.interpreter_selector = QComboBox()
        self.interpreter_selector.setEditable(True)
        # Populate with current interpreter and any common ones
        current_interp = self.config.get("interpreter", sys.executable)
        interpreters = [
            current_interp,
            sys.executable,
            # input should look like this  ex: r"C:\Python39\python.exe",
        ]
        interpreters = list(dict.fromkeys(interpreters))
        self.interpreter_selector.addItems(interpreters)
        self.interpreter_selector.setCurrentText(current_interp)
        self.interpreter_selector.currentTextChanged.connect(self.change_interpreter)
        top_bar.addWidget(QLabel("Interpreter:"))
        top_bar.addWidget(self.interpreter_selector)

        # Shell selector
        self.shell_selector = QComboBox()
        self.shell_selector.addItems(["cmd", "powershell", "bash"])
        current_shell = self.config.get("default_shell", "cmd")
        idx = self.shell_selector.findText(current_shell)
        if idx >= 0:
            self.shell_selector.setCurrentIndex(idx)
        self.shell_selector.currentTextChanged.connect(self.change_shell)
        top_bar.addWidget(QLabel("Shell:"))
        top_bar.addWidget(self.shell_selector)

        # Script selector
        self.scripts_combo = QComboBox()
        top_bar.addWidget(QLabel("Script:"))
        top_bar.addWidget(self.scripts_combo)

        btn_run = QPushButton("Run Script")
        btn_run.clicked.connect(self.open_and_run_script)
        top_bar.addWidget(btn_run)

        btn_reload = QPushButton("Reload Scripts")
        btn_reload.clicked.connect(self.refresh_scripts_list)
        top_bar.addWidget(btn_reload)

        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self.clear_output)
        top_bar.addWidget(btn_clear)

        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Terminal output
        self.terminal_output = QPlainTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setFont(QFont("Consolas", 10))
        self.terminal_output.setStyleSheet("background-color: #181818; color: #e0e0e0; border-radius: 10px;")
        layout.addWidget(self.terminal_output)

        # Command input
        self.terminal_input = QLineEdit()
        self.terminal_input.setPlaceholderText("Type a command and press Enter...")
        self.terminal_input.returnPressed.connect(self.run_command)
        layout.addWidget(self.terminal_input)
        
        self.setLayout(layout)

    def change_interpreter(self, interp_path):
        self.config["interpreter"] = interp_path
        save_config(self.config)
        # Check if interpreter works
        try:
            completed = subprocess.run(
                [interp_path, "--version"],
                capture_output=True,
                text=True,
                shell=False,
                timeout=5
            )
            if completed.returncode == 0:
                version = completed.stdout.strip() or completed.stderr.strip()
                self.terminal_output.appendPlainText(f"[Interpreter connected: {interp_path} ({version})]")
                # Check CONDA_PREFIX
                conda_check = subprocess.run(
                    [interp_path, "-c", "import os; print(os.environ.get('CONDA_PREFIX', 'Conda NOT active'))"],
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=5
                )
                conda_status = conda_check.stdout.strip() or conda_check.stderr.strip()
                self.terminal_output.appendPlainText(f"[Conda status: {conda_status}]")
            else:
                self.terminal_output.appendPlainText(f"[Interpreter set to: {interp_path} but failed to run]")
        except Exception as e:
            self.terminal_output.appendPlainText(f"[Interpreter set to: {interp_path} but error: {e}]")

    def change_shell(self, shell_type):
        self.config["default_shell"] = shell_type
        save_config(self.config)
        self.terminal_output.appendPlainText(f"[Shell set to: {shell_type}]")

    def open_and_run_script(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Script File",
            self.scripts_folder,
            "Python Scripts (*.py);;All Files (*)"
        )
        if not file_path:
            return
        script_name = os.path.basename(file_path)
        self.last_script = script_name
        self.config["last_script"] = script_name
        save_config(self.config)
        self.run_script_by_path(file_path)

    def run_script_by_path(self, script_path):
        import os, sys, subprocess
        from PyQt5.QtCore import QProcess

        interpreter = self.config.get("interpreter", sys.executable)
        full_path  = os.path.abspath(script_path)
        script_dir = os.path.dirname(full_path)

        if not os.path.exists(full_path):
            self.terminal_output.appendPlainText(f"[Script not found: {full_path}]")
            return

        # Always cd into the script’s directory first
        cd_cmd = f'cd /d "{script_dir}"'

        # Detect whether we're already in a conda env
        conda_prefix = os.environ.get("CONDA_PREFIX", "")
        if not conda_prefix:
            # Try subprocess detection as fallback
            try:
                completed = subprocess.run(
                    [interpreter, "-c",
                    "import os; print(os.environ.get('CONDA_PREFIX',''))"],
                    capture_output=True, text=True, cwd=script_dir
                )
                conda_prefix = completed.stdout.strip()
            except Exception:
                conda_prefix = ""

        # Build the command to run under the persistent shell if available...
        if hasattr(self, "process") and self.process and self.process.state() == QProcess.Running:
            # 1) Change directory
            self.process.write((cd_cmd + "\n").encode("utf-8"))

            if not conda_prefix:
                # 2a) Activate base if needed, then run
                activate_bat = r"C:/Users/iceke/anaconda3/condabin/activate.bat"
                if not os.path.exists(activate_bat):
                    self.terminal_output.appendPlainText("[Conda activate.bat not found!]")
                    return
                cmd = f'call "{activate_bat}" base && python "{full_path}"'
                self.terminal_output.appendPlainText(f"[Running under conda base: {cmd}]")
            else:
                # 2b) Already active, just launch with interpreter
                cmd = f'{interpreter} "{full_path}"'
                self.terminal_output.appendPlainText(f">>> {cmd}")

            # 3) Send it into the live shell
            self.process.write((cmd + "\n").encode("utf-8"))

        else:
            # Fallback: no persistent shell, run via subprocess
            self.terminal_output.appendPlainText(f">>> Running via subprocess in {script_dir}")
            try:
                completed = subprocess.run(
                    [interpreter, full_path],
                    capture_output=True, text=True,
                    cwd=script_dir
                )
                if completed.stdout:
                    self.terminal_output.appendPlainText(completed.stdout)
                if completed.stderr:
                    self.terminal_output.appendPlainText(f"[stderr] {completed.stderr}")
                self.terminal_output.appendPlainText(f"--- Exit code {completed.returncode} ---")
            except Exception as e:
                self.terminal_output.appendPlainText(f"[Error running script: {e}]")


    def refresh_scripts_list(self):
        self.scripts_combo.clear()
        if not os.path.exists(self.scripts_folder):
            os.makedirs(self.scripts_folder)
        scripts = sorted([f for f in os.listdir(self.scripts_folder) if f.endswith(".py")])
        for script in scripts:
            self.scripts_combo.addItem(script)
        # Restore last script
        if self.last_script:
            idx = self.scripts_combo.findText(os.path.basename(self.last_script))
            if idx >= 0:
                self.scripts_combo.setCurrentIndex(idx)

    def run_selected_script(self):
        script_name = self.scripts_combo.currentText()
        if not script_name:
            self.terminal_output.appendPlainText("[No script selected]")
            return
        self.last_script = script_name
        self.config["last_script"] = script_name
        save_config(self.config)
        self.run_script(script_name)

    def run_chain(self):
        chain = self.config.get("script_chain", [])
        if not chain:
            self.terminal_output.appendPlainText("[No script_chain defined in config]")
            return
        for script in chain:
            self.run_script(script)

    def run_script(self, script_name):
        interpreter = self.config.get("interpreter", sys.executable)
        script_path = os.path.join(self.scripts_folder, script_name)
        if not os.path.exists(script_path):
            self.terminal_output.appendPlainText(f"[Script not found: {script_path}]")
            return

        self.terminal_output.appendPlainText(f">>> Running: {interpreter} {script_path}")
        try:
            completed = subprocess.run(
                [interpreter, script_path],
                capture_output=True,
                text=True,
                shell=False
            )
            if completed.stdout:
                self.terminal_output.appendPlainText(completed.stdout)
            if completed.stderr:
                self.terminal_output.appendPlainText(f"[stderr] {completed.stderr}")
            self.terminal_output.appendPlainText(f"--- Script exited with code {completed.returncode} ---")
        except Exception as e:
            self.terminal_output.appendPlainText(f"[Error running script: {e}]")

    def clear_output(self):
        """Clears the terminal output pane."""
        self.terminal_output.clear()

    def run_command(self):
        command = self.terminal_input.text().strip()
        if not command:
            return

        # 1) Handle built-in `cd` right here
        parts = command.split(maxsplit=1)
        if parts[0].lower() == "cd":
            target = parts[1] if len(parts) > 1 else os.path.expanduser("~")
            try:
                os.chdir(os.path.expandvars(target))
                self.terminal_output.appendPlainText(f"Changed directory to {os.getcwd()}")
            except Exception as e:
                self.terminal_output.appendPlainText(f"cd: {e}")
            self.terminal_input.clear()
            return

        # 2) All other commands still go out to subprocess.run()
        completed = subprocess.run(
            command, shell=True,
            cwd=os.getcwd(),       
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if completed.stdout:
            self.terminal_output.appendPlainText(completed.stdout)
        if completed.stderr:
            self.terminal_output.appendPlainText(f"[stderr] {completed.stderr}")
        self.terminal_input.clear()

class PersistentTerminal(QWidget):
    """A persistent QProcess-based terminal supporting cmd.exe or powershell.exe."""
    def __init__(self, shell="cmd", parent=None):
        super().__init__(parent)
        self.shell = shell
        self.process = None
        self.initUI()
        self.start_shell(self.shell)

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Shell selector
        shell_bar = QHBoxLayout()
        self.shell_selector = QComboBox()
        self.shell_selector.addItems(["cmd", "powershell"])
        self.shell_selector.setCurrentText(self.shell)
        self.shell_selector.currentTextChanged.connect(self.change_shell)
        shell_bar.addWidget(QLabel("Shell:"))
        shell_bar.addWidget(self.shell_selector)
        shell_bar.addStretch()
        layout.addLayout(shell_bar)

        # Output area
        self.terminal_output = QTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setFont(QFont("Consolas", 10))
        self.terminal_output.setStyleSheet("background-color: #181818; color: #e0e0e0; border-radius: 10px;")
        layout.addWidget(self.terminal_output)

        # Input area
        self.terminal_input = QLineEdit()
        self.terminal_input.setPlaceholderText("Type a command and press Enter...")
        self.terminal_input.setFont(QFont("Consolas", 10))
        self.terminal_input.setStyleSheet("background-color: #232323; color: #e0e0e0; border-radius: 8px;")
        self.terminal_input.returnPressed.connect(self.send_command)
        layout.addWidget(self.terminal_input)

        self.setLayout(layout)

    def start_shell(self, shell_type):
        if self.process:
            self.process.kill()
            self.process.deleteLater()
        self.process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        # Use full system environment and PATH
        self.process.setProcessEnvironment(env)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        # Set working directory to project folder
        project_dir = os.path.abspath(".")
        self.process.setWorkingDirectory(project_dir)
        if shell_type == "cmd":
            self.process.setProgram("cmd.exe")
        else:
            self.process.setProgram("powershell.exe")
        self.process.start()
        self.terminal_output.append(f"[Started {shell_type} in {project_dir}]")

    def change_shell(self, shell_type):
        self.shell = shell_type
        self.start_shell(shell_type)

    def send_command(self):
        command = self.terminal_input.text().strip()
        if not command or not self.process or self.process.state() != QProcess.Running:
            return
        self.terminal_output.append(f">>> {command}")
        self.terminal_input.clear()
        # Write command to the shell process
        self.process.write((command + "\n").encode("utf-8"))

    def handle_stdout(self):
        if self.process:
            data = self.process.readAllStandardOutput()
            text = bytes(data).decode(errors="replace")
            self.terminal_output.append(text.rstrip())

    def handle_stderr(self):
        if self.process:
            data = self.process.readAllStandardError()
            text = bytes(data).decode(errors="replace")
            self.terminal_output.append(f"[stderr] {text.rstrip()}")

class CortanaManager(QWidget):
    def __init__(self):
        super().__init__()
        # Frameless & translucent like Delta GUI
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.voice_process = None
        self.notifier_process = None
        self.manager_log = []
        self.terminal_process = None  # For terminal tab

        # --- Persistent QProcess Terminal Tab ---
        self.persistent_terminal = PersistentTerminal(shell="cmd", parent=self)
        # --- Persistent CMD QProcess for Terminal Tab ---
        self.cmd_process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        self.cmd_process.setProcessEnvironment(env)

        self.cmd_process.setProgram("cmd.exe")
        self.cmd_process.setArguments(["/K"])
        self.cmd_process.setProcessChannelMode(QProcess.MergedChannels)
        self.cmd_process.readyReadStandardOutput.connect(self.handle_cmd_stdout)
        self.cmd_process.readyReadStandardError.connect(self.handle_cmd_stderr)
        self.cmd_process.start()
        
        # make new self.cmd_process.write() to input commands on startup

        self.initUI()

        self.raphael_log_timer = QTimer(self)
        self.raphael_log_timer.timeout.connect(self.refresh_raphael_logs)
        self.raphael_log_timer.start(2000)  # Refresh every 2 seconds

        self.notifier_log_timer = QTimer(self)
        self.notifier_log_timer.timeout.connect(self.refresh_notifier_logs)
        self.notifier_log_timer.start(2000)  # Refresh every 2 seconds

        self.load_default_commands_on_startup()

    def initUI(self):
        self.setWindowTitle("Cortana Manager")
        self.resize(800, 600)

        # Close (X) button
        btn_close = QPushButton('✕')
        btn_close.setFixedSize(30, 30)
        btn_close.clicked.connect(self.close)
        btn_close.setStyleSheet(
            "QPushButton { background: transparent; color: white; font-size: 16px; }"
            "QPushButton:hover { color: #ff5c5c; }"
        )

        # Main tab widget
        main_tabs = QTabWidget()
        main_tabs.setCornerWidget(btn_close, Qt.TopRightCorner)

        # --- Manager Controls Tab ---
        mgr_tab = QWidget()
        mgr_layout = QVBoxLayout(mgr_tab)
        mgr_layout.setContentsMargins(10, 10, 10, 10)

        btn_start_voice = QPushButton("Start Voice Activation")
        btn_start_voice.clicked.connect(self.start_voice_activation)
        mgr_layout.addWidget(btn_start_voice)

        btn_stop_voice = QPushButton("Stop Voice Activation")
        btn_stop_voice.clicked.connect(self.stop_voice_activation)
        mgr_layout.addWidget(btn_stop_voice)

        btn_start_notifier = QPushButton("Start Resource Notifier")
        btn_start_notifier.clicked.connect(self.start_notifier)
        mgr_layout.addWidget(btn_start_notifier)

        btn_stop_notifier = QPushButton("Stop Resource Notifier")
        btn_stop_notifier.clicked.connect(self.stop_notifier)
        mgr_layout.addWidget(btn_stop_notifier)

        # Manager Logs pane
        self.manager_log_view = QTextEdit()
        self.manager_log_view.setReadOnly(True)
        mgr_layout.addWidget(self.manager_log_view)

        main_tabs.addTab(mgr_tab, "Manager")

        # --- Logs Tab ---
        logs_tab = QWidget()
        logs_layout = QVBoxLayout(logs_tab)
        logs_layout.setContentsMargins(10, 10, 10, 10)

        log_tabs = QTabWidget()

        # Raphael Logs
        raphael_tab = QWidget()
        r_layout = QVBoxLayout(raphael_tab)
        self.raphael_log_view = QTextEdit()
        self.raphael_log_view.setReadOnly(True)
        r_layout.addWidget(self.raphael_log_view)
        btn_refresh_raphael = QPushButton("Refresh Delta Logs")
        btn_refresh_raphael.clicked.connect(lambda: self.refresh_raphael_logs(True))
        r_layout.addWidget(btn_refresh_raphael)
        log_tabs.addTab(raphael_tab, "Delta Logs")

        # Notifier Logs
        notifier_tab = QWidget()
        n_layout = QVBoxLayout(notifier_tab)
        self.notifier_log_view = QTextEdit()
        self.notifier_log_view.setReadOnly(True)
        n_layout.addWidget(self.notifier_log_view)
        btn_refresh_notifier = QPushButton("Refresh Notifier Logs")
        btn_refresh_notifier.clicked.connect(lambda: self.refresh_notifier_logs(True))
        n_layout.addWidget(btn_refresh_notifier)
        log_tabs.addTab(notifier_tab, "Notifier Logs")

        logs_layout.addWidget(log_tabs)
        main_tabs.addTab(logs_tab, "Logs")

        # --- Settings Tab ---
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setContentsMargins(10, 10, 10, 10)

        # Default screen selector and button
        self.screen_selector = QComboBox()
        self.update_screen_list()
        settings_layout.addWidget(self.screen_selector)

        btn_set_default = QPushButton("Set Default Screen")
        btn_set_default.clicked.connect(self.set_default_screen)
        settings_layout.addWidget(btn_set_default)

        self.commands_form = QFormLayout()
        self.command_inputs = {}  # key: QLineEdit for command, value: QLineEdit for value

        self.load_commands_json()

        commands_widget = QWidget()
        commands_widget.setLayout(self.commands_form)
        scroll = QScrollArea()
        scroll.setWidget(commands_widget)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(200)
        settings_layout.addWidget(scroll)

        # Add new command row
        add_row = QHBoxLayout()
        self.new_command_key = QLineEdit()
        self.new_command_key.setPlaceholderText("Command name")
        self.new_command_value = QLineEdit()
        self.new_command_value.setPlaceholderText("Command value")
        btn_add_command = QPushButton("Add Command")
        btn_add_command.clicked.connect(self.add_command_row)
        add_row.addWidget(self.new_command_key)
        add_row.addWidget(self.new_command_value)
        add_row.addWidget(btn_add_command)
        settings_layout.addLayout(add_row)

        # Save commands button
        btn_save_commands = QPushButton("Save Commands")
        btn_save_commands.clicked.connect(self.save_commands_json)
        settings_layout.addWidget(btn_save_commands)

        main_tabs.addTab(settings_tab, "Settings")

        # --- Terminal Tab ---
        self.terminal_tab = Terminal(self)
        main_tabs.addTab(self.terminal_tab, "Terminal")
        
        style = """
            QWidget { background-color: rgba(0,0,0,150); border: 2px solid rgba(0,120,215,255); border-radius: 15px; }
            QTabWidget::pane { background: transparent; border: none; }
            QTabBar::tab { background: rgba(0,0,0,120); color: white; padding: 8px; border-top-left-radius: 10px; border-top-right-radius: 10px; }
            QTabBar::tab:selected { background: rgba(0,120,215,255); }
            QTextEdit, QPlainTextEdit { background-color: rgba(0,0,0,120); color: white; border-radius: 10px; }
            QPushButton { background-color: #0078D7; color: white; border-radius: 10px; padding: 6px; }
            QPushButton:hover { background-color: #0a84ff; }
            QComboBox { background-color: rgba(0,0,0,120); color: white; border-radius: 10px; padding: 4px; }
            QComboBox QAbstractItemView { background-color: rgba(0,0,0,180); color: white; }
            QLineEdit { background-color: rgba(0,0,0,120); color: white; border-radius: 8px; padding: 4px; }
            QLabel { color: white; }
        """
        self.setStyleSheet(style)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_tabs)
        self.setLayout(main_layout)

        # Initial log entry
        self.append_manager_log("CortanaManager UI initialized")
        self.tray_icon = QSystemTrayIcon(self)
        icon_file = resource_path("cortana.png")  # match the filename you bundled
        self.tray_icon = QSystemTrayIcon(QIcon(icon_file), self)

        # Create tray menu
        tray_menu = QMenu()
        show_action = QAction("Show")
        quit_action = QAction("Quit")

        show_action.triggered.connect(self.showNormal)
        quit_action.triggered.connect(QApplication.quit)

        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.setPen(QColor(0, 120, 215, 255))
        painter.drawRoundedRect(rect, 15, 15)

    def append_manager_log(self, message, color="white"):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{now}] {message}"
        self.manager_log.append(entry)
        # Use HTML for color styling
        html_entry = f'<span style="color:{color}">{entry}</span>'
        self.manager_log_view.append(html_entry)
        print(entry)

    def start_voice_activation(self):
        path = os.path.abspath("voice_activation.py")
        if self.voice_process is None or self.voice_process.state() == QProcess.NotRunning:
            self.voice_process = QProcess(self)
            self.voice_process.setProgram(sys.executable)
            self.voice_process.setArguments([path])
            self.voice_process.setProcessChannelMode(QProcess.MergedChannels)
            self.voice_process.readyReadStandardOutput.connect(self.handle_voice_stdout)
            self.voice_process.readyReadStandardError.connect(self.handle_voice_stderr)
            self.voice_process.started.connect(lambda: self.append_manager_log("Started voice activation", "white"))
            self.voice_process.finished.connect(lambda code, status: self.append_manager_log(f"Voice activation stopped (exit code {code})", "white"))
            self.voice_process.start()
            QMessageBox.information(self, "Voice Activation", "Started.")
        else:
            self.append_manager_log("Voice activation already running", "white")

    def stop_voice_activation(self):
        if self.voice_process and self.voice_process.state() != QProcess.NotRunning:
            self.voice_process.terminate()
            self.voice_process = None
            self.append_manager_log("Stopped voice activation", "white")
            QMessageBox.information(self, "Voice Activation", "Stopped.")
        else:
            self.append_manager_log("Voice activation not running", "white")

    def handle_voice_stdout(self):
        if self.voice_process:
            data = self.voice_process.readAllStandardOutput()
            text = bytes(data).decode(errors="replace")
            for line in text.splitlines():
                self.append_manager_log(f"[Voice][stdout] {line}", "white")

    def handle_voice_stderr(self):
        if self.voice_process:
            data = self.voice_process.readAllStandardError()
            text = bytes(data).decode(errors="replace")
            for line in text.splitlines():
                self.append_manager_log(f"[Voice][stderr] {line}", "red")

    def start_voice_activation(self):
        """CD into _internal then run voice_activation.py in the persistent shell."""
        proc = self.terminal_tab.process
        if not proc or proc.state() != QProcess.Running:
            self.append_manager_log("No shell running!", "red")
            return

        # 1) activate conda base in this shell session
        proc.write(b'call "C:/Users/iceke/anaconda3/condabin/activate.bat" base\n')
        # 2) switch to _internal folder
        proc.write(b"cd _internal\n")
        # 2b) switch to main folder (where voice_activation.py actually is)
        proc.write(b"cd main")
        # 3) run the script by name
        proc.write(b'python "voice_activation.py"\n')
        self.append_manager_log("Dispatched voice activation to terminal", "white")

    def start_notifier(self):
        """CD into _internal then run resource_notifier.py in the persistent shell."""
        proc = self.terminal_tab.process
        if not proc or proc.state() != QProcess.Running:
            self.append_manager_log("No shell running!", "red")
            return

        proc.write(b'call "C:/Users/iceke/anaconda3/condabin/activate.bat" base\n')
        proc.write(b"cd _internal\n")
        proc.write(b'python "resource_notifier.py"\n')
        self.append_manager_log("Dispatched resource notifier to terminal", "white")

    """"""""""
        def start_voice_activation(self):
            base = self.terminal_tab.config.get("script_directory", "scripts")
            base = os.path.abspath(base)
            internal = os.path.join(base, "_internal")
            script = os.path.abspath(os.path.join(internal, "voice_activation.py"))
            self.append_manager_log("Dispatched voice activation to terminal", "white")
            self.terminal_tab.run_script_by_path(script)
            
        def start_notifier(self):
            base = self.terminal_tab.config.get("script_directory", "scripts")
            base = os.path.abspath(base)
            internal = os.path.join(base, "_internal")
            script = os.path.abspath(os.path.join(internal, "resource_notifier.py"))
            self.terminal_tab.run_script_by_path(script)
            self.append_manager_log("Dispatched resource notifier to terminal", "white")
    """""""""

    def stop_notifier(self):
            if self.notifier_process and self.notifier_process.state() != QProcess.NotRunning:
                self.notifier_process.terminate()
                self.notifier_process = None
                self.append_manager_log("Stopped resource notifier", "white")
                QMessageBox.information(self, "Notifier", "Stopped.")
            else:
                self.append_manager_log("Notifier not running", "white")

    def handle_notifier_stdout(self):
        if self.notifier_process:
            data = self.notifier_process.readAllStandardOutput()
            text = bytes(data).decode(errors="replace")
            for line in text.splitlines():
                self.append_manager_log(f"[Notifier][stdout] {line}", "white")

    def handle_notifier_stderr(self):
        if self.notifier_process:
            data = self.notifier_process.readAllStandardError()
            text = bytes(data).decode(errors="replace")
            for line in text.splitlines():
                self.append_manager_log(f"[Notifier][stderr] {line}", "red")

    def update_screen_list(self):
        self.screen_selector.clear()
        for i, screen in enumerate(QGuiApplication.screens()):
            self.screen_selector.addItem(f"Screen {i+1}")

    def set_default_screen(self):
        idx = self.screen_selector.currentIndex()
        try:
            with open("settings.json", "w") as f:
                json.dump({'default_screen_index': idx}, f)
            self.append_manager_log(f"Set default screen to {idx+1}")
            QMessageBox.information(self, "Default Screen", f"Set to Screen {idx+1}")
        except Exception as e:
            self.append_manager_log(f"Error writing default screen: {e}")
            QMessageBox.warning(self, "Error", str(e))

    def refresh_raphael_logs(self, log_user_action=False):
        path = os.path.abspath("Delta_log_cache.txt")
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                self.raphael_log_view.setPlainText(f.read())
            if log_user_action:
                self.append_manager_log("Refreshed Delta logs")
        else:
            self.raphael_log_view.setPlainText("<No Delta logs found>")
            if log_user_action:
                self.append_manager_log("Delta logs not found")

    def refresh_notifier_logs(self, log_user_action=False):
        path = os.path.abspath("notifier_log.txt")
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                self.notifier_log_view.setPlainText(f.read())
            if log_user_action:
                self.append_manager_log("Refreshed notifier logs")
        else:
            self.notifier_log_view.setPlainText("<No notifier logs found>")
            if log_user_action:
                self.append_manager_log("Notifier logs not found")

    def load_commands_json(self):
        self.commands_form.setParent(None)
        self.commands_form = QFormLayout()
        self.command_inputs = {}
        try:
            with open("commands.json", "r", encoding="utf-8") as f:
                commands = json.load(f)
        except Exception:
            commands = {}
        for key, value in commands.items():
            key_input = QLineEdit(key)
            value_input = QLineEdit(value)
            self.commands_form.addRow(key_input, value_input)
            self.command_inputs[key_input] = value_input

    def add_command_row(self):
        key = self.new_command_key.text().strip()
        value = self.new_command_value.text().strip()
        if key and value:
            key_input = QLineEdit(key)
            value_input = QLineEdit(value)
            self.commands_form.addRow(key_input, value_input)
            self.command_inputs[key_input] = value_input
            self.new_command_key.clear()
            self.new_command_value.clear()
    def save_commands_json(self):
        commands = {}
        for key_input, value_input in self.command_inputs.items():
            key = key_input.text().strip()
            value = value_input.text().strip()
            if key:
                commands[key] = value
        try:
            with open("commands.json", "w", encoding="utf-8") as f:
                json.dump(commands, f, indent=2)
            self.append_manager_log("Saved commands.json")
            QMessageBox.information(self, "Commands", "Commands saved successfully.")
        except Exception as e:
            self.append_manager_log(f"Error saving commands.json: {e}")
            QMessageBox.warning(self, "Error", str(e))

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.showNormal()
            self.activateWindow()

    def closeEvent(self, event):
        """Override close to minimize to tray instead of quitting."""
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "Cortana Manager",
            "Running in background. Double-click tray icon to restore.",
            QSystemTrayIcon.Information,
            2000
        )

    # --- Terminal Tab Logic ---

    def handle_cmd_stdout(self):
        if self.cmd_process:
            data = self.cmd_process.readAllStandardOutput()
            text = bytes(data).decode(errors="replace")
            self.terminal_tab.terminal_output.appendPlainText(text.rstrip())

    def handle_cmd_stderr(self):
        if self.cmd_process:
            data = self.cmd_process.readAllStandardError()
            text = bytes(data).decode(errors="replace")
            for line in text.splitlines():
                self.terminal_tab.terminal_output.appendPlainText(f"[stderr] {line}")

    def run_terminal_command(self):
        command = self.terminal_input.text().strip()
        if not command:
            return

        if command.startswith("!M"):
            # Manager command
            mgr_cmd = command[2:].strip()
            self.terminal_tab.terminal_output.appendPlainText(f">>> !M {mgr_cmd}")
            self.terminal_input.clear()
            self.handle_manager_command(mgr_cmd)
            return

        # Normal shell command
        self.terminal_tab.terminal_output.appendPlainText(f">>> {command}")
        self.terminal_input.clear()
        if self.cmd_process and self.cmd_process.state() == QProcess.Running:
            try:
                self.cmd_process.write((command + "\n").encode("utf-8"))
            except Exception as e:
                self.terminal_tab.terminal_output.appendPlainText(f"[Error writing to cmd.exe: {e}]")
        else:
            self.terminal_tab.terminal_output.appendPlainText("[cmd.exe process not running. Restarting shell...]")
            self.cmd_process.start()

    def handle_manager_command(self, command):
        cmd = command.lower()
        if cmd == "help":
            self.terminal_tab.terminal_output.appendPlainText(
                "Manager commands:\n"
                "  help   - Show this help message\n"
                "  status - Show system status\n"
                "  reload - Reload configuration\n"
            )
        elif cmd == "status":
            status_lines = []
            status_lines.append(f"Voice process: {'Running' if self.voice_process and self.voice_process.state() == QProcess.Running else 'Stopped'}")
            status_lines.append(f"Notifier process: {'Running' if self.notifier_process and self.notifier_process.state() == QProcess.Running else 'Stopped'}")
            status_lines.append(f"Terminal (cmd.exe): {'Running' if self.cmd_process and self.cmd_process.state() == QProcess.Running else 'Stopped'}")
            self.terminal_tab.terminal_output.appendPlainText("System status:\n" + "\n".join(status_lines))
        elif cmd == "reload":
            self.load_commands_json()
            self.load_default_commands_on_startup()
            self.terminal_tab.terminal_output.appendPlainText("Configuration reloaded.")
        else:
            self.terminal_tab.terminal_output.appendPlainText(f"Unknown manager command: {command}")

    def load_default_commands_on_startup(self):
        config_path = os.path.join("config", "terminal_config.json")
        if not os.path.exists(config_path):
            self.terminal_tab.terminal_output.appendPlainText("[No terminal_config.json found. Skipping default commands.]")
            return
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            commands = config.get("default_commands", [])
            if not commands:
                self.terminal_tab.terminal_output.appendPlainText("[No default_commands in terminal_config.json]")
                return
            self.run_default_commands(commands)
        except Exception as e:
            self.terminal_tab.terminal_output.appendPlainText(f"[Error loading terminal_config.json: {e}]")

    def run_default_commands(self, commands):
        self._default_cmd_queue = list(commands)
        self._run_next_default_command()

    def _run_next_default_command(self):
        if not hasattr(self, "_default_cmd_queue") or not self._default_cmd_queue:
            return
        cmd_entry = self._default_cmd_queue.pop(0)
        # Support both string and dict for backward compatibility
        if isinstance(cmd_entry, str):
            interpreter = "cmd"
            command = cmd_entry
        else:
            interpreter = cmd_entry.get("interpreter", "cmd").lower()
            command = cmd_entry.get("command", "")

        self.terminal_tab.terminal_output.appendPlainText(f">>> [{interpreter}] {command}")
        self._default_process = QProcess(self)
        self._default_process.setProcessChannelMode(QProcess.MergedChannels)
        # Build args based on interpreter
        if interpreter == "python":
            args = [self.terminal_tab.config.get("interpreter", sys.executable), command]
        elif interpreter == "node":
            args = ["node", command]
        elif interpreter == "powershell":
            args = ["powershell.exe", "-Command", command]
        elif interpreter == "bash":
            args = ["bash", "-c", command]
        elif interpreter == "cmd":
            args = ["cmd.exe", "/c", command]
        else:
            # Fallback: try to run as a shell command
            args = [interpreter, command]

        self._default_process.setProgram(args[0])
        self._default_process.setArguments(args[1:])
        self._default_process.readyReadStandardOutput.connect(self._handle_default_stdout)
        self._default_process.readyReadStandardError.connect(self._handle_default_stderr)
        self._default_process.finished.connect(self._handle_default_finished)
        self._default_process.start()

    def _handle_default_stdout(self):
        if hasattr(self, "_default_process") and self._default_process:
            data = self._default_process.readAllStandardOutput()
            text = bytes(data).decode(errors="replace")
            self.terminal_tab.terminal_output.appendPlainText(text.rstrip())

    def _handle_default_stderr(self):
        if hasattr(self, "_default_process") and self._default_process:
            data = self._default_process.readAllStandardError()
            text = bytes(data).decode(errors="replace")
            for line in text.splitlines():
                self.terminal_tab.terminal_output.appendPlainText(f"[stderr] {line}")

    def _handle_default_finished(self):
        self.terminal_tab.terminal_output.appendPlainText("--- Process finished ---")
        self._run_next_default_command()
        
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    manager = CortanaManager()
    screen = QGuiApplication.primaryScreen().availableGeometry()
    window_size = manager.sizeHint()
    x = screen.left() + 10  # 10px padding from left
    y = screen.bottom() - window_size.height() - 170 # 170px padding from bottom
    manager.move(x, y)
    manager.show()
    sys.exit(app.exec_())