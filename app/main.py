"""FuckinDownloader web app. Public downloader at /, admin panel at ADMIN_PATH."""
import asyncio
import hmac
import os
import shutil
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from . import cookies as cookie_utils
from . import engines
from .config import (ADMIN_PASSWORD, ADMIN_PATH, COOKIE_SLOTS, DATA_DIR, FFMPEG_BIN, GALLERYDL_BIN,
                     SPOTDL_BIN, TRUST_PROXY, YTDLP_BIN, secret_key, settings)
from .jobs import EngineError, manager
from .netguard import BlockedURL, check_url

STATIC = Path(__file__).parent / "static"
VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(manager.janitor())
    yield
    task.cancel()


app = FastAPI(title="FuckinDownloader", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=secret_key(), session_cookie="fdl_admin",
                   max_age=7 * 24 * 3600, same_site="lax",
                   https_only=os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes"))
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# --- helpers -------------------------------------------------------------
def client_ip(req: Request) -> str:
    if TRUST_PROXY:
        fwd = req.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        if req.headers.get("x-real-ip"):
            return req.headers["x-real-ip"]
    return req.client.host if req.client else "?"


def is_admin(req: Request) -> bool:
    return bool(ADMIN_PASSWORD) and req.session.get("admin") is True


def require_admin(req: Request):
    if not is_admin(req):
        raise HTTPException(401, "Admins only.")
    # cheap CSRF guard: browsers won't add custom headers cross-site without CORS
    if req.method not in ("GET", "HEAD") and req.headers.get("x-fdl") != "1":
        raise HTTPException(403, "Missing X-FDL header.")


def require_public(req: Request):
    if is_admin(req):
        return
    cfg = settings.get()
    if not cfg.get("public_enabled", True):
        raise HTTPException(403, "The public downloader is switched off.")
    pw = cfg.get("public_password") or ""
    if pw:
        given = req.headers.get("x-access-key") or req.query_params.get("key") or ""
        if not hmac.compare_digest(given.encode(), pw.encode()):
            raise HTTPException(401, "Access key required.")


def _err(e: Exception, code: int = 400):
    return JSONResponse({"error": str(e)}, status_code=code)


# --- pages ---------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(STATIC / "index.html")


@app.get(ADMIN_PATH, response_class=HTMLResponse)
async def admin_page(req: Request):
    if not is_admin(req):
        return FileResponse(STATIC / "login.html")
    return FileResponse(STATIC / "admin.html")


_fails: dict[str, list[float]] = {}


@app.post(ADMIN_PATH + "/login")
async def admin_login(req: Request):
    ip = client_ip(req)
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 900]
    _fails[ip] = recent
    if len(recent) >= 8:
        raise HTTPException(429, "Too many attempts. Go touch grass for 15 minutes.")
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "Set the ADMIN_PASSWORD env var to enable the admin panel.")
    form = await req.form()
    pw = str(form.get("password", ""))
    if not hmac.compare_digest(pw.encode(), ADMIN_PASSWORD.encode()):
        recent.append(now)
        await asyncio.sleep(1)
        return RedirectResponse(ADMIN_PATH + "?bad=1", status_code=303)
    req.session.clear()
    req.session["admin"] = True
    return RedirectResponse(ADMIN_PATH, status_code=303)


@app.post(ADMIN_PATH + "/logout")
async def admin_logout(req: Request):
    req.session.clear()
    return RedirectResponse(ADMIN_PATH, status_code=303)


# --- public api ----------------------------------------------------------
class AnalyzeIn(BaseModel):
    url: str = Field(max_length=4000)
    mode: str = "video"


class Options(BaseModel):
    mode: str = "video"  # video | audio | image | thumbnail | original
    video_quality: str = "1080"
    video_container: str = "mp4"
    video_codec: str = "compat"
    audio_format: str = "mp3"
    audio_quality: str = "320"
    playlist: bool = False
    playlist_items: str = ""
    subtitles: bool = False
    sponsorblock: bool = False
    engine: str = "auto"


class JobIn(BaseModel):
    url: str = Field(max_length=4000)
    options: Options = Options()


ALLOWED = {
    "mode": {"video", "audio", "image", "thumbnail", "original"},
    "video_quality": {"best", "4320", "2160", "1440", "1080", "720", "480", "360", "240", "144"},
    "video_container": {"mp4", "mkv", "webm"},
    "video_codec": {"compat", "best"},
    "audio_format": {"mp3", "m4a", "opus", "flac", "wav", "ogg"},
    "audio_quality": {"best", "320", "256", "192", "160", "128", "96"},
}


