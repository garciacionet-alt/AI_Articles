#!/bin/bash
# Tiiny backup — restic. Model weights are excluded; a manifest is kept instead.
#
# Run as root on the device. The backup paths are root-owned, so run it
# through sudo (see the SSH access documentation from Tiiny for how your
# session reaches root). The repo password is never stored in this script:
# it lives in a password file (mode 600) that you create once.
#
# Repo: <your USB drive>/restic-repo — restic stores its repo as plain
# files, so any filesystem the drive uses is fine.
#
# Included: /data/backend minus model weights, Docker volumes,
# /data/raw_data/upgrade minus bundles/cache, your home directory.
# Excluded: model weights (re-downloadable; a manifest is kept instead),
# Docker image layers, OTA bundles, image cache, ~/.cache.
# First backup is a few GiB; later runs are incremental.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root: sudo $0"
  exit 1
fi

RESTIC=/home/tiiny/bin/restic
REPO=/media/Cdrive/restic-repo
PWFILE=/home/tiiny/.restic-password
# If restic cannot create its cache under /root, keep the cache on the
# USB drive instead.
CACHE_DIR=/media/Cdrive/restic-cache

[ -x "$RESTIC" ] || { echo "restic not found at $RESTIC"; exit 1; }
[ -f "$PWFILE" ] || { echo "password file missing: $PWFILE (create it, mode 600)"; exit 1; }
mountpoint -q /media/Cdrive || { echo "/media/Cdrive is not mounted"; exit 1; }

# --- Model manifest (what to re-pull after a recovery) ---
MANIFEST_DIR=/home/tiiny/backup-manifest
mkdir -p "$MANIFEST_DIR"
STAMP=$(date +%Y-%m-%dT%H%M%S%z)
{
  echo "Tiiny model manifest — $STAMP"
  echo "Models are EXCLUDED from the backup; re-pull by name after a recovery."
  echo
  echo "--- installed models (download_model) ---"
  du -sh /data/backend/tiiny_model_data/download_model/* 2>/dev/null | sort -rh || true
  echo
  echo "--- disk ---"
  df -h /data /media/Cdrive
} > "$MANIFEST_DIR/manifest-$STAMP.txt"
ln -sf "manifest-$STAMP.txt" "$MANIFEST_DIR/latest.txt"
# Note: the timestamp has no colons — exFAT rejects ':' in filenames.
mkdir -p /media/Cdrive/restic-manifests
cp "$MANIFEST_DIR/manifest-$STAMP.txt" /media/Cdrive/restic-manifests/

# --- Init the repo on first run only ---
if [ ! -f "$REPO/config" ]; then
  "$RESTIC" --repo "$REPO" --password-file "$PWFILE" --cache-dir "$CACHE_DIR" init
fi

# --- Back up ---
"$RESTIC" --repo "$REPO" --password-file "$PWFILE" --cache-dir "$CACHE_DIR" backup \
  --tag tiiny --tag no-models \
  --exclude /data/backend/tiiny_model_data \
  --exclude /data/raw_data/upgrade/os_blobs \
  --exclude /data/raw_data/upgrade/image-cache \
  --exclude /home/tiiny/.cache \
  /data/backend \
  /data/docker/volumes \
  /data/raw_data/upgrade \
  /home/tiiny

# --- Verify ---
"$RESTIC" --repo "$REPO" --password-file "$PWFILE" --cache-dir "$CACHE_DIR" snapshots --latest 1
"$RESTIC" --repo "$REPO" --password-file "$PWFILE" --cache-dir "$CACHE_DIR" check

echo
echo "--- done ---"
df -h /data /media/Cdrive
du -sh "$REPO"
