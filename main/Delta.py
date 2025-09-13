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

# tools
from tools.opencode_module import OpenCodeModule
from tools.AppLauncher import AppLauncher
from tools.kill_process import kill_process_tool

# TOOL: DeltaCommands (command handling, process management, resource toggles)
class DeltaCommands:
    """
    Encapsulates all command‐handling logic:
        - process_command (built‐in commands like list/kill, toggles, etc.)
        - chat_with_ai (fallback to the LLM)
    """
    
    # import the plugin/tool then put the tools def in tools then put a send prompt to say that it's active

    tools = [AppLauncher(), kill_process_tool]

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

        # Initialize tools
        self.app_launcher = AppLauncher()
        self.kill_process_tool = kill_process_tool

    from typing import Optional

    def process_command(self, user_input: str) -> Optional[str]:
        """
        Take a lowercase, stripped user_input string and return:
            - a text response if it matches a built‐in command
            - None if no built‐in command matched (so that the caller can fallback to AI)
        """
        cmd = user_input.lower().strip()
        
        # App launcher
        m = re.match(r"^(?:open|launch|start)\s+(.+)$", cmd, flags=re.I)
        if m:
            app_query = m.group(1).strip()
            ok, msg = self.app_launcher.launch(app_query)
            return msg  # Delta will speak this

        # kill process
        response = self.kill_process_tool(cmd)
        if response is not None:
            return response
        
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

        

        # nothing matched
        return None

# TOOL: ChatAI (speech-to-text and text-to-speech logic)
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
    # TOOL USAGE: ChatAI instance
    ai = ChatAI()
    # TOOL USAGE: DeltaCommands instance
    Delta = DeltaCommands()
    # TOOL USAGE: OpenCodeModule (code execution and interaction)
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