"""离线知识库门面。

汇总两类本地知识源：
  1. 官方 PDF 手册（User / Theory / Studio）
  2. C++ SDK 头文件（能力地图）

对外只暴露简单的 search / lookup 接口，供 MCP 工具层调用。
"""

from __future__ import annotations

import threading
from pathlib import Path

from .pdf_index import Hit, ManualIndex, expand_query
from .sdk_index import ClassInfo, SDKIndex

import config as _cfg  # 顶层 config（PYTHONPATH=repo root）


class KnowledgeBase:
    """懒加载 + 线程安全的本地知识库。"""

    def __init__(self, doc_dir: Path | None = None, sdk_dir: Path | None = None, cache_dir: Path | None = None):
        self.doc_dir = Path(doc_dir) if doc_dir else _cfg.DOC_DIR
        self.sdk_dir = Path(sdk_dir) if sdk_dir else _cfg.SDK_INCLUDE
        self.cache_dir = Path(cache_dir) if cache_dir else _cfg.CACHE_DIR
        self._manuals: list[ManualIndex] = []
        self._sdk: SDKIndex | None = None
        self._lock = threading.Lock()
        self._loaded = False
        self._load_error: str | None = None

    # -------------------------------------------------- 加载
    def ensure_loaded(self, rebuild: bool = False) -> None:
        if self._loaded and not rebuild:
            return
        with self._lock:
            if self._loaded and not rebuild:
                return
            self._manuals = []
            if self.doc_dir and self.doc_dir.exists():
                pdfs = sorted(self.doc_dir.glob("*.pdf"))
                # 按 MANUAL_ORDER 优先
                order = {n: i for i, n in enumerate(_cfg.MANUAL_ORDER)}
                pdfs.sort(key=lambda p: order.get(p.name, 99))
                for p in pdfs:
                    try:
                        self._manuals.append(ManualIndex(p, self.cache_dir).load(rebuild=rebuild))
                    except Exception as exc:  # 单个 PDF 坏了不影响其它
                        self._load_error = f"{p.name}: {exc}"
            if self.sdk_dir and self.sdk_dir.exists():
                self._sdk = SDKIndex(self.sdk_dir)
            self._loaded = True

    @property
    def manuals(self) -> list[ManualIndex]:
        self.ensure_loaded()
        return self._manuals

    @property
    def sdk(self) -> SDKIndex | None:
        self.ensure_loaded()
        return self._sdk

    # -------------------------------------------------- 检索
    def search(self, query: str, top_k: int = 8, manual: str | None = None) -> list[Hit]:
        self.ensure_loaded()
        terms = expand_query(query)
        if not terms:
            return []
        hits: list[Hit] = []
        for m in self._manuals:
            if manual and manual.lower() not in m.name.lower():
                continue
            hits.extend(m.search(terms, top_k=top_k))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def read_page(self, manual: str, page: int) -> str:
        self.ensure_loaded()
        for m in self._manuals:
            if manual.lower() in m.name.lower():
                return m.get_page(page)
        return f"manual not found: {manual}"

    def manual_names(self) -> list[str]:
        self.ensure_loaded()
        return [m.name for m in self._manuals]

    def toc(self, manual: str) -> list[str]:
        self.ensure_loaded()
        for m in self._manuals:
            if manual.lower() in m.name.lower():
                return m.toc()
        return []

    def stats(self) -> dict:
        self.ensure_loaded()
        return {
            "manuals": [
                {"name": m.name, "pages": len(m.pages), "cached": m.cache_file.exists()}
                for m in self._manuals
            ],
            "sdk_modules": (self.sdk.modules() if self.sdk else {}),
            "error": self._load_error,
        }


_KB: KnowledgeBase | None = None


def get_kb() -> KnowledgeBase:
    global _KB
    if _KB is None:
        _KB = KnowledgeBase()
    return _KB
