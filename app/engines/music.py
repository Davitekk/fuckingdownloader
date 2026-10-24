"""'match' engine for streaming services without a direct downloader
(Deezer, Apple Music, Tidal, Amazon Music, and Spotify when spotdl fails).
Reads track metadata from the service, finds the audio on YouTube Music,
then tags the file with the real title/artist/album/cover."""
import json
import re
import shutil
from html import unescape
from pathlib import Path
from urllib.parse import quote

import httpx

from . import ytdlp
from ..jobs import Ctx, EngineError, _safe_name

NAME = "match"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
HOSTS = ("deezer.com", "deezer.page.link", "link.deezer.com", "music.apple.com", "tidal.com",
         "music.amazon.", "open.spotify.com", "spotify.link")


def handles(host: str) -> bool:
    return any(h in host for h in HOSTS)


def _client(cfg: dict) -> httpx.AsyncClient:
    return httpx.AsyncClient(headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                             follow_redirects=True, timeout=20, proxy=cfg.get("proxy") or None)


def _t(title, artist, album="", cover=None, duration=None):
    return {"title": (title or "").strip(), "artist": (artist or "").strip(), "album": (album or "").strip(),
            "cover": cover, "duration": duration}


# --- resolvers -----------------------------------------------------------
async def _spotify(url: str, c: httpx.AsyncClient) -> dict:
    m = re.search(r"open\.spotify\.com/(?:intl-\w+/)?(track|album|playlist|artist|episode)/([A-Za-z0-9]+)", url)
    if not m:
        r = await c.get(url)  # spotify.link short links
        m = re.search(r"open\.spotify\.com/(?:intl-\w+/)?(track|album|playlist|artist|episode)/([A-Za-z0-9]+)", str(r.url))
        if not m:
            raise EngineError("Couldn't read that Spotify link.")
    kind, sid = m.groups()
    r = await c.get(f"https://open.spotify.com/embed/{kind}/{sid}")
    nd = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', r.text, re.S)
    if not nd:
        raise EngineError("Spotify embed page changed, can't read metadata.")
    ent = json.loads(nd.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    cover = None
    srcs = (ent.get("coverArt") or {}).get("sources") or (ent.get("visualIdentity") or {}).get("image") or []
    if srcs:
        cover = max(srcs, key=lambda s: s.get("width") or s.get("maxWidth") or 0).get("url")
    name = ent.get("name") or ent.get("title") or ""
    if kind in ("track", "episode"):
        artists = ", ".join(a.get("name", "") for a in ent.get("artists") or []) or ent.get("subtitle", "")
        return {"title": name, "cover": cover, "single": True,
                "tracks": [_t(name, artists, "", cover, (ent.get("duration") or 0) / 1000 or None)]}
    tracks = [_t(t.get("title"), t.get("subtitle"), name if kind == "album" else "", cover if kind == "album" else None,
                 (t.get("duration") or 0) / 1000 or None) for t in ent.get("trackList") or []]
    return {"title": name, "cover": cover, "tracks": tracks}


async def _deezer(url: str, c: httpx.AsyncClient) -> dict:
    pat = r"deezer\.com/(?:\w{2}(?:-\w{2})?/)?(track|album|playlist|artist)/(\d+)"
    m = re.search(pat, url)
    if not m:
        r = await c.get(url)
        m = re.search(pat, str(r.url)) or re.search(pat, r.text)
        if not m:
            raise EngineError("Couldn't read that Deezer link.")
    kind, did = m.groups()
    api = f"https://api.deezer.com/{kind}/{did}" + ("/top?limit=50" if kind == "artist" else "")
    d = (await c.get(api)).json()
    if "error" in d:
        raise EngineError(f"Deezer: {d['error'].get('message', 'error')}")
    if kind == "track":
        al = d.get("album") or {}
        return {"title": d["title"], "cover": al.get("cover_xl"), "single": True,
                "tracks": [_t(d["title"], d["artist"]["name"], al.get("title"), al.get("cover_xl"), d.get("duration"))]}
    if kind == "artist":
        data = d.get("data", [])
        title = f"{data[0]['artist']['name']} - Top" if data else "Deezer artist"
    else:
        data, title = d.get("tracks", {}).get("data", []), d.get("title")
    cover = d.get("cover_xl") or d.get("picture_xl")
    tracks = []
    for t in data:
        al = t.get("album") or {}
        tracks.append(_t(t["title"], t["artist"]["name"], al.get("title") or (d.get("title") if kind == "album" else ""),
                         al.get("cover_xl") or (cover if kind == "album" else None), t.get("duration")))
    return {"title": title or "Deezer", "cover": cover, "tracks": tracks}


def _meta(html: str, prop: str) -> str | None:
    m = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)', html) \
        or re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']', html)
    return unescape(m.group(1)) if m else None


