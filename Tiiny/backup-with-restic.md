# Backing up a Tiiny AI Pocket Lab with restic

A configuration guide for Tiiny owners: back up everything on the device
that cannot be re-downloaded, to an external USB drive, with
[restic](https://restic.net) — and leave the model weights out on purpose.

Tested Nov 20, 2026, on TiinyOS 0.1.39. First backup: 8,897 files,
3.29 GiB, 38 seconds, 2.38 GiB stored. Later runs are incremental and
take seconds when nothing changed.

## What this guide is not

It assumes you already have shell access to your Tiiny with root
available through `sudo`. That access comes from Tiiny's SSH access
package, available from the makers of Tiiny — installing or enabling it
is outside this guide. Nothing here covers Tiiny's proprietary software,
the device's cloud account, or reinstalling TiinyOS.

## Design decisions

**Why restic.** The backup target is a USB drive, typically formatted
exFAT. That rules out `rsync` with full fidelity (exFAT has no Unix
permissions or ownership) and makes `tar` a poor fit (no deduplication,
no incremental runs, no built-in verify). Restic is a single static
binary, stores the repo as plain files on any filesystem, deduplicates
and encrypts, and verifies with `restic check`. A plain tarball is fine
for a one-off snapshot; restic is the right tool for a backup you run
repeatedly.

**Why model weights are excluded.** On the device this was tested on,
the weights are ~720 GiB of an ~856 GiB data partition — the backup set
without them is ~3.3 GiB. Weights are also the fastest-changing data on
the device: models are added, removed, and updated frequently. And they
are re-downloadable from their sources after a recovery. Including them
would make every backup slow, huge, and dominated by data you can get
back with a download — which means the backup would get run less often,
which is the opposite of the point. What the backup covers instead is
the irreplaceable part: configuration, app data, conversations, and
service state. The weights are represented by a **manifest** (Section 3)
that lists exactly what was installed, so recovery re-pulls the same
models. The trade-off is explicit: recovery takes longer (re-download),
but the backup itself is small and fast enough to run often. A backup
you actually run beats a perfect one you never run.

## 1. Mount the external drive

Connect the drive to the Tiiny's USB port. The device sees it at the
kernel level but does **not** auto-mount it, so mount it by hand.

Find the partition:

```
lsblk -f
blkid
```

Look for your drive (on the tested device it appeared as `/dev/sda`,
with the data partition `/dev/sda2`, exFAT, label `Cdrive`). Then mount
it:

```
sudo mkdir -p /media/Cdrive
sudo mount -t exfat /dev/sda2 /media/Cdrive
```

Use your drive's own partition and label — `/dev/sda2` and `Cdrive`
are examples. If your drive uses a different filesystem, use the
matching `-t` type, or omit `-t` and let `mount` detect it. Verify:

```
df -h /media/Cdrive
```

You should see the drive's size and free space (the tested drive:
3.7T total, 3.1T free). This mount does **not** survive a reboot —
after restarting the device, mount it again before running a backup.
Check that it is mounted before every run; the script in Section 4
refuses to run if it is not.

## 2. Install and configure restic

**Install.** Download the Linux ARM64 release from restic's GitHub
releases page and verify it against the published `SHA256SUMS` before
using it:

```
# example — use the current release version
curl -LO https://github.com/restic/restic/releases/download/v0.20.0/restic-0.20.0-linux-arm64.bz2
# verify the checksum against the published SHA256SUMS, then:
bzip2 -d restic-0.20.0-linux-arm64.bz2
mkdir -p ~/bin
cp restic-0.20.0-linux-arm64 ~/bin/restic
chmod +x ~/bin/restic
~/bin/restic version
```

**Repo password.** Restic encrypts the repo with a password. Keep it in
a password file the script reads — never in the script itself. Create
it once, typing the password invisibly:

```
read -s -p 'Restic password: ' P; echo; printf '%s' "$P" > ~/.restic-password && chmod 600 ~/.restic-password
```

Only you know this password. Losing it means the backup is
irrecoverably lost; there is no reset.

**Repo location.** The repo lives on the USB drive, so it travels with
the drive and survives anything that happens to the device itself:

```
REPO=/media/Cdrive/restic-repo
```

The script initialises it on first run. It also keeps restic's cache on
the drive (`/media/Cdrive/restic-cache`): if restic complains it cannot
create its cache directory under `/root`, that is why — point
`--cache-dir` at the drive, as the script does.

## 3. The model manifest

Because weights are excluded, each backup run regenerates a manifest —
a text file listing what was installed, so recovery re-pulls the same
models. It is written to `~/backup-manifest/manifest-<timestamp>.txt`,
with `latest.txt` pointing at the newest, and a copy is kept on the
drive under `/media/Cdrive/restic-manifests/`. Format:

