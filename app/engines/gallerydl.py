"""gallery-dl engine: Instagram stories/highlights/profiles/carousels, Reddit
galleries, Pinterest, X images, TikTok slideshows, imageboards, pixiv, etc."""
import asyncio
import shlex

from ..config import GALLERYDL_BIN
from ..jobs import Ctx, EngineError

NAME = "gallery-dl"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic")


def _base(cfg: dict, cookies) -> list[str]:
    a = [GALLERYDL_BIN]
    if cookies:
        a += ["--cookies", str(cookies)]
    if cfg.get("proxy"):
        a += ["--proxy", cfg["proxy"]]
    return a


async def download(ctx: Ctx):
    cfg, o = ctx.cfg, ctx.opts
    a = _base(cfg, ctx.cookies) + ["-D", str(ctx.outdir), "--no-mtime", "-o", "videos=true"]
    max_items = int(cfg.get("max_playlist_items") or 0)
    if o.get("playlist_items"):
        a += ["--range", str(o["playlist_items"]).replace(":", "-")]
    elif not o.get("playlist"):
        # single post: carousels still come through in full, profiles get capped
        a += ["--range", f"1-{min(max_items or 50, 50)}"]
    elif max_items:
        a += ["--range", f"1-{max_items}"]
    if cfg.get("max_filesize_mb"):
        a += ["--filesize-max", f"{int(cfg['max_filesize_mb'])}M"]
    if cfg.get("gallerydl_extra_args"):
        a += shlex.split(cfg["gallerydl_extra_args"])
    a += ["--", ctx.url]

    count = 0
    outdir = str(ctx.outdir)

    def on_line(line: str):
        nonlocal count
        # gallery-dl prints each finished file path (skipped ones prefixed with "# ")
        if line.lstrip("# ").startswith(outdir):
            count += 1
            ctx.set(status="running", progress=None, message=f"Grabbed {count} file{'s' * (count != 1)}")

    ctx.set(message="Fetching media list...")
    rc = await ctx.run(a, on_line)
    if count == 0:
        raise EngineError(ctx.last_error("gallery-dl found nothing there."))
    if rc not in (0, 4, 8):  # 4/8 = some files failed but we got stuff
        ctx.log(f"[gallery-dl] exited {rc}, keeping what we got")


async def analyze(url: str, cfg: dict, cookies) -> dict:
    cmd = _base(cfg, cookies) + ["--get-urls", "--range", "1-60", "--", url]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        raise EngineError("gallery-dl took too long.")
    urls = [u.strip() for u in out.decode("utf-8", "replace").splitlines()
            if u.strip().startswith(("http", "ytdl:"))]
    if not urls:
        msg = [m for m in err.decode("utf-8", "replace").splitlines() if "error" in m.lower()]
        raise EngineError((msg[-1] if msg else "gallery-dl found nothing there.")[:400])
    thumb = next((u for u in urls if u.split("?")[0].lower().endswith(IMAGE_EXT)), None)
    return {
        "engine": NAME, "extractor": "gallery", "title": url.rstrip("/").split("/")[-1] or url,
        "thumbnail": thumb, "is_playlist": len(urls) > 1, "count": len(urls),
        "count_capped": len(urls) >= 60, "is_gallery": True,
        "entries": [{"title": u.split("?")[0].rsplit("/", 1)[-1], "thumbnail":
                     u if u.split("?")[0].lower().endswith(IMAGE_EXT) else None} for u in urls[:60]],
    }