def _ld_tracks(html: str):
    out, coll = [], None
    for blob in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.+?)</script>', html, re.S):
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        for obj in data if isinstance(data, list) else [data]:
            typ = obj.get("@type")
            def artist_of(o):
                a = o.get("byArtist") or (o.get("audio") or {}).get("byArtist") or []
                a = a if isinstance(a, list) else [a]
                return ", ".join(x.get("name", "") for x in a if isinstance(x, dict))
            if typ in ("MusicAlbum", "MusicPlaylist"):
                coll = obj
                for t in obj.get("tracks") or obj.get("track") or []:
                    if isinstance(t, dict) and t.get("name"):
                        out.append(_t(t["name"], artist_of(t) or artist_of(obj),
                                      obj.get("name") if typ == "MusicAlbum" else "", None))
            elif typ == "MusicRecording" and not out:
                out.append(_t(obj.get("name"), artist_of(obj), (obj.get("inAlbum") or {}).get("name", ""), None))
    return out, coll


async def _generic(url: str, c: httpx.AsyncClient) -> dict:
    r = await c.get(url)
    html = r.text
    cover = _meta(html, "og:image")
    tracks, coll = _ld_tracks(html)
    if tracks:
        for t in tracks:
            t["cover"] = t["cover"] or cover
        return {"title": (coll or {}).get("name") or tracks[0]["title"], "cover": cover, "tracks": tracks,
                "single": len(tracks) == 1}
    title = _meta(html, "og:title") or ""
    desc = _meta(html, "og:description") or ""
    # "Song Name by Artist on Apple Music" / "Song - Artist" / tidal "Artist - Song"
    title = re.sub(r"\s+(on|\|)\s+(Apple Music|TIDAL|Amazon Music).*$", "", title, flags=re.I)
    m = re.match(r"(.+?)\s+by\s+(.+)$", title)
    if m:
        name, artist = m.groups()
    else:
        name, artist = title, desc.split("·")[0] if "·" in desc else ""
    if not name:
        raise EngineError("Couldn't find any track info on that page.")
    return {"title": name, "cover": cover, "single": True, "tracks": [_t(name, artist, "", cover)]}


async def resolve(url: str, cfg: dict) -> dict:
    async with _client(cfg) as c:
        if "spotify" in url:
            return await _spotify(url, c)
        if "deezer" in url:
            return await _deezer(url, c)
        return await _generic(url, c)


async def analyze(url: str, cfg: dict) -> dict:
    info = await resolve(url, cfg)
    t = info["tracks"]
    return {
        "engine": NAME, "extractor": "music", "title": info["title"], "thumbnail": info.get("cover"),
        "uploader": t[0]["artist"] if t else None, "is_playlist": not info.get("single") and len(t) > 0,
        "count": len(t), "audio_only": True,
        "entries": [{"title": f"{x['artist']} - {x['title']}", "duration": x.get("duration")} for x in t[:200]],
    }


