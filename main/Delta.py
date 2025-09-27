import os
import sys
import json
import time
import base64
import queue
import array
import subprocess
import threading

from typing import Optional

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer, QObject, pyqtSignal, QThread

import speech_recognition as sr
import pyttsx3

# local UI / audio tools
from parts.mouth import ReactiveWireframe2DCircle
from parts.mic_system import MicSystem

# langchain / tools
from langchain_core.messages import HumanMessage
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import Tool

from tools.opencode_module import OpenCodeModule
from tools.AppLauncher import AppLauncher
from tools.kill_process import kill_process_tool

from langchain_ollama import ChatOllama, OllamaLLM

MIC_INDEX = None

# Helper: compact subprocess TTS to avoid blocking Qt
def _run_tts_subprocess(text: str):
    try:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        script = (
            "import base64,pyttsx3,sys\n"
            "t=base64.b64decode(sys.argv[1]).decode('utf-8')\n"
            "e=pyttsx3.init()\n"
            "try:\n"
            "    e.setProperty('rate',180)\n"
            "    e.setProperty('volume',1.0)\n"
            "except Exception:\n"
            "    pass\n"
            "e.say(t)\n"
            "e.runAndWait()\n"
        )
        subprocess.run([sys.executable, "-c", script, encoded], check=False)
    except Exception as e:
        print("TTS failed (subprocess):", e)

# safe orb level setter from non-Qt threads
def _safe_set_orb_level(level: float):
    try:
        orb = globals().get("orb_instance")
        if orb is not None and hasattr(orb, "setLevel"):
            orb.setLevel(level)
    except Exception:
        pass

# LLM & agent setup (kept compact)
llm = ChatOllama(model="qwen3:1.7b", reasoning=False)

tools = [AppLauncher, kill_process_tool, OpenCodeModule]

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are Delta, an intelligent, conversational AI assistant. Be helpful, friendly, concise."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# ChatAI: compact, readable, and de-duplicated speech/recognition handling
class ChatAI:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.audio_queue = queue.Queue()
        self._mic_system: Optional[MicSystem] = None
        self.speaking_flag = False

    def stop(self):
        # kept for API compatibility
        try:
            if self._mic_system:
                self._mic_system.stop_stream()
        except Exception:
            pass

    # wrapper to run TTS in a background thread while updating orb
    def _speak_in_thread(self, text: str):
        def runner():
            try:
                self.speaking_flag = True
                QTimer.singleShot(0, lambda: _safe_set_orb_level(0.3))
                _run_tts_subprocess(text)
                QTimer.singleShot(0, lambda: _safe_set_orb_level(0.0))
            finally:
                self.speaking_flag = False
        threading.Thread(target=runner, daemon=True).start()
        
    def speak(self, text: str):
        """Public TTS entrypoint used by speak_with_orb()."""
        self._speak_in_thread(text)

    def _audio_callback(self, chunk):
        self.audio_queue.put(chunk)

    # single helper to convert raw frames into text (returns "" on unknown)
    def _recognize_audio(self, frames: bytes, rate: int):
        audio = sr.AudioData(frames, rate, 2)
        try:
            return self.recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            return ""
        except sr.RequestError:
            return "Speech recognition service unavailable."

    # blocking single-shot input
    def get_input(self) -> str:
        self.audio_queue.queue.clear()
        self._mic_system = MicSystem(callback=self._audio_callback)
        self._mic_system.start_stream()
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
            audio_data = b"".join(frames)
            return self._recognize_audio(audio_data, self._mic_system.rate)
        finally:
            if self._mic_system:
                self._mic_system.stop_stream()

    # output routine
    def deliver_output(self, text: str, speak: bool = True):
        print(f"Delta: {text}")
        if speak:
            try:
                # Pulse orb immediately on the Qt thread (match belt.py behavior)
                try:
                    QTimer.singleShot(0, lambda: _safe_set_orb_level(0.3))
                except Exception:
                    pass

                self._speak_in_thread(text)
            except Exception:
                pass

    # continuous listening; user_callback receives raw text
    def start_continuous_listening(self, user_callback):
        def rms(chunk):
            samples = array.array('h', chunk)
            if not samples:
                return 0
            mean_square = sum(s * s for s in samples) / len(samples)
            return mean_square ** 0.5

        def loop():
            self._mic_system = MicSystem(callback=self._audio_callback)
            self._mic_system.start_stream()
            buffer = []
            silence_chunks = 0
            silence_threshold = 150
            silence_chunk_limit = 20

            while True:
                if self.speaking_flag:
                    buffer.clear()
                    silence_chunks = 0
                    time.sleep(0.05)
                    continue

                try:
                    chunk = self.audio_queue.get(timeout=0.5)
                    buffer.append(chunk)
                    if rms(chunk) < silence_threshold:
                        silence_chunks += 1
                    else:
                        silence_chunks = 0

                    if silence_chunks >= silence_chunk_limit and buffer:
                        audio_data = b"".join(buffer)
                        text = self._recognize_audio(audio_data, self._mic_system.rate)
                        if text.strip():
                            user_callback(text)
                        buffer.clear()
                        silence_chunks = 0

                except queue.Empty:
                    if buffer:
                        audio_data = b"".join(buffer)
                        text = self._recognize_audio(audio_data, self._mic_system.rate)
                        if text.strip():
                            user_callback(text)
                        buffer.clear()
                        silence_chunks = 0

        t = threading.Thread(target=loop, daemon=True)
        t.start()

