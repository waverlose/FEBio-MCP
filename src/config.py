"""集中式路径 / 环境配置（跨平台、多版本、可覆盖）。

设计原则：**不假设任何固定安装位置**，适配所有用户。

探测优先级（从高到低）：
  1. 显式环境变量：FEBIO_EXE / FEBIO_STUDIO / FEBIO_HOME / FEBIO_DOC / FEBIO_SDK
  2. 系统 PATH 中的 febio4 / febio3 可执行文件
  3. 各平台常见安装目录（Windows / Linux / macOS）

支持 FEBio 3 与 FEBio 4（自动识别，命令行接口兼容）。

其它可覆盖的环境变量：
    FEBIO_WORKSPACE   运行工作区（默认 <repo>/workspace）
    FEBIO_TIMEOUT     单次求解默认超时秒数（默认 3600）
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- 基础路径

REPO_ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# 可执行文件名候选（按优先级：新版本优先）
EXE_CANDIDATES = ["febio4", "febio3", "febio2", "febio"]
STUDIO_CANDIDATES = ["FEBioStudio", "FEBioStudio.exe"]


def _exe_names(names: list[str]) -> list[str]:
    if IS_WINDOWS:
        out: list[str] = []
        for n in names:
            out.append(n + ".exe" if not n.lower().endswith(".exe") else n)
            out.append(n)
        return out
    return names


def _first_existing(*cands: Path | None) -> Path | None:
    for c in cands:
        if c and c.exists():
            return c
    return None


def _local_fixed_drives() -> list[str]:
    """Windows 上本机固定磁盘的盘符。

    探测前先向系统确认盘符类型，跳过光驱、可移动盘与网络映射盘，
    避免对已断开的网络盘做 exists() 而长时间阻塞。
    """
    if not IS_WINDOWS:
        return []
    try:
        import ctypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        DRIVE_FIXED = 3
        mask = k32.GetLogicalDrives()
        return [
            ch
            for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            if (mask & (1 << i)) and k32.GetDriveTypeW(f"{ch}:\\") == DRIVE_FIXED
        ]
    except Exception:
        return []


def _windows_home_candidates() -> list[Path]:
    """Windows 上常见的 FEBio 安装位置。

    非系统盘上装 FEBio 很常见，但具体是哪个盘取决于用户机器，
    因此按系统实际挂载的固定磁盘逐个探测，而不写死盘符。
    """
    home = Path.home()
    cands = [
        Path(r"C:\Program Files\FEBio"),
        Path(r"C:\Program Files (x86)\FEBio"),
        Path(r"C:\FEBio"),
        home / "FEBio",
        home / "AppData" / "Local" / "FEBio",
    ]
    sysdrive = (os.environ.get("SystemDrive") or "C:").rstrip("\\/").upper()
    for ch in _local_fixed_drives():
        if f"{ch}:" == sysdrive:
            continue
        cands.append(Path(f"{ch}:\\FEBio"))
        cands.append(Path(f"{ch}:\\Program Files\\FEBio"))
    return cands


def _home_candidates() -> list[Path]:
    """各平台常见的 FEBio 安装根目录。"""
    home = Path.home()
    if IS_WINDOWS:
        return _windows_home_candidates()
    if IS_MAC:
        return [
            Path("/Applications/FEBio"),
            Path("/Applications/FEBio4"),
            home / "FEBio",
            home / "Applications" / "FEBio",
            Path("/usr/local/FEBio"),
            Path("/opt/FEBio"),
        ]
    # Linux / 其它 unix
    return [
        Path("/usr/local/FEBio"),
        Path("/opt/FEBio"),
        Path("/usr/share/FEBio"),
        home / "FEBio",
        home / "febio",
        home / ".local" / "FEBio",
        Path("/snap/febio/current/FEBio"),
    ]


def _detect_home() -> Path | None:
    env = os.environ.get("FEBIO_HOME")
    if env and Path(env).exists():
        return Path(env)
    for c in _home_candidates():
        if (c / "bin").exists():
            return c
    # 由 exe 反推
    exe = _detect_exe()
    if exe:
        # .../FEBio/bin/febio4  ->  .../FEBio
        if exe.parent.name == "bin":
            return exe.parent.parent
    return None


def _detect_exe() -> Path | None:
    # 1) 显式环境变量
    env = os.environ.get("FEBIO_EXE")
    if env and Path(env).exists():
        return Path(env)
    # 2) PATH
    for n in EXE_CANDIDATES:
        w = shutil.which(n)
        if w:
            return Path(w)
    # 3) 常见安装目录
    home_env = os.environ.get("FEBIO_HOME")
    homes = ([Path(home_env)] if home_env else []) + _home_candidates()
    for h in homes:
        for sub in ("bin", "", "FEBio", "FEBio/bin"):
            for n in _exe_names(EXE_CANDIDATES):
                p = (h / sub / n) if sub else (h / n)
                if p.exists() and p.is_file():
                    return p
    return None


def _detect_studio() -> Path | None:
    env = os.environ.get("FEBIO_STUDIO")
    if env and Path(env).exists():
        return Path(env)
    for n in STUDIO_CANDIDATES:
        w = shutil.which(n)
        if w:
            return Path(w)
    home_env = os.environ.get("FEBIO_HOME")
    homes = ([Path(home_env)] if home_env else []) + _home_candidates()
    for h in homes:
        for sub in ("bin", ""):
            for n in STUDIO_CANDIDATES:
                p = (h / sub / n) if sub else (h / n)
                if p.exists() and p.is_file():
                    return p
    # macOS 应用包
    if IS_MAC:
        for app in Path("/Applications").glob("FEBioStudio*.app"):
            p = app / "Contents" / "MacOS" / "FEBioStudio"
            if p.exists():
                return p
    return None


def _find_doc_dir() -> Path | None:
    """手册 PDF 目录。不同版本位置不同，做递归浅查找。"""
    env = os.environ.get("FEBIO_DOC")
    if env and Path(env).exists():
        return Path(env)
    roots = []
    if FEBIO_HOME:
        roots.append(FEBIO_HOME)
    roots += _home_candidates()
    for r in roots:
        if not r or not r.exists():
            continue
        for cand in (r / "doc", r / "docs", r / "Documentation"):
            if cand.exists():
                # 确认里面确实有 PDF
                if any(cand.glob("*.pdf")) or any(cand.rglob("*.pdf")):
                    return cand
    return None


def _find_sdk_include() -> Path | None:
    env = os.environ.get("FEBIO_SDK")
    if env and Path(env).exists():
        return Path(env)
    roots = []
    if FEBIO_HOME:
        roots.append(FEBIO_HOME)
    roots += _home_candidates()
    for r in roots:
        if not r or not r.exists():
            continue
        for cand in (r / "sdk" / "include", r / "include", r / "sdk"):
            if cand.exists() and any(cand.iterdir()):
                return cand
    return None


# 先算 exe，再由 exe 反推 home（顺序有依赖）
FEBIO_EXE: Path | None = _detect_exe()
FEBIO_HOME: Path | None = _detect_home()
FEBIO_STUDIO: Path | None = _detect_studio()
DOC_DIR: Path | None = _find_doc_dir()
SDK_INCLUDE: Path | None = _find_sdk_include()

# ---------------------------------------------------------------- 工作区

WORKSPACE = Path(os.environ.get("FEBIO_WORKSPACE", REPO_ROOT / "workspace"))
try:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
except Exception:
    WORKSPACE = Path.cwd()

CACHE_DIR = REPO_ROOT / "docs" / ".cache"
try:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    CACHE_DIR = WORKSPACE / ".cache"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TIMEOUT = int(os.environ.get("FEBIO_TIMEOUT", "3600"))

MANUAL_ORDER = [
    "FEBio_User_Manual.pdf",
    "FEBio_Theory_Manual.pdf",
    "FEBioStudio_User_Manual.pdf",
]


# ---------------------------------------------------------------- 能力探测

def febio_version() -> str:
    if not FEBIO_EXE:
        return "not found"
    try:
        out = subprocess.run(
            [str(FEBIO_EXE), "-info", "-norun"],
            capture_output=True, text=True, timeout=30, errors="replace",
        )
        txt = (out.stdout or "") + (out.stderr or "")
        for line in txt.splitlines():
            if "version" in line.lower():
                return line.strip()
        return txt.strip().splitlines()[0] if txt.strip() else "unknown"
    except Exception as exc:
        return f"error: {exc}"


def _has_gmsh() -> bool:
    try:
        import gmsh  # noqa: F401
        return True
    except Exception:
        return False


def _has_pyfebio() -> bool:
    try:
        import pyfebio  # noqa: F401
        return True
    except Exception:
        return False


def _has_pywinauto() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import pywinauto  # noqa: F401
        return True
    except Exception:
        return False


def status() -> dict:
    """环境自检快照（供 MCP 工具与排障使用）。"""
    caps = {
        "solve": bool(FEBIO_EXE),
        "build_model": _has_pyfebio(),
        "mesh": _has_gmsh(),
        "gui_control": _has_pywinauto() and bool(FEBIO_STUDIO),
        "offline_docs": bool(DOC_DIR),
        "sdk_map": bool(SDK_INCLUDE),
    }
    missing_hints = []
    if not FEBIO_EXE:
        missing_hints.append("未找到 febio4/febio3：请把 FEBio 加入 PATH，或设置环境变量 FEBIO_EXE / FEBIO_HOME。")
    if not DOC_DIR:
        missing_hints.append("未找到官方 PDF 手册：离线文档检索不可用。可设置 FEBIO_DOC 指向手册目录。")
    if not SDK_INCLUDE:
        missing_hints.append("未找到 FEBio SDK 头文件：能力地图不可用（不影响建模/求解）。")
    return {
        "platform": sys.platform,
        "febio_home": str(FEBIO_HOME) if FEBIO_HOME else None,
        "febio_exe": str(FEBIO_EXE) if FEBIO_EXE else None,
        "febio_studio": str(FEBIO_STUDIO) if FEBIO_STUDIO else None,
        "doc_dir": str(DOC_DIR) if DOC_DIR else None,
        "sdk_include": str(SDK_INCLUDE) if SDK_INCLUDE else None,
        "workspace": str(WORKSPACE),
        "cache_dir": str(CACHE_DIR),
        "version": febio_version(),
        "capabilities": caps,
        "hints": missing_hints,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(status(), indent=2, ensure_ascii=False))
