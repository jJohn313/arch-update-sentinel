#!/usr/bin/env bash
# Sync Moonlight package state to Moonveil Sentinel
set -euo pipefail

MOONVEIL_HOST="moonveil"
REMOTE_STATE="~/.local/state/sentinels"
TEMP_FOREIGN="/tmp/foreign-packages.txt"

# Ensure remote directories exist
ssh -o BatchMode=yes -o ConnectTimeout=3 "$MOONVEIL_HOST" "mkdir -p ~/.local/state/sentinels/moonlight_db" 2>/dev/null || exit 0

# Sync local pacman database (metadata only, world-readable)
rsync -a --delete --timeout=10 /var/lib/pacman/local/ "${MOONVEIL_HOST}:${REMOTE_STATE}/moonlight_db/local/" 2>/dev/null || true

# Export foreign (AUR) packages & IgnorePkg
pacman -Qm > "$TEMP_FOREIGN" 2>/dev/null || true
grep -E '^\s*IgnorePkg\s*=' /etc/pacman.conf > /tmp/moonlight-ignorepkg.txt 2>/dev/null || true

if [ -f "$TEMP_FOREIGN" ]; then
    scp -q -o BatchMode=yes -o ConnectTimeout=3 "$TEMP_FOREIGN" /tmp/moonlight-ignorepkg.txt "${MOONVEIL_HOST}:${REMOTE_STATE}/" 2>/dev/null || true
    rm -f "$TEMP_FOREIGN" /tmp/moonlight-ignorepkg.txt
fi

# Asynchronously trigger Moonveil Sentinel update run
ssh -f -o BatchMode=yes -o ConnectTimeout=3 "$MOONVEIL_HOST" "systemctl --user start arch-sentinel.service 2>/dev/null || true" >/dev/null 2>&1 || true
