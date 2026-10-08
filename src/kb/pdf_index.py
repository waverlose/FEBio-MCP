"""本地官方 PDF 手册的离线索引与检索。

数据源：FEBio 安装目录 doc/ 下的官方手册（User / Theory / Studio）。
纯离线，不联网。首次构建索引后缓存到 docs/.cache/，后续加载直接命中缓存。

检索特点：
  - 英文关键词直接命中；
  - 内置中英术语映射（覆盖力学/材料/网格/求解器/多孔介质等通用术语），
    中文提问也能命中英文手册。术语表是开放的，按需追加即可。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

CACHE_VERSION = 3

# ------------------------------------------------------------ 中英术语映射
# 用于把中文查询扩展成手册里实际出现的英文词。
TERM_MAP: dict[str, list[str]] = {
    "椎间盘": ["intervertebral disc", "disc", "disk"],
    "纤维环": ["annulus fibrosus", "annulus"],
    "髓核": ["nucleus pulposus", "nucleus"],
    "终板": ["endplate", "end plate"],
    "软骨": ["cartilage"],
    "关节": ["joint"],
    "骨": ["bone"],
    "韧带": ["ligament"],
    "肌腱": ["tendon"],
    "渗透": ["osmotic", "osmosis"],
    "渗透压": ["osmotic pressure", "osmolarity"],
    "渗透率": ["permeability", "hydraulic permeability"],
    "固定电荷密度": ["fixed charge density", "fixed charge", "FCD"],
    "唐南": ["Donnan", "Donnan equilibrium"],
    "双相": ["biphasic"],
    "三相": ["triphasic"],
    "多相": ["multiphasic"],
    "溶质": ["solute"],
    "溶剂": ["solvent"],
    "扩散": ["diffusion", "diffusivity"],
    "浓度": ["concentration"],
    "电荷": ["charge", "charge number"],
    "离子": ["ion", "ionic"],
    "孔隙": ["porous", "porosity", "void ratio"],
    "含水量": ["water content", "solid volume fraction"],
    "应变": ["strain"],
    "应力": ["stress"],
    "杨氏模量": ["Young's modulus", "Young modulus"],
    "泊松比": ["Poisson's ratio"],
    "剪切模量": ["shear modulus"],
    "体积模量": ["bulk modulus"],
    "超弹性": ["hyperelastic", "hyperelasticity"],
    "粘弹性": ["viscoelastic", "viscoelasticity"],
    "弹塑性": ["elastoplastic", "plastic"],
    "各向异性": ["anisotropic", "anisotropy", "transversely isotropic"],
    "各向同性": ["isotropic"],
    "纤维": ["fiber", "fibre"],
    "材料": ["material"],
    "接触": ["contact"],
    "绑定": ["tied", "tie"],
    "滑动": ["sliding"],
    "摩擦": ["friction", "frictional"],
    "约束": ["constraint"],
    "边界条件": ["boundary condition", "bc"],
    "载荷": ["load"],
    "位移": ["displacement"],
    "压力": ["pressure"],
    "预应变": ["prestrain"],
    "初始条件": ["initial condition"],
    "网格": ["mesh"],
    "单元": ["element"],
    "节点": ["node"],
    "六面体": ["hexahedral", "hex"],
    "四面体": ["tetrahedral", "tet"],
    "壳": ["shell"],
    "求解器": ["solver"],
    "收敛": ["convergence", "converged"],
    "时间步": ["time step", "timestep", "step size"],
    "分析步": ["step"],
    "重启": ["restart"],
    "输出": ["output"],
    "曲线": ["curve", "load curve", "loadcurve"],
    "优化": ["optimization"],
    "参数": ["parameter"],
    "单位": ["unit", "units"],
    "重力": ["gravity"],
    "蠕变": ["creep"],
    "松弛": ["relaxation", "stress relaxation"],
    "压缩": ["compression"],
    "拉伸": ["tension", "stretch"],
    "弯曲": ["bending"],
    "扭转": ["torsion"],
    "疲劳": ["fatigue"],
    "损伤": ["damage"],
    "生长": ["growth"],
    "重塑": ["remodeling"],
    "细胞": ["cell"],
    "主动收缩": ["active contraction"],
    "电场": ["electric field", "electrical"],
    "电势": ["potential", "electric potential"],
    "跨膜": ["transmembrane"],
    "离子通道": ["ion channel"],
    "pH": ["pH", "acid"],
}


def expand_query(query: str) -> list[str]:
    """把查询拆成检索词，并把中文术语扩展为英文。"""
    terms: list[str] = []
    q = query.strip()
    # 先处理多字中文术语（长的优先）
    for zh in sorted(TERM_MAP, key=len, reverse=True):
        if zh in q:
            terms.extend(TERM_MAP[zh])
            q = q.replace(zh, " ")
    # 英文 / 数字 / 连字符片段
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9'\-\.]{1,}", q):
        if len(tok) >= 2:
            terms.append(tok)
    # 去重保序
    seen, out = set(), []
    for t in terms:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            out.append(t)
    return out


@dataclass
class Hit:
    manual: str
    page: int
    score: float
    snippet: str
    heading: str = ""

    def to_dict(self) -> dict:
        return {
            "manual": self.manual,
            "page": self.page,
            "score": round(self.score, 3),
            "heading": self.heading,
            "snippet": self.snippet,
        }


@dataclass
class ManualIndex:
    pdf_path: Path
    cache_dir: Path
    pages: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.pdf_path.stem

    @property
    def cache_file(self) -> Path:
        return self.cache_dir / f"idx_{self.pdf_path.stem}.json"

    # -------------------------------------------------- 构建 / 加载
    def load(self, rebuild: bool = False) -> "ManualIndex":
        if not rebuild and self.cache_file.exists():
            try:
                data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                if data.get("version") == CACHE_VERSION and data.get("mtime") == self.pdf_path.stat().st_mtime:
                    self.pages = data["pages"]
                    self.headings = data["headings"]
                    return self
            except Exception:
                pass
        self._build()
        return self

    def _build(self) -> None:
        reader = PdfReader(str(self.pdf_path))
        pages: list[str] = []
        headings: list[str] = []
        for pg in reader.pages:
            try:
                txt = pg.extract_text() or ""
            except Exception:
                txt = ""
            txt = re.sub(r"[ \t]+", " ", txt)
            pages.append(txt)
            # 猜测该页标题：取最像章节标题的一行
            headings.append(_guess_heading(txt))
        self.pages = pages
        self.headings = headings
        self.cache_file.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "mtime": self.pdf_path.stat().st_mtime,
                    "pages": pages,
                    "headings": headings,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    # -------------------------------------------------- 检索
    def search(self, terms: list[str], top_k: int = 8, window: int = 320) -> list[Hit]:
        if not terms:
            return []
        lowered = [t.lower() for t in terms]
        hits: list[Hit] = []
        for i, txt in enumerate(self.pages):
            low = txt.lower()
            score = 0.0
            first_pos = -1
            for t in lowered:
                c = low.count(t)
                if c:
                    score += c * (1.0 + 0.1 * len(t))
                    if first_pos < 0:
                        first_pos = low.find(t)
            if score <= 0:
                continue
            # 标题命中加权
            h = self.headings[i]
            if h and any(t in h.lower() for t in lowered):
                score *= 1.6
            pos = first_pos if first_pos >= 0 else 0
            snippet = _snippet(self.pages[i], pos, window)
            hits.append(Hit(self.name, i + 1, score, snippet, h))
        hits.sort(key=lambda x: x.score, reverse=True)
        return hits[:top_k]

    def get_page(self, page_no: int) -> str:
        if 1 <= page_no <= len(self.pages):
            return self.pages[page_no - 1]
        return ""

    def toc(self) -> list[str]:
        """粗略目录：返回看起来像章节标题的行（去重）。"""
        seen, out = set(), []
        for h in self.headings:
            if h and h not in seen:
                seen.add(h)
                out.append(h)
        return out


def _guess_heading(txt: str) -> str:
    for line in txt.splitlines()[:6]:
        s = line.strip()
        if not s or len(s) > 90:
            continue
        # 形如 "3.4 Biphasic Material" 或 "Chapter 5 ..."
        if re.match(r"^(\d+(\.\d+)*)\s+\S", s) or re.match(r"^(Chapter|Appendix)\s+\d", s, re.I):
            return s
    return ""


def _snippet(txt: str, pos: int, window: int) -> str:
    start = max(0, pos - window // 3)
    end = min(len(txt), pos + window)
    s = txt[start:end].replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return ("..." if start > 0 else "") + s + ("..." if end < len(txt) else "")
