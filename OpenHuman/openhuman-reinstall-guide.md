---
title: How to Reinstall OpenHuman Without Losing Your Memory
type: work-instruction
audience: OpenHuman community
status: draft
tested-on: OpenHuman v0.64.10, macOS (Apple Silicon)
date: 2026-09-30
---

# How to Reinstall OpenHuman Without Losing Your Memory

A clean reinstall replaces the app and its config. Your memory tree (the vector database plus episodic content) lives inside `~/.openhuman`, so if you delete that folder, your agent's memory goes with it. This guide keeps a full copy of the old install and restores the memory tree into the new one.

**Time:** about 15 minutes, plus copy time for large memory trees
**Risk:** low, as long as you never delete the old folder until the new one is verified

## The short version

1. Stop OpenHuman
2. Back up the sandbox (workspace)
3. Rename `~/.openhuman` to `~/.openhumanOld`
4. Download the install image
5. Run the installer
6. Ask your agent to help recover your memories

## Golden rules (read before you start)

- **Copy, never move, from the old folder.** `~/.openhumanOld` is your only safety net. Treat it as read-only.
- **Do not delete anything until you have verified the new install.** Keep `~/.openhumanOld` for at least a week.
- **OpenHuman must be fully quit** while you rename folders or copy the database. Copying a SQLite database while it is being written can corrupt it.
- **Watch your agent during recovery.** Approve each command it proposes. Refuse any `rm`, `rm -rf`, or `mv` that touches `~/.openhumanOld` or the restored `memory_tree`. Copying is safe; deleting and moving are where things go wrong.
- **Verify with evidence.** After every step, run the `ls` or `du` check shown. Do not accept "done" without seeing the output.
  
  NOTE:  THIS DOES NOT COPY YOUR CRYPTO WALLET.  MOVE FUNDS OUT OF YOUR CRYPTO WALLET BEFORE BEGINNING

---

## Step 1: Stop OpenHuman

Quit the desktop app from its menu (on macOS, `Cmd+Q` with OpenHuman focused). Then confirm nothing is still running:

```bash
pgrep -il openhuman || echo "OpenHuman is stopped"
```

If a process is still listed, quit it from Activity Monitor or:

```bash
pkill -il openhuman
```

Run the `pgrep` check again until it reports stopped.

**Precaution:** if you have scheduled jobs (cron) that were mid-run, note them now. Jobs do not carry over to a fresh install automatically.

---

## Step 2: Back up the sandbox

The sandbox is the OpenHuman workspace: the folder your agent reads and writes. Your user workspace lives here:

```bash
ls ~/.openhuman/users/
```

You will see a long user ID folder (and possibly a `local` folder). Your workspace is `~/.openhuman/users/<your-id>/workspace/`.

Make a dated, independent backup of the entire config folder. This is separate from the rename in Step 3, so you end up with two copies:

```bash
rsync -a --progress ~/.openhuman/ ~/openhuman-backup-$(date +%Y-%m-%d)/
```

Verify the backup is complete by comparing sizes:

```bash
du -sh ~/.openhuman ~/openhuman-backup-$(date +%Y-%m-%d)
```

The two numbers should match (or be very close).

**Precautions:**

- Check free disk space first with `df -h ~`. The memory database alone can be several hundred MB.
- If your workspace is an Obsidian vault or a symlink to cloud storage (iCloud, Dropbox), back that up too. `rsync -a` copies a symlink as a link, not the files it points to. If you want the files themselves, back up the target folder directly.
- If you keep your workspace in git, commit and push before continuing.

---

## Step 3: Rename `~/.openhuman` to `~/.openhumanOld`

```bash
mv ~/.openhuman ~/.openhumanOld
```

Confirm:

```bash
ls -d ~/.openhuman ~/.openhumanOld
```

You should see `~/.openhumanOld` and an error that `~/.openhuman` does not exist. That is correct: the installer will create a fresh one.

**Why rename instead of delete:** the old folder holds your memory tree (`workspace/memory_tree/`), your config, session history, cron and workflow definitions. Renaming is instant and keeps everything recoverable.

---

## Step 4: Download the install image

Download the latest installer for your platform from the **official OpenHuman download page or release page only**. Do not use installers linked from chats, forums, or unofficial mirrors.

**Precautions:**

- Confirm you are downloading the build for your chip (Apple Silicon vs Intel on macOS).
- If a checksum is published, verify it:

```bash
shasum -a 256 ~/Downloads/<installer-file>
```

