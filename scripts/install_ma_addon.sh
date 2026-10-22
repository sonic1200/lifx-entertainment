#!/usr/bin/env sh
# Install (or update) the LIFX Lights Sync plugin into a running Music Assistant container.
#
# Run it from a shell that has the docker CLI, e.g. the "Advanced SSH & Web Terminal"
# Home Assistant add-on with protection mode disabled:
#
#   mkdir -p /config/lifx-entertainment
#   curl -fsSL -o /config/lifx-entertainment/install_ma_addon.sh \
#     https://raw.githubusercontent.com/sonic1200/lifx-entertainment/main/scripts/install_ma_addon.sh
#   sh /config/lifx-entertainment/install_ma_addon.sh
#
# Options (environment variables):
#   MA_CONTAINER  Music Assistant container (default: auto-detected *music_assistant* container)
#   LIFX_REPO     GitHub "owner/name" of this repository
#   LIFX_REF      Branch or tag to install (default: the latest release)
#
# Only the provider is copied: Music Assistant installs the library itself, from PyPI, when
# it loads the provider (the version pinned in the manifest's "requirements").
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

LIFX_REPO="${LIFX_REPO:-sonic1200/lifx-entertainment}"
LIFX_REF="${LIFX_REF:-}"

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
echo "Installing LIFX Lights Sync into ${MA_CONTAINER}..."

# The provider, into Music Assistant's providers directory.
docker exec -i "${MA_CONTAINER}" /app/venv/bin/python - "${LIFX_REPO}" "${LIFX_REF}" <<'PY'
import io
import json
import shutil
import sys
import sysconfig
import tarfile
import urllib.request
from pathlib import Path

repo, ref = sys.argv[1], sys.argv[2]
if not ref:
    latest = f"https://api.github.com/repos/{repo}/releases/latest"
    with urllib.request.urlopen(latest, timeout=30) as response:  # noqa: S310
        ref = json.load(response)["tag_name"]
print(f"Using {repo}@{ref}")
archive = f"https://github.com/{repo}/archive/{ref}.tar.gz"
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

# Music Assistant only reads the compiled translations/<lang>.json files at runtime (the
# per-provider strings.json is merged into them at build time), so merge ours in.
prefix = "provider.lifx_entertainment."


def flatten(node, key_prefix, out):
    for key, value in node.items():
        if isinstance(value, dict):
            flatten(value, f"{key_prefix}{key}.", out)
        elif isinstance(value, str):
            out[f"{key_prefix}{key}"] = value
    return out


translations = dest.parent.parent / "translations"
sources = {"en": dest / "strings.json"}
sources.update({p.stem: p for p in sorted((dest / "translations").glob("*.json"))})
for lang, source in sources.items():
    target = translations / f"{lang}.json"
    if lang != "en" and not target.exists():
        continue
    catalog = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    catalog = {k: v for k, v in catalog.items() if not k.startswith(prefix)}
    added = flatten(json.loads(source.read_text(encoding="utf-8")), prefix, {})
    catalog.update(added)
    target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Merged {len(added)} strings into {target}")
PY

echo "Restarting ${MA_CONTAINER}..."
docker restart "${MA_CONTAINER}" >/dev/null
echo "Done. In Music Assistant: Settings > Plugins > Add plugin > LIFX Lights Sync."
