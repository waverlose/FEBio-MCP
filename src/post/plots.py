"""结果可视化（无头 matplotlib）。

输出 PNG 到工作区，供 MCP 客户端展示。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 无 GUI 后端
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

# 中文字体（有则用，无则回落，不影响出图）
for _f in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "Arial Unicode MS"):
    try:
        matplotlib.rcParams["font.sans-serif"] = [_f] + list(matplotlib.rcParams["font.sans-serif"])
        break
    except Exception:
        pass
matplotlib.rcParams["axes.unicode_minus"] = False


def plot_curves(
    curves: list[dict],
    out_path: str | Path,
    title: str = "结果曲线",
    xlabel: str = "时间",
    ylabel: str = "数值",
    logy: bool = False,
) -> Path:
    """画一条或多条曲线。

    curves: [{"label": str, "x": [...], "y": [...]}, ...]
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=130)
    for c in curves:
        ax.plot(c["x"], c["y"], marker="o", markersize=3, linewidth=1.6, label=c.get("label", ""))
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if logy:
        ax.set_yscale("log")
    ax.grid(True, alpha=0.3)
    if any(c.get("label") for c in curves):
        ax.legend()
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_field(
    coords: np.ndarray,
    values: np.ndarray,
    out_path: str | Path,
    title: str = "场分布",
    cbar_label: str = "",
    component: int | None = None,
) -> Path:
    """画节点场分布（3D 散点着色）。

    coords: (N,3) 或结构化数组 [('id','x','y','z')]
    values: (N,) 或 (N,comps)
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if coords.dtype.names:  # 结构化数组
        xyz = np.column_stack([coords["x"], coords["y"], coords["z"]]).astype(float)
    else:
        xyz = np.asarray(coords, dtype=float)[:, :3]

    v = np.asarray(values, dtype=float)
    if v.ndim > 1:
        v = v[:, component] if component is not None else np.linalg.norm(v, axis=1)

    fig = plt.figure(figsize=(7.2, 5.4), dpi=130)
    ax = fig.add_subplot(111, projection="3d")
    sc = ax.scatter(xyz[:, 0], xyz[:, 1], xyz[:, 2], c=v, cmap="turbo", s=22)
    ax.set_title(title)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    fig.colorbar(sc, ax=ax, shrink=0.65, label=cbar_label or "value")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out
