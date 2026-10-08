# -*- coding: utf-8 -*-
"""FEBioStudio GUI 通道实测：启动 -> 连接 -> 截图 -> 菜单 -> 关闭。"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from gui.studio import StudioController, available

print("[0] 可用性:", available())

c = StudioController()
fig = REPO / "workspace" / "figures"
fig.mkdir(parents=True, exist_ok=True)

try:
    print("[1] 启动 FEBioStudio ...")
    t0 = time.time()
    r = c.launch(wait=40)
    print("   ", r, f"({time.time()-t0:.1f}s)")

    if r.get("ok") and not r.get("error"):
        print("[2] 截图 ...")
        s = c.screenshot(fig / "studio_test.png")
        print("   ", s)

        print("[3] 菜单 ...")
        m = c.menu_items()
        print("   ", m if not m.get("ok") else f"菜单数={len(m.get('menus', []))}: {m.get('menus')}")
finally:
    print("[4] 关闭 ...")
    print("   ", c.close(force=True))
