#!/usr/bin/env bash
# Installer for Arch Update Sentinel & Breaking Change Analyzer
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOONVEIL_HOST="moonveil"

echo "=== Installing Arch Update Sentinel ==="

# 1. Deploy Moonveil Components
echo "[1/5] Deploying Moonveil Sentinel service and analyzer..."
ssh "$MOONVEIL_HOST" "mkdir -p /home/john/scripts/sentinels /home/john/.config/systemd/user /home/john/.local/state/sentinels/moonlight_db /var/www/dashboard/data"
scp -q "${SCRIPT_DIR}/moonveil/arch_sentinel.py" "${MOONVEIL_HOST}:/home/john/scripts/sentinels/arch_sentinel.py"
scp -q "${SCRIPT_DIR}/moonveil/arch-sentinel.service" "${MOONVEIL_HOST}:/home/john/.config/systemd/user/arch-sentinel.service"
scp -q "${SCRIPT_DIR}/moonveil/arch-sentinel.timer" "${MOONVEIL_HOST}:/home/john/.config/systemd/user/arch-sentinel.timer"

ssh "$MOONVEIL_HOST" "chmod +x /home/john/scripts/sentinels/arch_sentinel.py && systemctl --user daemon-reload && systemctl --user enable --now arch-sentinel.timer"

# 2. Deploy Moonlight Sync Script & Hook
echo "[2/5] Deploying Moonlight package sync scripts..."
mkdir -p /home/john/.local/bin
cp -f "${SCRIPT_DIR}/moonlight/sync-packages.sh" /home/john/.local/bin/sentinel-sync-packages.sh
chmod +x /home/john/.local/bin/sentinel-sync-packages.sh

# 3. Update Waybar Scripts
echo "[3/5] Updating Waybar modules & Kitty pre-flight review..."
for dest in "/home/john/.config/waybar/scripts" "/home/john/dotfiles/waybar/scripts"; do
    if [ -d "$dest" ]; then
        cp -f "${SCRIPT_DIR}/moonlight/waybar/updates.py" "${dest}/updates.py"
        cp -f "${SCRIPT_DIR}/moonlight/waybar/review_updates.sh" "${dest}/review_updates.sh"
        chmod +x "${dest}/updates.py" "${dest}/review_updates.sh"
    fi
done

# 4. Update Waybar CSS Styles
echo "[4/5] Merging Waybar CSS styles..."
for css in "/home/john/.config/waybar/style.css" "/home/john/dotfiles/waybar/style.css"; do
    if [ -f "$css" ]; then
        if ! grep -q "review-needed" "$css"; then
            cat "${SCRIPT_DIR}/moonlight/waybar/style_snippet.css" >> "$css"
        fi
    fi
done

# 5. Run Initial Sync & Refresh
echo "[5/5] Running initial package sync and triggering Moonveil Sentinel..."
/home/john/.local/bin/sentinel-sync-packages.sh

# Wait for Moonveil cycle
sleep 3
pkill -RTMIN+8 waybar 2>/dev/null || true

echo "=== Deployment Complete! ==="
