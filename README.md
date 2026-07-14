# NOTG Launcher

NOTG Launcher is a desktop Minecraft launcher built with Python, PySide6, and `minecraft-launcher-lib`.

It is made around separate instances, so each Minecraft setup keeps its own versions, mods, screenshots, logs, settings, and playtime.

## Important Features

- Create and launch separate Minecraft instances.
- Install vanilla Minecraft or use Fabric, Forge, Quilt, and NeoForge loaders when supported.
- Import modpacks from Modrinth `.mrpack`, Prism/MultiMC-style packs, CurseForge packs, ZIP exports, or an existing `.minecraft` folder.
- Browse and install Modrinth modpacks.
- Manage mods, resource packs, screenshots, logs, RAM, and Minecraft optimization per instance.
- Use offline, Microsoft, or Ely.by accounts.
- Show Discord Rich Presence while playing.
- Track playtime and running Minecraft sessions.
- Use custom themes, accent colors, image/video backgrounds, and instance icons.
- Play local or online music with playlists.
- Check and install launcher updates from GitHub releases.

## Run From Source

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app\main.py
```

## Build

```powershell
.\build_pyinstaller.ps1
```

## Notes

- Keep private keys and local settings out of Git.
- Put `CURSEFORGE_API_KEY` in `.env` or `curseforge-api-key.txt` if you want CurseForge content support.
- Launcher data is stored in the user's local app data folder, not inside the source code folder.