Compare the output to the published value.

---

## Step 5: Run the installer

Open the installer and follow the prompts. On macOS this is usually: open the disk image, drag OpenHuman to Applications, then launch it.

When it launches:

1. **Sign in with the same account you used before.** Your user ID folder name is tied to your account. Signing in with the same account means the new folder under `~/.openhuman/users/` will have the same ID as the old one, which makes recovery simple.
2. Let it finish first-run setup.
3. Reconnect integrations (Gmail, Calendar, etc.) as prompted. OAuth connections may need to be re-approved.

Confirm the user ID matches:

```bash
ls ~/.openhumanOld/users/
ls ~/.openhuman/users/
```

The long ID folder should appear in both.

---

## Step 6: Ask your agent to help recover memories

You can let your agent do this, or run the commands yourself. Either way, **quit OpenHuman before the database copy**, then relaunch after. Copying `chunks.db` while the app is running risks a corrupted or overwritten database.

### Option A: Ask your agent

Say something like:

> My old install is at `~/.openhumanOld`. Help me restore my memory tree into the new install. Copy only, never move or delete anything in the old folder. Show me the output of every command.

Then review each command before approving it. Good commands use `cp` or `rsync` from `.openhumanOld` into `.openhuman`. Stop the agent if it proposes `rm`, `rm -rf`, `rmdir`, or `mv` on the memory tree.

> **Note: use a strong model for this step.** Restoring memory means working with multi-step file operations on data you cannot easily replace. Before you ask for help, set your agent to a strong LLM. The minimum quality bar is something like **Claude Opus 5.5** or a comparable frontier model. Weaker models are more likely to get paths wrong, nest folders at the wrong level, report a step as done when it never ran, or suggest destructive commands. In the reinstall this guide is based on, most of the problems came from exactly those mistakes. If you can't use a strong model, use Option B and run the commands yourself.  Example: Deepseek V4 Flash will absolutely make mistakes and delete files that should not be deleted  accidentally and without permission.

### Option B: Do it yourself

Quit OpenHuman first (Step 1 check). Then set two variables. Replace `<your-id>` with the ID folder from Step 5:

```bash
OLD=~/.openhumanOld/users/<your-id>/workspace/memory_tree
NEW=~/.openhuman/users/<your-id>/workspace/memory_tree
```

Look at both before copying:

```bash
ls -la "$OLD"
ls -la "$NEW"
du -sh "$OLD" "$NEW"
```

The old one should be large (hundreds of MB if you used OpenHuman for a while). The new one will be nearly empty.

Copy the vector database:

```bash
cp -v "$OLD/chunks.db" "$NEW/chunks.db"
```

Copy the content tree. Use `rsync` with trailing slashes on both paths. This copies the *contents* of `content/` into `content/`, avoiding the most common mistake (folders landing one level too high or too deep):

```bash
mkdir -p "$NEW/content"
rsync -a --progress "$OLD/content/" "$NEW/content/"
```

Copy the sync audit log (optional, useful for continuity):

```bash
cp -v "$OLD/sync_audit.jsonl" "$NEW/" 2>/dev/null
```

**Do not copy** `chunks.db-journal` or any `.lock` files. Those are temporary files from the old running app.

### What the result should look like

```
memory_tree/
├── chunks.db            (same size as the old one)
├── content/
│   ├── chat/
│   ├── episodic/
│   ├── raw/
│   ├── wiki/
│   └── (any loose notes from the old content folder)
└── sync_audit.jsonl
```

If you see `chat/`, `episodic/`, `raw/` or `wiki/` sitting directly in `memory_tree/` instead of inside `content/`, the copy went one level too high. **Do not start deleting.** Re-run the `rsync` command above exactly as written, verify `content/` is complete, and only then remove the misplaced top-level copies.

---

## Step 7: Verify recovery

Compare old and new side by side:

```bash
ls -la "$OLD" "$NEW"
ls -la "$OLD/content" "$NEW/content"
du -sh "$OLD" "$NEW"
```

Check that:

- `chunks.db` is the same size in both
- `content/` has the same subfolders in both
- total sizes are close

Then relaunch OpenHuman and ask your agent:

> Run a health check and tell me how many memory chunks you can see. Then recall something from my past, for example my current projects.

If recall returns real past context, the restore worked.

---

## Step 8: Clean up (only after a week of normal use)

When you are confident the new install is working:

```bash
rm -rf ~/.openhumanOld
```

Keep the dated backup from Step 2 a while longer, or archive it somewhere safe.

