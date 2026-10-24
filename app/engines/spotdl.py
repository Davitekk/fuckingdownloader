"""spotdl engine: Spotify tracks, albums, playlists and artists. Metadata and
cover art come from Spotify, audio is matched on YouTube Music."""
import re
import shlex

from ..config import FFMPEG_BIN, SPOTDL_BIN
from ..jobs import Ctx, EngineError

NAME = "spotdl"
SPOTDL_FORMATS = {"mp3", "flac", "ogg", "opus", "m4a", "wav"}


async def download(ctx: Ctx):
    cfg, o = ctx.cfg, ctx.opts
    fmt = o.get("audio_format", "mp3")
    fmt = fmt if fmt in SPOTDL_FORMATS else "mp3"
    q = str(o.get("audio_quality", "320"))
    is_list = not re.search(r"/track/", ctx.url)
    tpl = "{list-name}/{list-position} - {artists} - {title}.{output-ext}" if is_list else "{artists} - {title}.{output-ext}"
    a = [SPOTDL_BIN, "download", ctx.url, "--output", str(ctx.outdir / tpl), "--format", fmt,
         "--bitrate", "auto" if q == "best" else f"{q}k", "--ffmpeg", FFMPEG_BIN, "--threads", "2",
         "--simple-tui", "--print-errors", "--overwrite", "skip"]
    sp = cfg.get("spotify") or {}
    if sp.get("client_id") and sp.get("client_secret"):
        a += ["--client-id", sp["client_id"], "--client-secret", sp["client_secret"]]
    if ctx.cookies:
        a += ["--cookie-file", str(ctx.cookies)]
    if cfg.get("proxy"):
        a += ["--proxy", cfg["proxy"]]
    if o.get("sponsorblock"):
        a += ["--sponsor-block"]
    if cfg.get("spotdl_extra_args"):
        a += shlex.split(cfg["spotdl_extra_args"])

    st = {"total": None, "done": 0}

    def on_line(line: str):
        m = re.search(r"Found (\d+) songs? in (.+?)(?: \(|$)", line)
        if m:
            st["total"] = int(m.group(1))
            ctx.job.title = ctx.job.title or m.group(2).strip()
        if line.startswith(("Downloaded", "Skipping")) or "LookupError" in line or "AudioProviderError" in line:
            st["done"] += 1
        if st["total"]:
            ctx.set(status="running", progress=min(st["done"] / st["total"] * 100, 99.0),
                    item=min(st["done"] + 1, st["total"]), items=st["total"],
                    message=f"Song {min(st['done'] + 1, st['total'])}/{st['total']}")
        elif "Processing query" in line or "Fetching" in line:
            ctx.set(message="Asking Spotify...")

    ctx.set(message="Asking Spotify...")
    rc = await ctx.run(a, on_line)
    got = [p for p in ctx.outdir.rglob("*") if p.is_file() and not p.name.endswith((".part", ".temp"))]
    if not got:
        raise EngineError(ctx.last_error("spotdl got nothing (missing Spotify API credentials?)"))
    if rc != 0:
        ctx.log(f"[spotdl] exited {rc}, keeping {len(got)} file(s)")