# --- tagging -------------------------------------------------------------
def tag_file(path: Path, t: dict, cover: bytes | None, track_no: int | None):
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TALB, TIT2, TPE1, TRCK
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            for k in ("TIT2", "TPE1", "TALB", "TRCK"):
                tags.delall(k)
            tags.add(TIT2(encoding=3, text=t["title"]))
            tags.add(TPE1(encoding=3, text=t["artist"]))
            if t["album"]:
                tags.add(TALB(encoding=3, text=t["album"]))
            if track_no:
                tags.add(TRCK(encoding=3, text=str(track_no)))
            if cover:
                tags.delall("APIC")
                tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
            tags.save(path)
        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4, MP4Cover
            m = MP4(path)
            m["\xa9nam"], m["\xa9ART"] = [t["title"]], [t["artist"]]
            if t["album"]:
                m["\xa9alb"] = [t["album"]]
            if track_no:
                m["trkn"] = [(track_no, 0)]
            if cover:
                m["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
            m.save()
        elif ext == ".flac":
            from mutagen.flac import FLAC, Picture
            f = FLAC(path)
            f["title"], f["artist"] = t["title"], t["artist"]
            if t["album"]:
                f["album"] = t["album"]
            if cover:
                pic = Picture()
                pic.type, pic.mime, pic.data = 3, "image/jpeg", cover
                f.clear_pictures()
                f.add_picture(pic)
            f.save()
        else:
            from mutagen import File
            f = File(path, easy=True)
            if f is not None:
                f["title"], f["artist"] = t["title"], t["artist"]
                if t["album"]:
                    f["album"] = t["album"]
                f.save()
    except Exception as e:  # tagging is a bonus, never fail the download over it
        print(f"[match] tagging {path.name} failed: {e!r}")


# --- download ------------------------------------------------------------
async def download(ctx: Ctx):
    ctx.set(message="Reading track list...")
    info = await resolve(ctx.url, ctx.cfg)
    tracks = info["tracks"]
    if not info.get("single") and not ctx.opts.get("playlist"):
        tracks = tracks[:1]
    cap = int(ctx.cfg.get("max_playlist_items") or 0)
    if cap:
        tracks = tracks[:cap]
    if not tracks:
        raise EngineError("No tracks found.")
    ctx.job.title = ctx.job.title or info["title"]
    ctx.job.thumbnail = ctx.job.thumbnail or info.get("cover") or ""
    fmt = ctx.opts.get("audio_format", "mp3")
    q = str(ctx.opts.get("audio_quality", "320"))
    dest_dir = ctx.outdir / _safe_name(info["title"]) if len(tracks) > 1 else ctx.outdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    covers: dict[str, bytes | None] = {}
    ok = 0
    async with _client(ctx.cfg) as c:
        for i, t in enumerate(tracks, 1):
            ctx.check()
            ctx.set(status="running", item=i, items=len(tracks), progress=(i - 1) / len(tracks) * 100,
                    message=f"Matching {i}/{len(tracks)}: {t['artist']} - {t['title']}"[:140])
            query = f"{t['artist']} - {t['title']}".strip(" -")
            got = None
            for src in (f"https://music.youtube.com/search?q={quote(query)}#songs", f"ytsearch1:{query} audio"):
                tmp = ctx.tmpdir / f"m{i}"
                shutil.rmtree(tmp, ignore_errors=True)
                cmd = ytdlp.common_args(ctx.cfg, ctx.cookies) + [
                    "-I", "1", "-f", "ba/b", "-x", "--audio-format", fmt,
                    "--audio-quality", "0" if q == "best" else f"{q}K",
                    "-o", str(tmp / "track.%(ext)s"), "--", src]
                await ctx.run(cmd)
                files = [p for p in tmp.glob("track.*") if not p.name.endswith((".part", ".ytdl"))] if tmp.exists() else []
                if files:
                    got = files[0]
                    break
            if not got:
                ctx.log(f"[match] no match for {query}")
                continue
            curl = t.get("cover") or info.get("cover")
            if curl and curl not in covers:
                try:
                    covers[curl] = (await c.get(curl)).content
                except httpx.HTTPError:
                    covers[curl] = None
            tag_file(got, t, covers.get(curl) if curl else None, i if len(tracks) > 1 else None)
            prefix = f"{i:02d} - " if len(tracks) > 1 else ""
            shutil.move(str(got), dest_dir / f"{prefix}{_safe_name(query)}{got.suffix}")
            ok += 1
    if not ok:
        raise EngineError("Couldn't match any of those tracks on YouTube Music.")
