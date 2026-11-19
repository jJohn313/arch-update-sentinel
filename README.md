# Arch Update Sentinel & Breaking Change Analyzer

Distributed, proactive Arch Linux update analysis and pre-caching co-pilot between **Moonveil** (24/7 edge server) and **Moonlight** (daily driver workstation).

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                      MOONVEIL (24/7)                        │
│                                                             │
│  Hourly Systemd Timer: `arch-sentinel.service`              │
│   1. Reads Moonlight's installed package database           │
│   2. Synchronizes repository databases via fakeroot         │
│   3. Pre-warms Moonveil's Pacoloco cache (:9129)            │
│   4. Multi-tier Risk & Breaking Change Analyzer:            │
│       • Arch News RSS: Scrapes manual intervention alerts   │
│       • Kernel & Driver: Validates Linux / Nvidia pairs     │
│       • Wayland / Hyprland: Checks version bumps & syntax   │
│       • Core ABI: Detects Python/ICU/OpenSSL bumps for AUR  │
│   5. Publishes `update-risk.json` via DarkHTTPD (:8083)     │
│   6. Dispatches instant NTFY push alerts for manual actions │
└──────────────────────────────┬──────────────────────────────┘
                               │ LAN HTTP Sync (:8083)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                         MOONLIGHT                           │
│                                                             │
│  • Waybar Updates Pill:                                     │
│      🟢 󰄬 Up to date (or low-risk pre-cached)               │
│      🟡 󰏗 14 󰅚 (Review needed: Kernel, Nvidia, Hyprland)    │
│      🔴 󰏗 5  MANUAL (Arch News manual intervention)        │
│                                                             │
│  • Kitty Review Window:                                     │
│      Pre-flight checklist displaying exact "Why & How",     │
│      exact commands for manual steps, and 1-key `yay -Syu`. │
│                                                             │
│  • Backup Guarantee:                                        │
│      Automatic Btrfs pre- and post-upgrade snapshots taken  │
│      seamlessly by `snap-pac` during transaction.           │
└─────────────────────────────────────────────────────────────┘
```

---

## Features

1. **Zero-Delay LAN Installs**: Moonveil pre-downloads every pending package into its local Pacoloco mirror cache. When Moonlight runs `yay -Syu`, packages stream over Gigabit LAN at ~110 MB/s.
2. **Arch News Scraper**: Matches pending packages against Arch Linux announcements. If a manual intervention step is declared upstream, the Sentinel flags it in red and extracts the exact terminal commands required.
3. **Display & Driver Incompatibility Protection**: Identifies Linux kernel bumps, Nvidia DKMS modules, Hyprland compositor releases, and Mesa updates before you upgrade.
4. **Instant Phone & Desktop Alerts**: Dispatches NTFY notifications over LAN (`:8080`) when manual user intervention is mandated.
5. **Preserved Backup Guarantees**: Keeps `yay -Syu` execution hooked to `snap-pac` for automatic pre/post Btrfs snapshot rollbacks.

---

## Repository Structure

```text
arch-update-sentinel/
├── moonveil/
│   ├── arch_sentinel.py        # Core analyzer & Pacoloco pre-fetcher
│   ├── arch-sentinel.service   # Systemd oneshot service
│   └── arch-sentinel.timer     # Hourly systemd timer
├── moonlight/
│   ├── sync-packages.sh        # Synchronizes Moonlight package DB to Moonveil
│   ├── 95-sentinel-sync.hook   # Pacman post-transaction ALPM hook
│   └── waybar/
│       ├── updates.py          # Fast Waybar JSON module
│       ├── review_updates.sh   # Interactive Kitty pre-flight review UI
│       └── style_snippet.css   # Waybar pill styles
├── install.sh                  # One-step automated deployment
└── README.md
```
