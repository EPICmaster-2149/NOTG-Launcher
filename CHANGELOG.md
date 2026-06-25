# Changelog

## NOTG Launcher v2.1.0 — Build System Overhaul

### What's New
- **Optimized PyInstaller build configuration** — Smaller, faster executables with `--optimize 2` bytecode optimization and `--runtime-tmpdir` for cleaner temp directories
- **Proper dependency separation** — `requirements.txt` now clearly separates runtime dependencies from development/testing tools
- **Expanded Qt module exclusions** — 17 additional unused Qt modules now excluded, reducing bundle size significantly
- **Updater becomes truly lightweight** — The updater executable now excludes all network libraries (requests, urllib3, certifi, charset_normalizer, idna) since it doesn't make HTTP requests itself

### What's Fixed
- **Missing PIL/Pillow hidden import** — The launcher uses `PIL.Image` for skin texture resizing, but it was never declared as a hidden import for PyInstaller. This could cause crashes on systems where PyInstaller didn't auto-detect it.
- **Missing yt_dlp hidden import** — The background music player imports yt_dlp for YouTube/streaming audio, which was never declared as a hidden import.
- **10 orphan packages removed from requirements** — PyYAML, pytokens, watchdog, Pygments, click, and others were listed as dependencies but never imported anywhere in the application code.
- **Cleaner build documentation** — Every hidden import, exclusion, and dependency now has a verified code reference explaining why it's included or excluded.

### Optimizations Applied
- All unused Qt Quick/QML/WebEngine modules excluded
- All development-only libraries excluded from the bundle
- PyInstaller `--optimize 2` bytecode optimization enabled
- The updater is now built as a standalone one-file executable with only QtCore/QtGui/QtWidgets + psutil