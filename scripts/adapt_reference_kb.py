# -*- coding: utf-8 -*-
"""把外部参考知识库的 materials.json 适配成本项目 MCP 消费的卡片格式。

输入：<ref>/knowledge/materials.json（186 张手册卡片）
输出：<repo>/data/material_guides/<type>.json（MATERIAL_CARD_SCHEMA.md 定义的格式）

做的事：
  1. `parameters` list -> `params` dict（按参数名索引）
  2. 参数名与本项目 pyfebio 的实际字段名对账，标出「手册有、pyfebio 无」的项
  3. 从 pyfebio 默认值生成 `example.spec`，并**实际构造一次**验证它可用
  4. 从 category 推断 `kind`（standalone / nested）
  5. 保留手册章节号与页码，用于回溯

不覆盖已存在的手写卡片。

用法：
    python scripts/adapt_reference_kb.py --ref <参考知识库目录>
    python scripts/adapt_reference_kb.py --ref <参考知识库目录> --dry-run

参考知识库只需满足 `<ref>/knowledge/materials.json` 这一结构，
目录位置由使用者在命令行指定，本脚本不假设任何固定路径。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from modeling.builder import MATERIAL_REGISTRY, build_material, material_fields  # noqa: E402
from pyfebio.material import MaterialParameter  # noqa: E402

GUIDES = REPO / "data" / "material_guides"

# category 里出现这些关键词 -> 该类型只能作为嵌套组件使用
NESTED_KEYWORDS = (
    "permeability", "diffusivity", "fiber", "cdf", "relaxation", "recruitment",
    "chemical reaction", "reaction rate", "damage/yield", "plastic flow curve",
    "solubility", "osmotic coefficient", "solvent supply", "fluid supply",
    "integration scheme", "prestrain generator", "homogenization", "container",
)


# ------------------------------------------------------------------ 工具
def to_number(v):
    """MaterialParameter.text 可能是 str 也可能是数值；保持原样返回数值。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    try:
        return int(v)
    except Exception:
        try:
            return float(v)
        except Exception:
            return v


def model_to_spec(v):
    """把 pyfebio 的 pydantic 模型（含嵌套）递归转成 spec dict。"""
    if v is None:
        return None
    if isinstance(v, MaterialParameter):
        return to_number(v.text)
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple)):
        out = [model_to_spec(x) for x in v]
        return [x for x in out if x is not None]
    if hasattr(type(v), "model_fields"):
        d: dict = {}
        t = getattr(v, "type", None)
        if t:
            d["type"] = t
        for fn in type(v).model_fields:
            # name/id 由调用方决定是否加；带点号的字段名不是合法参数名
            if fn in ("type", "name", "id") or "." in fn:
                continue
            c = model_to_spec(getattr(v, fn, None))
            if c is not None and c != [] and c != {}:
                d[fn] = c
        return d
    return None


def default_spec(mtype: str, name: str = "sample") -> tuple[dict | None, str]:
    """用 pyfebio 默认值生成一份 spec 片段，并验证它确实能构造出来。

    返回 (spec, 失败原因)。spec 为 None 表示无法自动生成可用示例。
    """
    cls = MATERIAL_REGISTRY.get(mtype)
    if cls is None:
        return None, "本机 pyfebio 没有该材料类型"
    try:
        spec = model_to_spec(cls())
        if not isinstance(spec, dict):
            return None, "默认值无法序列化为 spec"
        spec = apply_completions(spec, mtype)
    except Exception as e:
        return None, f"读取默认值失败：{type(e).__name__}: {e}"

    # name 只在该类确实声明了该字段时才加
    candidates = [dict(spec)]
    if "name" in cls.model_fields:
        with_name = dict(spec)
        with_name["name"] = name
        candidates.insert(0, with_name)

    last = ""
    for cand in candidates:
        try:
            build_material(cand)      # 实测：构造不出来就不算可用
            return cand, ""
        except Exception as e:
            last = f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"
    return None, last


def infer_kind(category: str) -> str:
    c = (category or "").lower()
    return "nested" if any(k in c for k in NESTED_KEYWORDS) else "standalone"


# pyfebio 默认值为 None、但求解时 FEBio 强制要求存在的参数 —— 按类型名补默认值。
# 依据：实测报错 "Component \"x\" needs to have property \"fiber\" defined"。
COMPLETIONS: list[tuple] = [
    (
        lambda t: "trans iso" in t.lower() or "trans-iso" in t.lower(),
        {"fiber": {"type": "vector", "text": "1.0,0.0,0.0"}},
    ),
    (
        lambda t: "solid mixture" in t.lower(),
        {"solid_list": [{"type": "neo-Hookean", "E": 1.0, "v": 0.3}]},
    ),
]


