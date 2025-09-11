import psutil
import time
import json
import threading
import socket
from plyer import notification
import sys
import os
import atexit

log_cache = []

def cached_print(*args, sep=' ', end='\n', file=sys.stdout, flush=True, to_console=True):
    """
    Replacement for built-in print that saves all output into log_cache,
    writes to a file, and optionally forwards to the real print.
    """
    # Construct the message
    message = sep.join(str(arg) for arg in args) + end
    log_cache.append(message)

    # Write the message to the file
    log_file_path = os.path.abspath("notifier_log.txt".format(date=time.localtime()))
    try:
        with open(log_file_path, 'a', encoding='utf-8') as log_file:
            log_file.write(message)
    except Exception as e:
        print(f"[ERROR] Failed to write to log file: {e}", file=sys.stderr)

    # Optionally print to the console
    if to_console:
        print(message, end='', file=file, flush=flush)
            
def write_log_to_file(path="notifier_log.txt"):
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(log_cache)

# Optional GPU support
gpu_available = True
gpu_name = ("" if gpu_available else "Unknown GPU")
gpu_handle = None

try:
    from pynvml import (
        nvmlInit, nvmlDeviceGetHandleByIndex, nvmlDeviceGetUtilizationRates,
        nvmlShutdown, nvmlDeviceGetName
    )
    nvmlInit()
    gpu_handle = nvmlDeviceGetHandleByIndex(0)
    gpu_name = nvmlDeviceGetName(gpu_handle)
    if isinstance(gpu_name, bytes):
        gpu_name = gpu_name.decode("utf-8")
    gpu_available = True
    cached_print(f"[INFO] GPU monitoring enabled: {gpu_name}")
except Exception as e:
    cached_print(f"[WARNING] GPU monitoring not available: {e}")
    gpu_available = False

# Thresholds
CPU_THRESHOLD = 30          # % per core
GPU_THRESHOLD = 20          # %
RAM_THRESHOLD_MB = 20000    # in MB
CHECK_INTERVAL = 10         # seconds

cached_print(f"[INFO] CPU threshold: {CPU_THRESHOLD}% per core")
cached_print(f"[INFO] GPU threshold: {GPU_THRESHOLD}%")
cached_print(f"[INFO] RAM threshold: {RAM_THRESHOLD_MB} MB")
cached_print(f"[INFO] Check interval: {CHECK_INTERVAL} seconds")
cached_print(f"[INFO] GPU available: {gpu_available}")
cached_print(f"[INFO] GPU name: {gpu_name}")

# Monitoring flags
cpu_monitoring_enabled = True
gpu_monitoring_enabled = True
ram_monitoring_enabled = True

def load_ignored_programs():
    try:
        with open(os.path.join(os.path.dirname(__file__), "config", "ignore_config.json"), "r") as f:
            config = json.load(f)
        return [p.lower() for p in config.get("ignored_programs", [])]
    except:
        return []

cached_print(f"[INFO] Ignored programs: {load_ignored_programs()}")

def notify(title, msg):
    cached_print(msg)
    notification.notify(
        title=title,
        message=msg,
        timeout=5
    )

