"""Job queue: runs engines as subprocesses, tracks progress, zips multi-file
results and garbage-collects old downloads."""
import asyncio
import os
import re
import shutil
import signal
import sys
import time
import uuid
import zipfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .config import DOWNLOAD_DIR, TMP_DIR, settings
from . import cookies as cookie_utils

JUNK_SUFFIXES = (".part", ".ytdl", ".frag", ".temp", ".tmp", ".partial")


class Cancelled(Exception):
    pass


class EngineError(Exception):
    pass


@dataclass
class Job:
    url: str
    opts: dict
    ip: str
    owner: str = ""  # random per-browser id from the fdl_owner cookie
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    expires_at: float | None = None
    status: str = "queued"  # queued | running | processing | done | error | cancelled
    progress: float | None = None
    speed: float | None = None
    eta: float | None = None
    downloaded: int | None = None
    total: int | None = None
    item: int | None = None
    items: int | None = None
    message: str = "Waiting in line..."
    title: str = ""
    thumbnail: str = ""
    engine: str = ""
    error: str = ""
    files: list = field(default_factory=list)
    archive: str = ""
    log: deque = field(default_factory=lambda: deque(maxlen=300))
    cancelled: bool = False
    proc: object = None

    @property
    def dir(self) -> Path:
        return DOWNLOAD_DIR / self.id

    @property
    def outdir(self) -> Path:
        return self.dir / "files"

    def public(self, admin: bool = False) -> dict:
        d = {
            "id": self.id, "url": self.url, "status": self.status,
            "progress": self.progress, "speed": self.speed, "eta": self.eta,
            "downloaded": self.downloaded, "total": self.total,
            "item": self.item, "items": self.items, "message": self.message,
            "title": self.title, "thumbnail": self.thumbnail, "engine": self.engine,
            "error": self.error, "created": self.created, "finished": self.finished,
            "expires_at": self.expires_at,
            "expires_in": max(0.0, self.expires_at - time.time()) if self.expires_at else None,
            "mode": self.opts.get("mode"),
            "files": [{"name": Path(f).name, "path": f, "size": s} for f, s in self.files],
            "has_archive": bool(self.archive),
        }
        if admin:
            d["ip"] = self.ip
            d["log"] = list(self.log)[-80:]
            d["opts"] = self.opts
        return d


class Ctx:
    """What an engine gets to work with."""

    def __init__(self, job: Job, cfg: dict):
        self.job = job
        self.cfg = cfg
        self.outdir = job.outdir
        self.tmpdir = TMP_DIR / job.id
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.cookies = cookie_utils.write_merged(cfg.get("cookies", {}), self.tmpdir / "cookies.txt")
        self.opts = job.opts

    @property
    def url(self) -> str:
        return self.job.url

    def set(self, **kw):
        for k, v in kw.items():
            setattr(self.job, k, v)

    def log(self, line: str):
        self.job.log.append(line)

    def check(self):
        if self.job.cancelled:
            raise Cancelled()

    async def run(self, cmd: list[str], on_line=None, cwd: Path | None = None, env: dict | None = None) -> int:
        self.check()
        self.log("$ " + " ".join(_redact(cmd)))
        full_env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **(env or {})}
        kwargs = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, cwd=str(cwd or self.outdir), env=full_env, **kwargs,
        )
        self.job.proc = proc
        buf = b""
        try:
            while True:
                chunk = await proc.stdout.read(8192)
                if not chunk:
                    break
                buf += chunk
                parts = re.split(rb"[\r\n]", buf)
                buf = parts.pop()
                for raw in parts:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    if not line.startswith("FDLP "):
                        self.log(line)
                    if on_line:
                        try:
                            on_line(line)
                        except Exception as e:  # never let a parser bug kill the job
                            self.log(f"[parser] {e!r}")
            if buf.strip():
                line = buf.decode("utf-8", "replace").strip()
                self.log(line)
                if on_line:
                    on_line(line)
            return await proc.wait()
        finally:
            self.job.proc = None
            if proc.returncode is None:
                _kill(proc)
            self.check()

    def last_error(self, default: str = "Download failed.") -> str:
        for line in reversed(self.job.log):
            if "ERROR" in line or "[error]" in line or "Error:" in line:
                return re.sub(r"^.*?ERROR:\s*", "", line)[:500]
        return default


def _redact(cmd):
    out, hide = [], False
    for a in cmd:
        out.append("***" if hide else a)
        hide = a in ("--client-secret", "--password", "-p")
    return out


def _kill(proc):
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _is_junk(p: Path) -> bool:
    n = p.name.lower()
    return n.endswith(JUNK_SUFFIXES) or ".temp." in n or n.startswith(".")