def apply_completions(spec: dict, mtype: str) -> dict:
    """按类型名补默认值，但只补目标类**确实声明了**的字段。

    否则会误伤：例如 perm-ref-trans-iso 名字里也有 trans-iso，
    但它没有 fiber 字段，硬塞进去会构造失败。
    """
    cls = MATERIAL_REGISTRY.get(mtype)
    if cls is None:
        return dict(spec)
    out = dict(spec)
    for match, patch in COMPLETIONS:
        if not match(mtype):
            continue
        for k, v in patch.items():
            if k in cls.model_fields:
                out.setdefault(k, v)
    return out


# ------------------------------------------------------------------ 主流程
def build_card(card: dict) -> dict | None:
    mtype = card.get("type")
    if not mtype or mtype not in MATERIAL_REGISTRY:
        return None

    fields = material_fields(mtype)
    spec, why = default_spec(mtype)

    params: dict = {}
    not_in_pyfebio: list[str] = []
    for p in card.get("parameters") or []:
        pname = p.get("name")
        if not pname:
            continue
        in_pf = pname in fields
        if not in_pf:
            not_in_pyfebio.append(pname)

        entry: dict = {"meaning": (p.get("meaning") or "").strip()}
        unit = (p.get("units") or "").strip()
        if unit and unit != "-":
            entry["unit"] = unit
        rng = (p.get("range") or "").strip()
        if rng and rng != "-":
            entry["range"] = rng
        dflt = p.get("default")
        if dflt not in (None, "", "-"):
            entry["manual_default"] = dflt
        # required：以 pyfebio 默认值为准 —— 默认值为 None 说明确实必须给
        if in_pf:
            dv = fields[pname].get("default")
            entry["required"] = dv in (None, "None")
        else:
            entry["required"] = False
            entry["note"] = "手册列出该参数，但 pyfebio 当前版本没有对应字段，建模时无法传入。"
        params[pname] = entry

    # 出处只记官方手册章节/页码；不记录输入文件所在位置，
    # 以免把某台机器上的目录结构写进产出的卡片里。
    ref = []
    sec = (card.get("manual_section") or "").strip()
    page = card.get("manual_page")
    if sec or page:
        ref.append(f"FEBio 4.x User Manual §{sec}, p{page}（4.13）")

    out: dict = {
        "type": mtype,
        "kind": infer_kind(card.get("category", "")),
        "display_name": card.get("name") or mtype,
        "summary": (card.get("notes") or "").strip() or f"FEBio 材料类型 {mtype}。",
        "manual_ref": ref,
        "module": (card.get("module") or "").strip(),
        "category": (card.get("category") or "").strip(),
        "params": params,
    }

    if spec is not None:
        out["example"] = {
            "spec": spec,
            "source": "pyfebio 0.3.0 默认值，已通过构造验证；数值为占位默认，建模前请按实际工况替换。",
            "verified": False,
        }
    else:
        out["example"] = {
            "buildable": False,
            "reason": why,
            "source": "pyfebio 默认值不足以构造出该材料，需人工补全必要参数后给出示例。",
            "verified": False,
        }

    if not_in_pyfebio:
        out["params_not_in_pyfebio"] = not_in_pyfebio
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="参考知识库目录（须含 knowledge/materials.json）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(args.ref) / "knowledge" / "materials.json"
    if not src.exists():
        print(f"找不到 {src}", file=sys.stderr)
        return 2

    cards = json.loads(src.read_text(encoding="utf-8"))["materials"]
    GUIDES.mkdir(parents=True, exist_ok=True)

    written = skipped_exists = skipped_unbuildable_type = 0
    kind_stat: Counter = Counter()
    unbuildable: list[str] = []
    new_files: list[Path] = []

    for c in cards:
        mtype = c.get("type")
        if not mtype or mtype not in MATERIAL_REGISTRY:
            skipped_unbuildable_type += 1
            continue
        dest = GUIDES / f"{mtype}.json"
        if dest.exists():
            skipped_exists += 1
            continue
        card = build_card(c)
        if card is None:
            continue
        if not card["example"].get("spec"):
            unbuildable.append(mtype)
        kind_stat[card["kind"]] += 1
        if not args.dry_run:
            dest.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
        new_files.append(dest)
        written += 1

    print(f"参考库卡片总数        : {len(cards)}")
    print(f"本机 pyfebio 建不了   : {skipped_unbuildable_type}")
    print(f"已存在卡片（未覆盖）  : {skipped_exists}")
    print(f"{'将写入' if args.dry_run else '已写入'}卡片数        : {written}")
    print(f"  kind 分布           : {dict(kind_stat)}")
    print(f"  无法自动生成示例    : {len(unbuildable)}  {unbuildable[:10]}")
    if args.dry_run:
        print("\n[dry-run] 未写文件。前 5 个将生成：")
        for f in new_files[:5]:
            print("  ", f.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
