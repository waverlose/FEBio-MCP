"""结果后处理：读取 FEBio 的 .xplt 结果文件。

流程：.xplt --(pyfebio.xplt.to_hdf5)--> .hdf5 --(h5py)--> numpy。

HDF5 结构（由 pyfebio 定义）：
    /meshes/0/nodes                    [('id','x','y','z')]
    /meshes/0/domains/<part>           (n_elem, 1+n_nodes) 第0列为单元 id
    /meshes/0/nodesets/<name>
    /states/<k>.attrs['time']          该状态对应的时间
    /states/<k>/node_data/<var>/<part>  (n_nodes, comps)
    /states/<k>/element_data/<var>/<part> (n_elem, comps)
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np


class Results:
    """一个 .xplt 结果的读取器（首次访问时自动转 HDF5 并缓存）。"""

    def __init__(self, xplt_path: str | Path, h5_path: str | Path | None = None, rebuild: bool = False):
        self.xplt = Path(xplt_path)
        if not self.xplt.exists():
            raise FileNotFoundError(f"结果文件不存在: {self.xplt}")
        self.h5 = Path(h5_path) if h5_path else self.xplt.with_suffix(".hdf5")
        if rebuild or not self.h5.exists() or self.h5.stat().st_mtime < self.xplt.stat().st_mtime:
            self._convert()

    def _convert(self) -> None:
        from pyfebio.xplt import to_hdf5

        to_hdf5(self.xplt, self.h5)

    # -------------------------------------------------- 概览
    def states(self) -> list[dict]:
        """所有输出状态（时间点）。"""
        out = []
        with h5py.File(self.h5, "r") as f:
            st = f.get("states")
            if st is None:
                return out
            for k in sorted(st.keys(), key=lambda s: int(s)):
                a = dict(st[k].attrs)
                t = a.get("time")
                if t is not None:
                    arr = np.asarray(t).ravel()
                    t = float(arr[0]) if arr.size else None
                out.append({
                    "index": int(k),
                    "time": t,
                    "vars": {
                        kind: list(st[k][kind].keys())
                        for kind in ("node_data", "element_data", "surface_data")
                        if kind in st[k]
                    },
                })
        return out

    def variables(self) -> dict[str, list[str]]:
        with h5py.File(self.h5, "r") as f:
            st = f["states"]
            if not st.keys():
                return {}
            first = sorted(st.keys(), key=lambda s: int(s))[0]
            return {
                kind: list(st[first][kind].keys())
                for kind in ("node_data", "element_data", "surface_data")
                if kind in st[first]
            }

    def parts(self, kind: str = "node_data", var: str | None = None) -> list[str]:
        with h5py.File(self.h5, "r") as f:
            st = f["states"]
            first = sorted(st.keys(), key=lambda s: int(s))[0]
            g = st[first].get(kind)
            if g is None:
                return []
            name = var or list(g.keys())[0]
            return list(g[name].keys())

    def nodes(self, mesh: int = 0) -> np.ndarray:
        with h5py.File(self.h5, "r") as f:
            return f[f"meshes/{mesh}/nodes"][:]

    def node_sets(self, mesh: int = 0) -> dict[str, np.ndarray]:
        out = {}
        with h5py.File(self.h5, "r") as f:
            g = f.get(f"meshes/{mesh}/nodesets")
            if g is not None:
                for k in g.keys():
                    out[k] = g[k][:]
        return out

    def elements(self, part: str, mesh: int = 0) -> np.ndarray:
        with h5py.File(self.h5, "r") as f:
            return f[f"meshes/{mesh}/domains/{part}"][:]

    # -------------------------------------------------- 取值
    def get(
        self,
        variable: str,
        kind: str = "node_data",
        part: str | None = None,
        state: int = -1,
    ) -> np.ndarray:
        """取某个状态下的场数据。state=-1 表示最后一步。"""
        with h5py.File(self.h5, "r") as f:
            st = f["states"]
            keys = sorted(st.keys(), key=lambda s: int(s))
            key = keys[state]
            g = st[key].get(kind)
            if g is None:
                raise KeyError(f"该状态无 '{kind}'，可用: {list(st[key].keys())}")
            if variable not in g:
                raise KeyError(f"变量 '{variable}' 不存在，可用: {list(g.keys())}")
            vg = g[variable]
            if part:
                if part not in vg:
                    raise KeyError(f"part '{part}' 不存在，可用: {list(vg.keys())}")
                return vg[part][:]
            return {p: vg[p][:] for p in vg.keys()}

    def history(
        self,
        variable: str,
        kind: str = "node_data",
        part: str | None = None,
        component: int | None = None,
        reduce: str = "mean",
        node_set: str | None = None,
    ) -> dict:
        """沿时间提取某个变量的历史曲线。

        reduce: mean / max / min / norm / absmax / sum
        component: 指定分量下标（如位移的 z 分量为 2）
        node_set: 只统计某个节点集（如 "zmax" 看顶面位移）
        """
        idx = self._node_indices(node_set) if node_set else None
        times: list[float] = []
        values: list[float] = []
        with h5py.File(self.h5, "r") as f:
            st = f["states"]
            for k in sorted(st.keys(), key=lambda s: int(s)):
                grp = st[k]
                t = dict(grp.attrs).get("time")
                g = grp.get(kind)
                if g is None or variable not in g:
                    continue
                vg = g[variable]
                parts = [part] if part else list(vg.keys())
                chunks = []
                for p in parts:
                    if p in vg:
                        chunks.append(vg[p][:])
                if not chunks:
                    continue
                arr = np.concatenate(chunks, axis=0).astype(float)
                if idx is not None and kind == "node_data" and idx.size and idx.max() < arr.shape[0]:
                    arr = arr[idx]
                if component is not None:
                    arr = arr[..., component]
                values.append(_reduce(arr, reduce))
                if t is not None:
                    ta = np.asarray(t).ravel()
                    t = float(ta[0]) if ta.size else None
                times.append(float(t) if t is not None else float(len(times)))
        return {"variable": variable, "kind": kind, "part": part, "node_set": node_set,
                "reduce": reduce, "component": component,
                "times": times, "values": values}

    def _node_indices(self, node_set: str) -> np.ndarray | None:
        """把节点集名转换成节点数组的 0-based 下标。

        ⚠ 重要：FEBio 的 plot 文件（以及 pyfebio 转出的 HDF5）里，
        `meshes/<m>/nodesets/<name>` 存的**已经是 0-based 数组下标，不是节点 id**。
        实测依据：某模型 xmin 集合存 [68]，按 0-based 下标取到的 x 恰为全局最小值；
        按节点 id 取则不是。因此这里直接沿用原值。

        仅当取值越界（max >= 节点总数，说明该文件存的确实是 id）时，
        才回退到按节点 id 查找。历史上这里误当 id 处理，
        导致每个集合混入相邻节点、结果整体错位一位。
        """
        try:
            raw = self.node_sets().get(node_set)
            if raw is None:
                return None
            idx = np.asarray(raw).ravel().astype(np.int64)
            if idx.size == 0:
                return idx
            n_nodes = int(np.asarray(self.nodes()["id"]).ravel().size)
            if idx.max() < n_nodes:
                return idx
            node_ids = np.asarray(self.nodes()["id"]).ravel()
            order = np.argsort(node_ids)
            pos = np.searchsorted(node_ids[order], idx)
            return order[pos]
        except Exception:
            return None

    def summary(self) -> dict:
        st = self.states()
        vars_ = self.variables()
        return {
            "xplt": str(self.xplt),
            "hdf5": str(self.h5),
            "n_states": len(st),
            "times": [s["time"] for s in st],
            "variables": vars_,
            "parts": {k: self.parts(k) for k in vars_},
        }

    def human(self) -> str:
        s = self.summary()
        L = [f"# 结果概览: {self.xplt.name}"]
        L.append(f"状态数: {s['n_states']}  时间点: {s['times']}")
        L.append("可用变量:")
        for kind, vs in s["variables"].items():
            L.append(f"  [{kind}] {vs}")
            L.append(f"      parts: {s['parts'].get(kind)}")
        return "\n".join(L)


def _reduce(arr: np.ndarray, mode: str) -> float:
    a = arr
    if mode == "mean":
        return float(np.mean(a))
    if mode == "max":
        return float(np.max(a))
    if mode == "min":
        return float(np.min(a))
    if mode == "absmax":
        return float(np.max(np.abs(a)))
    if mode == "norm":
        return float(np.linalg.norm(a))
    if mode == "sum":
        return float(np.sum(a))
    raise ValueError(f"未知 reduce 模式 '{mode}'，可用: mean/max/min/absmax/norm/sum")
