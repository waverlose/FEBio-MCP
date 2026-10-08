"""三维结果渲染（无头 VTK）。

FEBio 本体没有渲染器；FEBioStudio 的渲染必须打开 GUI。本模块用 VTK（经 pyvista）
在**离屏**状态下把结果渲染成图片：真实单元面、光照、色标、多视角，
不依赖任何 GUI 会话，可用于批处理与无桌面环境。

数据来源是本服务已有的 HDF5（由 pyfebio 从 .xplt 转出），
因此不引入新的求解侧依赖。

说明：FEBioStudio 的图形视图同样基于 VTK（其可执行文件静态链接了 VTK），
本模块与它**共用同一套渲染引擎**，差别主要在配色预设与交互界面。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .results import Results

# ---------------------------------------------------------------- 单元类型

# FEBio 绘图文件的元素类型编码。
# 来源：FEBio SDK 的 `FEBioPlot/FEBioPlotFile.h` 中的 `enum Elem_Type`。
# 注意：这**不是** FECore 的 `FE_Element_Type`，两者顺序不同，不可混用。
_PLT_ELEM = {
    0: "hex8",
    1: "penta6",
    2: "tet4",
    3: "quad4",
    4: "tri3",
    5: "line2",
    6: "hex20",
    7: "tet10",
    8: "tet15",
    9: "hex27",
    10: "tri6",
    11: "quad8",
    12: "quad9",
    13: "penta15",
    14: "tet20",
    15: "tri10",
    16: "pyra5",
    17: "tet5",
    18: "pyra13",
    19: "line3",
}

# FEBio 单元类型 -> (VTK 单元类型码, 节点数)
_VTK_CELL: dict[str, tuple[int, int]] = {
    "hex8": (12, 8),      # VTK_HEXAHEDRON
    "hex20": (25, 20),    # VTK_QUADRATIC_HEXAHEDRON
    "hex27": (29, 27),    # VTK_TRIQUADRATIC_HEXAHEDRON
    "tet4": (10, 4),      # VTK_TETRA
    "tet10": (24, 10),    # VTK_QUADRATIC_TETRA
    "penta6": (13, 6),    # VTK_WEDGE
    "penta15": (26, 15),  # VTK_QUADRATIC_WEDGE
    "pyra5": (14, 5),     # VTK_PYRAMID
    "quad4": (9, 4),      # VTK_QUAD
    "quad8": (23, 8),     # VTK_QUADRATIC_QUAD
    "quad9": (28, 9),     # VTK_BIQUADRATIC_QUAD
    "tri3": (5, 3),       # VTK_TRIANGLE
    "tri6": (22, 6),      # VTK_QUADRATIC_TRIANGLE
}

# 由节点数反推单元类型（当 etype 不可用或越界时兜底）。
# 仅覆盖实体单元常见的节点数，避免把 4 节点的面单元误判成四面体。
_NODES_TO_ELEM = {8: "hex8", 4: "tet4", 6: "penta6", 5: "pyra5",
                  20: "hex20", 10: "tet10", 27: "hex27"}

# 预设视角。视角名 = **相机所在的模型侧面**：
#   front = +y 侧，back = -y 侧，right = +x 侧，left = -x 侧，
#   top = +z 侧（俯视），bottom = -z 侧（仰视）；iso = 等轴测。
#
# 每个视角给两个向量：(相机相对模型的偏移方向, view-up)。
# 注意 pyvista 的 `view_vector(v)` 语义是「相机被放在 焦点 + v*length」，
# 即 **v 由模型指向相机**（不是视线方向）——实测 cpos = focal + v*length，
# 传反了会得到相反一侧的视图。view-up 与视线平行时 VTK 会告警并自行重置，
# 因此俯视/仰视必须显式给 view-up。
_VIEWS: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]] | None] = {
    "iso": None,
    "front": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "back": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "left": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "bottom": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
}


def _pick_component(vals: np.ndarray, component: int | None) -> tuple[np.ndarray, str]:
    """把多分量场压成单分量。component=None 时取模（适合位移/速度/热流）。"""
    v = np.asarray(vals, dtype=float)
    if v.ndim == 1:
        return v, ""
    if component is not None:
        return v[:, component], f"[{component}]"
    if v.shape[1] == 1:
        return v[:, 0], ""
    return np.linalg.norm(v, axis=1), " magnitude"


def build_grid(res: Results, part: str | None = None):
    """把 HDF5 里的网格建成 pyvista 的 UnstructuredGrid。

    返回 (grid, part_ranges)。part_ranges 记录每个 part 占用的单元区间，
    供按 part 取单元场数据时对齐。
    """
    import pyvista as pv

    nodes = res.nodes()
    pts = np.column_stack([nodes["x"], nodes["y"], nodes["z"]]).astype(float)
    n_pts = pts.shape[0]

    # 节点 id -> 0-based 下标（仅在需要回退时使用）
    node_ids = np.asarray(nodes["id"]).ravel().astype(np.int64)
    order = np.argsort(node_ids)
    sorted_ids = node_ids[order]

    def to_index(raw: np.ndarray) -> np.ndarray:
        """把单元连接里的节点编号解析成 0-based 数组下标。

        与 nodesets 的情况一致：FEBio 绘图文件里 `domains` 的单元连接存的
        **已经是 0-based 数组下标，不是节点 id**（实测 `conn` 值域 0..N-1，
        而 `nodes` 的 id 是 1..N）。因此优先直接沿用；
        仅当取值越界时才回退到按节点 id 查找。
        """
        v = np.asarray(raw, dtype=np.int64)
        if v.size and v.min() >= 0 and v.max() < n_pts:
            return v
        pos = np.searchsorted(sorted_ids, v)
        if np.any(pos >= sorted_ids.size) or np.any(sorted_ids[np.clip(pos, 0, sorted_ids.size - 1)] != v):
            raise ValueError("网格连接里出现未定义的节点编号，无法建立单元拓扑。")
        return order[pos]

    all_cells: list[np.ndarray] = []
    all_types: list[int] = []
    part_ranges: dict[str, tuple[int, int]] = {}
    cursor = 0

    with _open_domains(res) as domains:
        names = [part] if part else list(domains.keys())
        for name in names:
            if name not in domains:
                raise KeyError(f"part '{name}' 不存在，可用: {list(domains.keys())}")
            conn = domains[name][:]
            etype = int(_domain_etype(res, name))
            declared = _PLT_ELEM.get(etype)

            n_per = conn.shape[1] - 1
            if declared is None or _VTK_CELL.get(declared, (0, -1))[1] != n_per:
                # etype 不认识或与节点数不符时，按节点数兜底
                declared = _NODES_TO_ELEM.get(n_per)
            if declared is None or declared not in _VTK_CELL:
                raise ValueError(
                    f"无法识别 part '{name}' 的单元类型：etype={etype}, 每单元 {n_per} 个节点。"
                )
            vtk_type, _ = _VTK_CELL[declared]

            # VTK 的单元数组格式为 [n, n1..nk, n, n1..nk, ...]，
            # 即每个单元前必须带一个「节点数」前缀。
            idx = to_index(conn[:, 1:])
            blk = np.empty((conn.shape[0], n_per + 1), dtype=np.int64)
            blk[:, 0] = n_per
            blk[:, 1:] = idx
            all_cells.append(blk.ravel())
            all_types.append(np.full(conn.shape[0], vtk_type, dtype=np.uint8))

            part_ranges[name] = (cursor, cursor + conn.shape[0])
            cursor += conn.shape[0]

    if not all_cells:
        raise ValueError("网格里没有任何单元。")

    cells = np.concatenate(all_cells)
    celltypes = np.concatenate(all_types)
    grid = pv.UnstructuredGrid(cells, celltypes, pts)
    return grid, part_ranges


class _open_domains:
    """按需打开 HDF5 的 domains 组（上下文管理器，避免长期持有文件句柄）。"""

    def __init__(self, res: Results):
        self.res = res
        self._f = None

    def __enter__(self):
        import h5py

        self._f = h5py.File(self.res.h5, "r")
        return self._f["meshes/0/domains"]

    def __exit__(self, *exc):
        if self._f is not None:
            self._f.close()
        return False


def _domain_etype(res: Results, part: str) -> int:
    import h5py

    with h5py.File(res.h5, "r") as f:
        d = f[f"meshes/0/domains/{part}"]
        et = d.attrs.get("etype")
        return int(np.asarray(et).ravel()[0]) if et is not None else -1


def render_field(
    xplt_path: str | Path,
    out_path: str | Path,
    variable: str,
    kind: str = "node_data",
    part: str | None = None,
    state: int = -1,
    component: int | None = None,
    cmap: str = "turbo",
    view: str = "iso",
    show_edges: bool = False,
    opacity: float = 1.0,
    clim: tuple[float, float] | None = None,
    window_size: tuple[int, int] = (1280, 960),
    background: str = "white",
    scalar_bar_title: str = "",
    show_axes: bool = True,
) -> Path:
    """把某个场渲染成 PNG（离屏，无需 GUI）。

    xplt_path  : .xplt 或已转好的 .hdf5
    variable   : 变量名，如 "temperature"、"displacement"、"stress"
    kind       : "node_data" 或 "element_data"
    part       : 只渲染某个 part；None 表示全部
    state      : 时间点下标，-1 为最后一步
    component  : 多分量场取哪一分量；None 表示取模
    view       : 相机所在侧面——iso（等轴测）/ front(+y) / back(-y) /
                 right(+x) / left(-x) / top(+z 俯视) / bottom(-z 仰视)
    clim       : 色标范围 (min, max)；None 表示自动
    """
    import pyvista as pv

    res = Results(xplt_path)
    grid, part_ranges = build_grid(res, part)

    # ---------------------------------------------------------- 取场数据
    label = variable
    if kind == "node_data":
        vals = res.get(variable, "node_data", part, state)
        if isinstance(vals, dict):  # 未指定 part 时返回 {part: 数组}
            vals = np.concatenate([np.atleast_2d(v) for v in vals.values()], axis=0) \
                if len(vals) > 1 else np.atleast_2d(next(iter(vals.values())))
        arr, suffix = _pick_component(vals, component)
        if arr.size != grid.n_points:
            raise ValueError(f"节点场长度 {arr.size} 与节点数 {grid.n_points} 不一致。")
        grid.point_data[variable] = arr
        label = f"{variable}{suffix}"
    elif kind == "element_data":
        vals = res.get(variable, "element_data", part, state)
        if isinstance(vals, dict):
            chunks = []
            for name, v in vals.items():
                a, suffix = _pick_component(v, component)
                chunks.append(a)
                if not label.endswith(suffix):
                    label = f"{variable}{suffix}"
            arr = np.concatenate(chunks)
        else:
            arr, suffix = _pick_component(vals, component)
            label = f"{variable}{suffix}"
        if arr.size != grid.n_cells:
            raise ValueError(f"单元场长度 {arr.size} 与单元数 {grid.n_cells} 不一致。")
        grid.cell_data[variable] = arr
    else:
        raise ValueError("kind 只能是 'node_data' 或 'element_data'。")

    # ---------------------------------------------------------- 渲染
    p = pv.Plotter(off_screen=True, window_size=list(window_size))
    p.set_background(background)
    p.add_mesh(
        grid,
        scalars=variable,
        cmap=cmap,
        clim=clim,
        show_edges=show_edges,
        edge_color="#444444",
        line_width=0.4,
        opacity=opacity,
        smooth_shading=False,
        scalar_bar_args={
            "title": scalar_bar_title or label,
            "vertical": True,
            "title_font_size": 16,
            "label_font_size": 13,
            "n_labels": 5,
        },
    )
    if show_axes:
        p.add_axes(line_width=2, labels_off=False)
    if view not in _VIEWS:
        raise ValueError(f"view 只能是 {list(_VIEWS)}，收到 '{view}'。")
    spec = _VIEWS[view]
    if spec is None:
        p.view_isometric()
    else:
        p.view_vector(spec[0], viewup=spec[1])
    p.camera.zoom(1.15)
    p.enable_anti_aliasing("msaa")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    p.screenshot(str(out))
    p.close()
    return out
