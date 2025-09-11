#!/usr/bin/env python3
"""
mic_system.py

A simple microphone system for:
    1) streaming audio chunks via a callback
    2) recording a fixed-duration WAV file

Usage:
    • Stream in real time:
        def process(chunk: bytes):
            # e.g. send to ASR, compute levels, etc.
            print(f"Chunk size: {len(chunk)}")

      mic = MicSystem(callback=process)
      mic.start_stream()
      input("Streaming... press Enter to stop\n")
      mic.stop_stream()

    • Record to file:
        MicSystem.record_to_file("output.wav", duration=5)
"""

import wave
import threading
import pyaudio
from typing import Callable

class MicSystem:
    def __init__(self,
                    rate: int = 16000,
                    channels: int = 1,
                    chunk_size: int = 1024,
                    callback: Callable[[bytes], None] = None):
        """
        :param rate:         sampling rate (Hz)
        :param channels:     mono=1, stereo=2
        :param chunk_size:   frames per buffer
        :param callback:     function(chunk_bytes), called on each captured chunk
        """
        self.rate = rate
        self.channels = channels
        self.chunk = chunk_size
        self.callback = callback
        self._stream = None
        self._pyaudio = pyaudio.PyAudio()
        self._running = False

    def _stream_loop(self):
        while self._running:
            data = self._stream.read(self.chunk, exception_on_overflow=False)
            if self.callback:
                self.callback(data)

    def start_stream(self):
        """Begin streaming audio and feeding it to the callback."""
        if self._stream is not None:
            return
        self._running = True
        self._stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk,
            stream_callback=lambda in_data, frame_count, time_info, status: (self.callback(in_data), pyaudio.paContinue) if self.callback else (None, pyaudio.paContinue)
        )
        self._stream.start_stream()
        print("[MicSystem] Stream started.")

    def stop_stream(self):
        """Stop streaming and clean up."""
        self._running = False
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        print("[MicSystem] Stream stopped.")

    @staticmethod
    def record_to_file(filename: str, duration: float,
                        rate: int =16000, channels: int =1, chunk_size: int =1024):
        """
        Record for `duration` seconds and save as a WAV file.
        """
        import wave
        import pyaudio
        pa = pyaudio.PyAudio()
        stream = pa.open(format=pyaudio.paInt16,
                            channels=channels,
                            rate=rate,
                            input=True,
                            frames_per_buffer=chunk_size)
        frames = []
        total_frames = int(rate / chunk_size * duration)
        print(f"[MicSystem] Recording {duration}s to {filename}…")

        for _ in range(total_frames):
            data = stream.read(chunk_size, exception_on_overflow=False)
            frames.append(data)

        stream.stop_stream()
        stream.close()
        pa.terminate()

        wf = wave.open(filename, 'wb')
        wf.setnchannels(channels)
        wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
        wf.setframerate(rate)
        wf.writeframes(b''.join(frames))
        wf.close()
        print(f"[MicSystem] Saved recording to {filename}")

if __name__ == "__main__":
    import sys

    def demo_callback(chunk):
        # Example: print RMS volume
        import math
        # interpret bytes as signed 16-bit little endian
        samples = memoryview(chunk).cast('h')
        rms = math.sqrt(sum(s*s for s in samples) / len(samples))
        print(f"RMS={rms:.1f}", end='\r')

    if len(sys.argv) > 1 and sys.argv[1] == "--record":
        # python mic_system.py --record output.wav 5
        out = sys.argv[2] if len(sys.argv) > 2 else "output.wav"
        dur = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
        MicSystem.record_to_file(out, dur)
    else:
        # demo streaming mode
        mic = MicSystem(callback=demo_callback)
        mic.start_stream()
        try:
            input("Streaming... press Enter to stop\n")
        finally:
            mic.stop_stream()
