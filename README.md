# NOTG Launcher

## Current architecture

The launcher is now split so installer-managed files and user-managed files do not live in the same place.

- Program files stay in the app folder:
  `app/`, `assets/`, bundled source, bundled default icons, and future installer-owned binaries.
- User data now lives in the per-user app-data location resolved by `platformdirs`:
  `C:\Users\<user>\AppData\Local\NOTG Launcher`

Current user-data layout:

- `instances/`
  Each launcher instance with its own `instance.json` and `.minecraft` directory.
- `icons/`
  User-added instance icons.
- `runtime/`
  Temporary staging/runtime data used while creating or importing instances.
- `Logs/`
  Launcher logs and future updater/installer logs.
- `Cache/`
  Reserved for future cached downloads and metadata if needed.

## Changes made for future installer/updater support

- Moved mutable launcher data out of the workspace/install folder and into Local AppData.
- Kept bundled default icons in `assets/` so updates can replace program assets safely.
- Added legacy bootstrap copy logic for old `instances/` and `app/icons/` data so existing local setups still load.
- Stopped automatically migrating the old `runtime/` tree because it is temporary data and can be large.
- Normalized stored user-icon references to a launcher-owned prefix format:
  `user-icons/<file>.png`
- Kept instance metadata (`instance.json`) self-contained so future installers/updaters do not need to rewrite every instance folder during app updates.

## Rules for a future installer

- Install the launcher code/assets into an installer-owned location such as `Program Files`.
- Do not write instances, user icons, logs, or caches into the install directory.
- Preserve `%LocalAppData%\NOTG Launcher` during uninstall unless the user explicitly asks to remove data.
- If you bundle Python or other runtimes later, keep them in the install directory, not in the user-data directory.

## Rules for a future auto-updater

- Update only program files in the install location.
- Never overwrite the Local AppData data root.
- Treat `instances/` and `icons/` as user-owned content.
- Keep metadata compatibility for `instance.json` and `user-icons/...` paths.
- Use a staged replace strategy for program files so a failed update does not corrupt the installed app.
- Write updater logs into `Logs/` and temporary downloaded update files into `Cache/` or another temp-only folder.

## UI/runtime improvements in this revision

- Fixed the `QLabel` import crash in `main_window.py`.
- Removed the top branding block and rebalanced the main header layout.
- Reworked instance cards to reduce clipping and keep icon/text spacing stable.
- Made toolbar/menu buttons visibly rendered with rectangular rounded styling and safer text/icon layout.
- Enlarged the icon picker and kept it in a 4-column grid.
- Deferred Add Instance catalog loading so the dialog can appear immediately.
- Loaded version and mod-loader catalogs in background threads instead of blocking dialog construction.

## Notes

- Existing data in the old workspace layout is copied forward only when the new AppData target folders are still empty.
- Default icons remain bundled in `assets/default-instance-icons/`.
- User-added icons are now expected to resolve from the AppData `icons/` folder through the `user-icons/...` metadata prefix.
