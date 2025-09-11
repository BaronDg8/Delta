import datetime
from pydoc import text
import psutil
import socket
import speech_recognition as sr
import pyttsx3
import threading
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor
import numpy as np
import random
import json

import os, sys, subprocess, shutil, glob, re
from difflib import get_close_matches

from mouth import ReactiveWireframe2DCircle
from mic_system import MicSystem
import queue
import array

from tools.opencode_module import OpenCodeModule

class TeeStream:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()
    def flush(self):
        for s in self.streams:
            s.flush()

# log_file = open("Delta_log_cache.txt", "a", encoding="utf-8")
# sys.stdout = TeeStream(sys.__stdout__, log_file)
    

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

class DeltaCommands:
    """
    Encapsulates all command‐handling logic:
        - process_command (built‐in commands like list/kill, toggles, etc.)
        - chat_with_ai (fallback to the LLM)
        - send_notifier_command (CPU/GPU/RAM toggles)
    """

        # import the plugin/tool then put the tools def in tools then put a send prompt to say that it's active
    
    tools = []

    def __init__(self):
        self.custom_commands = {}
        try:
            # Build the path to commands.json next to this script
            base_dir = os.path.dirname(os.path.abspath(__file__))
            commands_path = os.path.join(base_dir, "config", "commands.json")

            with open(commands_path, "r", encoding="utf-8") as f:
                self.custom_commands = json.load(f)
        except Exception as e:
            print(f"Error loading commands.json: {e}")
        self.app_launcher = AppLauncher()

    from typing import Optional

    def process_command(self, user_input: str) -> Optional[str]:
        """
        Take a lowercase, stripped user_input string and return:
            - a text response if it matches a built‐in command
            - None if no built‐in command matched (so that the caller can fallback to AI)
        """
        cmd = user_input.lower().strip()
        
        # --- generic "open <app>" support ---
        m = re.match(r"^(?:open|launch|start)\s+(.+)$", cmd, flags=re.I)
        if m:
            app_query = m.group(1).strip()
            ok, msg = self.app_launcher.launch(app_query)
            return msg  # Delta will speak this
        
        # Checks custom commands.json first
        if cmd in self.custom_commands:
            action = self.custom_commands[cmd]
            # Always run in a new PowerShell instance with working directory set
            powershell_cmd = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"Set-Location -Path 'C:\\Users\\iceke'; {action}"
            ]
            try:
                subprocess.Popen(
                    powershell_cmd,
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return f"Okay, running {cmd}"
            except Exception as e:
                return f"Sorry, I couldn’t run {cmd}: {e}"

        if cmd == "list processes":
            processes = []
            for proc in psutil.process_iter(attrs=["pid", "name", "status"]):
                try:
                    info = proc.info
                    processes.append(
                        f"PID: {info['pid']}, Name: {info.get('name','N/A')}, "
                        f"Status: {info.get('status','N/A')}"
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            response = "\n".join(processes[:30])
            if len(processes) > 30:
                response += "\n... (listing first 30 processes)"
            return response

        if cmd.startswith("kill process") or cmd.startswith("kill"):
            parts = cmd.split(maxsplit=2)
            if len(parts) < 3:
                return "Please specify a process ID or name to kill."
            target = parts[2]
            try:
                pid = int(target)
                proc = psutil.Process(pid)
                proc.terminate()
                return f"Process {pid} terminated."
            except ValueError:
                # treat as name substring
                matched = [
                    p for p in psutil.process_iter(attrs=["pid","name"])
                    if target in (p.info["name"] or "").lower()
                ]
                if not matched:
                    return f"No process found with name containing '{target}'."
                killed = []
                for p in matched:
                    try:
                        p.terminate()
                        killed.append(p.info["pid"])
                    except Exception:
                        pass
                return (
                    f"Killed processes with PIDs: {killed}"
                    if killed
                    else f"Could not kill any processes matching '{target}'."
                )

        # GPU/CPU/RAM toggles
        toggles = {
            "disable gpu monitoring": ("disable_gpu_monitoring", "GPU monitoring disabled."),
            "enable gpu monitoring":  ("enable_gpu_monitoring",  "GPU monitoring enabled."),
            "disable cpu monitoring": ("disable_cpu_monitoring", "CPU monitoring disabled."),
            "enable cpu monitoring":  ("enable_cpu_monitoring",  "CPU monitoring enabled."),
            "disable ram monitoring": ("disable_ram_monitoring", "RAM monitoring disabled."),
            "enable ram monitoring":  ("enable_ram_monitoring",  "RAM monitoring enabled."),
            "tell me my resource usage": ("get_resource_usage", "Current resource usage:"),
        }
        if cmd in toggles:
            (command_to_send, reply_message) = toggles[cmd]
            # Caller will use send_notifier_command to actually send it
            # Return a special prefix so GUI knows to call send_notifier
            reply_message = f"{reply_message}\n{self.get_resource_usage()}" if command_to_send == "get_resource_usage" else reply_message
            print (f"[NOTIFIER::{command_to_send}]")
            return f"{reply_message}"

        if cmd == "open task manager":
            return "opening task manager..."

        # Built‑in simple replies
        basics = {
            "hello": "Hello! How can I assist you today?",
            "how are you": "I'm just a virtual assistant, but I'm always ready to help!",
            "who are you": "I am Delta, your AI assistant.",
            "bye": "Goodbye! Have a great day!",
            "what time is it": f"The time is {datetime.datetime.now().strftime('%I:%M %p')}.",
            "what is today's date": f"Today's date is {datetime.datetime.now().strftime('%A, %B %d, %Y')}."
        }
        if cmd in basics:
            return basics[cmd]
        
        def command_scripts():
            """
            List of command scripts that can be executed.
            """
            return {
                "open notepad": "notepad.exe",
                "open powershell": "powershell.exe",
                "open command prompt": "cmd.exe",
                "open settings": "ms-settings:"
            }
            
        if cmd in command_scripts():
            return f"[LAUNCH::{command_scripts()[cmd]}]"

        # nothing matched
        return None

    def send_notifier_command(self, command_str: str, host='localhost', port=5050) -> str:
        """
        Send one of the CPU/GPU/RAM toggle commands (string like "disable_cpu_monitoring") 
        to the resource_notifier's socket. Returns whatever text the notifier replied.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((host, port))
                s.sendall(command_str.encode('utf-8'))
                resp = s.recv(1024).decode()
                return resp
        except Exception as e:
            return f"[ERROR] Could not send to notifier: {e}"

    def get_resource_usage(self) -> str:
        """
        Get current CPU, GPU, and RAM usage as a formatted string.
        """
        cpu_usage = psutil.cpu_percent(interval=1) if hasattr(psutil, "cpu_percent") else "N/A (CPU monitoring not available)"
        ram_usage = psutil.virtual_memory().percent if hasattr(psutil, "virtual_memory") else "N/A (RAM monitoring not available)"
        gpu_usage = psutil.gpu_percent(interval=1) if hasattr(psutil, "gpu_percent") else "N/A (GPU monitoring not available)"

        # Try to get GPU temperature if available
        if hasattr(psutil, "sensors_temperatures"):
            try:
                temps = psutil.sensors_temperatures()
                # Try common GPU keys
                for key in ("gpu", "amdgpu", "nvidia", "coretemp"):
                    if key in temps and temps[key]:
                        gpu_usage = f"{temps[key][0].current}°C"
                        break
            except Exception:
                pass

        return (
            f"CPU Usage: {cpu_usage}%\n"
            f"RAM Usage: {ram_usage}%\n"
            f"GPU Usage: {gpu_usage}"
        )

    def get_gpu_status(self) -> str:
        """
        Returns a string with GPU utilization, memory usage, and temperature using nvidia-smi.
        If not available, returns a message.
        """
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2
            )
            if result.returncode != 0:
                return "GPU status not available (nvidia-smi error)."
            # Example output: "12, 1024, 4096, 45"
            values = result.stdout.strip().split(',')
            if len(values) == 4:
                util, mem_used, mem_total, temp = [v.strip() for v in values]
                return (
                    f"GPU Utilization: {util}%\n"
                    f"GPU Memory: {mem_used} MiB / {mem_total} MiB\n"
                    f"GPU Temperature: {temp}°C"
                )
            else:
                return "GPU status not available (unexpected nvidia-smi output)."
        except FileNotFoundError:
            return "nvidia-smi not found. GPU status unavailable."
        except Exception as e:
            return f"Error retrieving GPU status: {e}"

class ChatAI:
    # Handles microphone input (speech-to-text) and text-to-speech using MicSystem.
    
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.engine     = pyttsx3.init()
        self.audio_queue= queue.Queue()
        self._listening = False
        self._mic_system= None

        self.speaking_flag = False

    def _audio_callback(self, chunk):
        self.audio_queue.put(chunk)

    def listen(self) -> str:
        """
        Records a phrase using MicSystem and returns the recognized text.
        """
        self.audio_queue.queue.clear()
        self._mic_system = MicSystem(callback=self._audio_callback)
        self._mic_system.start_stream()
        print("Listening (MicSystem)... Speak now.")
        try:
            frames = []
            silence_chunks = 0
            max_chunks = int(5 * self._mic_system.rate / self._mic_system.chunk)
            while len(frames) < max_chunks:
                try:
                    chunk = self.audio_queue.get(timeout=0.5)
                except queue.Empty:
                    silence_chunks += 1
                    if silence_chunks > 5:
                        break
                    continue
                frames.append(chunk)
            self._mic_system.stop_stream()
            audio_data = b''.join(frames)
            audio = sr.AudioData(audio_data, self._mic_system.rate, 2)
            try:
                return self.recognizer.recognize_google(audio)
            except sr.UnknownValueError:
                return ""  # Return empty string instead of error message
            except sr.RequestError:
                return "Speech recognition service unavailable."
        finally:
            if self._mic_system:
                self._mic_system.stop_stream()

    def speak(self, text: str):
        # tell the listener to pause
        self.speaking_flag = True

        self.engine.say(text)
        self.engine.runAndWait()

        # now resume listening
        self.speaking_flag = False
    
    def listen_continuous(self, callback):
        """
        Continuously listens in the background and calls the callback with recognized text.
        Uses simple silence detection to determine end of speech.
        """
        def rms(chunk):
            # Convert bytes to signed 16-bit integers
            samples = array.array('h', chunk)
            if not samples:
                return 0
            mean_square = sum(s * s for s in samples) / len(samples)
            return mean_square ** 0.5

        def stream_and_recognize():
            self._mic_system = MicSystem(callback=self._audio_callback)
            self._mic_system.start_stream()
            buffer = []
            silence_chunks = 0
            silence_threshold = 150   # Lower = less sensitive to silence
            silence_chunk_limit = 20  # Higher = waits longer before ending phrase

            while True:
                if self.speaking_flag:
                    # drop any partial buffer and wait a moment
                    buffer.clear()
                    silence_chunks = 0
                    continue
                
                try:
                    chunk = self.audio_queue.get(timeout=0.5)
                    buffer.append(chunk)
                    volume = rms(chunk)
                    if volume < silence_threshold:
                        silence_chunks += 1
                    else:
                        silence_chunks = 0
                    # If we've had enough silence, treat as end of phrase
                    if silence_chunks >= silence_chunk_limit and buffer:
                        audio_data = b''.join(buffer)
                        audio = sr.AudioData(audio_data, self._mic_system.rate, 2)
                        try:
                            text = self.recognizer.recognize_google(audio)
                            if text.strip():
                                callback(text)
                        except sr.UnknownValueError:
                            pass
                        except sr.RequestError:
                            callback("Speech recognition service unavailable.")
                        buffer.clear()
                        silence_chunks = 0
                except queue.Empty:
                    # If buffer has data but no new chunks, treat as end of phrase
                    if buffer:
                        audio_data = b''.join(buffer)
                        audio = sr.AudioData(audio_data, self._mic_system.rate, 2)
                        try:
                            text = self.recognizer.recognize_google(audio)
                            if text.strip():
                                callback(text)
                        except sr.UnknownValueError:
                            pass
                        except sr.RequestError:
                            callback("Speech recognition service unavailable.")
                        buffer.clear()
                        silence_chunks = 0

        t = threading.Thread(target=stream_and_recognize, daemon=True)
        t.start()
        def stop(wait_for_stop=True):
            if self._mic_system:
                self._mic_system.stop_stream()
        return stop



def start_voice_activation():
    script_path = os.path.join(os.path.dirname(__file__), "voice_activation.py")
    subprocess.Popen([sys.executable, script_path])

if __name__ == "__main__":
    ai = ChatAI()
    Delta = DeltaCommands()
    
    # Choose how to talk to OpenCode: "run" (simplest) or "serve" (HTTP API)
    oc = OpenCodeModule(mode="run")  # or: OpenCodeModule(mode="serve")
    
    # Start Qt application first
    app = QApplication(sys.argv)

    # --- Load settings.json for default_screen_index ---
    import json
    default_screen_index = 0  # Fallback if settings not found
    try:
        with open(os.path.join(os.path.dirname(__file__), "config", "settings.json"), "r") as f:
            settings = json.load(f)
        default_screen_index = settings.get("default_screen_index", 0)
    except Exception:
        pass

    # Move orb to the selected screen
    screens = app.screens()
    if 0 <= default_screen_index < len(screens):
        screen_geom = screens[default_screen_index].geometry()
    else:
        screen_geom = app.primaryScreen().geometry()

    # Calculate the max size that fits the screen
    max_orb_size = min(300, screen_geom.width(), screen_geom.height())
    # Ensure orb fits within available screen area
    max_orb_size = min(max_orb_size, screen_geom.width(), screen_geom.height())

    # --- Add the orb widget with correct diameter ---
    orb = ReactiveWireframe2DCircle(
        n_nodes=50,
        threshold=0.6,
        fps=30,
        diameter=max_orb_size,
        max_pulse=0.5,
        damping=0.2
    )
    orb.setMinimumSize(max_orb_size, max_orb_size)
    orb.setMaximumSize(max_orb_size, max_orb_size)
    orb.resize(max_orb_size, max_orb_size)
    orb.show()

    x = (screen_geom.width() - max_orb_size) // 2 + screen_geom.x()
    y = screen_geom.height() - max_orb_size - 40 + screen_geom.y()
    orb.move(x, y)

    # Start speech recognition in a background thread
    stop_listening_holder = [None]  # Use a list to hold the reference

    def handle_text(text):
        print(f"You said: {text}")
        
        lower = text.strip().lower()
        if lower.startswith("ask open code") or lower.startswith("open code:"):
            # extract the prompt after the prefix
            if lower.startswith("ask open code"):
                prompt = text.strip()[len("ask open code"):]
            else:
                prompt = text.split(":", 1)[1].strip()
            try:
                # If you picked serve mode above:
                # oc.ensure_server()
                # reply = oc.ask_serve(prompt)
                # Otherwise (run mode, default):
                reply = oc.ask_run(prompt)
            except Exception as e:
                reply = f"OpenCode error: {e}"
                print(reply)

            # speak it with your existing orb/tts pattern
            orb.setLevel(0.3)
            ai.speak(reply)
            orb.setLevel(0.0)

            # your existing “finish & go back to voice_activation” flow
            if stop_listening_holder[0]:
                stop_listening_holder[0](wait_for_stop=False)
            orb.close()
            start_voice_activation()
            app.quit()
            return
        
        
        if text.strip().lower() == "exit":
            print("Exiting...")
            if stop_listening_holder[0]:
                stop_listening_holder[0](wait_for_stop=False)
            orb.close()
            start_voice_activation()  # <-- Add this line
            app.quit()
            return
        response = Delta.process_command(text)
        if response is None:
            response = f"Sorry, I didn't understand '{text}'. Can you please rephrase?"
        print(f"Delta: {response}")        
        
                
        # --- Pulse orb when speaking ---
        orb.setLevel(0.3)
        ai.speak(response)
        orb.setLevel(0.0)

        # After handling any command, exit and start voice activation
        if stop_listening_holder[0]:
            stop_listening_holder[0](wait_for_stop=False)
        orb.close()
        start_voice_activation()
        app.quit()
        return

    def start_listening():
        stop_listening_holder[0] = ai.listen_continuous(handle_text)

    threading.Thread(target=start_listening, daemon=True).start()

    sys.exit(app.exec_())
    start_voice_activation()