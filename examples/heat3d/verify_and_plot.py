# -*- coding: utf-8 -*-
"""三维传热算例：与解析解对账，并出图。"""
from __future__ import annotations

import os
from pathlib import Path

import h5py
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
H5 = HERE / "heat3d.hdf5"
OUT = HERE / "heat3d_verification.png"

K = 1.0
T_TOP = 100.0
LZ = 1.0
Q_THEORY = -K * T_TOP / LZ      # -100 W/m^2

f = h5py.File(H5, "r")
nodes = f["/meshes/0/nodes"][:]
x = nodes["x"].astype(float)
y = nodes["y"].astype(float)
z = nodes["z"].astype(float)

T = f["/states/1/node_data/temperature/block"][:, 0].astype(float)
q = f["/states/1/element_data/heat flux/Part1"][:].astype(float)

T_exact = T_TOP * z / LZ
err = np.abs(T - T_exact)

print("=" * 62)
print("三维固体传热验证  ——  稳态导热，单位立方体")
print("=" * 62)
print(f"网格            : {len(np.unique(z)) - 1} x ... 共 64 hex8 单元 / 125 节点")
print(f"材料            : isotropic Fourier, k = {K}")
print(f"边界            : z=0 -> T=0 (zero temperature) ; z=1 -> T={T_TOP:.0f}")
print()
print(f"节点温度 T       : min {T.min():.6f}  max {T.max():.6f}")
print(f"解析解 T=100z    : min {T_exact.min():.6f}  max {T_exact.max():.6f}")
print(f"最大绝对误差     : {err.max():.3e} K")
print(f"相对误差(峰值)   : {err.max() / T_TOP:.3e}")
print()
print(f"热流 q_z 数值解  : {q[:, 2].mean():.6f}  (min {q[:,2].min():.6f}, max {q[:,2].max():.6f})")
print(f"热流 q_z 解析解  : {Q_THEORY:.6f} W/m^2")
print(f"热流相对误差     : {abs(q[:,2].mean() - Q_THEORY) / abs(Q_THEORY):.3e}")
print()
ok_T = err.max() < 1e-3 * T_TOP
ok_q = abs(q[:, 2].mean() - Q_THEORY) / abs(Q_THEORY) < 1e-3
print(f"温度场判定       : {'通过' if ok_T else '不通过'}")
print(f"热流场判定       : {'通过' if ok_q else '不通过'}")
print("=" * 62)

# ---------------------------------------------------------------- 出图
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

fig = plt.figure(figsize=(14, 4.6))

# (a) 温度 vs z：所有节点 + 解析解
ax1 = fig.add_subplot(1, 3, 1)
ax1.scatter(z, T, s=16, color="#185FA5", alpha=0.65, label="FEBio 数值解", zorder=3)
zz = np.linspace(0, LZ, 100)
ax1.plot(zz, T_TOP * zz / LZ, "--", color="#D85A30", lw=1.8, label="解析解 T = 100z", zorder=2)
ax1.set_xlabel("z")
ax1.set_ylabel("温度 T")
ax1.set_title("(a) 温度沿 z 的分布", fontsize=11)
ax1.legend(fontsize=9, loc="upper left")
ax1.grid(alpha=0.25)

# (b) 热流密度分量
ax2 = fig.add_subplot(1, 3, 2)
zc = np.array([z[f["/meshes/0/domains/Part1"][i][1:] - 1].mean() for i in range(len(q))])
ax2.scatter(zc, q[:, 2], s=18, color="#0F6E56", alpha=0.7, label="FEBio 数值解 $q_z$", zorder=3)
ax2.axhline(Q_THEORY, ls="--", color="#D85A30", lw=1.8, label="解析解 $q_z$ = -100", zorder=2)
ax2.set_xlabel("z")
ax2.set_ylabel("热流密度 $q_z$")
ax2.set_title("(b) 热流密度沿 z 的分布", fontsize=11)
ax2.legend(fontsize=9, loc="upper right")
ax2.grid(alpha=0.25)

# (c) 中截面温度云图
ax3 = fig.add_subplot(1, 3, 3)
sel = np.abs(y - 0.5) < 1e-6
sc = ax3.tricontourf(x[sel], z[sel], T[sel], levels=20, cmap="inferno")
cs = ax3.tricontour(x[sel], z[sel], T[sel], levels=10, colors="w", linewidths=0.5, alpha=0.6)
ax3.clabel(cs, inline=True, fontsize=7, fmt="%.0f")
ax3.set_xlabel("x")
ax3.set_ylabel("z")
ax3.set_title("(c) y=0.5 截面温度场", fontsize=11)
ax3.set_aspect("equal")
fig.colorbar(sc, ax=ax3, label="温度 T", fraction=0.046, pad=0.04)

fig.suptitle("FEBioHeat 插件验证：三维固体稳态导热（k=1, 底面 0 / 顶面 100）", fontsize=12)
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(OUT, dpi=150)
print("图已保存:", OUT)
