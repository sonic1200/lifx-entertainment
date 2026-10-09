#!/usr/bin/env sh
# Install (or update) the LIFX Lights Sync plugin into a running Music Assistant container.
#
# Run it from a shell that has the docker CLI, e.g. the "Advanced SSH & Web Terminal"
# Home Assistant add-on with protection mode disabled:
#
#   mkdir -p /config/lifx-entertainment
#   curl -fsSL -o /config/lifx-entertainment/install_ma_addon.sh \
#     https://raw.githubusercontent.com/OWNER/lifx-entertainment/main/scripts/install_ma_addon.sh
#   sh /config/lifx-entertainment/install_ma_addon.sh
#
# Options (environment variables):
#   MA_CONTAINER  Music Assistant container (default: auto-detected *music_assistant* container)
#   LIFX_REPO     GitHub "owner/name" of this repository
#   LIFX_REF      Branch or tag to install (default: main)
#
# The Home Assistant Supervisor re-creates the add-on container on every restart and
# update, which drops the plugin again. Run the script with "watch" to keep it installed:
# it re-installs (and restarts Music Assistant) whenever the plugin has gone missing.
# Add this to the SSH add-on's "init_commands" so the watcher starts at boot:
#
#   - nohup sh /config/lifx-entertainment/install_ma_addon.sh watch > /dev/null 2>&1 &
#
# Commands: install (default), watch, check.

set -eu

MODE="${1:-install}"
WATCH_INTERVAL="${WATCH_INTERVAL:-60}"

LIFX_REPO="${LIFX_REPO:-OWNER/lifx-entertainment}"
LIFX_REF="${LIFX_REF:-main}"
ARCHIVE="https://github.com/${LIFX_REPO}/archive/${LIFX_REF}.tar.gz"

find_container() {
  if [ -n "${MA_CONTAINER:-}" ]; then
    echo "${MA_CONTAINER}"
  else
    docker ps --format '{{.Names}}' | grep -m1 'music_assistant' || true
  fi
}

is_installed() {
  docker exec "$1" /app/venv/bin/python -c '
import sys, sysconfig
from pathlib import Path
import lifx_entertainment
manifest = Path(sysconfig.get_path("purelib")) / "music_assistant/providers/lifx_entertainment/manifest.json"
sys.exit(0 if manifest.is_file() else 1)
' >/dev/null 2>&1
}

if [ "${MODE}" = "watch" ]; then
  while true; do
    container="$(find_container)"
    if [ -n "${container}" ] && ! is_installed "${container}"; then
      MA_CONTAINER="${container}" sh "$0" install || true
    fi
    sleep "${WATCH_INTERVAL}"
  done
fi

MA_CONTAINER="$(find_container)"
if [ -z "${MA_CONTAINER}" ]; then
  echo "Music Assistant container not found; set MA_CONTAINER" >&2
  exit 1
fi
if [ "${MODE}" = "check" ]; then
  if is_installed "${MA_CONTAINER}"; then
    echo "LIFX Lights Sync is installed in ${MA_CONTAINER}"
  else
    echo "LIFX Lights Sync is NOT installed in ${MA_CONTAINER}"
    exit 1
  fi
  exit 0
fi
echo "Installing LIFX Lights Sync (${LIFX_REPO}@${LIFX_REF}) into ${MA_CONTAINER}..."

# 1. The library, into Music Assistant's virtualenv.
docker exec "${MA_CONTAINER}" sh -c \
  "uv pip install --python /app/venv/bin/python --no-cache --reinstall '${ARCHIVE}'"

# 2. The provider, into Music Assistant's providers directory.
docker exec -i "${MA_CONTAINER}" /app/venv/bin/python - "${ARCHIVE}" <<'PY'
import io
import shutil
import sys
import sysconfig
import tarfile
import urllib.request
from pathlib import Path

archive = sys.argv[1]
dest = Path(sysconfig.get_path("purelib")) / "music_assistant" / "providers" / "lifx_entertainment"
marker = "/music_assistant_provider/lifx_entertainment/"
with urllib.request.urlopen(archive, timeout=60) as response:  # noqa: S310
    data = response.read()
if dest.exists():
    shutil.rmtree(dest)
dest.mkdir(parents=True)
count = 0
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
    for member in tar.getmembers():
        if not member.isfile() or marker not in member.name:
            continue
        relative = member.name.split(marker, 1)[1]
        if not relative or ".." in Path(relative).parts:
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source = tar.extractfile(member)
        if source is not None:
            target.write_bytes(source.read())
            count += 1
if not (dest / "manifest.json").exists():
    sys.exit(f"Provider files not found in {archive}")
print(f"Installed {count} provider files to {dest}")
PY

echo "Restarting ${MA_CONTAINER}..."
docker restart "${MA_CONTAINER}" >/dev/null
echo "Done. In Music Assistant: Settings > Plugins > Add plugin > LIFX Lights Sync."
