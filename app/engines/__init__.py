"""Picks which engine(s) handle a URL and falls through the chain until one
of them actually produces a file."""
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from . import custom, gallerydl, music, sniff, spotdl, ytdlp
from .. import cookies as cookie_utils
from ..config import TMP_DIR
from ..jobs import Cancelled, Ctx, EngineError

GALLERY_HOSTS = (
    "pinterest.", "pin.it", "imgur.com", "flickr.com", "deviantart.com", "artstation.com", "pixiv.net",
    "tumblr.com", "danbooru.", "gelbooru.", "e621.net", "rule34.", "kemono.", "coomer.", "bsky.app",
    "imgbox.com", "catbox.moe", "4chan.org", "4channel.org", "hentai-foundry.com", "nhentai.net",
    "exhentai.org", "e-hentai.org", "furaffinity.net", "weibo.", "vsco.co", "threads.net",
)
ENGINES = {
    "ytdlp": ("yt-dlp", lambda ctx: ytdlp.download(ctx)),
    "gallerydl": ("gallery-dl", lambda ctx: gallerydl.download(ctx)),
    "spotdl": ("spotdl", lambda ctx: spotdl.download(ctx)),
    "match": ("match", lambda ctx: music.download(ctx)),
    "sniff": ("sniffer", lambda ctx: sniff.download(ctx)),
}


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def plan(url: str, opts: dict, cfg: dict) -> list[str]:
    forced = opts.get("engine") or "auto"
    if forced != "auto":
        return [forced]
    host, path = _host(url), urlparse(url).path.lower()
    mode = opts.get("mode", "video")
    chain = [f"custom:{e['name']}" for e in custom.matching(cfg, url)]
    if "spotify" in host:
        chain += ["spotdl", "match"]
    elif music.handles(host):
        chain += ["match", "ytdlp"]
    elif "instagram.com" in host:
        is_video_post = any(path.startswith(p) for p in ("/reel/", "/reels/", "/tv/")) or (
            path.startswith("/p/") and mode in ("audio", "video"))
        chain += ["ytdlp", "gallerydl"] if is_video_post else ["gallerydl", "ytdlp"]
    elif "tiktok.com" in host and "/photo/" in path:
        chain += ["gallerydl", "ytdlp"]
    elif any(h in host for h in GALLERY_HOSTS) or mode == "image":
        chain += ["gallerydl", "ytdlp", "sniff"]
    else:
        chain += ["ytdlp", "gallerydl", "sniff"]
    return list(dict.fromkeys(chain))


async def run_chain(ctx: Ctx):
    chain = plan(ctx.url, ctx.opts, ctx.cfg)
    errors = []
    for name in chain:
        ctx.check()
        if name.startswith("custom:"):
            eng = custom.by_name(ctx.cfg, name[7:])
            label, runner = name[7:], (lambda c, e=eng: custom.download(c, e))
        elif name in ENGINES:
            label, runner = ENGINES[name]
        else:
            eng = custom.by_name(ctx.cfg, name)
            if not eng:
                raise EngineError(f"Unknown engine: {name}")
            label, runner = name, (lambda c, e=eng: custom.download(c, e))
        ctx.set(engine=label, progress=None)
        ctx.log(f"[fdl] trying {label}")
        try:
            await runner(ctx)
            if any(p.is_file() for p in ctx.outdir.rglob("*")):
                return
            raise EngineError("finished but produced no files")
        except Cancelled:
            raise
        except Exception as e:
            errors.append((label, str(e) or e.__class__.__name__))
            ctx.log(f"[fdl] {label} failed: {e}")
            shutil.rmtree(ctx.outdir, ignore_errors=True)
            ctx.outdir.mkdir(parents=True, exist_ok=True)
    if not errors:
        raise EngineError("No engine for that link.")
    first = errors[0]
    rest = "; ".join(f"{n}: {m[:120]}" for n, m in errors[1:])
    raise EngineError(f"{first[1]}" + (f"  (also tried {rest})" if rest else ""))


async def analyze(url: str, opts: dict, cfg: dict) -> dict:
    tmp = Path(tempfile.mkdtemp(dir=TMP_DIR))
    try:
        cookies = cookie_utils.write_merged(cfg.get("cookies", {}), tmp / "cookies.txt")
        chain = [n for n in plan(url, {**opts, "engine": "auto"}, cfg) if not n.startswith("custom:")]
        if not chain and custom.matching(cfg, url):
            return {"engine": "custom", "title": url, "is_playlist": False}
        errors = []
        for name in chain:
            try:
                if name in ("spotdl", "match"):
                    res = await music.analyze(url, cfg)
                elif name == "ytdlp":
                    res = await ytdlp.analyze(url, cfg, cookies)
                elif name == "gallerydl":
                    res = await gallerydl.analyze(url, cfg, cookies)
                elif name == "sniff":
                    hits = await sniff.sniff(url, cfg, cookies)
                    if not hits:
                        raise EngineError("No media found on that page.")
                    res = {"engine": "sniffer", "title": url, "is_playlist": False, "count": len(hits),
                           "sniffed": [h[0] for h in hits[:10]]}
                else:
                    continue
                res["chain"] = chain
                return res
            except Exception as e:
                errors.append(str(e))
        raise EngineError(errors[0] if errors else "Can't figure that link out.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
