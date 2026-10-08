# -*- coding: utf-8 -*-
"""biphasic 诊断：对比几何/网格/边界对收敛的影响。"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from modeling.builder import build_from_spec
from solver.logparser import parse_log
from solver.runner import FebioRunner

WS = REPO / "workspace" / "_diag_bp"
WS.mkdir(parents=True, exist_ok=True)


def run_case(tag, geom, bc_extra=None, mat_extra=None, step=0.02, nsteps=10):
    mat = {
        "name": "porous_sample", "type": "biphasic", "phi0": 0.2, "fluid_density": 1e-6,
        "solid": {"type": "neo-Hookean", "E": 1.0, "v": 0.3},
        "permeability": {"type": "perm-const-iso", "perm": 0.001},
    }
    mat.update(mat_extra or {})
    bc = [
        {"type": "zero displacement", "node_set": "zmin", "x_dof": 1, "y_dof": 1, "z_dof": 1},
        {"type": "prescribed displacement", "node_set": "zmax", "dof": "z", "value": -0.05},
    ]
    bc += bc_extra or []
    spec = {
        "name": tag, "module": "biphasic", "geometry": geom,
        "materials": [mat], "domains": [{"name": "Part1", "mat": "porous_sample"}],
        "boundary": bc,
        "control": {"analysis": "TRANSIENT", "time_steps": nsteps, "step_size": step,
                    "solver": "biphasic"},
    }
    feb = WS / f"{tag}.feb"
    build_from_spec(spec, feb)
    job = FebioRunner().run_sync(feb, timeout=600)
    s = parse_log(job.log_file)
    print(f"  [{tag}] 状态={job.status:7s} 步数={len(s.time_steps):2d} "
          f"末时={s.final_time} 错误={s.errors[:2]}")
    return job.status


print("A. box 几何（规则网格）")
run_case("box_bp", {"type": "box", "size": [1, 1, 1], "mesh_size": 0.28, "elem_type": "tet"})

print("B. cylinder 几何")
run_case("cyl_bp", {"type": "cylinder", "radius": 5.0, "height": 2.0, "mesh_size": 1.3})

print("C. box + 高渗透率")
run_case("box_bp_perm", {"type": "box", "size": [1, 1, 1], "mesh_size": 0.28},
         mat_extra={"permeability": {"type": "perm-const-iso", "perm": 1.0}})

print("D. box + 自由排水边界（顶面流体压力=0）")
run_case("box_bp_drain", {"type": "box", "size": [1, 1, 1], "mesh_size": 0.28},
         bc_extra=[{"type": "zero fluid pressure", "node_set": "zmax"}])

print("E. box + 六面体网格")
run_case("box_bp_hex", {"type": "box", "size": [1, 1, 1], "mesh_size": 0.3, "elem_type": "hex"})
