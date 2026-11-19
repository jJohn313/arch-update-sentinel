#!/usr/bin/env python3
"""
Moonveil Update Sentinel & Breaking Change Analyzer
24/7 Arch Linux update sentinel that:
1. Syncs repositories against Moonlight's package database.
2. Detects breaking changes, Arch News manual intervention alerts, kernel/driver pairs, and ABI bumps.
3. Pre-warms Moonveil's local Pacoloco cache (:9129) for instant LAN upgrades.
4. Dispatches NTFY push alerts when manual intervention is required.
5. Publishes update-risk.json via DarkHTTPD (:8083) for Moonlight's Waybar and Kitty review.
"""

import datetime
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

STATE_DIR = os.path.expanduser("~/.local/state/sentinels")
DB_PATH = os.path.join(STATE_DIR, "moonlight_db")
PACMAN_CONF = os.path.join(STATE_DIR, "sentinel_pacman.conf")
FOREIGN_PKGS_FILE = os.path.join(STATE_DIR, "foreign-packages.txt")
OUTPUT_JSON_HTTP = "/var/www/dashboard/data/update-risk.json"
OUTPUT_JSON_LOCAL = os.path.join(STATE_DIR, "update-risk.json")
PACOLOCO_BASE = "http://127.0.0.1:9129"
NTFY_URL = "http://localhost:8080/alerts"
NEWS_RSS_URL = "https://archlinux.org/feeds/news/"
AUR_RPC_URL = "https://aur.archlinux.org/rpc/v5/info"

def ensure_config():
    os.makedirs(STATE_DIR, exist_ok=True)
    if not os.path.exists(PACMAN_CONF):
        conf_content = """[options]
Architecture = x86_64
SigLevel = Never

[core]
Server = http://127.0.0.1:9129/repo/archlinux/$repo/os/$arch

[extra]
Server = http://127.0.0.1:9129/repo/archlinux/$repo/os/$arch

[multilib]
Server = http://127.0.0.1:9129/repo/archlinux/$repo/os/$arch
"""
        with open(PACMAN_CONF, "w") as f:
            f.write(conf_content)

def sync_repos():
    """Sync Arch repository databases using user fakeroot and sandbox disable."""
    if not os.path.exists(os.path.join(DB_PATH, "local")):
        print(f"[-] Moonlight local database not found at {DB_PATH}/local. Waiting for sync.")
        return False
    cmd = [
        "fakeroot", "--", "pacman", "-Sy",
        "--disable-sandbox-filesystem",
        "--config", PACMAN_CONF,
        "--dbpath", DB_PATH,
        "--logfile", "/dev/null"
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=45)
        return True
    except Exception as e:
        print(f"[!] Repo sync failed: {e}")
        return False

def get_official_updates():
    """Returns list of dicts: {name, old_version, new_version}"""
    cmd = ["pacman", "-Qu", "--dbpath", DB_PATH]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        updates = []
        for line in lines:
            # format: pkgname old -> new
            parts = line.split()
            if len(parts) >= 4 and parts[2] == "->":
                updates.append({
                    "name": parts[0],
                    "old_version": parts[1],
                    "new_version": parts[3]
                })
            elif len(parts) >= 2:
                updates.append({
                    "name": parts[0],
                    "old_version": "unknown",
                    "new_version": parts[1]
                })
        return updates
    except Exception as e:
        print(f"[!] Failed to check pacman updates: {e}")
        return []

