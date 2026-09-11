---
title: "Sync downloads to CyVerse"
description: "Mirror a neon-mcp download folder to the CyVerse Data Store with a GoCommands sync script that launchd (macOS) or cron (Linux) runs every hour."
type: Guide
tags:
  - getting-started
  - downloads
  - cyverse
  - gocommands
  - sync
generated:
  by: "claude/opus-5"
  at: "2026-09-11T00:00:00Z"
sources:
  - id: gocommands
    resource: "https://github.com/cyverse/gocommands"
    title: "GoCommands — iRODS command-line client"
    author: "team:cyverse"
  - id: cyverse-install
    resource: "https://learning.cyverse.org/ds/gocommands/installation/"
    title: "GoCommands Installation and Upgrade"
    author: "team:cyverse"
  - id: cyverse-config
    resource: "https://learning.cyverse.org/ds/gocommands/configuration/"
    title: "GoCommands Configuration"
    author: "team:cyverse"
  - id: apple-launchd
    resource: "https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html"
    title: "Creating Launch Daemons and Agents"
    author: "team:apple"
  - id: idss-mesa
    resource: "https://idss-mesa.github.io/docs/"
    title: "IDSS MESA documentation"
    author: "team:idss-mesa"
status: stable
stale_after: "2027-03-11T00:00:00Z"
---

# Sync downloads to CyVerse