---

## What does not come back automatically

| Item | How to restore |
|------|----------------|
| Scheduled jobs (cron) | Re-create them. Old definitions are in `~/.openhumanOld/users/<id>/workspace/cron/` for reference. |
| Workflows | Check `~/.openhumanOld/users/<id>/workspace/flows/` and rebuild or re-import. |
| Integration connections | Reconnect when prompted. Your agent can start the connection flow for you. |
| Custom persona files (SOUL, ROLE, etc.) | If you customized them, compare against the copies in `~/.openhumanOld/users/<id>/workspace/`. |
| Session history | Past context is in the memory tree; raw session logs stay in the old folder. |
Note :  OpenHuman stores soul parameters in many places, both in the sandbox and in the hidden directories.  It's easier to just remake them from scratch in the UI and let the app write them in the many places they need to go.
---

## Optional: One-script reinstall for Mac users

If you are comfortable in Terminal, this script runs Steps 1 through 7 for you. It pauses at the points where it needs you. Those points are installing the app (if you do not give it the installer file), signing in, and quitting the app before the memory copy.

**What it does, in order:**

1. Checks that you are on macOS, that there is room for a backup, and that `~/.openhumanOld` does not already exist.
2. Verifies the installer checksum, if you supply one.
3. Quits OpenHuman and confirms nothing is still running.
4. Backs up `~/.openhuman` to `~/OpenHuman-Reinstall-Backup-<date>/`.
5. Renames `~/.openhuman` to `~/.openhumanOld`.
6. Installs the app from your downloaded `.dmg`, or waits while you install it by hand. The old app bundle is moved into the backup folder, not deleted.
7. Waits while you sign in with the same account, then quit.
8. Copies `chunks.db`, the `content/` tree and `sync_audit.jsonl` into the new install. Any fresh empty database is renamed aside first.
9. Verifies the result: a byte-for-byte compare of `chunks.db`, a file count on `content/`, and a SQLite quick check.

**It never deletes** `~/.openhumanOld` or the backup. You do that yourself, later, per Step 8.

### How to use it

1. Download the installer (`.dmg`) from the official OpenHuman download page. If the page lists a SHA-256 checksum, copy it.
2. Save the script below as `reinstall-openhuman.sh` in your home folder.
3. Read it before you run it. Then:

```bash
cd ~
chmod +x reinstall-openhuman.sh

# Option 1: let the script install from the .dmg, with checksum check
EXPECTED_SHA256=<checksum-from-download-page> ./reinstall-openhuman.sh ~/Downloads/<installer>.dmg

# Option 2: install the app by hand when the script prompts you
./reinstall-openhuman.sh

# If the script stopped after the rename and you finished installing by hand:
./reinstall-openhuman.sh --restore-only
```

### The script

