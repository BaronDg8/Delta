import os
import sys
import time
import threading
import queue
import subprocess
import numpy as np
import speech_recognition as sr

from main.parts.mic_system import MicSystem

WAKE_WORDS = ("cortana",)           # add more aliases if you want
PHRASE_TIME_LIMIT = 3.0             # seconds max per phrase chunk
MIN_PHRASE_SECONDS = 0.35           # discard ultra-short blips
CALIBRATION_SECONDS = 0.6           # ambient noise sample
SILENCE_CHUNKS_END = 12             # how many silent chunks to decide phrase ended (≈ 12 * chunk_ms)
ENERGY_BOOST = 3.0                  # dynamic threshold multiplier above noise floor

# If your MicSystem exposes these; adjust if different:
TARGET_RATE = 16000                 # sample rate (Hz)
CHUNK_MS = 30                       # 30ms per chunk
SAMPLE_WIDTH = 2                    # 16-bit PCM

def rms_int16(samples: np.ndarray) -> float:
    """Root-mean-square energy for int16 samples."""
    # small epsilon to avoid div by zero
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float32)))) + 1e-9)

def heard_wake_word(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in WAKE_WORDS)

def start_delta():
    """Launch Delta.py using the same interpreter and a clean working dir."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    delta_py = os.path.join(base_dir, "Delta.py")
    # Use the same python/conda that launched this script
    subprocess.Popen([sys.executable, delta_py], cwd=base_dir)

def main():
    # 1) Build recognizer once
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = False  # we handle noise threshold ourselves

    # 2) Prepare queue and callback for streaming chunks
    audio_q: queue.Queue[bytes] = queue.Queue(maxsize=64)
    stop_flag = threading.Event()

    def mic_callback(chunk: bytes):
        try:
            audio_q.put(chunk, timeout=0.2)
        except queue.Full:
            pass

    # 3) Start mic stream with callback
    mic = MicSystem(rate=TARGET_RATE, chunk_size=int(TARGET_RATE * (CHUNK_MS / 1000.0)), callback=mic_callback)
    mic.start_stream()

    # 4) Calibrate noise floor for dynamic energy threshold
    print("Calibrating noise floor…")
    calib_bytes = bytearray()
    calib_target_bytes = int(TARGET_RATE * CALIBRATION_SECONDS) * SAMPLE_WIDTH
    while len(calib_bytes) < calib_target_bytes:
        try:
            chunk = audio_q.get(timeout=1.0)
        except queue.Empty:
            continue
        if not chunk:
            time.sleep(0.005)
            continue
        calib_bytes.extend(chunk)

    calib_np = np.frombuffer(bytes(calib_bytes), dtype=np.int16)
    noise_floor = rms_int16(calib_np)
    vad_threshold = noise_floor * ENERGY_BOOST
    print(f"[calibration] noise_rms≈{noise_floor:.1f} → vad_threshold≈{vad_threshold:.1f}")

    started_delta = False
    chunk_bytes = int(TARGET_RATE * (CHUNK_MS / 1000.0)) * SAMPLE_WIDTH

    def phrase_loop():
        nonlocal started_delta
        buf = bytearray()
        voiced = False
        silence_count = 0
        phrase_start_time = None

        while not stop_flag.is_set():
            try:
                chunk = audio_q.get(timeout=0.4)
            except queue.Empty:
                continue

            buf.extend(chunk)

            # VAD: compute energy on this chunk
            if len(chunk) >= 2:
                np_chunk = np.frombuffer(chunk, dtype=np.int16)
                energy = rms_int16(np_chunk)
            else:
                energy = 0.0

            is_voice = energy >= vad_threshold

            if is_voice and not voiced:
                # voice started
                voiced = True
                silence_count = 0
                phrase_start_time = time.time()

            if voiced:
                # bound phrase length in case of continuous talk/noise
                if phrase_start_time and (time.time() - phrase_start_time > PHRASE_TIME_LIMIT):
                    is_voice = False  # force end

            if not is_voice and voiced:
                # transition to silence; count chunks until we decide phrase end
                silence_count += 1
                if silence_count >= SILENCE_CHUNKS_END:
                    # finalize phrase
                    phrase_bytes = bytes(buf)
                    # reset state for next phrase
                    buf.clear()
                    voiced = False
                    silence_count = 0
                    phrase_len_sec = len(phrase_bytes) / (TARGET_RATE * SAMPLE_WIDTH)
                    if phrase_len_sec < MIN_PHRASE_SECONDS:
                        continue  # ignore ultra short blips

                    # Turn the raw PCM into sr.AudioData and recognize
                    try:
                        audio_data = sr.AudioData(phrase_bytes, TARGET_RATE, SAMPLE_WIDTH)
                        text = recognizer.recognize_google(audio_data)
                    except sr.UnknownValueError:
                        text = ""
                    except sr.RequestError as e:
                        print(f"[STT error] {e}")
                        text = ""

                    if not text:
                        continue

                    # print(f"Heard ({text})")

                    if (not started_delta) and heard_wake_word(text):
                        print("Wake word detected — starting Delta")
                        started_delta = True
                        start_delta()
                        # Optional: if you want to stop once started:
                        # stop_flag.set()
                        # return

    # Run the phrase loop in the foreground (blocks main thread)
    try:
        phrase_loop()
    except KeyboardInterrupt:
        pass
    finally:
        stop_flag.set()
        time.sleep(0.1)
        try:
            mic.stop_stream()
        except Exception:
            pass

if __name__ == "__main__":
    main()
