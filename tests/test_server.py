# -*- coding: utf-8 -*-
"""冒烟测试：server 能加载、工具能注册、关键工具能调用。"""
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import server  # noqa: E402


async def main():
    tools = await server.server.list_tools()
    print(f"[工具数] {len(tools)}")
    for t in tools:
        print("  -", t.name)

    print("\n[env_status]")
    r = server.febio_env_status()
    for k, v in r.items():
        print(f"  {k}: {v}")

    print("\n[list_materials]")
    r = server.febio_list_materials("biphasic")
    print(" ", r)

    print("\n[search_docs]")
    r = server.febio_search_docs("渗透率 双相", top_k=2)
    print("  命中:", r.get("n_hits"))
    for h in r.get("hits", []):
        print("   ", h["manual"], "p" + str(h["page"]), h["snippet"][:120])

    print("\n[validate]")
    r = server.febio_validate_model(str(REPO / "workspace" / "e2e_uniaxial" / "uniaxial.feb"))
    print(" ", {k: r[k] for k in ("valid", "issues")})

    print("\n[results_summary]")
    r = server.febio_results_summary(str(REPO / "workspace" / "e2e_uniaxial" / "uniaxial.xplt"))
    print(" ", {k: r[k] for k in ("n_states", "times", "variables")})

    print("\n[extract_history]")
    r = server.febio_extract_history(str(REPO / "workspace" / "e2e_uniaxial" / "uniaxial.xplt"),
                                     "displacement", component=2, reduce="max")
    print("  times:", [round(t, 2) for t in r["times"]])
    print("  vals :", [round(v, 5) for v in r["values"]])


asyncio.run(main())