[`neon_download_files`](../tools/reference.md#neon_download_files) writes NEON files
into `downloads.directory` (`~/neon-downloads` by default) on the machine running the
server ([Downloading](../tools/availability-and-data.md#downloading-stdio)). To keep
that folder mirrored in the CyVerse Data Store, for the Discovery Environment,
for sharing or as the home of a MESA project, pair it with GoCommands[^gocommands],
CyVerse's command-line client, and a short script that runs `gocmd sync` every hour.

The steps below were tested with GoCommands v0.12.4 on macOS (Apple Silicon). The
Linux variants (the `md5sum` check, the cron line and the Linux log path) use the same
script but have not been run on Linux.

## What the sync does

* **One way, local → Data Store.** Your machine is the source. New and changed files
  upload; unchanged files are skipped by checksum, so a run with nothing new moves no
  data. `-k` verifies each upload's checksum.
* **It never deletes anything in the Data Store.** The script leaves out `--delete`,
  so files that exist only in the Data Store survive, such as the
  `.mesa/ducklake/` history of a MESA project. The flip side: deleting or renaming a
  file locally leaves the old copy in the Data Store until you remove it with
  `gocmd rm`.
* **Tags (AVUs) on a file survive when sync overwrites its content.** New files arrive
  with only the tags CyVerse adds itself (`ipc_UUID`, `ipc-filetype`). `gocmd sync`
  moves bytes, not metadata, and does not go through MESA, so it records no DuckLake
  history.
* **Hidden files upload too.** gocmd has no exclude option, so the script deletes
  macOS `.DS_Store` files before each run.

## 1. Install GoCommands

CyVerse publishes one-line installers per platform[^cyverse-install]. The steps below
do the same for the latest release, check the download against its published MD5 and
put `gocmd` in `~/.local/bin` (there is no Homebrew tap). Set `PLATFORM` to
`darwin-arm64`, `darwin-amd64`, `linux-amd64` or `linux-arm64`:

```bash
GOCMD_VER=$(curl -sL https://raw.githubusercontent.com/cyverse/gocommands/main/VERSION.txt)
PLATFORM=darwin-arm64
URL=https://github.com/cyverse/gocommands/releases/download/${GOCMD_VER}/gocmd-${GOCMD_VER}-${PLATFORM}.tar.gz
curl -sSL -o gocmd.tar.gz "$URL" && curl -sSL -o gocmd.tar.gz.md5 "$URL.md5"

case "$(uname -s)" in
  Darwin) SUM=$(md5 -q gocmd.tar.gz) ;;
  *) SUM=$(md5sum gocmd.tar.gz | cut -d' ' -f1) ;;
esac
[ "$SUM" = "$(cat gocmd.tar.gz.md5)" ] && echo "checksum OK"

mkdir -p ~/.local/bin && tar -xzf gocmd.tar.gz -C ~/.local/bin gocmd
~/.local/bin/gocmd --version
```

## 2. Log in once

Run `gocmd init` yourself, in your own terminal, and answer the prompts with your
CyVerse account[^cyverse-config]:

| Prompt | Value |
|---|---|
| `irods_host` | `data.cyverse.org` |
| `irods_port` | `1247` |
| `irods_zone_name` | `iplant` |
| `irods_user_name` | your CyVerse username |
| `irods_user_password` | your CyVerse password |

`init` writes its configuration under `~/.irods`, and every later `gocmd` call,
scheduled ones included, reuses it. Keep the password out of scripts, shell history
and command lines. Check the login with `gocmd ls`, then create the destination
collection:

```bash
~/.local/bin/gocmd mkdir -p /iplant/home/YOUR_USERNAME/neon-downloads
```

## 3. Save the sync script

Save this as `~/.local/bin/neon-sync`, set `SRC` and `DEST`, and make it executable
with `chmod 755 ~/.local/bin/neon-sync`. Point `SRC` at one folder inside the download
directory (for example a dated session folder) to sync just those files, or at the
download directory itself to mirror everything neon-mcp downloads: products,
prototype datasets and documents. Point `DEST` at the matching Data Store collection.

```bash
#!/bin/bash
# neon-sync: one-way upload of a local neon-mcp download folder to the CyVerse
# Data Store with GoCommands. launchd (macOS) or cron (Linux) runs it every
# hour; run it by hand any time.
#
# Never add --delete: the iRODS copy holds files that exist only there
# (.mesa/ducklake history), and those must survive every run.
set -uo pipefail

SRC="$HOME/neon-downloads"
DEST="/iplant/home/YOUR_USERNAME/neon-downloads"
GOCMD="$HOME/.local/bin/gocmd"
STATE="$HOME/.local/state/neon-sync"
case "$(uname -s)" in
  Darwin) LOG="$HOME/Library/Logs/neon-sync.log" ;;
  *) LOG="$STATE/neon-sync.log" ;;
esac
MAX_LOG_BYTES=1048576

mkdir -p "$STATE" "$(dirname "$LOG")"
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG")" -gt "$MAX_LOG_BYTES" ]; then
  mv -f "$LOG" "$LOG.1"
fi
exec >>"$LOG" 2>&1

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

# One run at a time: a slow upload must not overlap the next hourly start.
LOCK="$STATE/lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if kill -0 "$(cat "$LOCK/pid" 2>/dev/null)" 2>/dev/null; then
    log "skip: previous run (pid $(cat "$LOCK/pid")) still active"
    exit 0
  fi
  log "removing stale lock"
  rm -rf "$LOCK"
  mkdir "$LOCK"
fi
echo $$ >"$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

if [ ! -d "$SRC" ]; then
  log "error: $SRC does not exist"
  exit 1
fi

# gocmd has no exclude option, so remove Finder metadata before it can upload.
find "$SRC" -name .DS_Store -type f -print -delete | sed 's/^/deleted local /'

log "sync start $SRC -> i:$DEST"
# --no_root: sync the folder's contents into DEST, not into DEST/<name of SRC>.
# Unchanged files are skipped by checksum; drop those per-file notices.
"$GOCMD" sync -k --no_root "$SRC" "i:$DEST" 2>&1 |
  grep -v 'with the same hash already exists'
status=${PIPESTATUS[0]}
log "sync end status=$status"
exit "$status"
```

What the pieces do:

* `--no_root` puts the *contents* of `SRC` into `DEST`. Without it, gocmd creates a
  collection named after `SRC` inside `DEST`.
* The lock stops a slow upload from overlapping the next hourly start, and clears
  itself if a run was killed.
* The log keeps one line at the start and end of each run plus anything gocmd
  reports; it rolls over to `neon-sync.log.1` past 1 MB.

Run it once by hand before scheduling it:

```bash
~/.local/bin/neon-sync; echo "exit=$?"
tail -3 ~/Library/Logs/neon-sync.log     # Linux: ~/.local/state/neon-sync/neon-sync.log
```

## 4. Run it every hour

### macOS: launchd

Save this as `~/Library/LaunchAgents/local.neon-sync.plist`[^apple-launchd], replacing
`YOUR_MAC_USER`: launchd does not expand `~` or `$HOME`, so the paths must be
absolute.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>local.neon-sync</string>
	<key>ProgramArguments</key>
	<array>
		<string>/bin/bash</string>
		<string>/Users/YOUR_MAC_USER/.local/bin/neon-sync</string>
	</array>
	<key>StartInterval</key>
	<integer>3600</integer>
	<key>RunAtLoad</key>
	<true/>
	<key>ProcessType</key>
	<string>Background</string>
	<key>LowPriorityIO</key>
	<true/>
	<key>StandardOutPath</key>
	<string>/Users/YOUR_MAC_USER/Library/Logs/neon-sync.launchd.log</string>
	<key>StandardErrorPath</key>
	<string>/Users/YOUR_MAC_USER/Library/Logs/neon-sync.launchd.log</string>
</dict>
</plist>
```

Load it. It runs straight away (`RunAtLoad`), then every hour, and loads again at
each login:

```bash
plutil -lint ~/Library/LaunchAgents/local.neon-sync.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.neon-sync.plist
```

macOS may show a "background item added" notice for `bash`; that is this job. After
editing the plist, `bootout` and `bootstrap` it again. To stop it:

```bash
launchctl bootout gui/$(id -u)/local.neon-sync
rm ~/Library/LaunchAgents/local.neon-sync.plist   # or it loads again at next login
```

### Linux: cron

Add one line with `crontab -e`:

```text
0 * * * * $HOME/.local/bin/neon-sync
```

## Check on it

A failing sync is silent: if your CyVerse password changes or the network is down,
every run fails and nothing tells you. Look for a non-zero status now and then:

```bash
grep 'sync end status=[^0]' ~/Library/Logs/neon-sync.log    # any failed runs
launchctl print gui/$(id -u)/local.neon-sync | grep 'last exit code'   # macOS
```

A failed login is fixed by running `gocmd init` again.

## Syncing into a MESA project

If `DEST` is a MESA project, its `.mesa/ducklake/` history exists only in the Data
Store, which is why the script must never use `--delete`. The sync carries file
content only: to tag new files with DataCite or ontology metadata and record that in
the project's history, use mesa-mcp; see the
[IDSS MESA documentation](https://idss-mesa.github.io/docs/){target=_blank}[^idss-mesa].
Sync to a copy you own, and publish curated or shared copies deliberately rather
than syncing into them.

[^gocommands]: GoCommands — iRODS command-line client. <https://github.com/cyverse/gocommands>
[^cyverse-install]: GoCommands Installation and Upgrade. <https://learning.cyverse.org/ds/gocommands/installation/>
[^cyverse-config]: GoCommands Configuration. <https://learning.cyverse.org/ds/gocommands/configuration/>
[^apple-launchd]: Creating Launch Daemons and Agents. <https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html>
[^idss-mesa]: IDSS MESA documentation. <https://idss-mesa.github.io/docs/>
