"""FEBio .log 文件解析。

FEBio 的日志格式要点（4.x 实测）：
  - 正常终止：单独一行带空格的  "N O R M A L   T E R M I N A T I O N"
  - 消息框：用一排 ***** 包起来，框内标注 ERROR / WARNING，例如
        *************************************************************************
         *                                ERROR                                  *
         * tag "value" (line 364) : invalid value for attribute "lc"             *
         *************************************************************************
    → 只有框内出现 ERROR 才算错误，纯 ***** 行不是错误。
  - 时间步：  "===== beginning time step 1 : 0.1 ====="
  - 耗时：    "Total elapsed time .............. : 0:00:00 (0.1243 sec)"
  - 收敛：    "convergence summary" / "number of iterations   : 1"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_NORMAL_RE = re.compile(r"N\s*o\s*r\s*m\s*a\s*l\s+T\s*e\s*r\s*m\s*i\s*n\s*a\s*t\s*i\s*o\s*n", re.I)
_FAIL_RE = re.compile(r"(F\s*a\s*i\s*l\s*e\s*d|A\s*b\s*n\s*o\s*r\s*m\s*a\s*l\s+T\s*e\s*r\s*m\s*i\s*n|T\s*e\s*r\s*m\s*i\s*n\s*a\s*t\s*e\s*d\s+W\s*i\s*t\s*h)", re.I)
_BOX_TOP_RE = re.compile(r"^\s*\*{5,}\s*$")
_TIME_STEP_RE = re.compile(r"beginning time step\s+(\d+)\s*:\s*([\d.eE+\-]+)")
_ELAPSED_RE = re.compile(r"Total elapsed time.*?\(\s*([\d.eE+\-]+)\s*sec", re.I)
_ITER_RE = re.compile(r"number of iterations\s*:\s*(\d+)")
_FATAL_RE = re.compile(r"FATAL ERROR", re.I)


@dataclass
class LogSummary:
    path: str
    status: str = "unknown"  # normal | failed | error | unknown
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    time_steps: list[dict] = field(default_factory=list)
    final_time: float | None = None
    elapsed: float | None = None
    n_iterations: int = 0
    tail: list[str] = field(default_factory=list)
    total_lines: int = 0

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "status": self.status,
            "n_time_steps": len(self.time_steps),
            "time_steps": self.time_steps[-30:],
            "final_time": self.final_time,
            "elapsed_sec": self.elapsed,
            "n_iterations": self.n_iterations,
            "errors": self.errors[:20],
            "warnings": self.warnings[:20],
            "info": self.info[:10],
            "tail": self.tail[-40:],
            "total_lines": self.total_lines,
        }

    def human(self) -> str:
        L = [f"# FEBio 日志摘要: {Path(self.path).name}", f"状态: {self.status}"]
        if self.final_time is not None:
            L.append(f"结束时间: {self.final_time}")
        L.append(f"时间步数: {len(self.time_steps)}")
        if self.elapsed is not None:
            L.append(f"求解耗时: {self.elapsed} s")
        if self.n_iterations:
            L.append(f"末步迭代数: {self.n_iterations}")
        if self.errors:
            L.append("\n## 错误")
            L += [f"  ✗ {e}" for e in self.errors[:12]]
        if self.warnings:
            L.append("\n## 警告")
            L += [f"  ! {w}" for w in self.warnings[:8]]
        if self.status != "normal" and self.tail:
            L.append("\n## 日志末尾")
            L += [f"  {l}" for l in self.tail[-25:]]
        return "\n".join(L)


def _extract_boxes(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """解析 FEBio 的 **** 消息框，分离 ERROR / WARNING / INFO。"""
    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        if _BOX_TOP_RE.match(lines[i]):
            body: list[str] = []
            j = i + 1
            while j < n and not _BOX_TOP_RE.match(lines[j]):
                body.append(lines[j])
                j += 1
            text = " ".join(b.strip().strip("*").strip() for b in body)
            text = re.sub(r"\s+", " ", text).strip()
            up = text.upper()
            if "ERROR" in up:
                msg = re.sub(r"^\s*ERROR\s*", "", text, flags=re.I).strip()
                errors.append(msg or "ERROR")
            elif "WARNING" in up:
                msg = re.sub(r"^\s*WARNING\s*", "", text, flags=re.I).strip()
                warnings.append(msg or "WARNING")
            elif text:
                infos.append(text)
            i = j
        else:
            i += 1
    return errors, warnings, infos


def parse_log(path: str | Path) -> LogSummary:
    p = Path(path)
    if not p.exists():
        return LogSummary(path=str(p), status="error", errors=[f"日志文件不存在: {p}"])
    text = p.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    s = LogSummary(path=str(p), total_lines=len(lines))

    s.errors, s.warnings, s.info = _extract_boxes(lines)

    for line in lines:
        m = _TIME_STEP_RE.search(line)
        if m:
            s.time_steps.append({"step": int(m.group(1)), "time": float(m.group(2))})
            s.final_time = float(m.group(2))
            continue
        m = _ELAPSED_RE.search(line)
        if m:
            try:
                s.elapsed = float(m.group(1))
            except ValueError:
                pass
            continue
        m = _ITER_RE.search(line)
        if m:
            try:
                s.n_iterations = int(m.group(1))
            except ValueError:
                pass
        if _FATAL_RE.search(line):
            s.errors.append(line.strip()[:300])

    tail_text = "\n".join(lines[-80:])
    if _FAIL_RE.search(tail_text) or s.errors:
        s.status = "failed"
    elif _NORMAL_RE.search(tail_text):
        s.status = "normal"
    else:
        s.status = "unknown"

    s.tail = [l.rstrip()[:200] for l in lines[-60:] if l.strip()]
    return s


def quick_status(log_path: str | Path) -> str:
    """只看终止状态，用于轮询后台作业。"""
    p = Path(log_path)
    if not p.exists():
        return "no-log"
    try:
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            tail = f.read()[-6000:]
    except Exception:
        return "unknown"
    if _FAIL_RE.search(tail):
        return "failed"
    if _NORMAL_RE.search(tail):
        return "normal"
    return "running"
