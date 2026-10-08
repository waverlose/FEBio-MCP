# 示例：三维固体稳态导热

单位立方体 `[0,1]³`，4×4×4 结构化六面体（64 单元 / 125 节点），各向同性 Fourier 材料 `k=1`，
底面 `z=0` 固定 `T=0`、顶面 `z=1` 固定 `T=100`，其余四面绝热。

一维稳态热传导解析解为 `T(z) = 100z`、`q_z = -k·dT/dz = -100 W/m²`。
本算例在 FEBio 4.13.0 上 `NORMAL TERMINATION`，温度场与热流密度均与解析解一致
（最大绝对误差 `0.000e+00`），对账图见 `heat3d_verification.png`。

---

## 前置：FEBioHeat 插件需自行下载

**传热不是 FEBio 的内置模块**，必须以官方插件形式加载。该插件**不随本仓库分发**，
请自行获取后放到本目录，并确保文件名为 `FEBioHeat.dll`（FEBio 按文件名查找插件）。

获取途径：

- FEBioStudio 内 `Tools → Plugin Repository`，按当前 **SDK 版本**选择对应构建；
- 或访问插件仓库 <https://repo.febio.org/>。

插件版本必须与主程序匹配（FEBio 4.13 对应 SDK 4.13）。下载到的文件若被改名
（例如 `febioheat_pkg.bin`），需改回 `FEBioHeat.dll` 才能加载。

---

## 运行

```bash
# 1) 生成模型（写出 heat3d_block.feb）
python build_heat_model.py

# 2) 求解（需本目录下已放好 FEBioHeat.dll）
febio4 -import FEBioHeat.dll -i heat3d_block.feb

# 3) .xplt -> .hdf5
python -c "from pyfebio.xplt import to_hdf5; to_hdf5('heat3d.xplt', 'heat3d.hdf5')"

# 4) 与解析解对账并出图
python verify_and_plot.py
```

产物 `heat3d.hdf5` / `heat3d.log` / `heat3d.xplt` 已被 `.gitignore` 排除，可随时重新生成。

---

## 两个容易踩的点

- `Control` 段必须声明 `<solver type="heat"/>`，否则报
  `Component "" needs to have property "solver" defined`。
- 载荷曲线须写成 `<load_controller id="1" type="loadcurve">`；FEBio 4.x 不认旧版的
  `<load_curve>` 标签，且 `<value>` 的 `lc` 属性不能为 0。