```bash
# No warranty is offered for this script.
#!/usr/bin/env bash
# reinstall-openhuman.sh
# Reinstall OpenHuman on macOS and restore the memory tree.
#
# Usage:
#   ./reinstall-openhuman.sh                         # install the app by hand when prompted
#   ./reinstall-openhuman.sh ~/Downloads/<installer>.dmg
#   EXPECTED_SHA256=<checksum> ./reinstall-openhuman.sh ~/Downloads/<installer>.dmg
#   ./reinstall-openhuman.sh --restore-only           # skip to the memory restore
#
# Optional: VAULT=<path> also backs up your workspace or vault folder.
#
# Safety: this script never deletes ~/.openhumanOld or the backup folder.
# It stops at the first sign of trouble.

set -euo pipefail

OH="$HOME/.openhuman"
OLD="$HOME/.openhumanOld"
STAMP="$(date +%Y-%m-%d-%H%M)"
BACKUP="$HOME/OpenHuman-Reinstall-Backup-$STAMP"
ARG="${1:-}"
SELF="$(basename "$0")"

say()   { echo ""; echo "==> $*"; }
die()   { echo ""; echo "ERROR: $*" >&2; exit 1; }
pause() { read -r -p "$* Press Return to continue, or Ctrl-C to stop. " _; }

# Running OpenHuman processes, ignoring this script and grep itself.
oh_procs() {
  ps -axo pid=,command= | grep -i openhuman | grep -v -e grep -e "$SELF" || true
}

stop_openhuman() {
  osascript -e 'tell application "OpenHuman" to quit' >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    if [ -z "$(oh_procs)" ]; then return 0; fi
    sleep 1
  done
  echo "OpenHuman still appears to be running:"
  oh_procs
  pause "Quit it fully (OpenHuman menu > Quit), then"
  if [ -n "$(oh_procs)" ]; then
    die "OpenHuman is still running. Quit it and run the script again."
  fi
}

say "Pre-flight checks"
if [ "$(uname)" != "Darwin" ]; then die "This script is for macOS only."; fi

if [ "$ARG" != "--restore-only" ]; then
  DMG="$ARG"
  if [ ! -d "$OH" ]; then die "$OH not found. Nothing to reinstall."; fi
  if [ -e "$OLD" ]; then
    die "$OLD already exists. Move it somewhere safe first. This script will not overwrite it."
  fi

  NEED_KB="$(du -sk "$OH" | awk '{print $1}')"
  FREE_KB="$(df -k "$HOME" | awk 'NR==2 {print $4}')"
  if [ "$FREE_KB" -le $((NEED_KB * 2)) ]; then
    die "Not enough free disk space to back up $OH safely."
  fi
  echo "Disk space OK."

  if [ -n "$DMG" ]; then
    if [ ! -f "$DMG" ]; then die "Installer not found: $DMG"; fi
    if [ -n "${EXPECTED_SHA256:-}" ]; then
      ACTUAL="$(shasum -a 256 "$DMG" | awk '{print $1}')"
      if [ "$ACTUAL" != "$EXPECTED_SHA256" ]; then
        die "Checksum mismatch. Expected $EXPECTED_SHA256, got $ACTUAL. Do not install this file."
      fi
      echo "Installer checksum OK."
    else
      echo "No EXPECTED_SHA256 given. Skipping the checksum check."
    fi
  fi

  say "Step 1: Stop OpenHuman"
  stop_openhuman
  echo "OpenHuman is stopped."

  say "Step 2: Back up to $BACKUP"
  mkdir -p "$BACKUP"
  ditto "$OH" "$BACKUP/dot-openhuman"
  if [ -n "${VAULT:-}" ]; then
    echo "Backing up vault: $VAULT"
    ditto "$VAULT" "$BACKUP/vault"
  fi
  echo "Backup complete."

  say "Step 3: Rename $OH to $OLD"
  mv "$OH" "$OLD"
  echo "Renamed."

  say "Steps 4 and 5: Install OpenHuman"
  if [ -n "$DMG" ]; then
    MNT="$(mktemp -d "${TMPDIR:-/tmp}/openhuman-dmg.XXXXXX")"
    hdiutil attach "$DMG" -nobrowse -readonly -mountpoint "$MNT" >/dev/null
    APP="$(find "$MNT" -maxdepth 1 -name '*.app' | head -n 1)"
    if [ -z "$APP" ]; then
      hdiutil detach "$MNT" -quiet || true
      die "No .app found in $DMG. Install by hand, then run: ./$SELF --restore-only"
    fi
    DEST="/Applications/$(basename "$APP")"
    if [ -e "$DEST" ]; then
      echo "Moving the old app into the backup folder."
      mv "$DEST" "$BACKUP/"
    fi
    ditto "$APP" "$DEST"
    hdiutil detach "$MNT" -quiet || true
    echo "Installed $DEST"
    open "$DEST"
  else
    echo "Install OpenHuman now from the official download page, then launch it."
  fi
  pause "Sign in with the SAME account as before. When setup finishes, QUIT OpenHuman."
fi

say "Step 6: Restore the memory tree"
if [ ! -d "$OLD/users" ]; then die "$OLD/users not found."; fi
if [ ! -d "$OH/users" ]; then die "$OH/users not found. Launch OpenHuman and sign in first."; fi
stop_openhuman

USER_ID=""
for d in "$OLD"/users/*/; do
  id="$(basename "$d")"
  if [ "$id" = "local" ]; then continue; fi
  if [ -f "$d/workspace/memory_tree/chunks.db" ]; then
    if [ -n "$USER_ID" ]; then
      die "More than one old user has a memory tree. Restore by hand (Step 6, Option B)."
    fi
    USER_ID="$id"
  fi
done
if [ -z "$USER_ID" ]; then die "No chunks.db found under $OLD/users."; fi
echo "Found memory tree for user $USER_ID"

OLD_MT="$OLD/users/$USER_ID/workspace/memory_tree"
NEW_WS="$OH/users/$USER_ID/workspace"
if [ ! -d "$NEW_WS" ]; then
  die "The new install has no user $USER_ID. Sign in with the same account as before."
fi
NEW_MT="$NEW_WS/memory_tree"
mkdir -p "$NEW_MT/content"

# Rename any fresh database the new install created. Never delete.
for f in "$NEW_MT"/chunks.db*; do
  if [ -e "$f" ]; then mv "$f" "$f.fresh-install-$STAMP"; fi
done

# Copy only. The old folder is never modified.
for f in "$OLD_MT"/chunks.db*; do
  if [ -e "$f" ]; then cp -p "$f" "$NEW_MT/"; fi
done
if [ -d "$OLD_MT/content" ]; then
  rsync -a "$OLD_MT/content/" "$NEW_MT/content/"
fi
if [ -f "$OLD_MT/sync_audit.jsonl" ]; then
  cp -p "$OLD_MT/sync_audit.jsonl" "$NEW_MT/"
fi
echo "Copy complete."

say "Step 7: Verify"
if ! cmp -s "$OLD_MT/chunks.db" "$NEW_MT/chunks.db"; then
  die "chunks.db does not match the original. Quit OpenHuman and run: ./$SELF --restore-only"
fi
echo "chunks.db matches the original byte for byte ($(du -h "$NEW_MT/chunks.db" | awk '{print $1}'))."

if [ -d "$OLD_MT/content" ]; then
  OLD_N="$(find "$OLD_MT/content" -type f | wc -l | tr -d ' ')"
  NEW_N="$(find "$NEW_MT/content" -type f | wc -l | tr -d ' ')"
  echo "content/ files: old $OLD_N, new $NEW_N"
  if [ "$NEW_N" -lt "$OLD_N" ]; then
    die "The new content/ has fewer files than the original. Check the copy."
  fi
fi

if command -v sqlite3 >/dev/null 2>&1; then
  echo "SQLite quick check: $(sqlite3 -readonly "$NEW_MT/chunks.db" 'PRAGMA quick_check;' 2>&1 | head -n 1)"
fi

ls -la "$NEW_MT"

say "Done"
echo "Old install kept at: $OLD"
if [ -d "$BACKUP" ]; then echo "Backup kept at:      $BACKUP"; fi
echo "Next: launch OpenHuman and ask your agent something only your old install would know."
echo "Delete the old install and the backup yourself, only after a week of normal use (Step 8)."
```