class ResourceMonitorThread(threading.Thread):
    cached_print("[INFO] Resource monitor thread started.")
    def __init__(self, target_program=None):
        super().__init__(daemon=True)
        self.target_program = target_program.lower() if target_program else None
        self.ignored_programs = load_ignored_programs()

    def set_target_program(self, target):
        self.target_program = target.lower()

    def run(self):
        global cpu_monitoring_enabled, gpu_monitoring_enabled, ram_monitoring_enabled
        num_cpus = psutil.cpu_count(logical=True) or 1

        while True:
            alerts = []

            if self.target_program:
                procs = [
                    proc for proc in psutil.process_iter(attrs=["pid", "name"])
                    if self.target_program in proc.info.get('name', '').lower()
                ]
            else:
                procs = [
                    proc for proc in psutil.process_iter(attrs=["pid", "name"])
                    if not any(ig in proc.info.get("name", "").lower() for ig in self.ignored_programs)
                ]

            # Prime CPU usage
            for proc in procs:
                try:
                    proc.cpu_percent(interval=None)
                except:
                    pass

            time.sleep(0.5)

            # CPU Monitoring
            if cpu_monitoring_enabled:
                for proc in procs:
                    try:
                        if proc.info["pid"] == 0:
                            continue
                        raw_cpu = proc.cpu_percent(interval=None)
                        normalized_cpu = raw_cpu / num_cpus
                        if normalized_cpu > CPU_THRESHOLD:
                            alerts.append(
                                f"{proc.info['name']} (PID {proc.info['pid']}) using {normalized_cpu:.1f}% CPU"
                            )
                    except:
                        continue

            # RAM Monitoring
            if ram_monitoring_enabled:
                for proc in procs:
                    try:
                        mem_mb = proc.memory_info().rss / (1024 * 1024)
                        if mem_mb > RAM_THRESHOLD_MB:
                            alerts.append(
                                f"{proc.info['name']} (PID {proc.info['pid']}) using {mem_mb:.1f} MB RAM"
                            )
                    except:
                        continue

            # GPU Monitoring (NOTE: NVML does not support per-process GPU tracking easily)
            if gpu_available and gpu_monitoring_enabled:
                try:
                    usage = nvmlDeviceGetUtilizationRates(gpu_handle)
                    if usage.gpu > GPU_THRESHOLD:
                        cached_print(f"GPU overall usage at {usage.gpu}%")
                except Exception as e:
                    alerts.append(f"[GPU Error] {e}")

            for alert in alerts:
                notify("Resource Alert", alert)

            time.sleep(CHECK_INTERVAL)

def start_command_listener(host='localhost', port=5050):
    def listen():
        global cpu_monitoring_enabled, gpu_monitoring_enabled, ram_monitoring_enabled

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((host, port))
        server.listen(1)
        cached_print(f"[INFO] Command listener active on {host}:{port}")

        def set_flag(flag, value):
            global cpu_monitoring_enabled, gpu_monitoring_enabled, ram_monitoring_enabled
            if flag == "cpu":
                cpu_monitoring_enabled = value
            elif flag == "gpu":
                gpu_monitoring_enabled = value
            elif flag == "ram":
                ram_monitoring_enabled = value

        command_map = {
            "disable_gpu_monitoring": ("GPU monitoring disabled", lambda: set_flag("gpu", False)),
            "enable_gpu_monitoring": ("GPU monitoring enabled", lambda: set_flag("gpu", True)),
            "disable_cpu_monitoring": ("CPU monitoring disabled", lambda: set_flag("cpu", False)),
            "enable_cpu_monitoring": ("CPU monitoring enabled", lambda: set_flag("cpu", True)),
            "disable_ram_monitoring": ("RAM monitoring disabled", lambda: set_flag("ram", False)),
            "enable_ram_monitoring": ("RAM monitoring enabled", lambda: set_flag("ram", True)),
        }

        while True:
            client, addr = server.accept()
            try:
                data = client.recv(1024).decode().strip().lower()
                response = "[COMMAND ERROR] Unknown command"

                action = command_map.get(data)
                if action:
                    response, func = action
                    func()

                cached_print(f"[COMMAND RECEIVED] {data} → {response}")
                client.sendall(response.encode('utf-8'))

            except Exception as e:
                cached_print(f"[ERROR] Command listener: {e}")
            finally:
                client.close()
    threading.Thread(target=listen, daemon=True).start()

def main():
    start_command_listener()
    monitor = ResourceMonitorThread()
    monitor.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cached_print("Resource notifier stopped.")
    finally:
        if gpu_available:
            try:
                nvmlShutdown()
            except:
                pass

if __name__ == "__main__":
    main()
    atexit.register(lambda: write_log_to_file("notifier_log.txt"))
