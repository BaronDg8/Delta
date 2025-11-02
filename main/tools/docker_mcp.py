
    # Linking MCP via LangChain Tool

    # Run every MCP container with a published host port, e.g. docker run --rm -p 7100:7000 your-mcp-image. 
    # Give each container a stable URL (or stash it in an env var) so Delta can reach it.
    
    # Create a wrapper in main/tools, for example mcp_bridge.py, 
    # that turns a text prompt into the HTTP/WebSocket payload your MCP server expects and returns the response string.


import os, requests, json
from langchain.tools import tool

MCP_URL = os.getenv("DELTA_MCP_URL", "http://127.0.0.1:7100")

@tool("docker_mcp", return_direct=True)
def docker_mcp(prompt: str) -> str:
    """
    Call the MCP server that is exposed from Docker.
    The server is expected to accept JSON { "query": ... } and return { "result": ... }.
    """
    payload = {"query": prompt}
    r = requests.post(f"{MCP_URL}/invoke", json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data.get("result", json.dumps(data, indent=2))