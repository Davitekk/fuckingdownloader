"""yt-dlp engine: YouTube, TikTok, Reddit, Instagram reels, X, Twitch,
SoundCloud, Vimeo, adult sites and ~1800 other extractors."""
import asyncio
import json
import os
import shlex

from ..config import YTDLP_BIN
from ..jobs import Ctx, EngineError

NAME = "yt-dlp"

PROGRESS_TPL = (
    "download:FDLP %(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
    "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|"
    "%(info.playlist_index)s|%(info.n_entries)s|%(info.thumbnail)s|%(info.title)s"
)

NO_THUMB_EMBED = {"wav", "webm", "aiff"}


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def common_args(cfg: dict, cookies, extra_net: bool = True) -> list[str]:
    a = [YTDLP_BIN, "--newline", "--no-colors", "--no-mtime"]
    if cookies:
        a += ["--cookies", str(cookies)]
    if extra_net and cfg.get("proxy"):
        a += ["--proxy", cfg["proxy"]]
    pot = cfg.get("pot_provider_url") or os.environ.get("POT_PROVIDER_URL")
    if pot:
        a += ["--extractor-args", f"youtubepot-bgutilhttp:base_url={pot}"]
    return a


def build_cmd(ctx: Ctx, url: str, referer: str | None = None) -> list[str]:
    o, cfg = ctx.opts, ctx.cfg
    mode = o.get("mode", "video")
    a = common_args(cfg, ctx.cookies)
    a += ["-P", str(ctx.outdir), "-P", f"temp:{ctx.tmpdir}", "--progress", "--progress-template", PROGRESS_TPL,
          "--concurrent-fragments", "4", "--trim-filenames", "160", "--windows-filenames"]
    if referer:
        a += ["--referer", referer]
    if cfg.get("max_filesize_mb"):
        a += ["--max-filesize", f"{int(cfg['max_filesize_mb'])}M"]

    max_items = int(cfg.get("max_playlist_items") or 0)
    if o.get("playlist"):
        a += ["--yes-playlist", "-o",
              "%(playlist_title,playlist_id|Playlist).80B/%(playlist_index,playlist_autonumber|0)03d - %(title).150B.%(ext)s"]
        if o.get("playlist_items"):
            a += ["-I", str(o["playlist_items"])]
        if max_items:
            a += ["--playlist-end", str(max_items)]
        a += ["--ignore-errors"]  # one dead video shouldn't kill the whole playlist
    else:
        a += ["--no-playlist", "-o", "%(title).180B.%(ext)s"]

    if mode == "audio":
        fmt = o.get("audio_format", "mp3")
        q = str(o.get("audio_quality", "320"))
        a += ["-f", "ba/b", "-x", "--audio-format", fmt,
              "--audio-quality", "0" if q == "best" else f"{q}K"]
        a += ["--embed-metadata"]
        if fmt not in NO_THUMB_EMBED:
            a += ["--embed-thumbnail", "--convert-thumbnails", "jpg",
                  # square-crop YouTube covers so they look like album art
                  "--ppa", "ThumbnailsConvertor+FFmpeg_o:-c:v mjpeg -vf crop=\"'if(gt(ih,iw),iw,ih)':'if(gt(iw,ih),ih,iw)'\""]
    elif mode == "thumbnail":
        a += ["--skip-download", "--write-thumbnail", "--convert-thumbnails", "jpg"]
    elif mode == "original":
        a += ["-f", "bv*+ba/b", "--embed-metadata"]
    else:
        q = str(o.get("video_quality", "1080"))
        container = o.get("video_container", "mp4")
        sort = [] if q == "best" else [f"res:{q}"]
        if o.get("video_codec", "compat") == "compat" and container == "mp4":
            sort += ["vcodec:h264", "acodec:m4a"]
        a += ["-f", "bv*+ba/b", "--merge-output-format", container, "--remux-video", container]
        if sort:
            a += ["-S", ",".join(sort)]
        a += ["--embed-metadata", "--embed-chapters"]
        if container != "webm":
            a += ["--embed-thumbnail", "--convert-thumbnails", "jpg"]
        if o.get("subtitles"):
            a += ["--embed-subs", "--sub-langs", "all,-live_chat"]

    if o.get("sponsorblock") and mode in ("audio", "video"):
        a += ["--sponsorblock-remove", "sponsor,selfpromo,interaction,intro,outro,music_offtopic"]

    if cfg.get("ytdlp_extra_args"):
        a += shlex.split(cfg["ytdlp_extra_args"])
    return a + ["--", url]


