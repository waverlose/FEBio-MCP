# -*- coding: utf-8 -*-
"""biphasic（双相）算例：验证「固体骨架 + 孔隙流体」的材料链路。

圆柱试件单轴压缩，固体骨架 neo-Hookean + 恒定各向同性渗透率。
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from modeling.builder import build_from_spec
from post.results import Results
from solver.logparser import parse_log
from solver.runner import FebioRunner

WS = REPO / "workspace" / "biphasic_basic"
WS.mkdir(parents=True, exist_ok=True)

spec = {
    "name": "biphasic_basic",
    "module": "biphasic",
    "geometry": {"type": "cylinder", "radius": 5.0, "height": 2.0, "mesh_size": 1.3},
    "materials": [
        {
            "name": "porous_sample",
            "type": "biphasic",
            "phi0": 0.2,               # 固体体积分数（手册 4.14）
            "fluid_density": 1e-6,
            "solid": {"type": "neo-Hookean", "E": 1.0, "v": 0.3},
            "permeability": {"type": "perm-const-iso", "perm": 0.001},
        }
    ],
    "domains": [{"name": "Part1", "mat": "porous_sample"}],
    "boundary": [
        {"type": "zero displacement", "node_set": "zmin", "x_dof": 1, "y_dof": 1, "z_dof": 1},
        {"type": "prescribed displacement", "node_set": "zmax", "dof": "z", "value": -0.2},
    ],
    "control": {
        "analysis": "TRANSIENT",
        "time_steps": 20,
        "step_size": 0.05,
        "solver": "biphasic",
    },
}

feb = WS / "biphasic_basic.feb"
print("[1] 建模 ...")
info = build_from_spec(spec, feb)
print("   ", info["mesh"])

print("[2] 求解 ...")
job = FebioRunner().run_sync(feb, timeout=600)
print("    状态:", job.status, "返回码:", job.returncode)
s = parse_log(job.log_file)
print(s.human()[:1200])

if Path(job.plot_file).exists():
    print("\n[3] 结果 ...")
    r = Results(job.plot_file)
    print("   ", {k: r.summary()[k] for k in ("n_states", "variables")})
    h = r.history("displacement", component=2, node_set="zmax", reduce="mean")
    print("    顶面 z 位移:", [round(v, 4) for v in h["values"]])
