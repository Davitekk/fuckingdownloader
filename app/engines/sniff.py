"""Last-resort sniffer: fetch the page (and its iframes), dig out any
m3u8 / mpd / direct media URLs and hand them to yt-dlp with the right Referer."""
import re
from html import unescape
from http.cookiejar import MozillaCookieJar
from urllib.parse import urljoin

import httpx

from . import ytdlp
from ..jobs import Ctx, EngineError
from ..netguard import BlockedURL, check_url

NAME = "sniffer"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MEDIA_RE = re.compile(
    r"""(https?:)?(?:\\?/\\?/)[^\s"'<>()\\]+?\.(m3u8|mpd|mp4|webm|m4v|mov|mkv|m4a|mp3|ogg|opus|flac)(?:\?[^\s"'<>\\]*)?(?=["'\s<>\\]|$)""",
    re.I,
)
TAG_SRC_RE = re.compile(r"""<(?:video|audio|source)[^>]+src=["']([^"']+)["']""", re.I)
IFRAME_RE = re.compile(r"""<iframe[^>]+src=["']([^"']+)["']""", re.I)
RANK = {"m3u8": 0, "mpd": 0, "mp4": 1, "webm": 1, "mkv": 1, "m4v": 1, "mov": 1}


def _jar(path):
    if not path:
        return None
    jar = MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return None
    return jar


def _find(html: str, base: str) -> list[tuple[str, str]]:
    found = []
    text = html.replace("\\/", "/")
    for m in MEDIA_RE.finditer(text):
        u = m.group(0)
        if u.startswith("//"):
            u = "https:" + u
        found.append((urljoin(base, u), m.group(2).lower()))
    for src in TAG_SRC_RE.findall(html):
        if src.startswith(("blob:", "data:")):
            continue
        ext = re.search(r"\.(m3u8|mpd|mp4|webm|m4v|mov|mkv|m4a|mp3|ogg|opus|flac)", src, re.I)
        found.append((urljoin(base, unescape(src)), ext.group(1).lower() if ext else "mp4"))
    return found


async def sniff(url: str, cfg: dict, cookies) -> list[tuple[str, str]]:
    allow_private = bool(cfg.get("allow_private_urls"))
    async with httpx.AsyncClient(headers={"User-Agent": UA}, cookies=_jar(cookies), follow_redirects=True,
                                 timeout=20, proxy=cfg.get("proxy") or None) as c:
        r = await c.get(url)
        hits = [(u, ext, url) for u, ext in _find(r.text, str(r.url))]
        for src in IFRAME_RE.findall(r.text)[:6]:
            frame = urljoin(str(r.url), src)
            try:
                await check_url(frame, allow_private)
                fr = await c.get(frame, headers={"Referer": str(r.url)})
                hits += [(u, ext, frame) for u, ext in _find(fr.text, str(fr.url))]
            except (BlockedURL, httpx.HTTPError):
                continue
    seen, out = set(), []
    for u, ext, ref in sorted(hits, key=lambda h: RANK.get(h[1], 2)):
        if u not in seen:
            seen.add(u)
            out.append((u, ref))
    return out


async def download(ctx: Ctx):
    ctx.set(message="Sniffing the page for media...")
    hits = await sniff(ctx.url, ctx.cfg, ctx.cookies)
    if not hits:
        raise EngineError("No media found on that page.")
    manifests = [h for h in hits if re.search(r"\.(m3u8|mpd)", h[0], re.I)]
    targets = manifests[:1] or hits[:10]
    errors = 0
    for media, ref in targets:
        try:
            await check_url(media, bool(ctx.cfg.get("allow_private_urls")))
            await ytdlp.download(ctx, media, referer=ref)
        except (EngineError, BlockedURL) as e:
            errors += 1
            ctx.log(f"[sniffer] {media}: {e}")
    if errors == len(targets):
        raise EngineError("Found media links but none would download.")
