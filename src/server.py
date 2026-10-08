"""FEBio MCP Server —— AI 全流程驱动 FEBio 有限元仿真。

覆盖链路：离线知识检索 -> 参数化建模 -> 网格生成 -> 求解 -> 后处理（曲线 / 伪彩 / 三维离屏渲染）-> GUI 控制。

运行（stdio，供 MCP 客户端连接）：
    python -m src.server
环境变量：
    FEBIO_EXE / FEBIO_HOME / FEBIO_DOC / FEBIO_SDK / FEBIO_WORKSPACE / FEBIO_TIMEOUT
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 允许 `python src/server.py` 与 `python -m src.server` 两种方式
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from mcp.server.mcpserver import MCPServer  # noqa: E402

import config as cfg  # noqa: E402

server = MCPServer(
    "febio",
    version="1.0.0",
    instructions=(
        "FEBio 有限元仿真全流程助手。典型工作流：\n"
        "1) 用 febio_search_docs / febio_material_info 查清材料与边界条件的正确写法；\n"
        "2) 用 febio_build_model 生成 .feb（几何用 box/cylinder/sphere/disc）；\n"
        "3) 用 febio_run 或 febio_submit 求解；\n"
        "4) 用 febio_results_summary / febio_extract_history / febio_plot_* 看结果，\n"
        "   要三维实体云图（真实单元面、单元场、多视角）用 febio_render_field（离屏，无需 GUI）。\n"
        "所有路径默认落在工作区内；长算例请用 febio_submit 异步提交。"
    ),
)


def _err(exc: Exception, hint: str = "") -> dict:
    d = {"error": f"{type(exc).__name__}: {exc}"}
    if hint:
        d["hint"] = hint
    return d


# ============================================================ 环境

@server.tool(name="febio_env_status")
def febio_env_status() -> dict:
    """检查本机 FEBio 环境：可执行文件、手册、SDK、工作区，以及各项能力是否可用。

    首次接入或排查问题时先调用这个。
    """
    return cfg.status()


# ============================================================ 离线知识库

@server.tool(name="febio_search_docs")
def febio_search_docs(query: str, top_k: int = 8, manual: str = "") -> dict:
    """在本地官方 PDF 手册中检索（纯离线）。

    query 支持中文（内置中英术语映射，会自动扩展为英文关键词）。
    manual 可限定手册名片段，如 "User" / "Theory" / "Studio"，留空则全部。
    """
    try:
        from kb import get_kb

        kb = get_kb()
        hits = kb.search(query, top_k=top_k, manual=manual or None)
        if not hits:
            return {
                "query": query,
                "n_hits": 0,
                "note": "未命中。可换用英文关键词（如 'biphasic permeability'），或先用 febio_sdk_modules 看能力清单。",
                "manuals": kb.manual_names(),
            }
        return {"query": query, "n_hits": len(hits), "hits": [h.to_dict() for h in hits]}
    except Exception as exc:
        return _err(exc, "若未找到手册，请设置环境变量 FEBIO_DOC 指向手册目录。")


@server.tool(name="febio_read_manual_page")
def febio_read_manual_page(manual: str, page: int) -> dict:
    """读取某本手册的某一页原文（页码从 1 开始）。"""
    try:
        from kb import get_kb

        txt = get_kb().read_page(manual, page)
        return {"manual": manual, "page": page, "text": txt[:8000]}
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_manual_toc")
def febio_manual_toc(manual: str) -> dict:
    """列出某本手册的章节标题（粗略目录）。"""
    try:
        from kb import get_kb

        return {"manual": manual, "toc": get_kb().toc(manual)}
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_list_materials")
def febio_list_materials(keyword: str = "") -> dict:
    """列出可用的 FEBio 材料类型（来自 pyfebio，即 FEBio 官方类型字符串）。

    keyword 可选，用于过滤，如 "biphasic" / "Mooney" / "Donnan"。
    """
    try:
        from modeling.builder import MATERIAL_REGISTRY, material_types

        types = material_types()
        if keyword:
            k = keyword.lower()
            types = [t for t in types if k in t.lower()]
        return {"n": len(types), "types": types, "note": "用 febio_material_info 查看某类型的参数。"}
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_material_info")
def febio_material_info(material_type: str) -> dict:
    """查看某种材料类型的全部可用参数与默认值（写 spec 时必查）。"""
    try:
        from modeling.builder import MATERIAL_REGISTRY, material_fields

        if material_type not in MATERIAL_REGISTRY:
            return {
                "error": f"未知材料类型 '{material_type}'",
                "available": sorted(MATERIAL_REGISTRY),
            }
        return {"type": material_type, "fields": material_fields(material_type)}
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_material_guide")
def febio_material_guide(material_type: str = "") -> dict:
    """查看材料「参数卡片」：每个参数的含义/单位/取值范围/典型组织取值、最小示例、踩坑清单。

    卡片来自精读官方手册的结构化整理，放在 data/material_guides/。
    material_type 留空则列出已有卡片。
    """
    try:
        import json

        d = cfg.REPO_ROOT / "data" / "material_guides"
        schema = str(cfg.REPO_ROOT / "docs" / "MATERIAL_CARD_SCHEMA.md")
        available = sorted(p.stem for p in d.glob("*.json")) if d.exists() else []
        if not material_type:
            return {"available": available, "schema": schema}
        f = d / f"{material_type}.json"
        if not f.exists():
            return {
                "error": f"尚无 '{material_type}' 的卡片",
                "available": available,
                "hint": "可用 febio_material_info 看原始字段名与默认值；卡片格式见 schema。",
                "schema": schema,
            }
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_sdk_modules")
def febio_sdk_modules() -> dict:
    """列出 FEBio C++ SDK 的模块与各类数量（能力地图，离线）。"""
    try:
        from kb import get_kb

        kb = get_kb()
        if kb.sdk is None:
            return {"error": "未找到 SDK 头文件目录", "hint": "可设置环境变量 FEBIO_SDK。"}
        return {"modules": kb.sdk.modules()}
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_sdk_find")
def febio_sdk_find(keyword: str, limit: int = 30) -> dict:
    """在 FEBio SDK 中按关键词查找类（材料/边界/接触/求解器等）。"""
    try:
        from kb import get_kb

        kb = get_kb()
        if kb.sdk is None:
            return {"error": "未找到 SDK 头文件目录"}
        return {"keyword": keyword, "matches": [c.to_dict() for c in kb.sdk.find(keyword, limit)]}
    except Exception as exc:
        return _err(exc)


# ============================================================ 网格 / 建模

@server.tool(name="febio_generate_mesh")
def febio_generate_mesh(
    geometry: str = "box",
    size: list[float] | None = None,
    radius: float = 0.5,
    height: float = 1.0,
    mesh_size: float = 0.1,
    n_layers: int = 1,
    elem_type: str = "tet",
    order: int = 1,
) -> dict:
    """生成参数化网格并返回摘要（不写文件，用于快速评估网格规模）。

    geometry: box / cylinder / sphere / disc（disc 为圆盘状，可沿 z 轴分层）。
    size 仅对 box 有效，形如 [Lx, Ly, Lz]。
    """
    try:
        from meshing import gmsh_builder as gb

        if geometry == "box":
            md = gb.generate_box(size=tuple(size or (1, 1, 1)), mesh_size=mesh_size,
                                 elem_type=elem_type, order=order)
        elif geometry == "cylinder":
            md = gb.generate_cylinder(radius=radius, height=height, mesh_size=mesh_size, order=order)
        elif geometry == "sphere":
            md = gb.generate_sphere(radius=radius, mesh_size=mesh_size, order=order)
        elif geometry == "disc":
            md = gb.generate_disc(radius=radius, height=height, mesh_size=mesh_size,
                                  n_layers=n_layers, order=order)
        else:
            return {"error": f"未知几何 '{geometry}'", "available": ["box", "cylinder", "sphere", "disc"]}
        return {"geometry": geometry, **md.summary()}
    except ImportError:
        return {"error": "缺少 gmsh 依赖", "hint": "pip install gmsh"}
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_build_model")
def febio_build_model(spec: dict, out_path: str = "") -> dict:
    """从结构化 spec 一键生成完整的 .feb 模型文件。

    spec 示例（键含义）：
      geometry : {"type":"box","size":[1,1,1],"mesh_size":0.2,"elem_type":"tet"}
      materials: [{"name":"solid","type":"neo-Hookean","E":1000,"v":0.3}]
      domains  : [{"name":"Part1","mat":"solid"}]
      boundary : [{"type":"zero displacement","node_set":"zmin","x_dof":1,"y_dof":1,"z_dof":1}]
      loads    : [{"type":"pressure","surface":"top","value":0.1}]
      loaddata : [{"id":1,"points":["0,0","1,1"]}]
      control  : {"analysis":"STATIC","time_steps":10,"step_size":0.1,"solver":"solid"}
    材料参数用 febio_material_info 查；边界/载荷类型见返回的 available 列表。
    out_path 留空则写到工作区 <name>.feb。
    """
    try:
        from modeling.builder import build_from_spec

        name = spec.get("name", "model")
        if not out_path:
            out_path = str(cfg.WORKSPACE / name / f"{name}.feb")
        return build_from_spec(spec, out_path)
    except Exception as exc:
        return _err(exc, "可用 febio_material_info / febio_search_docs 核对参数名。")


@server.tool(name="febio_validate_model")
def febio_validate_model(feb_path: str) -> dict:
    """离线校验 .feb 文件：XML 语法、必需段、集合引用是否自洽。不调用求解器。"""
    try:
        from lxml import etree

        p = Path(feb_path)
        if not p.exists():
            return {"error": f"文件不存在: {p}"}
        parser = etree.XMLParser(recover=False)
        tree = etree.parse(str(p), parser)
        root = tree.getroot()

        issues: list[str] = []
        ok: list[str] = []

        if root.tag != "febio_spec":
            issues.append(f"根标签应为 febio_spec，实际为 {root.tag}")
        else:
            ok.append(f"根标签 febio_spec, version={root.get('version')}")

        # 收集 mesh 中定义的集合名
        node_sets = {e.get("name") for e in root.findall(".//NodeSet")}
        surfaces = {e.get("name") for e in root.findall(".//Surface")}
        elem_sets = {e.get("name") for e in root.findall(".//ElementSet")}
        parts = {e.get("name") for e in root.findall(".//Elements")} | {e.get("name") for e in root.findall(".//Nodes")}
        mats = {e.get("name") for e in root.findall(".//Material/material")} | {e.get("name") for e in root.findall(".//Material/solid")}

        # 引用检查
        for bc in root.findall(".//Boundary/bc"):
            ns = bc.get("node_set")
            if ns and ns not in node_sets and ns not in parts:
                issues.append(f"边界条件引用了不存在的 node_set: '{ns}'")
        for dom in root.findall(".//SolidDomain"):
            m = dom.get("mat")
            if m and m not in mats:
                issues.append(f"域 '{dom.get('name')}' 引用了不存在的材料: '{m}'")
        for ld in root.findall(".//Loads/*"):
            for attr in ("surface", "node_set"):
                v = ld.get(attr)
                if v and v not in surfaces and v not in node_sets:
                    issues.append(f"载荷引用了不存在的 {attr}: '{v}'")

        for seg in ("Mesh", "Material", "MeshDomains", "Control"):
            if root.find(seg) is None:
                issues.append(f"缺少必需段 <{seg}>")

        if node_sets:
            ok.append(f"node_sets: {sorted(node_sets)}")
        if mats:
            ok.append(f"materials: {sorted(m for m in mats if m)}")

        return {"path": str(p), "valid": not issues, "issues": issues, "ok": ok}
    except Exception as exc:
        return _err(exc)


# ============================================================ 求解

def _runner():
    from solver.runner import FebioRunner

    return FebioRunner()


@server.tool(name="febio_run")
def febio_run(
    feb_path: str,
    out_dir: str = "",
    timeout: int = 0,
    silent: bool = True,
    debug: bool = False,
    task: str = "",
    restart: str = "",
    dump: str = "",
) -> dict:
    """同步运行一个 FEBio 算例并等待结束（适合小模型）。

    大模型请改用 febio_submit 异步提交，避免长时间阻塞。
    timeout 为秒，0 表示用默认值（环境变量 FEBIO_TIMEOUT，默认 3600）。
    """
    try:
        kw: dict[str, Any] = {"silent": silent, "debug": debug}
        if task:
            kw["task"] = task
        if restart:
            kw["restart"] = restart
        if dump:
            kw["dump"] = dump
        job = _runner().run_sync(feb_path, out_dir or None, timeout or None, **kw)
        from solver.logparser import parse_log

        d = job.to_dict()
        d["log"] = parse_log(job.log_file).to_dict()
        return d
    except Exception as exc:
        return _err(exc, "确认 febio4 可用（febio_env_status）。")


@server.tool(name="febio_submit")
def febio_submit(feb_path: str, out_dir: str = "", silent: bool = True, debug: bool = False) -> dict:
    """后台提交一个 FEBio 算例，立即返回 job_id。用 febio_job_status 查进度。"""
    try:
        job = _runner().start(feb_path, out_dir or None, silent=silent, debug=debug)
        return job.to_dict()
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_job_status")
def febio_job_status(job_id: str, with_log: bool = True) -> dict:
    """查询作业状态；with_log=True 时附带日志摘要（收敛/错误）。"""
    try:
        return _runner().status(job_id, with_log=with_log)
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_list_jobs")
def febio_list_jobs(limit: int = 20) -> dict:
    """列出最近的作业（含历史，持久化在 workspace/jobs.json）。"""
    try:
        return {"jobs": _runner().list_jobs(limit)}
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_kill_job")
def febio_kill_job(job_id: str) -> dict:
    """终止一个正在运行的作业。"""
    try:
        return _runner().kill(job_id)
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_read_log")
def febio_read_log(path_or_job: str) -> dict:
    """解析 FEBio 日志（接受 .log 路径或 job_id）：终止状态、时间步、错误与警告。"""
    try:
        p = Path(path_or_job)
        if p.exists():
            from solver.logparser import parse_log

            return parse_log(p).to_dict()
        return _runner().read_log(path_or_job)
    except Exception as exc:
        return _err(exc)


# ============================================================ 后处理

@server.tool(name="febio_results_summary")
def febio_results_summary(xplt_path: str) -> dict:
    """概览一个 .xplt 结果文件：状态数、时间点、可用变量与 parts。"""
    try:
        from post.results import Results

        return Results(xplt_path).summary()
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_get_field")
def febio_get_field(
    xplt_path: str,
    variable: str,
    kind: str = "node_data",
    part: str = "",
    state: int = -1,
    component: int = -1,
    reduce: str = "",
) -> dict:
    """读取某状态下的场数据，返回统计量（不返回全部数组，避免过大）。

    kind: node_data / element_data。state=-1 为最后一步。
    reduce 留空时返回各分量的 min/max/mean；指定 component 只看该分量。
    """
    try:
        import numpy as np

        from post.results import Results

        r = Results(xplt_path)
        arr = r.get(variable, kind=kind, part=part or None, state=state)
        if isinstance(arr, dict):
            merged = np.concatenate([np.asarray(v) for v in arr.values()], axis=0).astype(float)
            parts = list(arr.keys())
        else:
            merged = np.asarray(arr).astype(float)
            parts = [part]
        if component >= 0:
            merged = merged[..., component] if merged.ndim > 1 else merged
        if reduce:
            from post.results import _reduce

            return {"variable": variable, "kind": kind, "parts": parts, "state": state,
                    "reduce": reduce, "value": _reduce(merged, reduce)}
        return {
            "variable": variable, "kind": kind, "parts": parts, "state": state,
            "shape": list(merged.shape),
            "min": float(np.min(merged)),
            "max": float(np.max(merged)),
            "mean": float(np.mean(merged)),
        }
    except Exception as exc:
        return _err(exc, "先用 febio_results_summary 看有哪些变量。")


@server.tool(name="febio_extract_history")
def febio_extract_history(
    xplt_path: str,
    variable: str,
    kind: str = "node_data",
    part: str = "",
    component: int = -1,
    reduce: str = "mean",
    node_set: str = "",
) -> dict:
    """沿时间提取某变量的历史曲线（时间-数值对）。

    例如提取顶面位移 z 分量：variable="displacement", component=2, node_set="zmax", reduce="mean"。
    """
    try:
        from post.results import Results

        return Results(xplt_path).history(
            variable, kind=kind, part=part or None,
            component=component if component >= 0 else None, reduce=reduce,
            node_set=node_set or None,
        )
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_plot_curves")
def febio_plot_curves(
    curves: list[dict],
    out_path: str = "",
    title: str = "结果曲线",
    xlabel: str = "时间",
    ylabel: str = "数值",
    logy: bool = False,
) -> dict:
    """画曲线图并保存 PNG。

    curves: [{"label":"载荷-位移","x":[...],"y":[...]}, ...]
    out_path 留空则存到工作区 figures/。
    """
    try:
        from post.plots import plot_curves

        if not out_path:
            out_path = str(cfg.WORKSPACE / "figures" / "curves.png")
        p = plot_curves(curves, out_path, title=title, xlabel=xlabel, ylabel=ylabel, logy=logy)
        return {"ok": True, "path": str(p)}
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_plot_field")
def febio_plot_field(
    xplt_path: str,
    variable: str,
    out_path: str = "",
    state: int = -1,
    component: int = -1,
    title: str = "",
) -> dict:
    """把节点场数据画成 3D 伪彩图并保存 PNG。"""
    try:
        from post.plots import plot_field
        from post.results import Results

        r = Results(xplt_path)
        arr = r.get(variable, kind="node_data", state=state)
        import numpy as np

        vals = np.concatenate([np.asarray(v) for v in arr.values()], axis=0) if isinstance(arr, dict) else np.asarray(arr)
        if not out_path:
            out_path = str(cfg.WORKSPACE / "figures" / f"{variable}.png")
        p = plot_field(r.nodes(), vals, out_path, title=title or variable,
                       cbar_label=variable, component=component if component >= 0 else None)
        return {"ok": True, "path": str(p)}
    except Exception as exc:
        return _err(exc)


@server.tool(name="febio_render_field")
def febio_render_field(
    xplt_path: str,
    variable: str,
    out_path: str = "",
    kind: str = "node_data",
    part: str = "",
    state: int = -1,
    component: int = -1,
    cmap: str = "turbo",
    view: str = "iso",
    show_edges: bool = False,
    opacity: float = 1.0,
    clim: list[float] | None = None,
    width: int = 1280,
    height: int = 960,
    background: str = "white",
    scalar_bar_title: str = "",
    show_axes: bool = True,
) -> dict:
    """离屏三维渲染：把结果场画成带真实单元面、光照与色标的 PNG（不需要 GUI）。

    与 febio_plot_field 的区别：那个只把节点撒成散点伪彩图；本工具按真实单元拓扑
    建面、支持单元场（如 stress / heat flux）、多视角与色标范围控制。
    渲染引擎与 FEBioStudio 同为 VTK，只是走离屏模式，可用于批处理与无桌面环境。

    xplt_path  : .xplt 或已转好的 .hdf5
    variable   : 变量名，如 "temperature"、"displacement"、"stress"
    kind       : "node_data" 或 "element_data"
    part       : 只渲染某个 part；留空表示全部
    state      : 时间点下标，-1 为最后一步
    component  : 多分量场取哪一分量（0/1/2...）；-1 表示取模
    view       : 相机所在侧面——iso(等轴测) / front(+y) / back(-y) /
                 right(+x) / left(-x) / top(+z 俯视) / bottom(-z 仰视)
    clim       : 色标范围 [min, max]；留空自动
    """
    try:
        import importlib.util

        if importlib.util.find_spec("pyvista") is None:
            return _err(
                ImportError("未安装 pyvista"),
                hint="三维渲染需要 pyvista：pip install 'pyvista>=0.49'（会自动带上 vtk）。",
            )
        from post.render3d import render_field
    except ImportError as exc:
        return _err(exc)

    try:
        if not out_path:
            out_path = str(cfg.WORKSPACE / "figures" / f"{variable}_3d.png")
        p = render_field(
            xplt_path,
            out_path,
            variable,
            kind=kind,
            part=part or None,
            state=state,
            component=component if component >= 0 else None,
            cmap=cmap,
            view=view,
            show_edges=show_edges,
            opacity=opacity,
            clim=(float(clim[0]), float(clim[1])) if clim else None,
            window_size=(int(width), int(height)),
            background=background,
            scalar_bar_title=scalar_bar_title,
            show_axes=show_axes,
        )
        return {"ok": True, "path": str(p), "variable": variable, "kind": kind, "view": view}
    except Exception as exc:
        return _err(exc)


# ============================================================ FEBioStudio GUI

_studio = None


def _get_studio():
    global _studio
    if _studio is None:
        from gui.studio import StudioController

        _studio = StudioController()
    return _studio


@server.tool(name="febio_studio_status")
def febio_studio_status() -> dict:
    """检查 FEBioStudio GUI 控制是否可用（仅 Windows）。"""
    from gui.studio import available

    ok, msg = available()
    return {"available": ok, "message": msg, "studio_path": str(cfg.FEBIO_STUDIO) if cfg.FEBIO_STUDIO else None}


@server.tool(name="febio_studio_launch")
def febio_studio_launch(file: str = "") -> dict:
    """启动 FEBioStudio（可选直接打开某个 .feb 或模型文件）。"""
    return _get_studio().launch(file or None)


@server.tool(name="febio_studio_screenshot")
def febio_studio_screenshot(out_path: str = "") -> dict:
    """截取 FEBioStudio 窗口。"""
    if not out_path:
        out_path = str(cfg.WORKSPACE / "figures" / "studio.png")
    return _get_studio().screenshot(out_path)


@server.tool(name="febio_studio_menu")
def febio_studio_menu(path: list[str] | None = None) -> dict:
    """列出主菜单；传入 path 则点击该菜单，如 ["Run","Run FEBio"]。"""
    c = _get_studio()
    return c.click_menu(path) if path else c.menu_items()


@server.tool(name="febio_studio_run")
def febio_studio_run() -> dict:
    """在 FEBioStudio 中触发一次分析。"""
    return _get_studio().run_analysis()


@server.tool(name="febio_studio_close")
def febio_studio_close(force: bool = False) -> dict:
    """关闭 FEBioStudio 进程。"""
    return _get_studio().close(force=force)


# ============================================================ 入口

def main() -> None:
    transport = "stdio"
    if len(sys.argv) > 1 and sys.argv[1] in ("stdio", "sse", "streamable-http"):
        transport = sys.argv[1]
    server.run(transport=transport)


if __name__ == "__main__":
    main()
