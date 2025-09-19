from langchain.tools import tool
import cmd
import psutil

@tool("kill_process", return_direct=True)
def kill_process_tool(cmd: str) -> str | None:
    """Kill a process by name or ID.

    Args:
        cmd (str): The command to execute, including the process name or ID.

    Returns:
        str | None: A message indicating the result of the operation.
    """
    cmd = cmd.strip().lower()

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