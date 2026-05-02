# NOTG Launcher

NOTG Launcher is a Python-based Minecraft launcher built with PySide6 and
Minecraft-Launcher-Lib. It focuses on instance-based play: each Minecraft setup
gets its own folder, metadata, mod list, screenshots, runtime state, and launch
configuration.

The launcher can install vanilla Minecraft, install supported mod loaders, import
existing packs or `.minecraft` folders, manage mods and screenshots, track
playtime, show Minecraft logs, publish Discord Rich Presence, and update itself
from GitHub release ZIPs.

## Highlights

- Modern PySide6 desktop UI with a responsive instance grid, sidebar actions,
  dark/light themes, custom backgrounds, and custom instance icons.
- Instance-based Minecraft installs stored outside the application bundle.
- Vanilla version catalog powered by `minecraft-launcher-lib`.
- Mod loader support through Minecraft-Launcher-Lib's loader abstraction:
  Fabric, Forge, Quilt, and NeoForge when available for the chosen Minecraft
  version.
- Import support for Modrinth `.mrpack`, Prism/MultiMC-style exports,
  self-contained CurseForge exports, generic ZIP exports, and existing
  `.minecraft` folders.
- Local username accounts for offline-style launch options.
- Per-instance RAM allocation with safe limits based on system memory.
- Per-instance mod table with enable/disable, remove, metadata, provider, and
  icon detection.
- Screenshot browser with thumbnails, rename, delete, copy-to-clipboard, and
  open-folder actions.
- Live Minecraft log viewer with copy, clear, search, and auto-scroll tools.
- Runtime session monitoring, crash attention, force-stop support, and playtime
  tracking.
- Discord Rich Presence while an instance is running.
- GitHub release checker and self-updater for PyInstaller one-folder builds.

## Screens And Workflows

### Main Window

The main window is centered around an instance grid. Selecting an instance fills
the sidebar with quick actions:

- `Launch` starts the selected instance.
- `Kill` force-stops a running session.
- `Folder` opens the instance folder.
- `Edit` opens the detailed instance editor.
- `Copy` duplicates the whole instance.
- `Delete` removes the instance and its files.

The top bar provides:

- Add Instance
- Instances folder shortcut
- Settings
- Account selector
- Manage Accounts

The bottom playtime bar shows selected-instance playtime, current session time,
and total playtime across all instances.

### Create Instance

The create dialog has two major modes:

- `Create`: install a fresh Minecraft version.
- `Import`: import a modpack archive or existing `.minecraft` folder.

Fresh installs support:

- Minecraft version search and filtering.
- Release, snapshot, beta, alpha, and experimental filters.
- Mod loader selection: None, Fabric, Forge, Quilt, NeoForge.
- Loader version search and refresh.
- Custom instance name.
- Custom icon selection.
- Optional selected-data copy from another instance.
- RAM allocation.

### Import Instance

The import flow accepts:

- Modrinth `.mrpack` archives.
- Prism/MultiMC exports with recognizable metadata.
- CurseForge exports only when they are self-contained. Exports that reference
  external CurseForge-hosted downloads are rejected because this build does not
  include a CurseForge download API.
- Generic ZIP archives containing a recognizable `.minecraft` layout.
- Existing `.minecraft` folders.

During import, the launcher tries to infer Minecraft version, installed launch
version, loader type, loader version, and icon metadata. If the imported files
are missing required launch metadata, the launcher installs the missing
Minecraft or mod-loader files using Minecraft-Launcher-Lib.

### Edit Instance

The edit dialog includes these pages:

- `Minecraft Log`: live log output, copy, clear, search, and jump-to-bottom.
- `Versions`: reinstall the instance with another Minecraft version or loader
  stack while keeping user data.
- `Mods`: list, search, enable, disable, remove, and inspect installed mods.
- `Screenshots`: browse thumbnails, copy an image, delete, rename, and open the
  screenshots folder.
- `Rich Presence`: enable/disable Discord Rich Presence per instance and
  override state/details text.
- `Advanced`: copy selected user data from another instance and adjust RAM.

## How Launching Works

NOTG Launcher uses `minecraft-launcher-lib.command.get_minecraft_command()` to
build the Java command for each instance. Launch options include:

- local username
- generated offline UUID
- offline token placeholder
- launcher name/version
- per-instance game directory
- per-instance JVM memory argument
- Minecraft logging configuration

The launcher then starts Minecraft as a child process and starts a background
session monitor. The monitor:

- marks the session as running
- waits for the Minecraft process to exit
- clears Discord Rich Presence
- records playtime
- updates runtime status
- reopens or activates the launcher if attention is needed, such as after a
  crash

## Accounts

Accounts are local player-name profiles stored in launcher config. The account
system does not implement Microsoft authentication in the current codebase.

Users can:

- add a local player name
- switch active account
- delete saved account names

## Storage Layout

Runtime data is stored through `platformdirs` using the app name
`NOTG Launcher`.

On Windows this typically resolves to:

```text
C:\Users\<you>\AppData\Local\NOTG Launcher\
```

Important folders and files:

```text
NOTG Launcher/
  accounts.json                  # local account names
  background.json                # selected background settings
  backgrounds/                   # user background images
  icons/                         # user-added instance icons
  instances/                     # all instance folders
  runtime/
    staging/                     # in-progress installs/imports
    sessions/                    # running session state
    launcher-ipc.json            # single-instance IPC endpoint
  Cache/
    generated-icons/             # cached mod icons
    release-notes-images/        # cached update release-note images
```

Each instance contains an `instance.json` metadata file and a `.minecraft`
folder:

