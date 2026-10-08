# 材料参数卡片 Schema

> 用途：把 FEBio 官方手册第 4 章「材料库」的精读成果，转成 **MCP 能直接消费的结构化数据**。
> 产出经 `febio_material_guide(type)` 工具暴露给 AI，使建模时能获得参数含义说明，而不只是参数名。

---

## 1. 文件放哪

一个材料类型一个文件，放在：

```
<repo>/data/material_guides/<type>.json
```

文件名就是材料类型字符串（与 `febio_list_materials` 返回的完全一致），例如：

| 材料类型 | 文件名 |
|---|---|
| `neo-Hookean` | `neo-Hookean.json` |
| `biphasic` | `biphasic.json` |
| `Mooney-Rivlin` | `Mooney-Rivlin.json` |
| `Arruda-Boyce unconstrained` | `Arruda-Boyce unconstrained.json` |

> 文件名里的 `/` 换成 `_`，其余（含空格与大小写）保持原样。

---

## 2. 通用性硬约束（所有卡片必须遵守）

**这个 MCP 面向所有 FEBio 用户，不服务任何单一学科。** 卡片里出现以某个特定领域为中心的表述，就等于给其他用户制造了误导。填写时逐条自查：

| 约束 | 反例（禁止） | 正例 |
|---|---|---|
| **summary 不得绑定单一学科/组织** | "椎间盘、软骨、半月板的标准材料模型" | "凡是『多孔可变形固体 + 可流动流体』的系统都适用" |
| **typical_uses 必须跨领域** | 只列生物组织 | 同时列土体/凝胶/聚合物/生物组织等 |
| **typical 取值至少给 2 个不同领域** | 只给"椎间盘纤维环 0.2" | 给"饱和砂土 0.55–0.65 / 水凝胶 0.05–0.20 / 致密软组织 0.15–0.25" |
| **数值必须可溯源** | 凭空写一个数 | 标手册页码，或标"量级参考，需按实测换算" |
| **manual_ref 必须带手册版本** | `§4.14, p330` | `FEBio 4.x User Manual §4.14, p330-332（4.13 实测）`，并注明页码随版本浮动、以章节号为准 |
| **example 用中性名字** | `"name": "disc"` | `"name": "porous_sample"` / `"sample"` / `"demo"` |
| **pitfalls 不得只在特定场景成立** | "压缩椎间盘时…" | "存在自由排水面时…" |

**一句话判据：把这张卡片给一个做土木/材料/机械的用户看，他能不能用？不能就说明写窄了。**

---

## 3. 格式

```json
{
  "type": "biphasic",
  "kind": "standalone",
  "display_name": "双相材料（可变形固体骨架 + 可流动孔隙流体）",
  "summary": "基于混合理论，把介质看成「固体骨架 + 孔隙流体」两相共占同一空间。能刻画固结、蠕变、应力松弛，以及流体渗出引起的体积变化与孔隙压力演化。凡是「多孔可变形固体 + 可流动流体」的系统都适用。",
  "manual_ref": ["FEBio 4.x User Manual §4.14, p330-332（4.13 实测）"],
  "manual_ref_note": "页码随手册版本浮动，请以章节号为准。",
  "typical_uses": ["饱和土体 / 岩石", "水凝胶、多孔聚合物", "生物软组织", "过滤介质、多孔电极"],

  "params": {
    "phi0": {
      "meaning": "参考构型下的固体体积分数 φs^r",
      "unit": "-",
      "range": "(0, 1)",
      "required": true,
      "typical": {
        "饱和砂土": "0.55–0.65",
        "水凝胶": "0.05–0.20",
        "致密含水软组织": "0.15–0.25"
      },
      "note": "注意：该参数是固体体积分数，不是孔隙率。换算关系 phi0 = 1 - 孔隙率 n。"
    },
    "solid": {
      "meaning": "固体骨架的本构模型（嵌套材料定义）",
      "kind": "nested_material",
      "required": true,
      "note": "常用 neo-Hookean；手册示例用 v=0.3，不要用 0.0。"
    }
  },

  "example": {
    "spec": {
      "name": "porous_sample",
      "type": "biphasic",
      "phi0": 0.2,
      "fluid_density": 1e-06,
      "solid": {"type": "neo-Hookean", "E": 1.0, "v": 0.3},
      "permeability": {"type": "perm-const-iso", "perm": 0.001}
    },
    "xml": "<material id=\"1\" name=\"porous_sample\" type=\"biphasic\">...</material>",
    "verified": false,
    "verified_note": "数值与所采用单位制绑定，换单位制必须同步换算。"
  },

  "analysis_note": "Module 必须设 biphasic，solver 用 BiphasicSolver，analysis 通常为 TRANSIENT。",
  "pitfalls": [
    "固体骨架 v 用 0.3（手册示例），用 0.0 会导致求解异常。",
    "初始步长过大会产生负雅可比并反复切割时间步；排查时应优先减小 step_size，而非更换网格。"
  ]
}
```

