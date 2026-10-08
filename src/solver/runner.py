"""FEBio 求解器调用与作业管理。

封装 febio4 命令行：
    febio4 -i in.feb -o out.log -p out.xplt [-task=..] [-r restart] [-g] [-silent]

支持：
  - 同步运行（阻塞，适合快速算例）
  - 后台作业（Popen + 线程监控，适合长时间算例）
  - 作业状态持久化到 workspace/jobs.json
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import config as _cfg
from solver.logparser import parse_log, quick_status


@dataclass
class Job:
    id: str
    input_feb: str
    log_file: str
    plot_file: str
    work_dir: str
    cmd: list[str] = field(default_factory=list)
    status: str = "queued"  # queued | running | normal | failed | error | timeout | killed
    returncode: int | None = None
    started_at: float | None = None
    finished_at: float | None = None
    stdout_tail: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.started_at and self.finished_at:
            d["duration_sec"] = round(self.finished_at - self.started_at, 2)
        elif self.started_at:
            d["duration_sec"] = round(time.time() - self.started_at, 2)
        d["cmd_str"] = " ".join(self.cmd)
        return d


class FebioRunner:
    _JOBS_FILE = _cfg.WORKSPACE / "jobs.json"

    def __init__(self, exe: Path | None = None):
        self.exe = Path(exe) if exe else _cfg.FEBIO_EXE
        self._jobs: dict[str, Job] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.RLock()
        self._load()

    # -------------------------------------------------- 持久化
    def _load(self) -> None:
        if self._JOBS_FILE.exists():
            try:
                data = json.loads(self._JOBS_FILE.read_text(encoding="utf-8"))
                for j in data:
                    job = Job(**{k: v for k, v in j.items() if k in Job.__dataclass_fields__})
                    # 上次进程已不在，running 视为中断
                    if job.status == "running":
                        job.status = "interrupted"
                    self._jobs[job.id] = job
            except Exception:
                pass

    def _save(self) -> None:
        try:
            self._JOBS_FILE.write_text(
                json.dumps([j.to_dict() for j in self._jobs.values()], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    # -------------------------------------------------- 命令行
    def _build_cmd(
        self,
        input_feb: Path,
        log_file: Path,
        plot_file: Path,
        *,
        silent: bool = True,
        debug: bool = False,
        task: str | None = None,
        restart: str | None = None,
        dump: str | None = None,
        extra_args: list[str] | None = None,
    ) -> list[str]:
        if not self.exe or not Path(self.exe).exists():
            raise FileNotFoundError(
                "找不到 febio4 可执行文件。请设置环境变量 FEBIO_HOME 指向 FEBio 安装目录。"
            )
        cmd = [str(self.exe), "-nosplash"]
        if restart:
            cmd += ["-r", str(restart)]
        else:
            cmd += ["-i", str(input_feb)]
        cmd += ["-o", str(log_file), "-p", str(plot_file)]
        if task:
            cmd += [f"-task={task}"]
        if dump:
            cmd += ["-dump", str(dump)]
        if debug:
            cmd += ["-g"]
        if silent:
            cmd += ["-silent"]
        if extra_args:
            cmd += [str(a) for a in extra_args]
        return cmd

    def _env(self) -> dict:
        env = os.environ.copy()
        if _cfg.FEBIO_HOME:
            binp = str(_cfg.FEBIO_HOME / "bin")
            env["PATH"] = binp + os.pathsep + env.get("PATH", "")
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    # -------------------------------------------------- 同步运行
    def run_sync(
        self,
        input_feb: str | Path,
        out_dir: str | Path | None = None,
        timeout: int | None = None,
        **kw,
    ) -> Job:
        input_feb = Path(input_feb).resolve()
        if not input_feb.exists():
            raise FileNotFoundError(f"输入文件不存在: {input_feb}")
        wd = Path(out_dir).resolve() if out_dir else input_feb.parent
        wd.mkdir(parents=True, exist_ok=True)
        stem = input_feb.stem
        log_file = wd / f"{stem}.log"
        plot_file = wd / f"{stem}.xplt"
        cmd = self._build_cmd(input_feb, log_file, plot_file, **kw)

        job = Job(
            id=uuid.uuid4().hex[:8],
            input_feb=str(input_feb),
            log_file=str(log_file),
            plot_file=str(plot_file),
            work_dir=str(wd),
            cmd=cmd,
            status="running",
            started_at=time.time(),
        )
        to = timeout or _cfg.DEFAULT_TIMEOUT
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(wd),
                env=self._env(),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=to,
            )
            job.returncode = proc.returncode
            job.stdout_tail = ((proc.stdout or "") + (proc.stderr or ""))[-3000:]
            job.status = self._classify(job)
        except subprocess.TimeoutExpired:
            job.status = "timeout"
            job.error = f"超时（>{to}s）"
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
        finally:
            job.finished_at = time.time()
            with self._lock:
                self._jobs[job.id] = job
                self._save()
        return job

    # -------------------------------------------------- 后台运行
    def start(self, input_feb: str | Path, out_dir: str | Path | None = None, **kw) -> Job:
        input_feb = Path(input_feb).resolve()
        if not input_feb.exists():
            raise FileNotFoundError(f"输入文件不存在: {input_feb}")
        wd = Path(out_dir).resolve() if out_dir else input_feb.parent
        wd.mkdir(parents=True, exist_ok=True)
        stem = input_feb.stem
        log_file = wd / f"{stem}.log"
        plot_file = wd / f"{stem}.xplt"
        cmd = self._build_cmd(input_feb, log_file, plot_file, **kw)

        job = Job(
            id=uuid.uuid4().hex[:8],
            input_feb=str(input_feb),
            log_file=str(log_file),
            plot_file=str(plot_file),
            work_dir=str(wd),
            cmd=cmd,
            status="running",
            started_at=time.time(),
        )
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(wd),
                env=self._env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
            )
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
            job.finished_at = time.time()
            with self._lock:
                self._jobs[job.id] = job
                self._save()
            return job

        with self._lock:
            self._jobs[job.id] = job
            self._procs[job.id] = proc
            self._save()

        t = threading.Thread(target=self._watch, args=(job, proc), daemon=True)
        t.start()
        return job

    def _watch(self, job: Job, proc: subprocess.Popen) -> None:
        try:
            out, _ = proc.communicate()
            job.stdout_tail = (out or "")[-3000:]
        except Exception:
            pass
        job.returncode = proc.returncode
        job.finished_at = time.time()
        job.status = self._classify(job)
        with self._lock:
            self._procs.pop(job.id, None)
            self._save()

    def _classify(self, job: Job) -> str:
        """结合返回码与日志判断最终状态。"""
        if Path(job.log_file).exists():
            summary = parse_log(job.log_file)
            if summary.status == "normal":
                return "normal"
            if summary.status == "failed":
                return "failed"
            if summary.status == "error" and job.returncode not in (None, 0):
                return "failed"
        # 没有日志文件（例如输入文件解析失败，FEBio 在读入阶段就退出）
        if job.returncode not in (None, 0):
            return "failed"
        return "normal"

    # -------------------------------------------------- 查询
    def status(self, job_id: str, with_log: bool = True) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return {"error": f"未找到作业 {job_id}"}
        # 运行中：实时看日志
        if job.status == "running":
            st = quick_status(job.log_file)
            if st in ("normal", "failed"):
                job.status = st
                job.finished_at = job.finished_at or time.time()
                with self._lock:
                    self._save()
        d = job.to_dict()
        if with_log:
            lp = Path(job.log_file)
            if lp.exists():
                d["log"] = parse_log(lp).to_dict()
            else:
                # 无日志文件：从屏幕输出里提取关键错误行
                lines = (job.stdout_tail or "").splitlines()
                errs = [l.strip() for l in lines if any(
                    k in l.upper() for k in ("ERROR", "FAILED", "INVALID", "FATAL")
                )]
                d["log"] = {
                    "path": str(lp),
                    "status": "no-log",
                    "errors": errs[:12],
                    "tail": [l.rstrip()[:200] for l in lines[-30:] if l.strip()],
                    "note": "FEBio 未生成日志（通常在读入输入文件阶段就失败），以上为屏幕输出。",
                }
        return d

    def list_jobs(self, limit: int = 20) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.started_at or 0, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    def kill(self, job_id: str) -> dict:
        with self._lock:
            proc = self._procs.get(job_id)
            job = self._jobs.get(job_id)
        if not job:
            return {"error": f"未找到作业 {job_id}"}
        if proc and proc.poll() is None:
            try:
                proc.kill()
                job.status = "killed"
                job.finished_at = time.time()
                with self._lock:
                    self._save()
                return {"ok": True, "job_id": job_id, "status": "killed"}
            except Exception as exc:
                return {"error": str(exc)}
        return {"ok": False, "job_id": job_id, "status": job.status, "note": "进程已结束"}

    def read_log(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return {"error": f"未找到作业 {job_id}"}
        return parse_log(job.log_file).to_dict()
