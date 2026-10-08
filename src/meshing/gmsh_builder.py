"""参数化网格生成（gmsh -> FEBio）。

支持常见参数化几何：
  - box      长方体
  - cylinder 圆柱
  - sphere   球
  - disc     圆盘状（沿 z 轴分层的圆柱，可指定层数）

输出中立的 MeshData（节点 / 单元 / 节点集），再由 modeling 层组装进 .feb。
单元类型映射到 FEBio 命名（tet4 / hex8 / tet10 / hex20 ...）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

# gmsh MSH 单元类型 -> (FEBio 名称, 节点数)
GMSH_TO_FEBIO = {
    1: ("line2", 2),
    2: ("tri3", 3),
    3: ("quad4", 4),
    4: ("tet4", 4),
    5: ("hex8", 8),
    6: ("penta6", 6),
    7: ("pyra5", 5),
    9: ("tri6", 6),
    10: ("quad9", 9),
    11: ("tet10", 10),
    17: ("hex20", 20),
}

# gmsh MSH 单元类型 -> 单元维度
GMSH_DIM = {1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 3, 7: 3, 9: 2, 10: 2, 11: 3, 17: 3}


@dataclass
class MeshData:
    """与具体软件解耦的网格容器。"""

    nodes: dict[int, tuple[float, float, float]] = field(default_factory=dict)
    elements: dict[str, list[tuple[int, list[int]]]] = field(default_factory=dict)
    node_sets: dict[str, list[int]] = field(default_factory=dict)
    surface_sets: dict[str, list[tuple[str, list[int]]]] = field(default_factory=dict)
    bbox: tuple[float, float, float, float, float, float] | None = None

    @property
    def n_nodes(self) -> int:
        return len(self.nodes)

    @property
    def n_elements(self) -> int:
        return sum(len(v) for v in self.elements.values())

    def summary(self) -> dict:
        return {
            "n_nodes": self.n_nodes,
            "n_elements": self.n_elements,
            "element_types": {k: len(v) for k, v in self.elements.items()},
            "node_sets": {k: len(v) for k, v in self.node_sets.items()},
            "surface_sets": {k: len(v) for k, v in self.surface_sets.items()},
            "bbox": self.bbox,
        }


# ------------------------------------------------------------ 通用工具

def _nodes_on_plane(mesh: MeshData, axis: int, value: float, tol: float) -> list[int]:
    out = []
    for nid, (x, y, z) in mesh.nodes.items():
        c = (x, y, z)[axis]
        if abs(c - value) <= tol:
            out.append(nid)
    return out


def _add_face_sets(mesh: MeshData, tol: float, names=("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")) -> None:
    if not mesh.bbox:
        return
    x0, y0, z0, x1, y1, z1 = mesh.bbox
    planes = [
        (0, x0), (0, x1),
        (1, y0), (1, y1),
        (2, z0), (2, z1),
    ]
    for nm, (axis, val) in zip(names, planes):
        ids = _nodes_on_plane(mesh, axis, val, tol)
        if ids:
            mesh.node_sets[nm] = sorted(ids)


# ------------------------------------------------------------ gmsh 后端

def _gmsh_extract(dim: int = 3, elem_order: int = 1) -> MeshData:
    """把当前 gmsh 模型的网格抽取成 MeshData。"""
    import gmsh

    mesh = MeshData()
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    for i, tag in enumerate(node_tags):
        mesh.nodes[int(tag)] = (
            float(coords[3 * i]),
            float(coords[3 * i + 1]),
            float(coords[3 * i + 2]),
        )
    xs = [c[0] for c in mesh.nodes.values()]
    ys = [c[1] for c in mesh.nodes.values()]
    zs = [c[2] for c in mesh.nodes.values()]
    if xs:
        mesh.bbox = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    # 体单元
    for et, etags, enodes in zip(*gmsh.model.mesh.getElements(dim)):
        fname = GMSH_TO_FEBIO.get(int(et))
        if not fname:
            continue
        name, nn = fname
        arr = enodes.reshape(-1, nn)
        lst = mesh.elements.setdefault(name, [])
        for k, tag in enumerate(etags):
            lst.append((int(tag), [int(v) for v in arr[k]]))

    # 面单元（用于表面集）
    for et, etags, enodes in zip(*gmsh.model.mesh.getElements(2)):
        fname = GMSH_TO_FEBIO.get(int(et))
        if not fname:
            continue
        name, nn = fname
        arr = enodes.reshape(-1, nn)
        lst = mesh.surface_sets.setdefault("_all_faces", [])
        for k, tag in enumerate(etags):
            lst.append((name, [int(v) for v in arr[k]]))
    return mesh


def _finish(mesh: MeshData, tol: float | None, add_faces: bool) -> MeshData:
    if add_faces and mesh.bbox:
        span = max(
            mesh.bbox[3] - mesh.bbox[0],
            mesh.bbox[4] - mesh.bbox[1],
            mesh.bbox[5] - mesh.bbox[2],
        )
        _add_face_sets(mesh, tol if tol is not None else span * 1e-4)
    return mesh


def _new_gmsh(verbose: bool = False):
    import gmsh

    # 注意：gmsh.initialize() 默认会调用 signal.signal(SIGINT, SIG_DFL)，
    # 而 MCP 框架（mcp>=2.x）把同步工具函数放在 worker 线程里执行，
    # 非主线程调用 signal.signal 会抛 "ValueError: signal only works in
    # main thread of the main interpreter"，导致网格/建模工具全挂。
    # 用 interruptible=False 跳过信号处理即可（headless 场景不需要 Ctrl-C 中断）。
    try:
        gmsh.initialize(interruptible=False)
    except TypeError:  # 老版本 gmsh 没有该参数
        gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1 if verbose else 0)
    gmsh.option.setNumber("General.Verbosity", 2 if verbose else 0)
    gmsh.model.add("febio_model")
    return gmsh


def _generate_optimize(gmsh, dim: int = 3) -> None:
    """生成网格并做质量优化 —— FEBio 对单元质量敏感，负雅可比多半源于此。"""
    gmsh.model.mesh.generate(dim)
    for algo in ("Netgen", "Laplace", "Relocate2D"):
        try:
            gmsh.model.mesh.optimize(algo, niter=20)
        except Exception:
            continue


# ------------------------------------------------------------ 几何

def generate_box(
    size: tuple[float, float, float] = (1.0, 1.0, 1.0),
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    mesh_size: float = 0.1,
    elem_type: Literal["tet", "hex"] = "tet",
    order: int = 1,
    add_faces: bool = True,
    verbose: bool = False,
) -> MeshData:
    gmsh = _new_gmsh(verbose)
    try:
        gmsh.model.occ.addBox(*origin, *size)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size)
        if elem_type == "hex":
            gmsh.option.setNumber("Mesh.Algorithm", 8)  # Front2D
            gmsh.option.setNumber("Mesh.RecombineAll", 1)
            gmsh.model.mesh.setRecombine(3, 1)
        gmsh.option.setNumber("Mesh.ElementOrder", order)
        _generate_optimize(gmsh, 3)
        mesh = _gmsh_extract(3, order)
    finally:
        gmsh.finalize()
    return _finish(mesh, None, add_faces)


def generate_cylinder(
    radius: float = 0.5,
    height: float = 1.0,
    mesh_size: float = 0.1,
    n_seg: int = 16,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    order: int = 1,
    add_faces: bool = True,
    verbose: bool = False,
) -> MeshData:
    """沿 z 轴、以 origin 为底面中心的圆柱。"""
    gmsh = _new_gmsh(verbose)
    try:
        ox, oy, oz = origin
        gmsh.model.occ.addCylinder(ox, oy, oz, 0, 0, height, radius)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size)
        gmsh.option.setNumber("Mesh.ElementOrder", order)
        _generate_optimize(gmsh, 3)
        mesh = _gmsh_extract(3, order)
    finally:
        gmsh.finalize()
    return _finish(mesh, None, add_faces)


def generate_sphere(
    radius: float = 0.5,
    mesh_size: float = 0.1,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    order: int = 1,
    verbose: bool = False,
) -> MeshData:
    gmsh = _new_gmsh(verbose)
    try:
        ox, oy, oz = origin
        gmsh.model.occ.addSphere(ox, oy, oz, radius)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size)
        gmsh.option.setNumber("Mesh.ElementOrder", order)
        _generate_optimize(gmsh, 3)
        mesh = _gmsh_extract(3, order)
    finally:
        gmsh.finalize()
    return _finish(mesh, None, False)


def generate_disc(
    radius: float = 5.0,
    height: float = 1.0,
    mesh_size: float = 0.5,
    n_layers: int = 1,
    n_seg: int = 16,
    order: int = 1,
    verbose: bool = False,
) -> MeshData:
    """圆盘状几何：沿 z 轴分层的圆柱。

    生成 1 层时等价于圆柱；n_layers>1 时生成多个 z 方向的体，可分别赋材料
    （例如多层结构、涂层基体、分层复合件）。
    """
    gmsh = _new_gmsh(verbose)
    try:
        dz = height / n_layers
        tags = []
        for k in range(n_layers):
            t = gmsh.model.occ.addCylinder(0, 0, k * dz, 0, 0, dz, radius)
            tags.append(t)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size)
        gmsh.option.setNumber("Mesh.ElementOrder", order)
        _generate_optimize(gmsh, 3)
        mesh = _gmsh_extract(3, order)
    finally:
        gmsh.finalize()

    span = max(mesh.bbox[3] - mesh.bbox[0], mesh.bbox[4] - mesh.bbox[1], mesh.bbox[5] - mesh.bbox[2]) if mesh.bbox else 1.0
    tol = span * 1e-4
    # 底面 / 顶面
    if mesh.bbox:
        z0, z1 = mesh.bbox[2], mesh.bbox[5]
        mesh.node_sets["bottom"] = sorted(_nodes_on_plane(mesh, 2, z0, tol))
        mesh.node_sets["top"] = sorted(_nodes_on_plane(mesh, 2, z1, tol))
        # 侧面（半径附近的节点）
        side = []
        for nid, (x, y, z) in mesh.nodes.items():
            if abs((x * x + y * y) ** 0.5 - radius) <= max(tol, mesh_size * 0.35):
                side.append(nid)
        if side:
            mesh.node_sets["lateral"] = sorted(side)
    return mesh


# ------------------------------------------------------------ 由网格导出 .feb 片段

def mesh_to_febio_xml(mesh: MeshData, name: str = "Part1", indent: str = "    ") -> str:
    """把 MeshData 渲染成 FEBio 4 的 <Mesh> ... </Mesh> 段（字符串）。"""
    L: list[str] = []
    L.append(f"{indent}<Mesh>")
    L.append(f'{indent}    <Nodes name="{name}">')
    for nid in sorted(mesh.nodes):
        x, y, z = mesh.nodes[nid]
        L.append(f'{indent}        <node id="{nid}">{x:g},{y:g},{z:g}</node>')
    L.append(f"{indent}    </Nodes>")
    for etype, elems in mesh.elements.items():
        L.append(f'{indent}    <Elements type="{etype}" name="{name}">')
        for eid, conn in elems:
            L.append(f'{indent}        <elem id="{eid}">{"".join(str(c) + "," for c in conn).rstrip(",")}</elem>')
        L.append(f"{indent}    </Elements>")
    for sname, ids in mesh.node_sets.items():
        L.append(f'{indent}    <NodeSet name="{sname}">')
        for nid in ids:
            L.append(f'{indent}        <node id="{nid}"/>')
        L.append(f"{indent}    </NodeSet>")
    L.append(f"{indent}</Mesh>")
    return "\n".join(L)