def _safe_name(s: str, default: str = "download") -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", s or "").strip(" .")
    return (s[:120] or default)


def expiry_seconds() -> float:
    try:
        return max(1.0, float(settings.get().get("file_expiry_minutes") or 10)) * 60
    except (TypeError, ValueError):
        return 600.0


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.running: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    # --- queue -----------------------------------------------------------
    def active_for_ip(self, ip: str) -> int:
        return sum(1 for j in self.jobs.values() if j.ip == ip and j.status in ("queued", "running", "processing"))

    def for_owner(self, owner: str) -> list[Job]:
        return sorted((j for j in self.jobs.values() if j.owner == owner), key=lambda j: -j.created)

    def submit(self, url: str, opts: dict, ip: str, owner: str) -> Job:
        job = Job(url=url, opts=opts, ip=ip, owner=owner)
        self.jobs[job.id] = job
        self._kick()
        return job

    def _kick(self):
        limit = max(1, int(settings.get().get("max_concurrent", 3)))
        for job in sorted(self.jobs.values(), key=lambda j: j.created):
            if len(self.running) >= limit:
                break
            if job.status == "queued" and job.id not in self.running:
                self.running.add(job.id)
                t = asyncio.create_task(self._run(job))
                self._tasks.add(t)
                t.add_done_callback(self._tasks.discard)
        # update queue positions
        pos = 0
        for job in sorted(self.jobs.values(), key=lambda j: j.created):
            if job.status == "queued" and job.id not in self.running:
                pos += 1
                job.message = f"In queue (#{pos})"

    async def _run(self, job: Job):
        from .engines import run_chain  # avoid import cycle

        job.status, job.started, job.message = "running", time.time(), "Starting..."
        ctx = None
        try:
            ctx = Ctx(job, settings.get())
            await run_chain(ctx)
            ctx.check()
            self._finalize(job)
            job.status, job.progress, job.message = "done", 100.0, "Done. Go get it."
        except Cancelled:
            job.status, job.message = "cancelled", "Cancelled."
            shutil.rmtree(job.dir, ignore_errors=True)
            job.files = []
        except Exception as e:  # EngineError or anything unexpected
            job.status, job.error = "error", str(e) or e.__class__.__name__
            job.message = "Failed."
            job.log.append(f"[fdl] {e!r}")
        finally:
            job.finished = time.time()
            job.expires_at = job.finished + expiry_seconds()
            job.speed = job.eta = None
            if ctx:
                shutil.rmtree(ctx.tmpdir, ignore_errors=True)
            self.running.discard(job.id)
            self._kick()

    def _finalize(self, job: Job):
        files = sorted(
            (p for p in job.outdir.rglob("*") if p.is_file() and not _is_junk(p)),
            key=lambda p: str(p).lower(),
        )
        if not files:
            raise EngineError("Nothing got downloaded. The link might be private, geo-blocked or need cookies.")
        job.files = [(str(p.relative_to(job.outdir)).replace("\\", "/"), p.stat().st_size) for p in files]
        if not job.title:
            job.title = files[0].stem
        if len(files) > 1:
            job.status, job.message = "processing", f"Zipping {len(files)} files..."
            subdirs = [p for p in job.outdir.iterdir() if p.is_dir()]
            name = _safe_name(subdirs[0].name if len(subdirs) == 1 else job.title)
            zpath = job.dir / f"{name}.zip"
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
                for p in files:
                    z.write(p, str(p.relative_to(job.outdir)))
            job.archive = str(zpath)

    def cancel(self, job: Job):
        if job.status in ("done", "error", "cancelled"):
            return
        job.cancelled = True
        if job.status == "queued":
            job.status, job.message, job.finished = "cancelled", "Cancelled.", time.time()
            job.expires_at = job.finished + expiry_seconds()
        if job.proc is not None:
            _kill(job.proc)

    def delete(self, job: Job):
        self.cancel(job)
        shutil.rmtree(job.dir, ignore_errors=True)
        self.jobs.pop(job.id, None)

    # --- housekeeping ----------------------------------------------------
    async def janitor(self):
        # wipe leftovers from a previous run, jobs live in memory only
        for d in list(DOWNLOAD_DIR.iterdir()) + list(TMP_DIR.iterdir()):
            shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True)
        while True:
            await asyncio.sleep(10)
            try:
                now = time.time()
                for job in list(self.jobs.values()):
                    if job.expires_at and job.expires_at <= now:
                        self.delete(job)
            except Exception as e:
                print(f"[janitor] {e!r}", file=sys.stderr)


manager = JobManager()