### Precautions for the script

- **Read it before running it.** Never pipe a script from the internet straight into your shell, this one included.
- **Quit other agents** that might read or write `~/.openhuman` while it runs.
- **Expect a disk-space hit.** The backup is a full copy of `~/.openhuman`, often several hundred MB, because the memory database is large. The script refuses to run without twice that amount free.
- **Use the same account** when you sign in to the new install. The restore matches on your user ID and stops if it cannot find it.
- **The app must be fully quit** during the memory copy. The script checks this. If it says OpenHuman is still running, quit it from the menu bar, not just the window.
- **`/Applications` may need admin rights.** If the install step fails with a permissions error, install the app by hand and rerun with `--restore-only`.
- **If anything fails, nothing is lost.** Your old install is in `~/.openhumanOld` and in the backup folder. Fix the problem, then rerun with `--restore-only`.
- **The app name is assumed to be "OpenHuman"** for the automatic quit. If that does not work, the script asks you to quit it by hand.

---

## Troubleshooting

**Recall returns nothing after restore**
Check `ls -la "$NEW/chunks.db"`. If it is missing or much smaller than the old one, quit OpenHuman and repeat the copy.

**Health check says the database has 0 chunks**
OpenHuman may have been running during the copy and written a fresh empty database. Quit fully, copy `chunks.db` again, relaunch.

**"Daemon state file not found" warning**
Normal right after a fresh install.

**My agent says it finished but I cannot see the file or folder**
Ask it to show the `ls -la` output of the exact path. Agents can write to a different workspace than you expect, especially if your workspace uses symlinks or cloud-synced folders. Trust the listing, not the summary.

---

## Lessons from a real reinstall

This guide came from an actual reinstall. What went wrong, so you can avoid it:

1. A recursive copy of `content/` put folders at the wrong level. Using `rsync` with trailing slashes on both paths avoids this.
2. Trying to fix that with `mv` and `rm` briefly removed the restored content. It was recoverable only because the old folder was untouched. Never modify the old folder.
3. The agent reported files as written when they had gone to a different location. Always verify with a directory listing.

*Tested on OpenHuman v0.64.10, macOS Apple Silicon. Paths may differ on other platforms.*