# small helpers used in main
def load_settings() -> int:
    default = 0
    candidates = [
        os.path.join(os.path.dirname(__file__), "config", "settings.json"),
        os.path.join(os.path.dirname(__file__), "settings.json"),
        os.path.join(os.getcwd(), "settings.json"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                return cfg.get("default_screen_index", default)
            except Exception:
                pass
    return default

def create_orb(screen_geom):
    max_orb_size = min(300, screen_geom.width(), screen_geom.height())
    try:
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
        return orb
    except Exception:
        return None
    
class OrbBridge(QObject):
    """Lets worker threads request orb.setLevel(level) safely."""
    setLevelRequested = pyqtSignal(float)
    def __init__(self, orb):
        super().__init__()
        self.setLevelRequested.connect(orb.setLevel)

_orb_bridge = None  # will be set in main() after orb is created

def set_orb_level(level: float):
    """Safe from any thread."""
    if _orb_bridge:
        _orb_bridge.setLevelRequested.emit(level)


def start_voice_activation():
    script_path = os.path.join(os.path.dirname(__file__), "voice_activation.py")
    subprocess.Popen([sys.executable, script_path])

def speak_with_orb(ai: "ChatAI", text: str):
    """
    Raise orb, speak (async), wait until speaking finishes,
    then lower orb. Safe from any thread.
    """
    # raise
    set_orb_level(0.3)

    # start TTS (this returns immediately; TTS runs in a thread)
    ai.speak(text)

    # wait while TTS is active
    deadline = time.time() + 120  # 2 min safety cap
    while ai.speaking_flag and time.time() < deadline:
        QThread.msleep(50)  # do not busy-spike CPU

    # lower
    set_orb_level(0.0)


if __name__ == "__main__":
    def main():
        ai = ChatAI()
        app = QApplication(sys.argv)
        
        default_screen_index = load_settings()
        screens = app.screens()
        if 0 <= default_screen_index < len(screens):
            screen_geom = screens[default_screen_index].geometry()
        else:
            screen_geom = app.primaryScreen().geometry()

        orb = create_orb(screen_geom)
        globals()["orb_instance"] = orb
        
        # Create the bridge only after orb exists
        global _orb_bridge
        if orb is not None:
            _orb_bridge = OrbBridge(orb)

        stop_listening_holder = [None]

        def handle_user_input(user_input):
            print(f"User: {user_input}")
            def process_input(text):
                try:
                    result = executor.invoke({"input": text})
                    if isinstance(result, dict):
                        for k in ("output", "result", "text"):
                            if k in result and result[k]:
                                response = result[k]; break
                        else:
                            vals = [v for v in result.values() if isinstance(v, str) and v.strip()]
                            response = vals[0] if vals else str(result)
                    else:
                        response = str(result)
                except Exception as e:
                    print("Agent error:", e)
                    response = "Sorry, I couldn't process that."
                print(f"Delta: {response}")
                speak_with_orb(ai, response)

                
            threading.Thread(target=process_input, args=(user_input,), daemon=True).start()

        
        
        # start background continuous listening
        threading.Thread(target=lambda: ai.start_continuous_listening(handle_user_input), daemon=True).start()

        try:
            sys.exit(app.exec_())
        finally:
            try:
                ai.stop()
            except Exception:
                pass
            try:
                o = globals().get("orb_instance")
                if o is not None:
                    o.close()
            except Exception:
                pass

    main()