---

## 4. 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `type` | ✅ | 材料类型字符串，必须与文件名一致 |
| `kind` | ✅ | `standalone`（可直接赋给 part）或 `nested`（只能作为嵌套组件使用）。**标注错误会导致用户将其误用为独立材料。** |
| `display_name` | ✅ | 中文名，一句话 |
| `summary` | ✅ | 2–3 句：描述什么物理、什么时候该用。**不得绑定单一学科** |
| `manual_ref` | ✅ | 手册章节 + 页码 + **手册版本**，必须可回溯 |
| `manual_ref_note` | | 页码随版本浮动时，说明以章节号为准 |
| `typical_uses` | | 典型应用场景，**必须跨领域** |
| `params` | ✅ | 每个参数的说明，键名必须是 pyfebio 里的真实参数名 |
| `params.<p>.meaning` | ✅ | 参数含义（自然语言说明，避免只写符号） |
| `params.<p>.unit` | | 单位（无量纲写 `-`）；单位制相关时必须写明 |
| `params.<p>.range` | | 取值范围/约束 |
| `params.<p>.required` | ✅ | 是否必填 |
| `params.<p>.typical` | | 典型取值，**至少覆盖 2 个不同领域**；非精确值请标区间或"量级参考" |
| `params.<p>.note` | | 易错点 |
| `params.<p>.kind` | | 嵌套材料时写 `nested_material` |
| `example.spec` | ✅ | **能直接喂给 `febio_build_model` 的 spec 片段**（注意：这是"材料条目"，不是完整模型 spec） |
| `example.xml` | | 对应的 XML，便于人工核对 |
| `example.verified` | | 是否已实际跑通（true/false）。**只有真跑过才写 true** |
| `example.verified_note` | | 验证环境/单位制等附加说明 |
| `analysis_note` | | 该材料要求哪个 Module / Solver / 分析类型 |
| `pitfalls` | ✅ | 常见误用与排查要点，**不得只在特定学科场景成立** |

---

## 5. 怎么确认参数名没写错

参数名必须和 pyfebio 一致，否则建模时会报"不支持参数"。核对方式：

```
febio_material_info("biphasic")     # 返回真实字段名与默认值
```

或命令行：

```bash
cd <repo>
PYTHONPATH=. .venv/Scripts/python.exe -c "import sys;sys.path.insert(0,'src');from modeling.builder import material_fields;import json;print(json.dumps(material_fields('biphasic'),ensure_ascii=False,indent=2))"
```

**以 `febio_material_info` 的输出为准**——手册里出现的 `<solid>` 这类标签名，在 spec 里要写成 pyfebio 的字段名（通常一致，但嵌套层级要展开成 dict）。

---

## 6. 交付方式

每个文件写好后放入 `data/material_guides/` 即可，无需修改代码。
MCP 的 `febio_material_guide` 工具会自动发现并按 `type` 索引。

若某材料没有卡片，工具会提示"尚无卡片"，并给出本 Schema 的路径 —— 属于正常降级，不影响建模。

**填写顺序建议**（按全用户通用性，不按学科）：

- **T0 通用必填**：`neo-Hookean`、`isotropic elastic`、`Mooney-Rivlin`、`Ogden`、`rigid body`、`biphasic`、`multiphasic`、`perm-const-iso`、`solid mixture`、`Holmes-Mow`、`Donnan equilibrium`、`viscoelastic`
- **T1 高频扩展**：`Yeoh`、`Arruda-Boyce`、`Veronda-Westmann`、`Fung orthotropic`、`Holzapfel-Gasser-Ogden`、`trans iso Mooney-Rivlin`、`continuous fiber distribution`、`perm-Holmes-Mow`、`perm-ref-iso`、`perm-ref-ortho`、`biphasic-solute`、`uncoupled viscoelastic`
- **T2 领域专用**：`lung`、`tendon material`、`muscle material`、`cell growth`、`Carter-Hayes`、`Shenoy`、`PRLig`、CLE 族、纤维分布族、`osm-coef-*`
- **T3 嵌套组件**（`kind: nested`）：`vector`/`local`/`circular`/`spherical`/`elliptical` 等方向定义、`fiber-*` 系列、`perm-*` 变体、`solub-const`
