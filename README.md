# NOTG Launcher

NOTG Launcher is a Python and PySide6 Minecraft launcher inspired by Prism Launcher and built around isolated per-instance `.minecraft` directories.

This repository now includes:

- a modern main window with top bar, instance sidebar, instance grid, and status bar
- Prism-style add-instance, edit-instance, settings, and copy flows
- `minecraft-launcher-lib` integration for Minecraft versions, loader versions, Java detection, launch planning, and `.mrpack` installs
- a lightweight session monitor process that tracks launched game instances and restores launcher state
- per-instance metadata, playtime tracking, background-image support, and offline profile switching

## Project Layout

```text
NOTG-Launcher/
├── docs/
│   └── combined-launcher-design.md
├── launcher_root/              # created at runtime, gitignored
├── src/notg_launcher/
│   ├── app/
│   │   ├── core/
│   │   ├── models/
│   │   ├── services/
│   │   ├── ui/
│   │   └── utils/
│   ├── assets/
│   ├── core/                   # compatibility shims
│   ├── storage/                # compatibility shims
│   └── ui/                     # compatibility shims
├── notg_launcher/              # bridge package for repo-root `python -m`
├── tests/
├── pyproject.toml
└── requirements.txt
```

## Launcher Root Layout

```text
launcher_root/
├── Backgrounds/
├── Cache/
├── Configs/
│   ├── settings.json
│   └── ui_state.json
├── Downloads/
├── Icons/
│   ├── custom/
│   └── default/
├── Instances/
│   └── <instance-id>/
│       ├── instance.json
│       ├── servers.json
│       └── .minecraft/
├── Java/
├── Logs/
├── Sessions/
├── Skins/
└── Temp/
```

## Setup

```bash
./venv/bin/pip install -r requirements.txt
```

Optional editable install:

```bash
./venv/bin/pip install -e .
```

## Run

```bash
./venv/bin/python -m notg_launcher
```

## Test

```bash
./venv/bin/python -m pytest
```

## Design Reference

The combined UI and architecture blueprint is documented in:

- `docs/combined-launcher-design.md`
