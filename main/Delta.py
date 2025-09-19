from mouth import ReactiveWireframe2DCircle
from PyQt5.QtWidgets import QApplication
from mic_system import MicSystem
import speech_recognition as sr
import os, sys, subprocess
import pyttsx3
import threading
import json
import queue
import array

from langchain_core.messages import HumanMessage
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import Tool

# tools
from tools.opencode_module import OpenCodeModule
from tools.AppLauncher import AppLauncher
from tools.kill_process import kill_process_tool

import logging
logging.basicConfig(level=logging.DEBUG)  # logging

MIC_INDEX = None
recognizer = sr.Recognizer()
mic = sr.Microphone(device_index=MIC_INDEX)


from langchain_ollama import ChatOllama, OllamaLLM

llm = ChatOllama(model="qwen3:1.7b", reasoning=False)

# instantiate your tool classes (if they expose a callable method like .run or .call)

tools = [AppLauncher, kill_process_tool, OpenCodeModule]

prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are Delta, an intelligent, conversational AI assistant. Your goal is to be helpful, friendly, and informative. You can respond in natural, human-like language and use tools when needed to answer questions more accurately. Always explain your reasoning simply when appropriate, and keep your responses conversational and concise.",
        ),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
)

agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)


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

    # Synchronous single-shot input
    def get_input(self) -> str:
        """
        Records a phrase using MicSystem and returns the recognized text.
        This method only returns the user's raw input (no side effects like speaking).
        """
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

    # Synchronous output (text-only or text+speech)
    def deliver_output(self, text: str, speak: bool = True):
        """
        Outputs text to console and optionally speaks it.
        This method only handles assistant output.
        """
        print(f"Delta: {text}")
        if speak:
            self.speaking_flag = True
            self.engine.say(text)
            self.engine.runAndWait()
            self.speaking_flag = False

    # Continuous listening with separated user input callback
    def start_continuous_listening(self, user_callback):
        """
        Continuously listens in the background and calls user_callback(user_text).
        The callback receives only the user's raw text input. Assistant output should be handled separately.
        Returns a stop() function.
        """
        def rms(chunk):
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
            silence_threshold = 150
            silence_chunk_limit = 20

            while True:
                if self.speaking_flag:
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
                    if silence_chunks >= silence_chunk_limit and buffer:
                        audio_data = b''.join(buffer)
                        audio = sr.AudioData(audio_data, self._mic_system.rate, 2)
                        try:
                            text = self.recognizer.recognize_google(audio)
                            if text.strip():
                                user_callback(text)
                        except sr.UnknownValueError:
                            pass
                        except sr.RequestError:
                            user_callback("Speech recognition service unavailable.")
                        buffer.clear()
                        silence_chunks = 0
                except queue.Empty:
                    if buffer:
                        audio_data = b''.join(buffer)
                        audio = sr.AudioData(audio_data, self._mic_system.rate, 2)
                        try:
                            text = self.recognizer.recognize_google(audio)
                            if text.strip():
                                user_callback(text)
                        except sr.UnknownValueError:
                            pass
                        except sr.RequestError:
                            user_callback("Speech recognition service unavailable.")
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
    def setup_orb(app):
        # Load default screen index from config (safe fallback)
        default_screen_index = 0
        try:
            with open(os.path.join(os.path.dirname(__file__), "config", "settings.json"), "r") as f:
                settings = json.load(f)
            default_screen_index = settings.get("default_screen_index", 0)
        except Exception:
            pass

        screens = app.screens()
        if 0 <= default_screen_index < len(screens):
            screen_geom = screens[default_screen_index].geometry()
        else:
            screen_geom = app.primaryScreen().geometry()

        max_orb_size = min(300, screen_geom.width(), screen_geom.height())
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
        x = (screen_geom.width() - max_orb_size) // 2 + screen_geom.x()
        y = screen_geom.height() - max_orb_size - 40 + screen_geom.y()
        orb.move(x, y)
        orb.show()
        return orb


    def main():
        ai = ChatAI()
        app = QApplication(sys.argv)
        orb = setup_orb(app)

        stop_listening_holder = [None]

        def handle_user_input(user_input):
            # separate user input from assistant output
            print(f"User: {user_input}")

            # run the agent in a background thread so recognition/UI aren't blocked
            def process_input(text):
                try:
                    # Use the agent executor to generate a reply instead of echoing
                    response = executor.run(text)
                except Exception as e:
                    response = "Sorry, I couldn't process that."
                    print("Agent error:", e)

                # show assistant output separately and speak
                try:
                    orb.setLevel(0.3)
                except Exception:
                    pass
                ai.deliver_output(response, speak=True)
                try:
                    orb.setLevel(0.0)
                except Exception:
                    pass

                # After handling any command, shut down UI and restart voice activation
                if stop_listening_holder[0]:
                    stop_listening_holder[0](wait_for_stop=False)
                try:
                    orb.close()
                except Exception:
                    pass
                start_voice_activation()
                app.quit()

            threading.Thread(target=process_input, args=(user_input,), daemon=True).start()

        def start_listening():
            stop_listening_holder[0] = ai.start_continuous_listening(handle_user_input)

        # Start continuous listening in a daemon thread
        threading.Thread(target=start_listening, daemon=True).start()

        try:
            sys.exit(app.exec_())
        finally:
            if stop_listening_holder[0]:
                stop_listening_holder[0](wait_for_stop=False)
            try:
                orb.close()
            except Exception:
                pass

    main()