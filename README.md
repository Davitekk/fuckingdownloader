<p align="center">
  <img src="app/static/icon.svg" width="96" alt="">
</p>

<h1 align="center">FuckinDownloader</h1>
<p align="center"><b>Just fucking download it.</b><br>
No ads. No subscriptions. No "please wait 30 seconds". No popups. Paste a link, get the file.</p>

---

A self-hosted, NoTube-style web downloader with a JDownloader-sized appetite. One Docker container, a public page
anyone can use, and a password-protected admin panel only you can get into.

Under the hood it glues together the best open-source downloaders and picks the right one for each link,
falling back to the next one if the first fails:

| Engine | What it handles |
| --- | --- |
| **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** | YouTube (videos, Shorts, playlists, channels), YT Music, TikTok (no watermark), Reddit, X/Twitter, Instagram reels, Facebook, Twitch, Vimeo, SoundCloud, Bandcamp, Bilibili, Dailymotion, adult sites, and [~1800 others](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) |
| **[gallery-dl](https://github.com/mikf/gallery-dl)** | Instagram stories, highlights, profiles, carousels; Reddit galleries; Pinterest; X images; TikTok slideshows; Tumblr, pixiv, DeviantArt, imageboards and [lots more](https://github.com/mikf/gallery-dl/blob/master/docs/supportedsites.md) |
| **[spotdl](https://github.com/spotDL/spotify-downloader)** | Spotify tracks, albums, playlists, artists, with full metadata and album art |
| **Music matcher** (built in) | Deezer, Apple Music, Tidal, Amazon Music, and Spotify without API keys: reads the track list, finds the audio on YouTube Music, tags it with the real title/artist/album/cover |
| **Page sniffer** (built in) | Last resort for random sites: digs m3u8 / mpd / mp4 links out of the page and its iframes and downloads them with the right Referer |
| **Custom engines** | Any CLI tool you install, wired to a URL regex from the admin panel |

## Features

- **MP4 / MP3 / images / original / cover-only** modes
- **Quality picker**: 144p up to 8K, H.264 "plays everywhere" or best codec (VP9/AV1), MP4/MKV/WEBM
- **Audio**: MP3, M4A, OPUS, OGG, FLAC, WAV at 96 to 320 kbps or best VBR
- **Covers and metadata embedded** (title, artist, album, chapters, square album art for music)
- **Playlists, albums, channels, profiles**, with optional item ranges (`1-10,15`), zipped automatically
- Live preview of what you pasted (thumbnail, title, duration, available qualities, playlist contents)
- Live progress, speed, ETA, cancel, auto-save when done
- Optional subtitles and SponsorBlock (cut sponsors/intros/outros)
- **Admin panel** (hidden path + password): cookies per site (cookies.txt or JSON), Spotify API keys, proxy,
  limits, file expiry, default theme, access key for the public page, custom engines, all downloads with logs,
  one-click engine updates
- **Private by default**: visitors only see their own downloads, and files self-destruct after 10 minutes (configurable)
- Blue, green and red themes
- Built for public instances: per-IP limits, SSRF protection, auto-cleanup of old files, no accounts, no tracking
- YouTube anti-bot measures handled: Deno JS runtime for yt-dlp + optional
  [bgutil PO token provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) sidecar

## Quick start (Debian + Docker)

Install Docker if you don't have it:

```bash
curl -fsSL https://get.docker.com | sh
```

Get the code and configure it:

```bash
git clone https://github.com/Davitekk/fuckingdownloader.git
cd fuckingdownloader
cp .env.example .env
nano .env   # set ADMIN_PASSWORD at least, and ideally a weird ADMIN_PATH
```

Start it:

```bash
docker compose up -d --build
```

Open `http://your-server:8080` for the downloader, and `http://your-server:8080/<ADMIN_PATH>` for the admin panel.

Update later with:

```bash
git pull && docker compose up -d --build
```

Downloads, settings and cookies live in `./data`.

## Configuration

Everything except the basics below is configured from the admin panel.

| Env var | Default | What it does |
| --- | --- | --- |
| `ADMIN_PASSWORD` | *(empty)* | Admin panel password. **Required**, otherwise the panel is disabled. |
| `ADMIN_PATH` | `admin` | URL path of the admin panel. Make it something unguessable. |
| `SECRET_KEY` | auto | Signs the admin session cookie. Auto-generated into `data/.secret_key` if empty. |
| `TRUST_PROXY` | `false` | Set `true` behind a reverse proxy so per-IP limits see real visitor IPs. |
| `COOKIE_SECURE` | `false` | Set `true` when served over HTTPS. |
| `AUTO_UPDATE` | `false` | Update yt-dlp, gallery-dl and spotdl on every container start. Recommended: `true` (it's `true` in `.env.example`). |
| `POT_PROVIDER_URL` | *(set in compose)* | URL of the bgutil PO token provider. |
| `PUID` / `PGID` | `1000` | User/group the app runs as (owner of `./data`). |

### HTTPS / reverse proxy

Put it behind anything. Example with [Caddy](https://caddyserver.com) (`/etc/caddy/Caddyfile`):

```
dl.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Then set `TRUST_PROXY=true` and `COOKIE_SECURE=true` in `.env`, and change the port mapping in
`docker-compose.yml` to `"127.0.0.1:8080:8080"` so the app isn't reachable around the proxy.

### Cookies (Instagram, private stuff, "sign in to confirm you're not a bot")

Lots of sites need you to be logged in now: Instagram stories and most posts, Reddit, TikTok in some regions,
age-restricted YouTube, X, members-only content. To fix that:

1. Log in to the site in your browser (use a throwaway account: heavy downloading can get accounts flagged).
2. Export cookies with an extension like **Get cookies.txt LOCALLY** (Netscape format) or **Cookie-Editor** (JSON export).
3. Admin panel, **Cookies** tab: paste or upload into the matching slot, hit **Save settings**.

For YouTube, export from a private/incognito window and close it right after, so YouTube doesn't rotate the cookies away.

### Spotify

spotdl works out of the box but its built-in API keys are shared by every spotdl user on earth and get
rate-limited a lot. Create a free app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
and paste the client ID and secret into **Admin, Engines**. If spotdl fails anyway, Spotify links automatically fall
back to the built-in matcher, which needs no keys at all.

Audio comes from YouTube Music (matched by spotdl/the matcher), not from Spotify's own encrypted streams.

### Sites with no built-in support

1. Try it. The page sniffer handles a surprising number of "unsupported" sites with plain HLS/MP4 players.
2. **yt-dlp plugins**: drop any yt-dlp extractor plugin into `data/config/yt-dlp/plugins/<name>/yt_dlp_plugins/extractor/`.
   It's picked up on the next download, no rebuild needed.
3. **Custom engines** (admin, Engines): run any CLI downloader for URLs that match a regex. Placeholders:
   `{url}` `{outdir}` `{tmpdir}` `{cookies}` `{proxy}` `{mode}` `{audio_format}` `{quality}`. Example:

   | Name | URL regex | Command |
   | --- | --- | --- |
   | `n_m3u8` | `example\.com/watch` | `N_m3u8DL-RE {url} --save-dir {outdir}` |

   Install the tool by extending the image:

   ```dockerfile
   FROM fuckindownloader:local
   RUN pip install some-downloader   # or download a binary into /usr/local/bin
   ```

## Public instance tips

- **Admin, General, Access key** turns the public page into "people with the key only".
- Tune **parallel downloads**, **active downloads per IP**, **max file size**, **max playlist items** and
  **delete files after (minutes)** to fit your disk and bandwidth.
- Your server IP is what sites see. If YouTube starts blocking you, keep the PO token sidecar on, add cookies,
  or set a proxy in the admin panel.
- When something breaks, hit **Update** in the admin panel's System tab (or keep `AUTO_UPDATE=true`).
  Most "it stopped working" problems are fixed by a newer yt-dlp.

## Running without Docker (dev)

Needs Python 3.11+, ffmpeg and (for YouTube) [Deno](https://deno.com).

On Windows there's a one-shot script that sets everything up in `.venv` and starts it on port 8090
(it reads `ADMIN_PASSWORD` etc. from `.env`):

```powershell
powershell -ExecutionPolicy Bypass -File .\run-local.ps1
```

On Linux/macOS:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install spotdl   # optional, ideally in its own venv; point FDL_SPOTDL at its binary
FDL_DATA_DIR=./data ADMIN_PASSWORD=dev uvicorn app.main:app --reload --port 8080
```

## How it works

```
app/
  main.py          FastAPI app: public API, admin API, auth
  jobs.py          job queue, subprocess runner, progress, zipping, cleanup
  config.py        env + settings.json store
  cookies.py       cookies.txt / JSON cookie parsing and merging
  netguard.py      blocks private/LAN URLs (SSRF)
  engines/         yt-dlp, gallery-dl, spotdl, music matcher, sniffer, custom + the router
  static/          the whole frontend (vanilla HTML/CSS/JS, no build step)
```

Jobs live in memory; files live in `data/downloads/<job-id>/` and are deleted when they expire
(10 minutes after finishing by default, configurable in the admin panel). Each browser gets a random
`fdl_owner` cookie and only sees, and can only download, its own files.
A container restart clears old downloads.

## Legal

This is a tool. Only download content you own or have permission to download, and respect the terms of the
sites you use and the copyright laws where you live. You are responsible for your instance and what people do with it.

## Credits

All the heavy lifting is done by [yt-dlp](https://github.com/yt-dlp/yt-dlp), [gallery-dl](https://github.com/mikf/gallery-dl),
[spotDL](https://github.com/spotDL/spotify-downloader), [FFmpeg](https://ffmpeg.org) and
[bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider). Go star them.

## License

[MIT](LICENSE)
