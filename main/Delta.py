import os
import sys
import json
import time
import base64
import queue
import array
import subprocess
import threading
import audioop 
import collections
import speech_recognition as sr

from typing import Optional

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer, QObject, pyqtSignal, QThread

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
from tools.docker_mcp import docker_mcp

from langchain_ollama import ChatOllama, OllamaLLM

MIC_INDEX = None

TRIGGER_WORD = "Delta"          # or whatever you want to say
EXIT_WORDS = ("thank you", "that’s all", "stop listening")  # phrases to exit UI/agent

# --- VAD / streaming mic config ---
CHUNK_MS = 30                 # ~20–30 ms is typical
SAMPLE_RATE = 16000           # match your mic/STT expectation
SAMPLE_WIDTH = 2              # 16-bit PCM
ENERGY_BOOST = 2.0            # raise if noisy room triggers false speech
CALIBRATION_SECONDS = 1.0
SILENCE_CHUNKS_END = 20       # ~0.6 sec at 30 ms chunks
MIN_PHRASE_SECONDS = 0.5
PHRASE_TIME_LIMIT = 15.0      # cut very long monologues

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

tools = [AppLauncher, kill_process_tool, OpenCodeModule, docker_mcp]

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

    def get_input(self) -> str:
        return ""

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
    global _orb_bridge
    bridge = _orb_bridge
    if not bridge:
        return
    try:
        if bridge is None:
            _orb_bridge = None
            return
    except Exception:
        return
    bridge.setLevelRequested.emit(level)

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

def _calibrate_noise_floor(recognizer: sr.Recognizer, mic: sr.Microphone) -> float:
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=CALIBRATION_SECONDS)
        # Grab a short buffer to estimate RMS
        frames_to_read = int(SAMPLE_RATE * CALIBRATION_SECONDS) * SAMPLE_WIDTH
        try:
            raw = source.stream.read(frames_to_read)
        except OSError:
            # If overflow occurs, use zeros so VAD still starts with conservative floor
            raw = b"\x00" * frames_to_read
        rms = audioop.rms(raw, SAMPLE_WIDTH)
        return max(100, rms)  # avoid zero floor


def start_vad_listener(on_phrase, stop_event: threading.Event, mic_index: int = None):
    """Continuously read the mic stream and emit whole phrases via on_phrase(text)."""
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.8
    recognizer.phrase_threshold = 0.2
    recognizer.non_speaking_duration = 0.5

    mic = sr.Microphone(device_index=mic_index, sample_rate=SAMPLE_RATE)
    noise_floor = _calibrate_noise_floor(recognizer, mic)
    vad_threshold = noise_floor * ENERGY_BOOST

    chunk_frames = int(SAMPLE_RATE * (CHUNK_MS / 1000.0))
    max_frames = int(SAMPLE_RATE * PHRASE_TIME_LIMIT)
    min_frames = int(SAMPLE_RATE * MIN_PHRASE_SECONDS)

    with mic as source:
        stream = source.stream  # PyAudio stream (stays OPEN)
        buffer = bytearray()
        voiced = False
        silence_chunks = 0

        while not stop_event.is_set():
            try:
                chunk = stream.read(chunk_frames * SAMPLE_WIDTH)
            except OSError:
                continue
            if not chunk:
                continue

            # Keep the stream alive—no open/close toggling
            buffer.extend(chunk)
            rms = audioop.rms(chunk, SAMPLE_WIDTH)

            if rms > vad_threshold:
                voiced = True
                silence_chunks = 0
            else:
                if voiced:
                    silence_chunks += 1

            phrase_ended = voiced and (
                silence_chunks >= SILENCE_CHUNKS_END
                or len(buffer) >= max_frames * SAMPLE_WIDTH
            )

            if phrase_ended:
                # Only accept phrases with some minimum length
                if len(buffer) >= min_frames * SAMPLE_WIDTH:
                    audio = sr.AudioData(bytes(buffer), SAMPLE_RATE, SAMPLE_WIDTH)
                    try:
                        # Use the same recognizer backend you already use elsewhere
                        text = recognizer.recognize_google(audio)
                        if text and text.strip():
                            on_phrase(text.strip())
                    except sr.UnknownValueError:
                        pass
                    except Exception as e:
                        print("STT error:", e)

                # Reset for next phrase (stream stays open)
                buffer.clear()
                voiced = False
                silence_chunks = 0


def start_ui_and_ai(on_exit):
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

    global _orb_bridge
    if orb is not None:
        _orb_bridge = OrbBridge(orb)

    session_stop = threading.Event()
    exit_signaled = False

    # One worker that processes phrases
    def handle_phrase(text: str):
        nonlocal exit_signaled
        print("User:", text)
        lower = text.lower()

        # exit words end the ACTIVE session
        if any(kw in lower for kw in EXIT_WORDS):
            try: speak_with_orb(ai, "")
            except Exception: pass
            # ensure no further audio processing runs
            session_stop.set()
            QTimer.singleShot(0, app.quit)
            exit_signaled = True
            on_exit()
            return

        def process():
            try:
                result = executor.invoke({"input": text})
                resp = (result.get("output") or result.get("result") or result.get("text")
                        or next((v for v in result.values() if isinstance(v, str) and v.strip()), str(result))
                        if isinstance(result, dict) else str(result))
            except Exception as e:
                print("Agent error:", e)
                resp = "Sorry, I couldn't process that."
            print("Delta:", resp)
            speak_with_orb(ai, resp)

        threading.Thread(target=process, daemon=True).start()

    threading.Thread(
        target=start_vad_listener,
        args=(handle_phrase, session_stop, MIC_INDEX),
        daemon=True
    ).start()

    app.exec_()
    session_stop.set()


    # Clean up after Qt closes
    session_stop.set()
    if not exit_signaled:
        on_exit()
    try: ai.stop()
    except Exception: pass
    try:
        o = globals().get("orb_instance")
        if o is not None: o.close()
        globals()["orb_instance"] = None
        globals()["_orb_bridge"] = None
    except Exception: pass


if __name__ == "__main__":
    recognizer = sr.Recognizer()
    mic = sr.Microphone(device_index=MIC_INDEX)

    def listen_for_trigger(timeout=10):
        """
        Keep the microphone stream open and continuously monitor for the trigger word.
        We only close the stream when a trigger phrase is detected so the device does
        not churn on/off between timeouts.
        """
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            print("active")

            while True:
                try:
                    audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=3.5)
                except sr.WaitTimeoutError:
                    continue

                try:
                    spoken_text = recognizer.recognize_google(audio)
                except sr.UnknownValueError:
                    continue
                except Exception as err:
                    print("Wake STT error:", err)
                    continue

                if spoken_text and TRIGGER_WORD.lower() in spoken_text.lower():
                    return spoken_text

    while True:
        text = listen_for_trigger(timeout=10)
        if not text:
            continue

        print(f"Wake word detected: {text}")
        # Launch the UI/agent; return here when user says EXIT_WORDS or timeout hits
        done = threading.Event()
        start_ui_and_ai(on_exit=lambda: done.set())
        # Wait until UI closed (set by on_exit) before resuming wake mode
        done.wait()
