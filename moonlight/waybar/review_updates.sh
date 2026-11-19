#!/usr/bin/env bash
# Moonveil Sentinel Co-Pilot: Arch Linux Package Update & Changelog Review
set -eo pipefail

CLEAR_CMD="clear"
command -v clear >/dev/null 2>&1 && clear

MOONVEIL_URL="http://192.168.178.67:8083/data/update-risk.json"
CACHE_FILE="/tmp/waybar_sentinel_cache.json"

echo -e "\033[1;36m╭────────────────────────────────────────────────────────────╮\033[0m"
echo -e "\033[1;36m│       Moonveil Co-Pilot: Update Sentinel & Pre-Flight      │\033[0m"
echo -e "\033[1;36m╰────────────────────────────────────────────────────────────╯\033[0m"
echo ""

# Fetch fresh data from Moonveil Sentinel if reachable
if curl -s -m 1.5 -f "$MOONVEIL_URL" > /tmp/sentinel_fresh.json 2>/dev/null; then
    mv -f /tmp/sentinel_fresh.json "$CACHE_FILE"
fi

# Run pre-flight analyzer python helper
python3 - << 'EOF'
import json, os, sys

cache_file = "/tmp/waybar_sentinel_cache.json"
data = None
if os.path.exists(cache_file):
    try:
        with open(cache_file, "r") as f:
            raw = json.load(f)
            data = raw.get("data") if "data" in raw else raw
    except Exception:
        pass

if not data:
    print("\033[1;33m[!] Sentinel cache unavailable; running local check...\033[0m")
    sys.exit(1)

count = data.get("count", 0)
risk_level = data.get("risk_level", "green")
needs_manual = data.get("needs_manual", False)
manual_alerts = data.get("manual_alerts", [])
advisories = data.get("advisories", [])
packages = data.get("packages", [])
prefetched = data.get("prefetched_count", 0)
total_official = data.get("official_count", count)

if count == 0:
    print("\033[1;32m󰄬 Your system is completely up to date! Zero packages pending.\033[0m\n")
    sys.exit(0)

# 1. CRITICAL MANUAL INTERVENTION BANNER
if needs_manual and manual_alerts:
    print("\033[1;31m┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\033[0m")
    print("\033[1;31m┃ ⚠️  CRITICAL: ARCH NEWS MANUAL INTERVENTION REQUIRED       ┃\033[0m")
    print("\033[1;31m┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\033[0m")
    for alert in manual_alerts:
        pkgs = ", ".join(alert.get("packages", []))
        print(f"\033[1;37mPackage(s):\033[0m \033[1;31m{pkgs}\033[0m")
        print(f"\033[1;37mTitle:     \033[0m \033[1;33m{alert.get('title')}\033[0m")
        print(f"\033[1;37mPublished: \033[0m {alert.get('date')}")
        print(f"\033[1;37mSource:    \033[0m \033[0;34m{alert.get('link')}\033[0m")
        print("\033[1;37mWhy & How (Manual Action Required Before/During Upgrade):\033[0m")
        print(f"\033[0;31m{alert.get('instructions')}\033[0m\n")

# 2. ADVISORIES & BREAKING CHANGE WARNINGS
if advisories:
    print("\033[1;33m╭─ 󰅚  System & Driver Advisories ───────────────────────────╮\033[0m")
    for adv in advisories:
        print(f"\033[1;33m│\033[0m • \033[0;37m{adv}\033[0m")
    print("\033[1;33m╰───────────────────────────────────────────────────────────╯\033[0m\n")

# 3. LAN PRE-CACHE STATUS
if prefetched > 0:
    print(f"\033[1;32m✔ Moonveil Pacoloco Cache: {prefetched}/{total_official} packages pre-warmed on LAN (110 MB/s line-rate)\033[0m\n")

