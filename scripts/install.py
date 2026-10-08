#!/usr/bin/env python3
"""一键安装脚本（跨平台）。

用法：
    python scripts/install.py            # 建 venv + 装依赖 + 打印 MCP 配置
    python scripts/install.py --no-venv  # 直接装到当前解释器

完成后把打印出的 JSON 片段合并进你的 MCP 客户端配置即可。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
IS_WIN = sys.platform.startswith("win")


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if IS_WIN else "bin/python")


def main() -> int:
    use_venv = "--no-venv" not in sys.argv
    venv = REPO / ".venv"

    if use_venv and not venv_python(venv).exists():
        print(f"[1/3] 创建虚拟环境: {venv}")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv_python(venv) if use_venv else Path(sys.executable)

    print(f"[2/3] 安装依赖（解释器: {py}）")
    req = REPO / "requirements.txt"
    cmd = [str(py), "-m", "pip", "install", "-r", str(req)]
    # 国内网络可加镜像：--index-url https://pypi.tuna.tsinghua.edu.cn/simple
    if os.environ.get("PIP_INDEX_URL"):
        cmd += ["--index-url", os.environ["PIP_INDEX_URL"]]
    subprocess.run(cmd, check=True)

    print("[3/3] 生成 MCP 客户端配置片段：")
    entry = {
        "febio": {
            "command": str(py),
            "args": ["-m", "src.server"],
            "cwd": str(REPO),
            "env": {
                "PYTHONPATH": str(REPO),
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        }
    }
    print(json.dumps({"mcpServers": entry}, indent=2, ensure_ascii=False))
    print(
        "\n提示：\n"
        "  * 若 FEBio 未加入 PATH，请在上面 env 中补 FEBIO_HOME（或 FEBIO_EXE）。\n"
        "  * 离线手册目录不同时，补 FEBIO_DOC 指向手册所在文件夹。\n"
        "  * 配置写入后，需在客户端的连接器页面「信任」该 MCP 才会生效。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