def progress_parser(ctx: Ctx):
    state = {"item": None, "items": None}

    def on_line(line: str):
        j = ctx.job
        if line.startswith("FDLP "):
            parts = line[5:].split("|", 9)
            if len(parts) < 10:
                return
            status, done, total, est, speed, eta, idx, n, thumb, title = parts
            done, total = _num(done), _num(total) or _num(est)
            idx, n = _num(idx), _num(n)
            frac = (done / total) if done is not None and total else None
            if idx and n and ctx.opts.get("playlist"):
                state["item"], state["items"] = int(idx), int(n)
                pct = ((idx - 1) + (frac or 0)) / n * 100
                msg = f"Downloading {int(idx)}/{int(n)}"
            else:
                pct = frac * 100 if frac is not None else None
                msg = "Downloading"
            ctx.set(status="running", progress=pct, speed=_num(speed), eta=_num(eta),
                    downloaded=int(done) if done else None, total=int(total) if total else None,
                    item=state["item"], items=state["items"], message=msg)
            if title and title != "NA" and not j.title:
                j.title = title
            if thumb and thumb != "NA" and not j.thumbnail:
                j.thumbnail = thumb
        elif line.startswith("[download] Downloading item "):
            # "[download] Downloading item 3 of 12"
            try:
                bits = line.split()
                state["item"], state["items"] = int(bits[3]), int(bits[5])
                ctx.set(item=state["item"], items=state["items"])
            except (IndexError, ValueError):
                pass
        elif line.startswith("[download] Downloading playlist: "):
            ctx.job.title = line.split(": ", 1)[1]
        elif line.startswith(("[Merger]", "[ExtractAudio]", "[EmbedThumbnail]", "[VideoRemuxer]",
                              "[FFmpegMetadata]", "[Metadata]", "[SponsorBlock]", "[ModifyChapters]",
                              "[EmbedSubtitle]", "[ThumbnailsConvertor]", "[VideoConvertor]")):
            ctx.set(status="processing", message=line.split("]", 1)[0].strip("[") + "...", speed=None, eta=None)
    return on_line


async def download(ctx: Ctx, url: str | None = None, referer: str | None = None):
    rc = await ctx.run(build_cmd(ctx, url or ctx.url, referer), progress_parser(ctx))
    if rc != 0:
        # with --ignore-errors on playlists a partial result is still a result
        if ctx.opts.get("playlist") and any(ctx.outdir.rglob("*.*")):
            return
        raise EngineError(ctx.last_error())


async def analyze(url: str, cfg: dict, cookies) -> dict:
    cmd = common_args(cfg, cookies) + ["-J", "--flat-playlist", "--no-warnings", "--playlist-end", "200",
                                       "--", url]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=90)
    except asyncio.TimeoutError:
        proc.kill()
        raise EngineError("Took too long to look at that link.")
    if proc.returncode != 0:
        msg = err.decode("utf-8", "replace").strip().splitlines()
        msg = [m for m in msg if "ERROR" in m] or msg or ["yt-dlp couldn't read that."]
        raise EngineError(msg[-1].replace("ERROR: ", "")[:400])
    info = json.loads(out)
    is_list = info.get("_type") in ("playlist", "multi_video") or bool(info.get("entries"))
    res = {
        "engine": NAME,
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "title": info.get("title") or info.get("id"),
        "uploader": info.get("uploader") or info.get("channel") or info.get("artist"),
        "thumbnail": info.get("thumbnail") or _best_thumb(info.get("thumbnails")),
        "duration": info.get("duration"),
        "is_playlist": is_list,
    }
    if is_list:
        entries = [e for e in (info.get("entries") or []) if e]
        res["count"] = info.get("playlist_count") or len(entries)
        res["entries"] = [{
            "title": e.get("title") or e.get("id") or e.get("url"),
            "duration": e.get("duration"),
            "thumbnail": e.get("thumbnail") or _best_thumb(e.get("thumbnails")),
        } for e in entries[:200]]
        if not res["thumbnail"] and res["entries"]:
            res["thumbnail"] = res["entries"][0]["thumbnail"]
    else:
        fmts = info.get("formats") or []
        heights = sorted({f["height"] for f in fmts if f.get("height") and f.get("vcodec") != "none"}, reverse=True)
        res["heights"] = heights
        res["has_video"] = bool(heights) or info.get("vcodec") not in (None, "none")
        res["has_audio"] = any(f.get("acodec") not in (None, "none") for f in fmts) or not fmts
    return res


def _best_thumb(thumbs):
    if not thumbs:
        return None
    thumbs = [t for t in thumbs if t.get("url")]
    if not thumbs:
        return None
    return max(thumbs, key=lambda t: (t.get("preference") or 0, t.get("width") or 0))["url"]
