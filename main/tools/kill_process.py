# kill_process.py
from langchain.tools import tool
import psutil
from typing import Optional

@tool("kill_process", return_direct=True)
def kill_process_tool(cmd: str) -> str:
    """
    Process control on Windows.

    Examples the agent can send:
    - "list processes"
    - "kill 1234"
    - "kill process chrome"
    """
    cmd = (cmd or "").strip().lower()

    if cmd == "list processes":
        processes = []
        for proc in psutil.process_iter(attrs=["pid", "name", "status"]):
            try:
                info = proc.info
                processes.append(
                    f"PID: {info['pid']}, Name: {info.get('name','N/A')}, Status: {info.get('status','N/A')}"
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        response = "\n".join(processes[:30])
        if len(processes) > 30:
            response += "\n... (listing first 30 processes)"
        return response

    if cmd.startswith("kill process") or cmd.startswith("kill"):
        parts = cmd.split(maxsplit=2)
        if len(parts) < 2:
            return "Please specify a process ID or name to kill. Example: 'kill 1234' or 'kill process chrome'"
        target = parts[-1]
        try:
            pid = int(target)
            psutil.Process(pid).terminate()
            return f"Process {pid} terminated."
        except ValueError:
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
            return f"Killed processes with PIDs: {killed}" if killed else f"Could not kill any processes matching '{target}'."

    return "Unsupported command. Use 'list processes' or 'kill <pid|name>'."