def _clean_opts(o: Options, admin: bool) -> dict:
    d = o.model_dump()
    for k, allowed in ALLOWED.items():
        if d[k] not in allowed:
            raise HTTPException(400, f"Bad value for {k}.")
    items = d["playlist_items"].strip()
    if items and not all(c in "0123456789,:-" for c in items):
        raise HTTPException(400, "Playlist items look like '1-10,15' or '1:20'.")
    d["playlist_items"] = items[:100]
    builtin = {"auto", "ytdlp", "gallerydl", "spotdl", "match", "sniff"}
    if d["engine"] not in builtin:
        customs = {e.get("name") for e in settings.get().get("custom_engines") or []}
        if d["engine"] not in customs or not admin:
            d["engine"] = "auto"
    return d


@app.get("/api/config")
async def public_config(req: Request):
    cfg = settings.get()
    return {
        "title": cfg["site_title"], "tagline": cfg["tagline"], "defaults": cfg["defaults"],
        "public_enabled": cfg["public_enabled"], "access_key_required": bool(cfg["public_password"]),
        "is_admin": is_admin(req), "max_playlist_items": cfg["max_playlist_items"], "version": VERSION,
        "custom_engines": [e["name"] for e in cfg.get("custom_engines") or [] if e.get("enabled", True)]
        if is_admin(req) else [],
    }


_analyze_hits: dict[str, list[float]] = {}


@app.post("/api/analyze", dependencies=[Depends(require_public)])
async def api_analyze(body: AnalyzeIn, req: Request):
    cfg = settings.get()
    ip, now = client_ip(req), time.time()
    hits = [t for t in _analyze_hits.get(ip, []) if now - t < 60]
    if len(hits) >= 30 and not is_admin(req):
        return _err(Exception("Slow down a bit."), 429)
    _analyze_hits[ip] = hits + [now]
    try:
        url = await check_url(body.url, cfg["allow_private_urls"] or is_admin(req))
        return await engines.analyze(url, {"mode": body.mode}, cfg)
    except (BlockedURL, EngineError) as e:
        return _err(e, 422)
    except Exception as e:
        return _err(Exception(f"Couldn't analyze that: {e}"), 422)


@app.post("/api/jobs", dependencies=[Depends(require_public)])
async def api_create_job(body: JobIn, req: Request):
    cfg = settings.get()
    admin = is_admin(req)
    ip = client_ip(req)
    try:
        url = await check_url(body.url, cfg["allow_private_urls"] or admin)
    except BlockedURL as e:
        return _err(e)
    if not admin and manager.active_for_ip(ip) >= int(cfg.get("max_jobs_per_ip") or 3):
        return _err(Exception("Chill, you already have downloads running. Wait for them to finish."), 429)
    job = manager.submit(url, _clean_opts(body.options, admin), ip)
    return job.public()


def _get_job(job_id: str):
    job = manager.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "That download doesn't exist (anymore).")
    return job


@app.get("/api/jobs")
async def api_jobs(ids: str = ""):
    # job ids are unguessable, knowing one is the access token
    out = []
    for jid in ids.split(",")[:100]:
        job = manager.jobs.get(jid.strip())
        if job:
            out.append(job.public())
    return out


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str):
    return _get_job(job_id).public()


@app.post("/api/jobs/{job_id}/cancel")
async def api_cancel(job_id: str):
    job = _get_job(job_id)
    manager.cancel(job)
    return job.public()


@app.get("/api/jobs/{job_id}/file")
async def api_file(job_id: str):
    job = _get_job(job_id)
    if job.status != "done" or not job.files:
        raise HTTPException(409, "Not ready yet.")
    if job.archive:
        p = Path(job.archive)
    else:
        p = job.outdir / job.files[0][0]
    if not p.exists():
        raise HTTPException(410, "File expired.")
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


@app.get("/api/jobs/{job_id}/files/{idx}")
async def api_file_n(job_id: str, idx: int):
    job = _get_job(job_id)
    if job.status != "done" or not (0 <= idx < len(job.files)):
        raise HTTPException(404, "No such file.")
    p = (job.outdir / job.files[idx][0]).resolve()
    if not p.is_relative_to(job.outdir.resolve()) or not p.exists():
        raise HTTPException(410, "File expired.")
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


# --- admin api -----------------------------------------------------------
admin_dep = [Depends(require_admin)]
SECRET_FIELDS = ("public_password",)


@app.get("/api/admin/settings", dependencies=admin_dep)
async def admin_get_settings():
    cfg = settings.get()
    cfg["cookie_slots"] = COOKIE_SLOTS
    cfg["cookie_counts"] = {k: cookie_utils.count(v) for k, v in cfg["cookies"].items()}
    return cfg


