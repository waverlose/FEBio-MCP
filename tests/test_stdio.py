# -*- coding: utf-8 -*-
"""以真实 MCP 协议（stdio JSON-RPC）连接 server，验证握手与工具调用。"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = REPO / ".venv" / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")

env = os.environ.copy()
env["PYTHONPATH"] = str(REPO)
env["PYTHONUTF8"] = "1"
env["PYTHONIOENCODING"] = "utf-8"

p = subprocess.Popen(
    [str(PY), "-m", "src.server"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    cwd=str(REPO), text=True, encoding="utf-8", bufsize=1, env=env,
)


def send(obj):
    p.stdin.write(json.dumps(obj) + "\n")
    p.stdin.flush()


def recv(timeout=60):
    line = p.stdout.readline()
    if not line:
        err = p.stderr.read()
        raise RuntimeError(f"no response; stderr={err[:2000]}")
    return json.loads(line)


try:
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                     "clientInfo": {"name": "smoke", "version": "1.0"}}})
    init = recv()
    print("[initialize]", init.get("result", {}).get("serverInfo"))

    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tl = recv()
    tools = tl.get("result", {}).get("tools", [])
    print(f"[tools/list] {len(tools)} 个工具")
    print("  示例:", [t["name"] for t in tools[:6]], "...")

    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "febio_env_status", "arguments": {}}})
    r = recv()
    content = r.get("result", {}).get("content", [])
    if content:
        print("[tools/call febio_env_status] OK")
        txt = content[0].get("text", "")
        print("  ", txt[:300].replace("\n", " "))
    else:
        print("[tools/call] 异常:", json.dumps(r)[:400])
finally:
    p.terminate()
    try:
        p.wait(timeout=5)
    except Exception:
        p.kill()