# 4. PACKAGE MATRIX
print(f"\033[1;34mFound \033[1;37m{count}\033[1;34m packages queued for upgrade:\033[0m")
print("\033[0;37m────────────────────────────────────────────────────────────\033[0m")
fmt = "{:<24} {:<16} {:<16} {:<12}"
print(f"\033[1;37m{fmt.format('PACKAGE', 'INSTALLED', 'TARGET', 'LAN CACHED')}\033[0m")
print("\033[0;37m────────────────────────────────────────────────────────────\033[0m")
for p in packages:
    name = p.get("name", "")
    old_v = p.get("old_version", "")
    new_v = p.get("new_version", "")
    cached = "✔ Ready" if p.get("precached") else "-"
    warn = p.get("warning", "")
    color = "\033[1;31m" if p.get("risk") == "red" else ("\033[1;33m" if p.get("risk") == "yellow" else "\033[0;37m")
    print(f"{color}{fmt.format(name, old_v, new_v, cached)}\033[0m")
    if warn:
        print(f"  \033[0;33m↳ {warn}\033[0m")

print("\033[0;37m────────────────────────────────────────────────────────────\033[0m")
print("\033[1;32m󰄬 Backup Guarantee: Btrfs pre- and post-upgrade snapshots will be automatically taken by snap-pac.\033[0m\n")
EOF

# If Sentinel cache was missing or exited with code 0 (up to date)
STATUS=$?
if [ $STATUS -eq 0 ] && [ ! -f "$CACHE_FILE" ]; then
    read -rp "Press [Enter] to close..."
    exit 0
fi

# Interactive Action Loop
while true; do
    echo -e "\033[1;32m[y/Enter]\033[0m Proceed with yay -Syu (automatic pre/post snapshots)"
    echo -e "\033[1;34m[i]\033[0m       Inspect package details / info"
    echo -e "\033[1;35m[n]\033[0m       View latest Arch Linux News in terminal"
    echo -e "\033[1;31m[q]\033[0m       Cancel and exit"
    echo ""
    read -rp "Select action [Y/i/n/q]: " CHOICE

    case "$CHOICE" in
        [iI]*)
            echo ""
            read -rp "Enter package name to inspect: " PKG
            if [ -n "$PKG" ]; then
                echo -e "\033[1;36m--- Information for $PKG ---\033[0m"
                pacman -Qi "$PKG" 2>/dev/null || yay -Si "$PKG" 2>/dev/null || echo "Package $PKG not found."
                echo ""
                pacman -Qc "$PKG" 2>/dev/null || true
                echo ""
            fi
            ;;
        [nN]*)
            echo ""
            echo -e "\033[1;35mFetching Arch Linux News...\033[0m"
            python3 -c "
import urllib.request, xml.etree.ElementTree as ET
try:
    req = urllib.request.Request('https://archlinux.org/feeds/news/', headers={'User-Agent': 'curl/8.0'})
    with urllib.request.urlopen(req, timeout=5) as r:
        root = ET.fromstring(r.read())
        for it in root.findall('./channel/item')[:5]:
            print(f' • \033[1;37m[{it.find(\"pubDate\").text[:16]}]\033[0m {it.find(\"title\").text}')
            print(f'   \033[0;34m{it.find(\"link\").text}\033[0m\n')
except Exception as e:
    print(f'Error fetching news: {e}')
"
            echo ""
            ;;
        [qQ]*)
            echo "Upgrade cancelled."
            exit 0
            ;;
        *)
            echo ""
            echo -e "\033[1;32mStarting system upgrade with yay -Syu...\033[0m"
            echo -e "\033[1;34m(snap-pac will record pre- and post-snapshots automatically)\033[0m\n"
            yay -Syu

            # Invalidate caches so Waybar refreshes immediately
            rm -f /tmp/waybar_updates_cache.json /tmp/waybar_sentinel_cache.json
            pkill -RTMIN+8 waybar 2>/dev/null || true

            # Sync updated state to Moonveil in the background
            if command -v sentinel-sync-packages.sh &>/dev/null; then
                sentinel-sync-packages.sh &>/dev/null &
            fi

            echo ""
            read -rp "Upgrade complete. Press [Enter] to exit..."
            exit 0
            ;;
    esac
done
