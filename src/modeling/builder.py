"""基于 pyfebio 的模型构建层。

设计目标：让 AI 用「接近自然语言的结构化 spec」就能生成完整 .feb，
而不必逐行拼 XML。

两层接口：
  1. ModelBuilder —— 面向对象的增量构建（add_mesh / add_material / add_bc ...）
  2. build_from_spec(dict) —— 一键从 JSON spec 生成完整模型文件

材料类型通过反射 pyfebio 自动注册，无需手工维护映射表。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pyfebio import boundary as feb_bc
from pyfebio import control as feb_ctrl
from pyfebio import loaddata as feb_ld
from pyfebio import loads as feb_loads
from pyfebio import material as feb_mat
from pyfebio import mesh as feb_mesh
from pyfebio import meshdomains as feb_md
from pyfebio import model as feb_model
from pyfebio import output as feb_out
from pyfebio import step as feb_step

from meshing.gmsh_builder import MeshData

# ------------------------------------------------------------ 注册表

# FEBio 单元类型 -> pyfebio 元素类
ELEM_CLASS = {
    "tet4": feb_mesh.Tet4Element,
    "tet10": feb_mesh.Tet10Element,
    "tet15": feb_mesh.Tet15Element,
    "hex8": feb_mesh.Hex8Element,
    "hex20": feb_mesh.Hex20Element,
    "hex27": feb_mesh.Hex27Element,
    "penta6": feb_mesh.Penta6Element,
    "penta15": feb_mesh.Penta15Element,
    "pyra5": feb_mesh.Pyra5Element,
    "tri3": feb_mesh.Tri3Element,
    "tri6": feb_mesh.Tri6Element,
    "quad4": feb_mesh.Quad4Element,
    "quad8": feb_mesh.Quad8Element,
    "quad9": feb_mesh.Quad9Element,
    "line2": feb_mesh.Line2Element,
    "line3": feb_mesh.Line3Element,
}


def _material_registry() -> dict[str, type]:
    """扫描 pyfebio.material，按 type 字符串（如 'neo-Hookean'）注册。"""
    reg: dict[str, type] = {}
    for name in dir(feb_mat):
        cls = getattr(feb_mat, name)
        if not (isinstance(cls, type) and hasattr(cls, "model_fields")):
            continue
        f = cls.model_fields.get("type")
        if f is None:
            continue
        d = f.default
        if isinstance(d, str):
            reg.setdefault(d, cls)
    return reg


MATERIAL_REGISTRY: dict[str, type] = _material_registry()


def material_types() -> list[str]:
    return sorted(MATERIAL_REGISTRY)


def material_fields(type_str: str) -> dict:
    """返回某材料类型的可用参数名与默认值。"""
    cls = MATERIAL_REGISTRY.get(type_str)
    if not cls:
        return {}
    out = {}
    for k, f in cls.model_fields.items():
        if k in ("name", "id", "type"):
            continue
        out[k] = {"annotation": str(f.annotation).replace("pyfebio.", ""), "default": repr(f.default)}
    return out


def _is_param_field(f) -> bool:
    return "MaterialParameter" in str(f.annotation)


def _P(v: Any):
    """把标量包成 MaterialParameter。"""
    if isinstance(v, feb_mat.MaterialParameter):
        return v
    return feb_mat.MaterialParameter(text=v)


def build_material(spec: dict):
    """从 dict 构造 pyfebio 材料对象（支持嵌套）。"""
    if not isinstance(spec, dict) or "type" not in spec:
        raise ValueError(f"材料 spec 需要 'type' 字段，收到: {spec!r}")
    t = spec["type"]
    cls = MATERIAL_REGISTRY.get(t)
    if cls is None:
        raise ValueError(
            f"未知材料类型 '{t}'。可用类型见 febio_list_materials 工具。"
        )
    kwargs: dict[str, Any] = {}
    for k, v in spec.items():
        if k == "type":
            continue
        f = cls.model_fields.get(k)
        if f is None:
            raise ValueError(
                f"材料 '{t}' 不支持参数 '{k}'。可用参数: {[n for n in cls.model_fields if n not in ('name','id','type')]}"
            )
        if isinstance(v, dict) and "type" in v:
            kwargs[k] = build_material(v)
        elif isinstance(v, list) and v and isinstance(v[0], dict) and "type" in v[0]:
            kwargs[k] = [build_material(x) for x in v]
        elif _is_param_field(f) and isinstance(v, (int, float, str)):
            kwargs[k] = _P(v)
        else:
            kwargs[k] = v
    return cls(**kwargs)


# ------------------------------------------------------------ Builder

class ModelBuilder:
    def __init__(self, name: str = "model", module: str | None = None):
        self.name = name
        self.model = feb_model.Model()
        if module:
            self.model.module_ = feb_model.module.Module(type=module)
        self._mat_ids = 0
        self._step_ids = 0

    # -------------------------------------------------- 网格
    def add_mesh_data(self, md: MeshData, name: str = "Part1") -> list[str]:
        """把 MeshData 写入模型，返回实际创建的 part 名列表。

        注意：FEBio 要求 part 名唯一。若网格含多种单元类型（例如 gmsh 的
        recombine 会同时产生 hex8 与 pyra5），会自动拆成 <name>_<type> 多个 part。
        """
        nodes = feb_mesh.Nodes(
            name=name,
            all_nodes=[feb_mesh.Node(id=int(i), text=f"{x:g},{y:g},{z:g}") for i, (x, y, z) in md.nodes.items()],
        )
        self.model.mesh_.add_node_domain(nodes)

        parts: list[str] = []
        multi = len(md.elements) > 1
        for etype, elems in md.elements.items():
            cls = ELEM_CLASS.get(etype)
            if cls is None:
                raise ValueError(
                    f"不支持的单元类型: {etype}（可用: {sorted(ELEM_CLASS)}）"
                )
            pname = f"{name}_{etype}" if multi else name
            els = [cls(id=int(eid), text=",".join(str(c) for c in conn)) for eid, conn in elems]
            self.model.mesh_.add_element_domain(feb_mesh.Elements(name=pname, type=etype, all_elements=els))
            parts.append(pname)

        for sname, ids in md.node_sets.items():
            self.model.mesh_.add_node_set(
                feb_mesh.NodeSet(name=sname, text=",".join(str(i) for i in ids))
            )
        return parts

    def add_node_set(self, name: str, node_ids: list[int]) -> "ModelBuilder":
        self.model.mesh_.add_node_set(
            feb_mesh.NodeSet(name=name, text=",".join(str(i) for i in node_ids))
        )
        return self

    def add_element_set(self, name: str, elem_ids: list[int]) -> "ModelBuilder":
        self.model.mesh_.add_element_set(
            feb_mesh.ElementSet(name=name, text=",".join(str(i) for i in elem_ids))
        )
        return self

    # -------------------------------------------------- 材料 / 域
    def add_material(self, spec: dict) -> str:
        spec = dict(spec)
        self._mat_ids += 1
        spec.setdefault("id", self._mat_ids)
        name = spec.get("name") or f"mat{spec['id']}"
        spec["name"] = name
        mat = build_material(spec)
        self.model.material_.add_material(mat)
        return name

    def add_solid_domain(self, name: str, mat: str, type: str | None = None) -> "ModelBuilder":
        self.model.meshdomains_.add_solid_domain(feb_md.SolidDomain(name=name, mat=mat, type=type))
        return self

    def add_shell_domain(self, name: str, mat: str, thickness: float = 0.01, type: str | None = None) -> "ModelBuilder":
        self.model.meshdomains_.add_shell_domain(
            feb_md.ShellDomain(name=name, mat=mat, shell_thickness=thickness, type=type)
        )
        return self

    # -------------------------------------------------- 载荷曲线
    def add_load_curve(self, lc_id: int, points: list[str | tuple], interpolate: str = "LINEAR") -> "ModelBuilder":
        pts = [f"{p[0]},{p[1]}" if isinstance(p, (tuple, list)) else str(p) for p in points]
        self.model.loaddata_.add_load_curve(
            feb_ld.LoadCurve(id=lc_id, interpolate=interpolate, points=feb_ld.CurvePoints(points=pts))
        )
        return self

    # -------------------------------------------------- 边界 / 载荷
    def add_bc(self, bc) -> "ModelBuilder":
        self.model.boundary_.add_bc(bc)
        return self

    def add_load(self, load) -> "ModelBuilder":
        if isinstance(load, (feb_loads.TractionLoad, feb_loads.PressureLoad,
                             feb_loads.FluidFlux, feb_loads.FluidPressure)):
            self.model.loads_.add_surface_load(load)
        elif isinstance(load, (feb_loads.NodalLoad, feb_loads.NodalForce,
                               feb_loads.NodalTargetForce, feb_loads.NodalFluidFlux)):
            self.model.loads_.add_nodal_load(load)
        else:
            self.model.loads_.add_body_load(load)
        return self

    # -------------------------------------------------- 控制 / 输出
    def set_control(self, **kw) -> "ModelBuilder":
        ctrl = self.model.control_ or feb_ctrl.Control()
        for k, v in kw.items():
            if not hasattr(ctrl, k):
                raise ValueError(f"Control 无字段 '{k}'。可用: {[n for n in feb_ctrl.Control.model_fields]}")
            setattr(ctrl, k, v)
        self.model.control_ = ctrl
        return self

    # -------------------------------------------------- 保存
    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.model.save(p)
        return p


# ------------------------------------------------------------ spec 驱动

_BC_REGISTRY = {
    "zero displacement": feb_bc.BCZeroDisplacement,
    "prescribed displacement": feb_bc.BCPrescribedDisplacement,
    "prescribed deformation": feb_bc.BCPrescribedDeformation,
    "zero fluid pressure": feb_bc.BCZeroFluidPressure,
    "prescribed fluid pressure": feb_bc.BCPrescribedFluidPressure,
    "zero concentration": feb_bc.BCZeroConcentration,
    "prescribed concentration": feb_bc.BCPrescribedConcentration,
    "rigid": feb_bc.BCRigid,
    "normal displacement": feb_bc.BCNormalDisplacement,
    "linear constraint": feb_bc.BCLinearConstraint,
}

_LOAD_REGISTRY = {
    "traction": feb_loads.TractionLoad,
    "pressure": feb_loads.PressureLoad,
    "fluid flux": feb_loads.FluidFlux,
    "fluid pressure": feb_loads.FluidPressure,
    "nodal force": feb_loads.NodalForce,
    "nodal load": feb_loads.NodalLoad,
    "nodal fluid flux": feb_loads.NodalFluidFlux,
    "constant body force": feb_loads.ConstantBodyForce,
    "body force": feb_loads.ConstantBodyForce,
    "centrifugal": feb_loads.CentrifugalBodyForce,
}


def _build_section_item(reg: dict, spec: dict, kind: str, default_lc_id: int = 1):
    t = spec.get("type")
    if t not in reg:
        raise ValueError(f"未知{kind}类型 '{t}'。可用: {sorted(reg)}")
    cls = reg[t]
    kwargs = {}
    for k, v in spec.items():
        if k == "type":
            continue
        f = cls.model_fields.get(k)
        if f is None:
            raise ValueError(f"{kind} '{t}' 不支持字段 '{k}'。可用: {[n for n in cls.model_fields if n!='type']}")
        if "Value" in str(f.annotation):
            # pyfebio 的 Value：lc 属性(必须指向已定义的载荷曲线) + text 子元素
            if isinstance(v, dict):
                kwargs[k] = feb_bc.Value(**v)
            else:
                kwargs[k] = feb_bc.Value(lc=default_lc_id, text=v)
        else:
            kwargs[k] = v
    return cls(**kwargs)


def _apply_geometry(spec: dict) -> tuple[MeshData, str]:
    """按 geometry spec 生成网格。"""
    g = spec.get("geometry", {"type": "box"})
    gt = g.get("type", "box")
    part = g.get("part_name", "Part1")
    from meshing import gmsh_builder as gb

    if gt == "box":
        md = gb.generate_box(
            size=tuple(g.get("size", (1, 1, 1))),
            origin=tuple(g.get("origin", (0, 0, 0))),
            mesh_size=g.get("mesh_size", 0.1),
            elem_type=g.get("elem_type", "tet"),
            order=g.get("order", 1),
        )
    elif gt == "cylinder":
        md = gb.generate_cylinder(
            radius=g.get("radius", 0.5),
            height=g.get("height", 1.0),
            mesh_size=g.get("mesh_size", 0.1),
            origin=tuple(g.get("origin", (0, 0, 0))),
            order=g.get("order", 1),
        )
    elif gt == "sphere":
        md = gb.generate_sphere(
            radius=g.get("radius", 0.5),
            mesh_size=g.get("mesh_size", 0.1),
            origin=tuple(g.get("origin", (0, 0, 0))),
            order=g.get("order", 1),
        )
    elif gt == "disc":
        md = gb.generate_disc(
            radius=g.get("radius", 5.0),
            height=g.get("height", 1.0),
            mesh_size=g.get("mesh_size", 0.5),
            n_layers=g.get("n_layers", 1),
            order=g.get("order", 1),
        )
    else:
        raise ValueError(f"未知几何类型 '{gt}'。支持: box / cylinder / sphere / disc")
    return md, part


def build_from_spec(spec: dict, out_path: str | Path) -> dict:
    """从 JSON spec 生成 .feb 文件。

    spec 结构示例见 docs/SPEC.md。
    """
    module = spec.get("module")
    b = ModelBuilder(name=spec.get("name", "model"), module=module)

    # 网格
    md, part = _apply_geometry(spec)
    parts = b.add_mesh_data(md, name=part)

    # 材料
    mat_names: list[str] = []
    for m in spec.get("materials", []):
        mat_names.append(b.add_material(m))

    # 域：若网格被拆成多个 part，而 spec 只给了一个域，则自动覆盖到全部 part
    domain_specs = spec.get("domains") or [{"name": part, "mat": mat_names[0] if mat_names else "material"}]
    for d in domain_specs:
        dname = d.get("name", part)
        targets = parts if (dname == part and len(parts) > 1) else [dname]
        for t in targets:
            if d.get("kind", "solid") == "shell":
                b.add_shell_domain(t, d["mat"], d.get("thickness", 0.01), d.get("type"))
            else:
                b.add_solid_domain(t, d["mat"], d.get("type"))

    # 载荷曲线：始终保证存在一条「恒定 1.0」曲线，供未显式指定 lc 的 value 引用。
    # （FEBio 要求 <value lc="N"> 中的 N 必须指向已定义的载荷曲线；lc 不能为 0。）
    lc_specs = list(spec.get("loaddata", []))
    used_ids = {int(lc["id"]) for lc in lc_specs}
    default_lc_id = 1
    while default_lc_id in used_ids:
        default_lc_id += 1
    b.add_load_curve(default_lc_id, ["0,1", "1,1"], interpolate="LINEAR")
    for lc in lc_specs:
        b.add_load_curve(lc["id"], lc["points"], lc.get("interpolate", "LINEAR"))

    # 边界
    for bc in spec.get("boundary", []):
        b.add_bc(_build_section_item(_BC_REGISTRY, bc, "边界条件", default_lc_id))

    # 载荷
    for ld in spec.get("loads", []):
        b.add_load(_build_section_item(_LOAD_REGISTRY, ld, "载荷", default_lc_id))

    # 控制
    ctrl = dict(spec.get("control", {}))
    # 若指定 analysis 需要匹配的 solver
    if "solver" in ctrl and isinstance(ctrl["solver"], str):
        sname = ctrl["solver"].lower()
        if sname in ("solid", "default"):
            ctrl["solver"] = feb_ctrl.SolidSolver()
        elif sname == "biphasic":
            ctrl["solver"] = feb_ctrl.BiphasicSolver()
        elif sname == "multiphasic":
            ctrl["solver"] = feb_ctrl.MultiphasicSolver()
        else:
            raise ValueError(f"未知 solver '{ctrl['solver']}'")
    if ctrl:
        b.set_control(**ctrl)

    p = b.save(out_path)
    return {
        "path": str(p),
        "name": spec.get("name", "model"),
        "materials": mat_names,
        "mesh": md.summary(),
        "n_bc": len(spec.get("boundary", [])),
        "n_loads": len(spec.get("loads", [])),
    }
