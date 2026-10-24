"""Paths, env config and the persistent settings store (/data/settings.json)."""
import copy
import json
import os
import secrets
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("FDL_DATA_DIR", "/data")).resolve()
DOWNLOAD_DIR = DATA_DIR / "downloads"
TMP_DIR = DATA_DIR / "tmp"
SETTINGS_FILE = DATA_DIR / "settings.json"
SECRET_FILE = DATA_DIR / ".secret_key"

for _d in (DATA_DIR, DOWNLOAD_DIR, TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# yt-dlp looks for plugins in $XDG_CONFIG_HOME/yt-dlp/plugins/
os.environ.setdefault("XDG_CONFIG_HOME", str(DATA_DIR / "config"))
(Path(os.environ["XDG_CONFIG_HOME"]) / "yt-dlp" / "plugins").mkdir(parents=True, exist_ok=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_PATH = "/" + os.environ.get("ADMIN_PATH", "admin").strip("/")
TRUST_PROXY = os.environ.get("TRUST_PROXY", "false").lower() in ("1", "true", "yes")

YTDLP_BIN = os.environ.get("FDL_YTDLP", "yt-dlp")
GALLERYDL_BIN = os.environ.get("FDL_GALLERYDL", "gallery-dl")
SPOTDL_BIN = os.environ.get("FDL_SPOTDL", "spotdl")
FFMPEG_BIN = os.environ.get("FDL_FFMPEG", "ffmpeg")


def secret_key() -> str:
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text().strip()
    key = secrets.token_urlsafe(48)
    SECRET_FILE.write_text(key)
    return key


# Cookie slots shown in the admin UI. Everything gets merged into one Netscape
# cookies.txt per job, since that format is keyed by domain on every line anyway.
COOKIE_SLOTS = {
    "youtube": "YouTube / YT Music",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "twitter": "X / Twitter",
    "reddit": "Reddit",
    "facebook": "Facebook",
    "spotify": "Spotify",
    "soundcloud": "SoundCloud",
    "adult": "Adult sites (PH & co.)",
    "other": "Anything else",
}

DEFAULT_SETTINGS = {
    "site_title": "FuckinDownloader",
    "default_theme": "blue",
    "tagline": "Just fucking download it.",
    "public_enabled": True,
    "public_password": "",
    "max_concurrent": 3,
    "max_jobs_per_ip": 3,
    "file_expiry_minutes": 10,
    "max_filesize_mb": 0,
    "max_playlist_items": 300,
    "allow_private_urls": False,
    "proxy": "",
    "pot_provider_url": "",  # empty = use the POT_PROVIDER_URL env var
    "cookies": {k: "" for k in COOKIE_SLOTS},
    "spotify": {"client_id": "", "client_secret": ""},
    "ytdlp_extra_args": "",
    "gallerydl_extra_args": "",
    "spotdl_extra_args": "",
    "custom_engines": [],
    "defaults": {
        "mode": "video",
        "video_quality": "1080",
        "video_container": "mp4",
        "audio_format": "mp3",
        "audio_quality": "320",
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._data = copy.deepcopy(DEFAULT_SETTINGS)
        if path.exists():
            try:
                self._data = _merge(DEFAULT_SETTINGS, json.loads(path.read_text("utf-8")))
            except Exception:
                pass

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def update(self, patch: dict) -> dict:
        with self._lock:
            self._data = _merge(self._data, patch)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), "utf-8")
            tmp.replace(self.path)
            return copy.deepcopy(self._data)


settings = SettingsStore(SETTINGS_FILE)
