# -*- coding: utf-8 -*-
"""三维固体传热验证模型：稳态导热，带解析解对照。

算例：单位立方体 [0,1]^3，底面 z=0 固定 T=0，顶面 z=1 固定 T=100，
      其余四面绝热。各向同性 Fourier 材料，k=1。

理论解（1D 稳态热传导，热流只沿 z 方向）：
    T(z) = 100 * z          线性温度分布
    q_z  = -k dT/dz = -100  热流密度 W/m^2（与 z 无关，恒为常数）

网格：nx*ny*nz 结构化六面体，手工生成，避免混合单元带来的干扰。
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent

NX = NY = NZ = 4          # 每方向单元数
LX = LY = LZ = 1.0        # 立方体边长
K = 1.0                   # 导热系数 W/(m.K)
T_BOTTOM = 0.0
T_TOP = 100.0


def nid(i: int, j: int, k: int) -> int:
    """节点编号（1 起）。"""
    return 1 + i + j * (NX + 1) + k * (NX + 1) * (NY + 1)


def build() -> str:
    L: list[str] = []
    A = L.append

    A('<?xml version="1.0" encoding="ISO-8859-1"?>')
    A('<febio_spec version="4.0">')
    A('\t<Module type="heat"/>')

    A('\t<Control>')
    A('\t\t<analysis>steady-state</analysis>')
    A('\t\t<time_steps>1</time_steps>')
    A('\t\t<step_size>1.0</step_size>')
    A('\t\t<plot_level>PLOT_MAJOR_ITRS</plot_level>')
    A('\t\t<solver type="heat"/>')
    A('\t</Control>')

    A('\t<Material>')
    A('\t\t<material id="1" name="block" type="isotropic Fourier">')
    A('\t\t\t<density>1.0</density>')
    A(f'\t\t\t<k>{K}</k>')
    A('\t\t\t<c>1.0</c>')
    A('\t\t</material>')
    A('\t</Material>')

    A('\t<Mesh>')

    # 节点
    A(f'\t\t<Nodes name="block">')
    for k in range(NZ + 1):
        for j in range(NY + 1):
            for i in range(NX + 1):
                x = LX * i / NX
                y = LY * j / NY
                z = LZ * k / NZ
                A(f'\t\t\t<node id="{nid(i, j, k)}">{x:.10g},{y:.10g},{z:.10g}</node>')
    A('\t\t</Nodes>')

    # 单元（hex8 标准节点顺序：底面逆时针 → 顶面对应节点）
    A('\t\t<Elements type="hex8" name="Part1" mat="1">')
    eid = 0
    for k in range(NZ):
        for j in range(NY):
            for i in range(NX):
                eid += 1
                ns = [
                    nid(i, j, k), nid(i + 1, j, k), nid(i + 1, j + 1, k), nid(i, j + 1, k),
                    nid(i, j, k + 1), nid(i + 1, j, k + 1), nid(i + 1, j + 1, k + 1), nid(i, j + 1, k + 1),
                ]
                A(f'\t\t\t<elem id="{eid}">{",".join(str(n) for n in ns)}</elem>')
    A('\t\t</Elements>')

    # 节点集：底面 / 顶面
    for setname, kk in (("zmin", 0), ("zmax", NZ)):
        ids = [nid(i, j, kk) for j in range(NY + 1) for i in range(NX + 1)]
        A(f'\t\t<NodeSet name="{setname}">{",".join(str(n) for n in ids)}</NodeSet>')

    A('\t</Mesh>')

    A('\t<MeshDomains>')
    A('\t\t<SolidDomain name="Part1" mat="block"/>')
    A('\t</MeshDomains>')

    # 载荷曲线：恒定 1.0，供 <value lc> 引用（lc 不能为 0）
    A('\t<LoadData>')
    A('\t\t<load_controller id="1" type="loadcurve">')
    A('\t\t\t<interpolate>LINEAR</interpolate>')
    A('\t\t\t<extend>CONSTANT</extend>')
    A('\t\t\t<points>')
    A('\t\t\t\t<pt>0,1</pt>')
    A('\t\t\t\t<pt>1,1</pt>')
    A('\t\t\t</points>')
    A('\t\t</load_controller>')
    A('\t</LoadData>')

    A('\t<Boundary>')
    A('\t\t<bc name="fix_bottom" node_set="zmin" type="zero temperature"/>')
    A('\t\t<bc name="hot_top" node_set="zmax" type="prescribed temperature">')
    A(f'\t\t\t<value lc="1">{T_TOP}</value>')
    A('\t\t\t<relative>0</relative>')
    A('\t\t</bc>')
    A('\t</Boundary>')

    A('\t<Output>')
    A('\t\t<plotfile type="febio">')
    A('\t\t\t<var type="temperature"/>')
    A('\t\t\t<var type="heat flux"/>')
    A('\t\t</plotfile>')
    A('\t\t<logfile>')
    A('\t\t\t<node_data data="T" node_set="zmax"/>')
    A('\t\t</logfile>')
    A('\t</Output>')

    A('</febio_spec>')
    return "\n".join(L)


if __name__ == "__main__":
    xml = build()
    feb = OUT / "heat3d_block.feb"
    feb.write_text(xml, encoding="latin-1")
    print(f"节点 {NX * NY * NZ} 单元 ->", (NX + 1) * (NY + 1) * (NZ + 1), "节点")
    print("已写出:", feb, feb.stat().st_size, "bytes")
    print("理论解: T(z) = 100*z ; q_z = -100 W/m^2")
