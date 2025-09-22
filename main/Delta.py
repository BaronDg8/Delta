import logging
import time
import pyttsx3
import speech_recognition as sr

# langchain / tools
from langchain_core.messages import HumanMessage
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import Tool

from tools.opencode_module import OpenCodeModule
from tools.AppLauncher import AppLauncher
from tools.kill_process import kill_process_tool


from mic_system import MicSystem

MIC_INDEX = None
TRIGGER_WORD = "delta"

logging.basicConfig(level=logging.DEBUG)  # change to DEBUG for more details


from langchain_ollama import ChatOllama, OllamaLLM

llm = ChatOllama(model="qwen3:1.7b", reasoning=False)

tools = [AppLauncher, kill_process_tool, OpenCodeModule]

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are Delta, an intelligent, conversational AI assistant. Be helpful, friendly, concise."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# TTS setup
def speak_text(text: str):
    try:
        engine = pyttsx3.init()
        for voice in engine.getProperty("voices"):
            if "jamie" in voice.name.lower():
                engine.setProperty("voice", voice.id)
                break
        engine.setProperty("rate", 180)
        engine.setProperty("volume", 1.0)
        engine.say(text)
        engine.runAndWait()
        time.sleep(0.3)
    except Exception as e:
        print(e)