def get_aur_updates():
    """Checks foreign packages against AUR RPC."""
    if not os.path.exists(FOREIGN_PKGS_FILE):
        return []
    installed_aur = {}
    try:
        with open(FOREIGN_PKGS_FILE, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    installed_aur[parts[0]] = parts[1]
                elif len(parts) == 1:
                    installed_aur[parts[0]] = "unknown"
    except Exception:
        return []

    if not installed_aur:
        return []

    # Query AUR in batches of 50
    pkgs = list(installed_aur.keys())
    aur_updates = []
    batch_size = 50
    for i in range(0, len(pkgs), batch_size):
        batch = pkgs[i:i + batch_size]
        query = "&".join(f"arg[]={urllib.parse.quote(p)}" for p in batch)
        url = f"{AUR_RPC_URL}?{query}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Moonveil-Sentinel/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                for result in data.get("results", []):
                    pkgname = result.get("Name")
                    remote_ver = result.get("Version")
                    local_ver = installed_aur.get(pkgname)
                    if remote_ver and local_ver and local_ver != "unknown" and remote_ver != local_ver:
                        aur_updates.append({
                            "name": pkgname,
                            "old_version": local_ver,
                            "new_version": remote_ver,
                            "repo": "aur"
                        })
        except Exception as e:
            print(f"[!] AUR query batch failed: {e}")

    return aur_updates

def resolve_package_info(pkgname):
    """Retrieves repository and package filename from pacman -Si and pacman -Sp."""
    cmd = ["pacman", "-Si", "--config", PACMAN_CONF, "--dbpath", DB_PATH, pkgname]
    repo = "extra"
    filename = ""
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
        for line in proc.stdout.splitlines():
            if line.startswith("Repository"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    repo = parts[1].strip()
    except Exception:
        pass

    # Resolve exact filename using pacman -Sp, filtering for valid pkg filename
    cmd_sp = ["pacman", "-Sp", "--config", PACMAN_CONF, "--dbpath", DB_PATH, pkgname]
    try:
        proc_sp = subprocess.run(cmd_sp, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
        for line in proc_sp.stdout.splitlines():
            line = line.strip()
            if ".pkg.tar." in line:
                filename = os.path.basename(line)
                break
    except Exception:
        pass

    return repo, filename

def prefetch_pacoloco(repo, filename):
    """Hits Pacoloco proxy to pre-warm package cache."""
    if not filename:
        return False
    url = f"{PACOLOCO_BASE}/repo/archlinux/{repo}/os/x86_64/{filename}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Moonveil-Sentinel-Prefetcher/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            # Read first chunk to verify stream
            resp.read(4096)
            return True
    except Exception as e:
        print(f"[!] Prefetch failed for {filename}: {e}")
        return False

def clean_html(raw_html):
    """Strip tags and unescape html entities."""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, ' ', raw_html)
    return " ".join(html.unescape(cleantext).split())

def fetch_arch_news():
    """Fetches recent Arch Linux News items."""
    try:
        req = urllib.request.Request(NEWS_RSS_URL, headers={"User-Agent": "Moonveil-Sentinel/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            root = ET.fromstring(r.read())
            items = []
            for it in root.findall('./channel/item')[:15]:
                title = it.find('title').text or ""
                link = it.find('link').text or ""
                pub = it.find('pubDate').text or ""
                desc = it.find('description').text or ""
                items.append({
                    "title": title.strip(),
                    "link": link.strip(),
                    "pubDate": pub.strip()[:16],
                    "raw_desc": desc,
                    "text_desc": clean_html(desc)
                })
            return items
    except Exception as e:
        print(f"[!] Arch news fetch error: {e}")
        return []

def analyze_risk(official_updates, aur_updates, news_items):
    """
    Evaluates:
    1. Critical Manual Intervention from Arch News
    2. High Risk: Hyprland, Wayland stack, Linux Kernel & Nvidia DKMS pairs
    3. Medium Risk: Core runtime ABI updates (Python, OpenSSL, ICU) affecting AUR
    """
    risk_level = "green"
    needs_manual = False
    manual_alerts = []
    advisories = []
    analyzed_pkgs = []

    all_update_names = {u["name"] for u in official_updates}.union({u["name"] for u in aur_updates})

    # 1. Match against Arch News
    for news in news_items:
        title_lower = news["title"].lower()
        desc_lower = news["text_desc"].lower()
        is_manual = "manual intervention" in title_lower or "manual intervention" in desc_lower or "requires manual" in title_lower
        
        # Check if any updating package is named in the news
        matched_pkgs = []
        for pkg in all_update_names:
            pattern = r'\b' + re.escape(pkg.lower()) + r'\b'
            if re.search(pattern, title_lower) or (is_manual and re.search(pattern, desc_lower)):
                matched_pkgs.append(pkg)

        if matched_pkgs:
            if is_manual:
                risk_level = "red"
                needs_manual = True
                manual_alerts.append({
                    "packages": matched_pkgs,
                    "title": news["title"],
                    "link": news["link"],
                    "date": news["pubDate"],
                    "instructions": news["text_desc"][:500]
                })
            else:
                advisories.append(f"Arch News Alert: '{news['title']}' ({news['link']})")

    # 2. Kernel & Nvidia Driver Analysis
    kernel_updates = [u for u in official_updates if re.match(r'^linux(-lts|-zen|-hardened)?$', u["name"])]
    nvidia_updates = [u for u in official_updates if "nvidia" in u["name"]]

    if kernel_updates:
        if risk_level != "red":
            risk_level = "yellow"
        k_names = ", ".join(f"{k['name']} ({k['old_version']} -> {k['new_version']})" for k in kernel_updates)
        advisories.append(f"Kernel upgrade detected: {k_names}. DKMS modules will rebuild; system reboot recommended.")

    if nvidia_updates:
        if risk_level != "red":
            risk_level = "yellow"
        nv_names = ", ".join(f"{n['name']} ({n['new_version']})" for n in nvidia_updates)
        advisories.append(f"Nvidia graphics stack update: {nv_names}.")

    # 3. Hyprland & Wayland Stack Analysis
    hyprland_updates = [u for u in official_updates if u["name"] == "hyprland"]
    if hyprland_updates:
        if risk_level != "red":
            risk_level = "yellow"
        h = hyprland_updates[0]
        advisories.append(f"Hyprland compositor upgrade ({h['old_version']} -> {h['new_version']}). Check configuration syntax & plugin compatibility.")

    wayland_stack = [u for u in official_updates if u["name"] in ("wlroots", "waybar", "xorg-xwayland", "mesa")]
    if wayland_stack:
        w_names = ", ".join(f"{w['name']} ({w['new_version']})" for w in wayland_stack)
        advisories.append(f"Wayland display stack components updated: {w_names}.")

    # 4. Core ABI Bumps
    core_abis = [u for u in official_updates if u["name"] in ("python", "icu", "openssl", "glibc")]
    for abi in core_abis:
        # Check major/minor change
        old_parts = abi["old_version"].split(".")[:2]
        new_parts = abi["new_version"].split(".")[:2]
        if old_parts != new_parts:
            if risk_level != "red":
                risk_level = "yellow"
            advisories.append(f"Core runtime ABI bump in {abi['name']} ({abi['old_version']} -> {abi['new_version']}). Foreign AUR packages may require rebuild.")

    # Categorize individual packages
    for u in official_updates:
        name = u["name"]
        cat = "app"
        pkg_risk = "green"
        warning = ""

        if re.match(r'^linux(-lts|-zen|-hardened)?$', name) or "headers" in name:
            cat = "kernel"
            pkg_risk = "yellow"
            warning = "Kernel update (DKMS rebuild & reboot advised)"
        elif "nvidia" in name:
            cat = "driver"
            pkg_risk = "yellow"
            warning = "Display driver update"
        elif name in ("hyprland", "wlroots", "waybar", "mesa", "xorg-xwayland"):
            cat = "display"
            pkg_risk = "yellow"
            warning = "Wayland / GUI environment component"
        elif name in ("python", "icu", "openssl", "glibc"):
            cat = "system"
            pkg_risk = "yellow"
            warning = "Core system runtime"

        for alert in manual_alerts:
            if name in alert["packages"]:
                pkg_risk = "red"
                warning = f"MANUAL INTERVENTION REQUIRED: {alert['title']}"

        analyzed_pkgs.append({
            "name": name,
            "old_version": u["old_version"],
            "new_version": u["new_version"],
            "category": cat,
            "risk": pkg_risk,
            "warning": warning
        })

    return risk_level, needs_manual, manual_alerts, advisories, analyzed_pkgs

def dispatch_ntfy_alert(manual_alerts):
    """Sends NTFY alert when manual intervention is required."""
    for alert in manual_alerts:
        pkgs_str = ", ".join(alert["packages"])
        ascii_title = f"Arch Manual Intervention: {pkgs_str}".encode('ascii', 'replace').decode('ascii')
        body = f"⚠️ MANUAL INTERVENTION REQUIRED: {pkgs_str}\n\nTitle: {alert['title']}\n\nInstructions:\n{alert['instructions']}\n\nDetails: {alert['link']}"
        try:
            req = urllib.request.Request(
                NTFY_URL,
                data=body.encode("utf-8"),
                headers={
                    "Title": ascii_title,
                    "Priority": "urgent",
                    "Tags": "warning,rotating_light,package"
                }
            )
            urllib.request.urlopen(req, timeout=5)
            print(f"[+] Dispatched NTFY manual alert for {pkgs_str}")
        except Exception as e:
            print(f"[!] Failed to dispatch NTFY alert: {e}")

def main():
    ensure_config()
    print("[*] Moonveil Sentinel starting update cycle...")

    if not sync_repos():
        print("[-] Skipping cycle due to sync failure.")
        return

    official_updates = get_official_updates()
    aur_updates = get_aur_updates()
    news_items = fetch_arch_news()

    total_count = len(official_updates) + len(aur_updates)
    print(f"[*] Found {len(official_updates)} official updates and {len(aur_updates)} AUR updates.")

    risk_level, needs_manual, manual_alerts, advisories, analyzed_pkgs = analyze_risk(
        official_updates, aur_updates, news_items
    )

    if needs_manual:
        print("[!] RED ALERT: Manual intervention required!")
        dispatch_ntfy_alert(manual_alerts)

    # Pre-cache official packages into Pacoloco
    prefetched_count = 0
    print("[*] Pre-warming Pacoloco cache (:9129)...")
    for pkg in analyzed_pkgs:
        repo, filename = resolve_package_info(pkg["name"])
        pkg["repo"] = repo
        pkg["filename"] = filename
        if filename:
            success = prefetch_pacoloco(repo, filename)
            pkg["precached"] = success
            if success:
                prefetched_count += 1
        else:
            pkg["precached"] = False

    payload = {
        "timestamp": int(time.time()),
        "formatted_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": total_count,
        "official_count": len(official_updates),
        "aur_count": len(aur_updates),
        "prefetched_count": prefetched_count,
        "risk_level": risk_level,
        "needs_manual": needs_manual,
        "manual_alerts": manual_alerts,
        "advisories": advisories,
        "packages": analyzed_pkgs,
        "aur_updates": aur_updates
    }

    # Write output to HTTP dashboard data directory and local state
    for dest in (OUTPUT_JSON_HTTP, OUTPUT_JSON_LOCAL):
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w") as f:
                json.dump(payload, f, indent=2)
            print(f"[+] Wrote Sentinel report to {dest}")
        except Exception as e:
            print(f"[!] Error writing to {dest}: {e}")

    print(f"[+] Sentinel cycle complete. Total: {total_count}, Risk: {risk_level.upper()}, Pre-cached: {prefetched_count}/{len(official_updates)}")

if __name__ == "__main__":
    main()