```
Tiiny model manifest — 2026-11-20T140346-0800
Models are EXCLUDED from the backup; re-pull by name after a recovery.

--- installed models (download_model) ---
63G  /data/backend/tiiny_model_data/download_model/openai__gpt-oss-120b
61G  /data/backend/tiiny_model_data/download_model/lightx2v__MiniMax-H3-Turbo
42G  /data/backend/tiiny_model_data/download_model/Qwen__Qwen3-Coder-Next
...

--- disk ---
Filesystem  Size  Used Avail Use% Mounted on
/dev/...    858G  793G   22G  98% /data
```

One note: the timestamp in the filename has **no colons** — exFAT
rejects `:` in filenames, and a colon-stamped filename fails to copy
onto the drive.

## 4. The backup script

Save this as `~/bin/tiiny-backup.sh` and make it executable
(`chmod +x ~/bin/tiiny-backup.sh`). It runs as root, checks its
preconditions, regenerates the manifest, initialises the repo on first
run, backs up, and verifies.

```bash
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
```

What is backed up, and what is not:

| Included | Why |
|---|---|
| `/data/backend` (minus `tiiny_model_data`) | App state: webapp, conversation data, local databases |
| `/data/docker/volumes` | Service state: configs, databases, workspace data |
| `/data/raw_data/upgrade` (minus `os_blobs`, `image-cache`) | Update metadata worth keeping |
| `/home/tiiny` (minus `.cache`) | User files and configuration |
| Model manifest | What to re-pull after a recovery |

| Excluded | Why |
|---|---|
| `/data/backend/tiiny_model_data` (~720 GiB) | Model weights — re-downloadable; see above |
| Docker image layers (`overlay2`, `image`) | Rebuildable from images; large and churny |
| OTA bundles, image cache | Superseded or re-fetchable update material |
| `~/.cache` | Regenerable cache data |

Adjust the path list to your device — the principle is the same: back
up what you cannot re-download, exclude what you can.

## 5. First run

Mount the drive (Section 1), then run the script as root:

```
sudo ~/bin/tiiny-backup.sh
```

The first run initialises the repo, backs up, and verifies. Expect
something like the tested run: 8,897 files, 3.29 GiB processed in
38 seconds, 2.38 GiB stored (compression), one snapshot saved. The
`restic check` at the end should report `no errors were found`.

## 6. Verify and test restore

`restic check` (run by the script every time) proves the repo is
internally consistent. A test restore proves you can actually get data
back — do it once after the first backup, and again any time the setup
changes. Restore one small path to a temporary directory and compare
it against the live original:

```
restic --repo /media/Cdrive/restic-repo --password-file ~/.restic-password \
  --cache-dir /media/Cdrive/restic-cache \
  restore latest --target /tmp/restore-test \
  --include /data/docker/volumes/aibox_connectors_config
diff -r /tmp/restore-test/data/docker/volumes/aibox_connectors_config \
  /data/docker/volumes/aibox_connectors_config && echo DIFF_OK
rm -rf /tmp/restore-test
```

On the tested device this restored 23 files (6.7 KiB) and the diff was
identical. Restore into `/tmp`, never over live data, and remove the
test directory afterward.

## 7. Scheduling and retention

Run the backup regularly — weekly is a reasonable cadence, and always
after adding or removing models or changing configuration. The script
as written keeps every snapshot; add retention once a schedule exists,
for example keeping the last seven snapshots:

```
restic --repo /media/Cdrive/restic-repo --password-file ~/.restic-password \
  --cache-dir /media/Cdrive/restic-cache \
  forget --keep-last 7 --prune
```

Schedule it with whatever your setup provides (`cron` or a systemd
timer). Keep the backup out of the device's busy hours if you run
inference jobs on it.

## 8. Recovering after a loss

1. Reinstall TiinyOS on the device (Tiiny's own process) and get the
   device back on the network.
2. Re-attach the USB drive and mount it (Section 1).
3. Re-pull the models listed in the latest manifest
   (`/media/Cdrive/restic-manifests/manifest-<latest>.txt`).
4. Restore the snapshot: `restic restore latest --target /` — or
   restore individual paths first and check them, then the rest.
5. Restart the device's services and confirm the apps come back.

## Gotchas

- **exFAT filenames:** no colons. Keep timestamps in filenames
  colon-free (`2026-11-20T140346-0800`, not `14:03:46`).
- **`--latest`, not `--last`:** restic 0.20.0 deprecated `--last`;
  `snapshots --last 1` mis-parses and fails. Use `--latest 1`.
- **Cache directory:** if restic cannot create its cache under
  `/root`, use `--cache-dir` on the drive (Section 2).
- **Mount before every run:** the drive does not auto-mount and the
  mount does not survive a reboot. The script checks and stops if the
  drive is not mounted.
- **The repo password is the only key.** There is no reset. Keep it
  somewhere safe, separate from the drive.
