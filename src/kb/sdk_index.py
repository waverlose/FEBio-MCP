"""FEBio C++ SDK 头文件的离线解析。

数据源：FEBio 安装目录 sdk/include/ 下的模块头文件。
作用：给 AI 一张「FEBio 到底有哪些能力」的地图 —— 有哪些材料类、边界类、
接触类、求解器等。细节参数再去 PDF 手册里查（见 pdf_index）。

纯离线。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# 模块 -> 人类可读说明
MODULE_DESC = {
    "FEBioMech": "固体力学（大变形结构力学）：超弹性/粘弹性/损伤/接触/离散单元等",
    "FEBioMix": "多孔介质与多相混合：双相(biphasic)/三相(triphasic)/多相(multiphasic)、溶质输运、渗透",
    "FEBioFluid": "流体：流体域、FSI",
    "FEBioOpt": "参数优化 / 反问题",
    "FEBioRVE": "代表性体积元（RVE）均质化",
    "FECore": "核心：求解器、矩阵、积分、几何",
    "FEBioXML": "输入文件 XML 解析（各 section 结构）",
    "FEAMR": "自适应网格加密",
    "FEImgLib": "图像处理",
}

CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M)
DOC_RE = re.compile(r"//!\s*(.+)")


@dataclass
class ClassInfo:
    name: str
    module: str
    path: str
    doc: str = ""

    def to_dict(self) -> dict:
        return {"class": self.name, "module": self.module, "doc": self.doc, "file": self.path}


def _strip_prefix(name: str) -> str:
    """FE + 模块缩写前缀 -> 可读名（仅用于展示）。"""
    n = re.sub(r"^FE", "", name)
    n = re.sub(r"^Bio", "", n)
    return n or name


def _read_doc(p: Path) -> str:
    """抽取文件顶部的 //! 文档注释。"""
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    lines = []
    for m in DOC_RE.finditer(txt[:4000]):
        s = m.group(1).strip()
        if s and not s.lower().startswith("this file is part"):
            lines.append(s)
    return " ".join(lines)[:300]


class SDKIndex:
    def __init__(self, include_dir: Path):
        self.include_dir = Path(include_dir)
        self._classes: list[ClassInfo] | None = None

    # -------------------------------------------------- 扫描
    def scan(self, rebuild: bool = False) -> list[ClassInfo]:
        if self._classes is not None and not rebuild:
            return self._classes
        out: list[ClassInfo] = []
        if not self.include_dir.exists():
            self._classes = out
            return out
        for mod_dir in sorted(self.include_dir.iterdir()):
            if not mod_dir.is_dir():
                continue
            module = mod_dir.name
            for h in sorted(mod_dir.glob("*.h")):
                try:
                    txt = h.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                names = CLASS_RE.findall(txt)
                if not names:
                    continue
                doc = _read_doc(h)
                for nm in names:
                    # 过滤掉常见的非实体类
                    if nm.endswith("Factory") or nm in ("stdafx",):
                        continue
                    out.append(ClassInfo(nm, module, str(h), doc))
        # 去重（同名取第一个）
        seen, uniq = set(), []
        for c in out:
            key = (c.module, c.name)
            if key not in seen:
                seen.add(key)
                uniq.append(c)
        self._classes = uniq
        return uniq

    # -------------------------------------------------- 查询
    def modules(self) -> dict[str, dict]:
        res: dict[str, dict] = {}
        for c in self.scan():
            d = res.setdefault(c.module, {"desc": MODULE_DESC.get(c.module, ""), "count": 0})
            d["count"] += 1
        return res

    def classes(self, module: str | None = None) -> list[ClassInfo]:
        return [c for c in self.scan() if module is None or c.module == module]

    def find(self, keyword: str, limit: int = 40) -> list[ClassInfo]:
        kw = keyword.lower()
        hits = []
        for c in self.scan():
            if kw in c.name.lower() or kw in c.doc.lower():
                hits.append(c)
        # 名字命中优先
        hits.sort(key=lambda c: (kw not in c.name.lower(), len(c.name)))
        return hits[:limit]

    def header_text(self, class_name: str, max_chars: int = 6000) -> str:
        for c in self.scan():
            if c.name.lower() == class_name.lower():
                try:
                    return Path(c.path).read_text(encoding="utf-8", errors="ignore")[:max_chars]
                except Exception:
                    return ""
        return ""

    def materials(self) -> list[str]:
        """启发式挑出可能的「材料类」名字，供进一步到手册查证。"""
        keys = ("Material", "Hookean", "MooneyRivlin", "Veronda", "Ogden", "Arruda",
                "Fung", "HolmesMow", "Biphasic", "Triphasic", "Multiphasic", "Solute",
                "Perm", "Diff", "Reaction", "Elastic", "Viscoelastic", "Damage",
                "Fiber", "Donnan", "Osm", "Spring", "Contraction")
        out = []
        for c in self.scan():
            if any(k in c.name for k in keys) and c.module in ("FEBioMech", "FEBioMix", "FEBioFluid"):
                out.append(c.name)
        return sorted(set(out))