@app.put("/api/admin/settings", dependencies=admin_dep)
async def admin_put_settings(req: Request):
    patch = await req.json()
    if not isinstance(patch, dict):
        raise HTTPException(400, "Expected an object.")
    patch.pop("cookie_slots", None)
    patch.pop("cookie_counts", None)
    for k in ("max_concurrent", "max_jobs_per_ip", "max_playlist_items", "max_filesize_mb"):
        if k in patch:
            patch[k] = max(0, int(patch[k] or 0))
    if "max_concurrent" in patch:
        patch["max_concurrent"] = max(1, patch["max_concurrent"])
    if "retention_hours" in patch:
        patch["retention_hours"] = max(0.1, float(patch["retention_hours"] or 6))
    if "custom_engines" in patch:
        patch["custom_engines"] = [
            {"name": str(e.get("name", "")).strip()[:40], "pattern": str(e.get("pattern", "")),
             "command": str(e.get("command", "")), "enabled": bool(e.get("enabled", True))}
            for e in patch["custom_engines"] if str(e.get("name", "")).strip()
        ]
    cfg = settings.update(patch)
    manager._kick()
    return {"ok": True, "cookie_counts": {k: cookie_utils.count(v) for k, v in cfg["cookies"].items()}}


@app.get("/api/admin/jobs", dependencies=admin_dep)
async def admin_jobs():
    return [j.public(admin=True) for j in sorted(manager.jobs.values(), key=lambda j: -j.created)]


@app.post("/api/admin/jobs/{job_id}/cancel", dependencies=admin_dep)
async def admin_cancel(job_id: str):
    manager.cancel(_get_job(job_id))
    return {"ok": True}


@app.delete("/api/admin/jobs/{job_id}", dependencies=admin_dep)
async def admin_delete(job_id: str):
    manager.delete(_get_job(job_id))
    return {"ok": True}


@app.post("/api/admin/jobs/clear", dependencies=admin_dep)
async def admin_clear():
    n = 0
    for job in list(manager.jobs.values()):
        if job.status in ("done", "error", "cancelled"):
            manager.delete(job)
            n += 1
    return {"ok": True, "removed": n}


async def _version(cmd: list[str], first: bool = False) -> str:
    try:
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(p.communicate(), 20)
        lines = [l for l in out.decode("utf-8", "replace").strip().splitlines() if l.strip()]
        line = lines[0] if first else lines[-1]
        return line.replace("Copyright", "").split(" (c)")[0].strip()[:80]
    except Exception:
        return "not installed"


@app.get("/api/admin/system", dependencies=admin_dep)
async def admin_system():
    vers = await asyncio.gather(
        _version([YTDLP_BIN, "--version"]), _version([GALLERYDL_BIN, "--version"]),
        _version([SPOTDL_BIN, "--version"]), _version([FFMPEG_BIN, "-version"], first=True),
        _version(["deno", "--version"], first=True),
    )
    du = shutil.disk_usage(DATA_DIR)
    used = sum(f.stat().st_size for f in (DATA_DIR / "downloads").rglob("*") if f.is_file())
    return {
        "app": VERSION, "python": sys.version.split()[0],
        "versions": dict(zip(["yt-dlp", "gallery-dl", "spotdl", "ffmpeg", "deno"], vers)),
        "disk": {"total": du.total, "free": du.free, "downloads": used},
        "jobs": {s: sum(1 for j in manager.jobs.values() if j.status == s)
                 for s in ("queued", "running", "processing", "done", "error", "cancelled")},
        "admin_path": ADMIN_PATH,
    }


_update_lock = asyncio.Lock()


@app.post("/api/admin/update", dependencies=admin_dep)
async def admin_update(req: Request):
    body = await req.json() if req.headers.get("content-length") not in (None, "0") else {}
    nightly = bool((body or {}).get("nightly"))
    if _update_lock.locked():
        raise HTTPException(409, "Already updating.")
    async with _update_lock:
        cmds = [[sys.executable, "-m", "pip", "install", "-U", "--no-cache-dir"]
                + (["--pre"] if nightly else []) + ["yt-dlp[default,curl-cffi]", "gallery-dl"]]
        spot_pip = os.environ.get("FDL_SPOTDL_PIP")
        if spot_pip and Path(spot_pip).exists():
            cmds.append([spot_pip, "install", "-U", "--no-cache-dir", "spotdl"])
        log = []
        for cmd in cmds:
            p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.STDOUT)
            out, _ = await asyncio.wait_for(p.communicate(), 600)
            text = out.decode("utf-8", "replace").strip().splitlines()
            log.append(f"$ {' '.join(cmd[-3:])}\n" + "\n".join(text[-6:]))
        return {"ok": True, "log": "\n\n".join(log)}


@app.get("/healthz")
async def healthz():
    return {"ok": True}