```text
instances/
  <instance-id>/
    instance.json
    .minecraft/
      versions/
      libraries/
      assets/
      mods/
      screenshots/
      logs/
```

The app bundle itself should not be used for instance storage. This keeps user
data separate from updates and rebuilds.

## Project Structure

```text
app/
  main.py                         # application entry point
  version.py                      # release version
  core/
    launcher.py                   # instance storage, install/import, launch logic
    updater.py                    # GitHub release update checker/installer
    session_monitor.py            # background process monitor
    ipc.py                        # local single-instance/restore messaging
    discord_presence.py           # Discord RPC wrapper
  ui/
    main_window.py                # main instance grid and sidebar shell
    add_instance_dialog.py        # create/import workflow
    edit_instance_dialog.py       # logs, versions, mods, screenshots, presence, advanced
    install_progress_dialog.py    # background install/import progress
    settings_dialog.py            # background, theme, close-on-launch, update settings
    update_settings.py            # update UI and release notes rendering
    accounts_dialog.py            # local account management
    icon_selector_dialog.py       # default/user icon picker
    theme.py                      # dark/light palette and styles
assets/
  default-background/
  default-instance-icons/
  app icon/
NOTG-Launcher.spec                # PyInstaller one-folder build spec
requirements.txt
```

## Development Setup

### Requirements

- Windows is the main target platform.
- Python 3.11 is recommended for the current PyInstaller bundle layout.
- Java must be available for Minecraft versions that require it.

### Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Run from source

```powershell
.\.venv\Scripts\python.exe app\main.py
```

### Useful development checks

```powershell
.\.venv\Scripts\python.exe -m py_compile app\core\updater.py app\main.py app\ui\update_settings.py
.\.venv\Scripts\python.exe -m pytest
```

## Building

The project includes a PyInstaller spec:

```powershell
.\.venv\Scripts\pyinstaller.exe NOTG-Launcher.spec
```

The spec collects:

- `assets/`
- `app/ui/`
- `minecraft_launcher_lib` package data, binaries, and hidden imports
- PySide6 core GUI/widget modules
- `Minecraft-Launcher.ico`

PyInstaller outputs a one-folder build. The spec name is currently
`NOTG-Launcher`, but the intended installed folder name is:

```text
NOTG Launcher
```

The installed executable name should also be:

```text
NOTG Launcher.exe
```

If the generated folder/exe uses `NOTG-Launcher`, rename the bundle to
`NOTG Launcher` before packaging it for users.

## Updates

The update checker reads the latest GitHub release from:

```text
EPICmaster-2149/NOTG-Launcher
```

The updater looks for a `.zip` release asset. The local cached download is named
after the installed folder, for example:

```text
NOTG Launcher-update.zip
```

That cache filename does not need to match the GitHub asset name. What matters
is the layout inside the ZIP.

Supported update ZIP layouts:

```text
NOTG Launcher/
  NOTG Launcher.exe
  _internal/
```

```text
NOTG-Launcher/
  NOTG-Launcher.exe
  _internal/
```

```text
NOTG Launcher.exe
_internal/
```

```text
NOTG-Launcher.exe
_internal/
```

During update, the BAT updater:

1. Downloads the release ZIP to the user cache.
2. Extracts the ZIP.
3. Finds the package root containing an `.exe` and `_internal`.
4. Renames `NOTG-Launcher.exe` to `NOTG Launcher.exe` if needed.
5. Renames the old install folder to `NOTG Launcher.old`.
6. Moves the new package root into the original install path.
7. Starts the updated launcher.
8. Deletes `.old`, extracted files, the ZIP, the BAT, and the log on success.

If update fails, the updater leaves the ZIP, BAT, and `updater.log` in cache for
diagnosis.

## Discord Rich Presence

Discord RPC is configured in:

```text
app/core/discord_presence.py
```

Current constants:

```python
APPLICATION_ID = "1496879744858325066"
LARGE_IMAGE_KEY = "graphicslogo"
SMALL_IMAGE_KEY = "notg_launcher_logo"
```

Rich Presence runs only while a Minecraft instance is active. Each instance can
disable it or override the displayed state/details text. If Discord is closed or
RPC setup fails, the launcher continues normally.

See [DISCORD_PRESENCE_SETUP.md](DISCORD_PRESENCE_SETUP.md) for setup notes.

## Troubleshooting

### Update Downloads But Does Not Replace Files

Check the update cache:

```text
C:\Users\<you>\AppData\Local\NOTG Launcher\Cache\
```

Look for:

- `NOTG Launcher-update.zip`
- `updater.bat`
- `updater.log`
- `extracted/`

If `updater.log` exists, the update failed before cleanup. The most common
causes are:

- the ZIP does not contain an `.exe` and `_internal` in the same package root
- the current launcher process did not fully exit before folder rename
- antivirus or Windows Explorer temporarily locked files in the install folder
- the installed folder/exe name does not match the expected `NOTG Launcher`
  naming

### Imported Pack Cannot Launch

Some exported modpacks only contain metadata and references to remote files.
This launcher can import Modrinth `.mrpack` files through
Minecraft-Launcher-Lib, but CurseForge exports with external file references are
rejected unless they are self-contained.

### No Logs Appear

The log viewer follows the active instance log output. Start the instance first,
then open `Edit Instance -> Minecraft Log`.

### Discord Presence Does Not Show

Make sure:

- Discord is running
- the configured Discord application ID is valid
- Rich Presence is enabled for the instance
- the instance is currently running

## Notes

NOTG Launcher is still a local desktop launcher project. The code favors
straightforward file-based state, local instance folders, and a PyInstaller
one-folder distribution model.

## Also its mostly vibe codded