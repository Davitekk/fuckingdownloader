#!/bin/sh
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ -z "$ADMIN_PASSWORD" ]; then
  echo "!! ADMIN_PASSWORD is not set, the admin panel is disabled."
fi

if [ "$(id -u)" = "0" ]; then
  # make the bind-mounted ./data and the venvs (for in-app updates) writable by the app user
  mkdir -p /data
  [ "$(stat -c %u:%g /data)" = "$PUID:$PGID" ] || chown -R "$PUID:$PGID" /data
  for d in /opt/venv /opt/spotdl; do
    [ "$(stat -c %u /$d)" = "$PUID" ] || chown -R "$PUID:$PGID" "$d"
  done
  RUN_AS="setpriv --reuid=$PUID --regid=$PGID --clear-groups"
else
  RUN_AS=""
fi

export HOME=/data

case "$(echo "${AUTO_UPDATE:-false}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes)
    echo ">> Updating yt-dlp, gallery-dl and spotdl..."
    $RUN_AS /opt/venv/bin/pip install -q --no-cache-dir -U "yt-dlp[default,curl-cffi]" gallery-dl \
      || echo "!! yt-dlp/gallery-dl update failed, using bundled versions"
    $RUN_AS /opt/spotdl/bin/pip install -q --no-cache-dir -U spotdl || echo "!! spotdl update failed"
    ;;
esac

echo ">> yt-dlp $(yt-dlp --version) | gallery-dl $(gallery-dl --version) | spotdl $(spotdl --version 2>/dev/null | tail -n1)"
echo ">> FuckinDownloader listening on :8080 (admin panel at /${ADMIN_PATH:-admin})"

exec $RUN_AS uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips '*' --no-access-log
