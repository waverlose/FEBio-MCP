# -*- coding: utf-8 -*-
"""对材料卡片里的 example.spec 做真实求解验证。

做法：把卡片里的 example.spec 包进一个最小三维算例（1×1×1 立方体、六面体网格、
单轴压缩 5%），真跑 FEBio；terminate normal 才把 `example.verified` 置为 true。

只验证 kind=standalone 且有 example.spec 的卡片 —— 嵌套组件（permeability、
fiber-* 等）不能单独赋给 part，需由宿主材料验证，另行处理。

用法：
    python scripts/verify_material_guides.py [--limit N] [--timeout 120]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from modeling.builder import build_from_spec  # noqa: E402
from solver.logparser import parse_log  # noqa: E402
from solver.runner import FebioRunner  # noqa: E402

GUIDES = REPO / "data" / "material_guides"
WS = REPO / "workspace" / "_guide_verify"


# 手写卡片可能没有 module 字段，按类型名兜底
MODULE_BY_TYPE = {
    "biphasic": "biphasic",
    "biphasic-solute": "biphasic",
    "multiphasic": "multiphasic",
    "solid mixture": "solid",
}


def pick_module(card: dict) -> str | None:
    m = (card.get("module") or "").lower()
    if "fluid" in m or "solute" in m:
        return None                     # pyfebio 不支持这两个 module
    if "multiphasic" in m:
        return "multiphasic"
    if "biphasic" in m:
        return "biphasic"
    if m:
        return "solid"
    return MODULE_BY_TYPE.get(card.get("type", ""), "solid")


def build_spec(card: dict, module: str) -> dict:
    mat = dict(card["example"]["spec"])
    mat["name"] = "sample"
    if module == "solid":
        ctrl = {"analysis": "STATIC", "time_steps": 10, "step_size": 0.02, "solver": "solid"}
    elif module == "biphasic":
        ctrl = {"analysis": "TRANSIENT", "time_steps": 10, "step_size": 0.02, "solver": "biphasic"}
    else:
        ctrl = {"analysis": "TRANSIENT", "time_steps": 10, "step_size": 0.02, "solver": "multiphasic"}
    return {
        "name": "guide_verify",
        "module": module,
        "geometry": {"type": "box", "size": [1, 1, 1], "mesh_size": 0.4, "elem_type": "hex"},
        "materials": [mat],
        "domains": [{"name": "Part1", "mat": "sample"}],
        "boundary": [
            {"type": "zero displacement", "node_set": "zmin", "x_dof": 1, "y_dof": 1, "z_dof": 1},
            {"type": "prescribed displacement", "node_set": "zmax", "dof": "z", "value": -0.01},
        ],
        "control": ctrl,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只验证前 N 个（0 = 全部）")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    WS.mkdir(parents=True, exist_ok=True)
    targets = []
    for p in sorted(GUIDES.glob("*.json")):
        card = json.loads(p.read_text(encoding="utf-8"))
        if card.get("kind") != "standalone":
            continue
        if not card.get("example", {}).get("spec"):
            continue
        targets.append((p, card))
    if args.limit:
        targets = targets[: args.limit]

    print(f"待验证卡片: {len(targets)} 张\n")
    runner = FebioRunner()
    ok = fail = skip = 0
    results = []

    for path, card in targets:
        mtype = card["type"]
        module = pick_module(card)
        if module is None:
            skip += 1
            results.append((mtype, "skip", "pyfebio 不支持该 module"))
            continue

        tag = "".join(ch if ch.isalnum() else "_" for ch in mtype)[:40]
        feb = WS / f"{tag}.feb"
        try:
            build_from_spec(build_spec(card, module), feb)
        except Exception as e:
            fail += 1
            results.append((mtype, "build-fail", f"{type(e).__name__}: {str(e)[:80]}"))
            continue

        try:
            job = runner.run_sync(feb, timeout=args.timeout)
            status = job.status
            if Path(job.log_file).exists():
                s = parse_log(job.log_file)
                detail = f"{status} / steps={len(s.time_steps)}"
                if s.errors:
                    detail += f" / {s.errors[0][:60]}"
            else:
                # 没生成日志 = 读入阶段就失败，错误只在 stdout 里
                msg = ""
                for ln in (job.stdout_tail or "").splitlines():
                    if "ERROR" in ln or "invalid" in ln.lower() or "needs to have" in ln:
                        msg = ln.strip()
                detail = f"{status} / 读入失败: {msg[:90] or (job.stdout_tail or '')[-90:]}"
        except Exception as e:
            status, detail = "exception", f"{type(e).__name__}: {str(e)[:80]}"

        if status == "normal":
            ok += 1
            card["example"]["verified"] = True
            card["example"]["verified_note"] = (
                "已在 FEBio 4.13.0 实测：包进 1×1×1 六面体网格、单轴压缩 1% 的算例，terminate normal。"
                "该结果只证明此 spec 可被 FEBio 正常读入并收敛，不代表参数取值适用于任何具体工况。"
            )
            path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append((mtype, "PASS", detail))
        else:
            fail += 1
            results.append((mtype, "fail", detail))

    print(f"{'材料类型':42s} {'结果':10s} 说明")
    print("-" * 100)
    for mtype, st, detail in results:
        print(f"{mtype:42s} {st:10s} {detail}")
    print("-" * 100)
    print(f"通过 {ok} / 失败 {fail} / 跳过 {skip}")
    shutil.rmtree(WS, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
