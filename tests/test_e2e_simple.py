# -*- coding: utf-8 -*-
"""端到端最小算例：立方体单轴压缩。

验证链路：gmsh 网格 -> pyfebio 建模 -> febio4 求解 -> 结果解析。
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from modeling.builder import build_from_spec, material_types
from solver.runner import FebioRunner
from solver.logparser import parse_log

WS = REPO / "workspace" / "e2e_uniaxial"
WS.mkdir(parents=True, exist_ok=True)

print("[1] 可用材料类型（前 20）:", material_types()[:20])
print("    neo-Hookean 参数:", __import__("modeling.builder", fromlist=["x"]).material_fields("neo-Hookean"))

spec = {
    "name": "uniaxial",
    "geometry": {
        "type": "box",
        "size": [1.0, 1.0, 1.0],
        "mesh_size": 0.34,
        "elem_type": "tet",
    },
    "materials": [
        {"name": "solid", "type": "neo-Hookean", "E": 1000.0, "v": 0.3, "density": 1e-6}
    ],
    "domains": [{"name": "Part1", "mat": "solid"}],
    "boundary": [
        {"type": "zero displacement", "node_set": "zmin", "x_dof": 1, "y_dof": 1, "z_dof": 1},
        {"type": "prescribed displacement", "node_set": "zmax", "dof": "z", "value": -0.1},
    ],
    "control": {"analysis": "STATIC", "time_steps": 10, "step_size": 0.1, "solver": "solid"},
}

feb_path = WS / "uniaxial.feb"
print("\n[2] 生成模型 ...")
info = build_from_spec(spec, feb_path)
print("    结果:", info["mesh"], "->", info["path"])

print("\n[3] 求解 ...")
runner = FebioRunner()
job = runner.run_sync(feb_path, timeout=300)
print("    状态:", job.status, "返回码:", job.returncode)
print("    日志:", job.log_file)
print("    结果:", job.plot_file, "存在:", Path(job.plot_file).exists())

print("\n[4] 日志解析 ...")
s = parse_log(job.log_file)
print(s.human()[:1500])
