# FuckinDownloader - Debian (bookworm) based image
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:/opt/spotdl/bin:$PATH" \
    FDL_DATA_DIR=/data \
    FDL_SPOTDL=/opt/spotdl/bin/spotdl \
    FDL_SPOTDL_PIP=/opt/spotdl/bin/pip

# ffmpeg for merging/converting, curl for the healthcheck,
# tini to reap the yt-dlp/ffmpeg child processes properly
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl tini atomicparsley \
 && rm -rf /var/lib/apt/lists/*

# Deno: yt-dlp needs a JavaScript runtime to solve YouTube's player challenges
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# Main venv (app + yt-dlp + gallery-dl). spotdl gets its own venv because it
# pins its own yt-dlp version and we always want the latest yt-dlp here.
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -U pip \
 && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
 && python -m venv /opt/spotdl \
 && /opt/spotdl/bin/pip install --no-cache-dir spotdl \
 && rm /tmp/requirements.txt \
 && mkdir -p /data \
 && chown -R 1000:1000 /data /opt/venv /opt/spotdl

WORKDIR /srv
COPY app ./app
COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# Starts as root only to fix /data permissions, then drops to PUID:PGID (default 1000:1000)
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fs http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
