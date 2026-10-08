# FEBio MCP Server

让 AI 全流程驱动 [FEBio](https://febio.org) 有限元仿真的 MCP 服务（面向所有 FEBio 用户，不绑定任何学科）：
**离线查手册 → 参数化建模 → 生成网格 → 调用求解器 → 解析结果出图**，并可选用 GUI 通道控制 FEBioStudio。

本服务不自行实现已有成熟组件：建模基于 FEBio 官方 Python API [`pyfebio`](https://github.com/febiosoftware/pyfebio)，
结果解析沿用其 XPLT→HDF5 实现，网格生成基于 `gmsh`，知识库直接索引官方 PDF 手册。

---

## 一、能力一览（30 个工具）

| 分类 | 工具 | 说明 |
|---|---|---|
| **环境** | `febio_env_status` | 自检：求解器/手册/SDK/工作区，以及各能力是否可用 |
| **离线知识库** | `febio_search_docs` | 在官方 PDF 手册中检索（支持中文提问，内置中英术语映射） |
| | `febio_read_manual_page` / `febio_manual_toc` | 读某页原文 / 列章节 |
| | `febio_list_materials` / `febio_material_info` | 材料类型清单 / 某类型全部参数与默认值 |
| | `febio_material_guide` | 材料参数卡片：含义 / 单位 / 取值范围 / 典型取值 / 最小示例 / 常见误用（见 `docs/MATERIAL_CARD_SCHEMA.md`） |
| | `febio_sdk_modules` / `febio_sdk_find` | SDK 能力地图（模块、类） |
| **建模** | `febio_build_model` | 从结构化 spec 生成完整 `.feb` |
| | `febio_validate_model` | 离线校验 XML、必需段、集合/材料引用自洽性 |
| **网格** | `febio_generate_mesh` | 参数化几何网格：box / cylinder / sphere / **disc（圆盘状，可沿 z 轴分层）** |
| **求解** | `febio_run` | 同步求解（小模型） |
| | `febio_submit` / `febio_job_status` / `febio_list_jobs` / `febio_kill_job` | 异步作业管理 |
| | `febio_read_log` | 日志解析：终止状态、时间步、错误与警告 |
| **后处理** | `febio_results_summary` | 结果概览：状态、时间点、可用变量 |
| | `febio_get_field` | 场数据统计（按分量/节点集） |
| | `febio_extract_history` | 提取时间历史曲线（如顶面位移-时间） |
| | `febio_plot_curves` / `febio_plot_field` | 出曲线图 / 3D 伪彩图（散点着色） |
| | `febio_render_field` | **离屏三维渲染**：按真实单元拓扑出实体云图，支持单元场、多视角、色标范围（无需 GUI） |
| **GUI（Windows）** | `febio_studio_status` / `launch` / `screenshot` / `menu` / `run` / `close` | 控制 FEBioStudio 界面 |

---

## 二、前置条件

1. **FEBio 本体**：从 <https://febio.org/downloads/> 安装 FEBio 3 或 4（含 `febio4` / `febio3` 可执行文件）。
2. **Python ≥ 3.10**。
3. 求解器能被找到，满足以下任一条件：
   - `febio4`（或 `febio3`）在系统 `PATH` 中；或
   - 设置了环境变量 `FEBIO_EXE` / `FEBIO_HOME`；或
   - 装在常见默认位置（Windows `C:\Program Files\FEBio`、Linux `/usr/local/FEBio`、macOS `/Applications/FEBio` 等，会自动探测）。

> 首次使用建议先调用 `febio_env_status`，它会报告缺失项与建议的补全方式。

---

## 三、安装

```bash
git clone <本仓库>            # 或直接拷贝本目录
cd febio-mcp-server
python scripts/install.py     # 建 .venv、装依赖、打印 MCP 配置片段
```

脚本会打印一段 `mcpServers` 配置，形如：

```json
{
  "mcpServers": {
    "febio": {
      "command": "/绝对路径/.venv/bin/python",
      "args": ["-m", "src.server"],
      "cwd": "/绝对路径/febio-mcp-server",
      "env": { "PYTHONPATH": "/绝对路径/febio-mcp-server", "PYTHONUTF8": "1" }
    }
  }
}
```

Windows 上 `command` 是 `.venv\Scripts\python.exe`。国内网络可先设
`PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` 再跑安装脚本。

手动安装等价于：

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
```

---

## 四、接入 MCP 客户端

把上面生成的 JSON 片段合并进客户端配置（WorkBuddy / Claude Desktop / Cursor 等），
然后**在客户端的连接器（Connector）页面点「信任 / Trust」**，服务才会生效。

手动启动（调试用）：

```bash
PYTHONPATH=. .venv/bin/python -m src.server        # stdio
PYTHONPATH=. .venv/bin/python -m src.server streamable-http   # HTTP 传输
```

---

## 五、环境变量（全部可选）

| 变量 | 作用 |
|---|---|
| `FEBIO_EXE` | 直接指定求解器可执行文件路径 |
| `FEBIO_HOME` | FEBio 安装根目录（由此推导 bin/doc/sdk） |
| `FEBIO_STUDIO` | FEBioStudio 可执行文件（GUI 控制用） |
| `FEBIO_DOC` | 官方 PDF 手册目录（离线知识库） |
| `FEBIO_SDK` | SDK include 目录（能力地图） |
| `FEBIO_WORKSPACE` | 运行工作区（默认 `<repo>/workspace`） |
| `FEBIO_TIMEOUT` | 单次求解默认超时秒数（默认 3600） |

---

## 六、快速上手

**1. 查材料怎么写**

```
febio_material_info("biphasic")
```

**2. 生成一个单轴压缩模型**

```json
{
  "name": "uniaxial",
  "geometry": {"type": "box", "size": [1,1,1], "mesh_size": 0.34, "elem_type": "tet"},
  "materials": [{"name": "solid", "type": "neo-Hookean", "E": 1000, "v": 0.3}],
  "domains": [{"name": "Part1", "mat": "solid"}],
  "boundary": [
    {"type": "zero displacement", "node_set": "zmin", "x_dof": 1, "y_dof": 1, "z_dof": 1},
    {"type": "prescribed displacement", "node_set": "zmax", "dof": "z", "value": -0.1}
  ],
  "control": {"analysis": "STATIC", "time_steps": 10, "step_size": 0.1, "solver": "solid"}
}
```

```
febio_build_model(spec)
febio_run(feb_path)
febio_extract_history(xplt_path, "displacement", component=2, node_set="zmax")
```

> 提示：`<value>` 必须引用一条已定义的载荷曲线（`lc` 不能为 0）。
> 本服务会自动补一条「恒定 1.0」曲线，所以你只写数值即可。

---

## 七、目录结构

```
febio-mcp-server/
├── src/
│   ├── server.py          MCP 入口，30 个工具
│   ├── config.py          跨平台路径探测（可被环境变量覆盖）
│   ├── kb/                离线知识库（PDF 手册 + SDK 头文件）
│   ├── modeling/          建模（pyfebio 封装 + spec 驱动）
│   ├── meshing/           网格（gmsh）
│   ├── solver/            求解（febio 调用 + 作业管理 + 日志解析）
│   ├── post/              后处理（xplt 读取 + 出图）
│   └── gui/               FEBioStudio 控制（Windows）
├── data/material_guides/  材料参数卡片（<type>.json，见 docs/MATERIAL_CARD_SCHEMA.md）
├── docs/                  设计与格式规范
├── examples/heat3d/       示例：三维固体稳态导热（需自行下载 FEBioHeat 插件）
├── scripts/               安装脚本 / 参考知识库适配器 / 卡片验证脚本
├── tests/                 冒烟与端到端测试
├── workspace/             运行产出（模型/日志/结果/图），已被 .gitignore 排除
├── requirements.txt
├── LICENSE                Apache License 2.0
└── .gitignore
```

---

## 八、常见问题

**Q：提示找不到 febio4？**
设置 `FEBIO_HOME` 或 `FEBIO_EXE`，或把 FEBio 的 `bin` 加入 `PATH`。用 `febio_env_status` 确认。

**Q：离线文档检索没结果？**
手册目录不同时设 `FEBIO_DOC`。若安装包不含手册，可从 <https://febiosoftware.github.io/febio-docs/> 下载 PDF 放入任意目录后指过去。
注意本服务**不联网**，手册必须本地存在。

**Q：GUI 控制不可用？**
该功能仅 Windows，且需 `pip install pywinauto` 与已安装 FEBioStudio。日常建模求解不需要它。

**Q：想要三维云图但不想开 FEBioStudio？**
用 `febio_render_field`。它走 VTK 的**离屏**模式，无需 GUI 会话，可在服务器/批处理里跑；
需要 `pip install 'pyvista>=0.49'`。FEBio 本体（`febio4.exe`）不含任何渲染器，可视化能力在
FEBioStudio 里，本工具用的是与之相同的 VTK 引擎。

**Q：算例跑很久？**
用 `febio_submit` 异步提交，再用 `febio_job_status` 轮询。

---

## 九、依赖的第三方组件

| 环节 | 采用的项目 |
|---|---|
| 生成 `.feb` | [`febiosoftware/pyfebio`](https://github.com/febiosoftware/pyfebio)（官方） |
| 解析 `.xplt` | 同上（`pyfebio.xplt.to_hdf5`） |
| 网格 | [`gmsh`](https://gmsh.info/) Python API |
| 三维渲染 | [`pyvista`](https://pyvista.org/) + [VTK](https://vtk.org/)（**离屏**模式；与 FEBioStudio 同一渲染引擎） |
| 知识库 | FEBio 官方 PDF 手册 + C++ SDK 头文件（本地） |
| MCP 协议 | [`modelcontextprotocol/python-sdk`](https://github.com/modelcontextprotocol/python-sdk) |

---

## 十、插件（自行下载）

FEBio 的部分物理场以**官方插件**形式提供，不包含在主程序中，**也不随本仓库分发**。
需要相应能力时请自行获取，本服务只负责调用。

| 能力 | 插件 |
|---|---|
| 传热（`heat` 模块、`isotropic Fourier` 材料、`temperature` / `heat flux` 输出变量） | FEBioHeat |

获取方式：

- 在 FEBioStudio 中打开 `Tools → Plugin Repository`，按当前 SDK 版本选择对应构建；
- 或访问插件仓库 <https://repo.febio.org/> 自行下载。

加载方式（二选一，均无需改动 FEBio 安装目录）：

```bash
# 1) 命令行临时加载
febio4 -import /path/to/FEBioHeat.dll -i model.feb

# 2) 写入 FEBio 配置文件，全局生效（详见 FEBio User Manual §10.1 Loading Plugins）
```

注意事项：

- 插件必须与主程序的 **SDK 版本匹配**。例如 FEBio 4.13 需选 SDK 4.13 的构建，否则加载失败。
- FEBio 按**文件名**查找插件。下载得到的文件若被改过名（如 `febioheat_pkg.bin`），
  需改回插件真实名称（`FEBioHeat.dll`）后再加载。
- 传热算例的 `Control` 段必须声明 `<solver type="heat"/>`，否则报
  `Component "" needs to have property "solver" defined`。
- `examples/heat3d/` 的验证算例依赖 FEBioHeat，插件未就位时无法运行。

---

## 十一、许可

本项目以 **Apache License 2.0** 发布，全文见 [LICENSE](LICENSE)。

```
Copyright 2026 Yuheng Liu
```

本许可**仅覆盖本仓库自身的代码与文档**。运行时依赖的第三方组件（FEBio 本体、`pyfebio`、
`gmsh`、MCP SDK 等）及 FEBio 官方手册内容，版权归各自权利人所有，见第九节。

`data/material_guides/` 下的材料参数卡片由 **FEBio 官方用户手册**（Musculoskeletal Research
Laboratories, University of Utah）的公开内容整理而成，仅供参数检索参考；引用与再分发请
遵循手册自身的版权约定。
