"""FEBioStudio 图形界面的自动化控制（仅 Windows）。

定位：headless 求解（febio4.exe）之外的补充通道 —— 用于交互式查看、
可视化截图、通过菜单触发分析等。

注意：GUI 自动化天然不如命令行稳定，所有操作都是 best-effort，
失败时返回结构化错误而不是抛异常。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import config as _cfg

IS_WINDOWS = sys.platform.startswith("win")


def _import_pywinauto():
    try:
        from pywinauto import Application  # noqa: F401
        return Application
    except Exception:
        return None


def available() -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "FEBioStudio GUI 控制仅在 Windows 上可用。"
    if not _cfg.FEBIO_STUDIO or not Path(_cfg.FEBIO_STUDIO).exists():
        return False, "未找到 FEBioStudio 可执行文件（可设置环境变量 FEBIO_STUDIO）。"
    if _import_pywinauto() is None:
        return False, "缺少 pywinauto 依赖：pip install pywinauto"
    return True, "ok"


class StudioController:
    """对 FEBioStudio 进程的薄封装。"""

    def __init__(self, exe: Path | None = None):
        self.exe = Path(exe) if exe else _cfg.FEBIO_STUDIO
        self._proc: subprocess.Popen | None = None
        self._app = None

    # -------------------------------------------------- 启动 / 连接
    def launch(self, file: str | Path | None = None, wait: float = 25.0) -> dict:
        ok, msg = available()
        if not ok:
            return {"ok": False, "error": msg}
        cmd = [str(self.exe)]
        if file:
            cmd.append(str(Path(file).resolve()))
        try:
            self._proc = subprocess.Popen(cmd, cwd=str(self.exe.parent))
        except Exception as exc:
            return {"ok": False, "error": f"启动失败: {exc}"}

        # 等待主窗口出现
        deadline = time.time() + wait
        while time.time() < deadline:
            if self._connect():
                return {"ok": True, "pid": self._proc.pid, "window": self._window_title()}
            time.sleep(0.8)
        return {"ok": True, "pid": self._proc.pid, "warning": "进程已启动，但未在超时内连上窗口（可能仍在加载）。"}

    def _connect(self) -> bool:
        Application = _import_pywinauto()
        if Application is None:
            return False
        try:
            self._app = Application(backend="uia").connect(path=str(self.exe), timeout=3)
            return True
        except Exception:
            try:
                self._app = Application(backend="uia").connect(
                    title_re=".*FEBio.*", timeout=3
                )
                return True
            except Exception:
                return False

    def _window_title(self) -> str | None:
        try:
            return self._app.window().window_text()
        except Exception:
            return None

    # -------------------------------------------------- 操作
    def open_file(self, file: str | Path) -> dict:
        """通过命令行再次打开文件（FEBioStudio 支持带参启动）。"""
        if not self._app:
            return {"ok": False, "error": "尚未连接 FEBioStudio，请先 launch()。"}
        try:
            subprocess.Popen([str(self.exe), str(Path(file).resolve())])
            return {"ok": True, "file": str(file)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def screenshot(self, out_path: str | Path) -> dict:
        """截取主窗口。"""
        if not self._app:
            return {"ok": False, "error": "尚未连接 FEBioStudio，请先 launch()。"}
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            img = self._app.window().capture_as_image()
            img.save(out)
            return {"ok": True, "path": str(out), "size": list(img.size)}
        except Exception as exc:
            # 回退：整屏截图
            try:
                from PIL import ImageGrab

                ImageGrab.grab().save(out)
                return {"ok": True, "path": str(out), "note": "窗口截取失败，已回退为整屏截图。"}
            except Exception as exc2:
                return {"ok": False, "error": f"{exc}; fallback: {exc2}"}

    def menu_items(self) -> dict:
        """列出主菜单项。

        FEBioStudio 是 Qt 应用，菜单栏不是标准 win32 菜单，
        因此先试标准方式，再回退到 UIA 遍历。
        """
        if not self._app:
            return {"ok": False, "error": "尚未连接 FEBioStudio。"}
        try:
            w = self._app.window()
            # 1) 标准 win32 菜单
            try:
                menus = [m.text() for m in w.menu().items()]
                if menus:
                    return {"ok": True, "menus": menus, "source": "win32-menu"}
            except Exception:
                pass
            # 2) UIA 遍历 MenuBar / Menu
            menus: list[str] = []
            for ctrl in w.descendants():
                try:
                    ct = ctrl.element_info.control_type
                except Exception:
                    continue
                if ct in ("MenuBar", "Menu"):
                    for c in ctrl.children():
                        try:
                            t = (c.window_text() or "").strip()
                        except Exception:
                            t = ""
                        if t and t not in menus:
                            menus.append(t)
            if menus:
                return {"ok": True, "menus": menus, "source": "uia"}
            return {
                "ok": False,
                "error": "未能枚举菜单（Qt 应用限制）",
                "hint": "可直接用 febio_studio_run 走快捷键，或 febio_studio_screenshot 看界面。",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def click_menu(self, path: list[str]) -> dict:
        """点击菜单，例如 ["FEBio", "Run"]。失败时回退到快捷键。"""
        if not self._app:
            return {"ok": False, "error": "尚未连接 FEBioStudio。"}
        target = (path[-1] if path else "").strip()
        try:
            w = self._app.window()
            # 先展开顶层菜单
            if len(path) > 1:
                for ctrl in w.descendants():
                    try:
                        if (ctrl.element_info.control_type in ("MenuBar", "Menu")
                                and (ctrl.window_text() or "").strip() == path[0]):
                            ctrl.click_input()
                            time.sleep(0.4)
                            break
                    except Exception:
                        continue
            # 再点目标项
            for ctrl in w.descendants():
                try:
                    if ctrl.element_info.control_type in ("MenuItem", "Menu") \
                            and (ctrl.window_text() or "").strip() == target:
                        ctrl.click_input()
                        return {"ok": True, "clicked": path, "source": "uia"}
                except Exception:
                    continue
            return {
                "ok": False,
                "error": f"未找到菜单项 '{target}'",
                "hint": "Qt 菜单枚举有限；运行分析请用 febio_studio_run（快捷键）。",
            }
        except Exception as exc:
            return {"ok": False, "error": f"菜单点击失败: {exc}"}

    def run_analysis(self) -> dict:
        """尝试触发一次分析（优先用快捷键 F5 / Ctrl+R，其次菜单）。"""
        if not self._app:
            return {"ok": False, "error": "尚未连接 FEBioStudio。"}
        try:
            w = self._app.window()
            w.set_focus()
            for key in ("{F5}", "^r", "^R"):
                try:
                    w.type_keys(key)
                    return {"ok": True, "triggered_by": key}
                except Exception:
                    continue
            return {"ok": False, "error": "未能触发分析，请用 click_menu 指定具体菜单。"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def close(self, force: bool = False) -> dict:
        try:
            if self._proc and self._proc.poll() is None:
                if force:
                    self._proc.kill()
                else:
                    self._proc.terminate()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
