#!/usr/bin/env python3
"""
Waybar Sentinel Updates Module
Fetches real-time update analysis from Moonveil (:8083), with graceful offline local fallback.
Outputs JSON for Waybar:
- 󰄬 Up to date (class: synced)
- 󰏗 <count> (class: updates - 100% pre-cached on LAN)
- 󰏗 <count> 󰅚 (class: review-needed - Kernel, Nvidia, or Hyprland updates)
- 󰏗 <count>  MANUAL (class: manual-alert - Arch News manual intervention alert)
"""

import html
import json
import os
import subprocess
import sys
import time
import urllib.request

MOONVEIL_URL = "http://192.168.178.67:8083/data/update-risk.json"
CACHE_FILE = "/tmp/waybar_sentinel_cache.json"
CACHE_TTL = 300  # 5 minutes local cache

def fetch_from_moonveil():
    """Fetches update-risk.json from Moonveil over LAN."""
    try:
        req = urllib.request.Request(MOONVEIL_URL, headers={"User-Agent": "Waybar-Sentinel/1.0"})
        with urllib.request.urlopen(req, timeout=1.5) as r:
            data = json.loads(r.read().decode())
            with open(CACHE_FILE, "w") as f:
                json.dump({"timestamp": time.time(), "data": data}, f)
            return data
    except Exception:
        return None

def get_cached_data():
    """Reads cached Sentinel data if fresh."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cached = json.load(f)
            if time.time() - cached.get("timestamp", 0) < CACHE_TTL:
                return cached.get("data")
        except Exception:
            pass
    return None

def fallback_local_check():
    """Fallback if Moonveil is completely unreachable."""
    try:
        cmd = "{ checkupdates 2>/dev/null || true; yay -Qua 2>/dev/null || true; }"
        out = subprocess.check_output(cmd, shell=True, timeout=8).decode().strip()
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        return {
            "count": len(lines),
            "risk_level": "green",
            "needs_manual": False,
            "prefetched_count": 0,
            "packages": [{"name": l.split()[0], "old_version": "", "new_version": "", "category": "app", "risk": "green", "warning": ""} for l in lines],
            "manual_alerts": [],
            "advisories": ["Moonveil Sentinel unreachable; showing local update estimate."],
            "is_fallback": True
        }
    except Exception:
        return {"count": 0, "risk_level": "green", "needs_manual": False, "packages": [], "manual_alerts": [], "advisories": []}

def main():
    data = fetch_from_moonveil()
    if not data:
        data = get_cached_data()
    if not data:
        data = fallback_local_check()

    count = data.get("count", 0)
    risk_level = data.get("risk_level", "green")
    needs_manual = data.get("needs_manual", False)
    manual_alerts = data.get("manual_alerts", [])
    advisories = data.get("advisories", [])
    packages = data.get("packages", [])
    prefetched = data.get("prefetched_count", 0)
    total_official = data.get("official_count", count)

    if count == 0:
        output = {
            "text": "󰄬 Up to date",
            "tooltip": "<b>System is completely up to date</b>\n󰑐 Right-click to refresh",
            "class": "synced"
        }
    else:
        # Build tooltip
        tooltip_lines = [f"<b>{count} package updates available:</b>"]

        # Manual alerts
        if needs_manual and manual_alerts:
            tooltip_lines.append("\n<span color='#f38ba8'><b>⚠️ MANUAL INTERVENTION REQUIRED:</b></span>")
            for alert in manual_alerts:
                pkgs = ", ".join(alert.get("packages", []))
                title = html.escape(alert.get("title", ""))
                tooltip_lines.append(f" • <b>{pkgs}</b>: {title}")

        # Advisories
        if advisories:
            tooltip_lines.append("\n<span color='#f9e2af'><b>󰅚 Review Advisories:</b></span>")
            for adv in advisories[:4]:
                tooltip_lines.append(f" • {html.escape(adv)}")

        # Pacoloco cache status
        if prefetched > 0:
            tooltip_lines.append(f"\n<span color='#a6e3a1'>✔ {prefetched}/{total_official} packages pre-cached on Moonveil LAN</span>")

        # Package preview
        max_preview = 12
        tooltip_lines.append("\n<b>Pending Packages:</b>")
        for p in packages[:max_preview]:
            name = p.get("name", "")
            old_v = p.get("old_version", "")
            new_v = p.get("new_version", "")
            warning = p.get("warning", "")
            warn_badge = " 󰅚" if warning else ""
            tooltip_lines.append(f" • {name} <i>({old_v} → {new_v})</i>{warn_badge}")

        if count > max_preview:
            tooltip_lines.append(f"<i>...and {count - max_preview} more</i>")

        tooltip_lines.append("\n󰄛 Click to review in Kitty\n󰑐 Right-click to refresh")
        tooltip = "\n".join(tooltip_lines)

        # Waybar pill text & class
        if needs_manual:
            text = f"󰏗 {count}  MANUAL"
            css_class = "manual-alert"
        elif risk_level == "yellow":
            text = f"󰏗 {count} 󰅚"
            css_class = "review-needed"
        else:
            text = f"󰏗 {count}"
            css_class = "updates"

        output = {
            "text": text,
            "tooltip": tooltip,
            "class": css_class
        }

    sys.stdout.write(json.dumps(output) + "\n")
    sys.stdout.flush()

if __name__ == "__main__":
    main()
