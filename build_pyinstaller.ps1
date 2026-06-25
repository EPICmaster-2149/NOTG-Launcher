<#
.SYNOPSIS
    PyInstaller build script for NOTG Launcher and NOTG Updater.
.DESCRIPTION
    Builds two separate executables:
      1. Main launcher (one-directory) - full NOTG Launcher experience
      2. Silent updater (one-file)     - lightweight update worker

    Run without flags for a clean production build.
    Use -SkipClean to preserve previous build artifacts.
    Use -KeepSpec to keep the .spec files after building.
#>

param(
    [switch]$SkipClean,
    [switch]$KeepSpec
)

$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

# ============================================================================
# Configuration
# ============================================================================
$appName        = "NOTG Launcher"
$updaterName    = "NOTG Updater"
$entryPoint     = "app/main.py"
$updaterEntry   = "app/updater_entry.py"
$iconPath       = "Minecraft-Launcher.ico"
$distDir        = Join-Path $PSScriptRoot "dist"
$mainDistDir    = Join-Path $distDir $appName
$mainExePath    = Join-Path $mainDistDir "$appName.exe"
$updaterDistDir = Join-Path $distDir "_updater_build"
$python         = "python"

# Locate a virtual-environment Python first.
foreach ($candidate in @(
    Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
)) {
    if (Test-Path -LiteralPath $candidate) {
        $python = $candidate
        break
    }
}

Write-Host "Using Python: $python"
Write-Host ""

# ============================================================================
# Pre-flight checks
# ============================================================================

# Warn about local secrets that must NOT reach the bundle.
$localSecretFiles = @(
    ".env",
    "curseforge_config.json",
    "curseforge-api-key.txt",
    "spotify_token_cache",
    ".spotify_token_cache"
)
foreach ($secretFile in $localSecretFiles) {
    if (Test-Path -LiteralPath $secretFile) {
        Write-Warning "  Local secret '$secretFile' is present and will be excluded from the bundle."
    }
}

# Verify PyInstaller is available for the selected Python.
try {
    $pyinstallerCheck = & $python -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)" 2>&1
    Write-Host $pyinstallerCheck
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller import check failed." }
} catch {
    throw "PyInstaller is not installed for '$python'.  Run: $python -m pip install pyinstaller"
}

# ============================================================================
# Clean previous builds
# ============================================================================
if (-not $SkipClean) {
    Write-Host "Cleaning previous build artifacts ..."
    foreach ($dir in @("build", "dist")) {
        if (Test-Path -LiteralPath $dir) {
            Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# ============================================================================
#                    MAIN LAUNCHER BUILD (one-directory)
# ============================================================================
# ---- AUDIT (June 2026) ----
#
# Every hidden import / data path / exclusion below was verified by scanning
# the complete source tree.  Details per category:
#
# PySide6 modules USED:
#   QtCore, QtGui, QtWidgets           (core UI)
#   QtMultimedia, QtMultimediaWidgets  (background videos, music player, video thumbnails)
#   QtNetwork                          (release notes image loading in update_settings.py)
#
# PySide6 modules EXCLUDED (confirmed zero references in entire codebase):
#   QtWebEngineCore, WebEngineWidgets, WebEngineQuick, QtDesigner, QtQml, QtQuick,
#   QtQuick3D, QtPdf, QtCharts, QtGraphs, QtSpatialAudio, QtSensors, QtBluetooth,
#   QtTextToSpeech, QtHttpServer, QtSerialPort, QtSql, QtSvg, QtTest, QtXml, QtDBus,
#   QtHelp, QtLocation, QtOpenGL, QtOpenGLWidgets
#
# Dynamic / optional imports (verified in source):
#   dotenv      (config.py, via try/except)
#   mutagen     (launcher.py, optional metadata helper)
#   PIL/Image   (launcher.py, skin resize)
#   pypresence  (discord_presence.py, optional RPC)
#   spotipy     (music.py, optional Spotify)
#   yt_dlp      (music.py, optional streaming)
#
# Third-party stdlib deps (always bundled by PyInstaller detection):
#   requests, psutil, platformdirs
#
# Packaged assets & resources:
#   assets/*     (icons, backgrounds, music, CustomSkinLoader, etc.)
#   app/ui/*.qss (stylesheets loaded by theme.py at runtime)
#
# NOT bundled (no source reference anywhere):
#   PyYAML, pytokens, watchdog, Pygments, black, flake8, pytest, pytest-qt,
#   mypy_extensions, pathspec, pluggy, pycodestyle, pyflakes, mccabe, iniconfig,
#   packaging, click
# ============================================================================

$mainArgs = @(
    "-m", "PyInstaller",
    "--onedir",
    "--noconsole",
    "--noconfirm",
    "--clean",
    "--name", $appName,
    "--runtime-tmpdir", ".",
    "--optimize", "2",

    # ---- Assets & resources ----
    "--add-data", "assets;assets",
    "--add-data", "app/ui;ui",
    "--icon", $iconPath,

    # ---- Core PySide6 modules (every file uses these) ----
    "--hidden-import", "PySide6.QtCore",
    "--hidden-import", "PySide6.QtGui",
    "--hidden-import", "PySide6.QtWidgets",

    # ---- Multimedia (background videos, music player, video thumbnails) ----
    "--hidden-import", "PySide6.QtMultimedia",
    "--hidden-import", "PySide6.QtMultimediaWidgets",

    # ---- Networking (release notes image loading in update_settings.py) ----
    "--hidden-import", "PySide6.QtNetwork",

    # ---- minecraft-launcher-lib (lazy proxy + dynamic submodules) ----
    "--hidden-import", "minecraft_launcher_lib.microsoft_account",
    "--hidden-import", "minecraft_launcher_lib.mod_loader",
    "--collect-data", "minecraft_launcher_lib",
    "--copy-metadata", "minecraft-launcher-lib",

    # ---- Dynamic / optional third-party imports ----
    "--hidden-import", "dotenv",
    "--hidden-import", "pypresence",
    "--hidden-import", "spotipy.oauth2",
    "--hidden-import", "yt_dlp",
    "--hidden-import", "PIL",
    "--hidden-import", "PIL.Image",

    # ---- Excluded Qt modules (zero usage) ----
    "--exclude-module", "PySide6.QtWebEngineCore",
    "--exclude-module", "PySide6.QtWebEngineWidgets",
    "--exclude-module", "PySide6.QtWebEngineQuick",
    "--exclude-module", "PySide6.QtDesigner",
    "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "PySide6.QtQuick3D",
    "--exclude-module", "PySide6.QtPdf",
    "--exclude-module", "PySide6.QtCharts",
    "--exclude-module", "PySide6.QtGraphs",
    "--exclude-module", "PySide6.QtSpatialAudio",
    "--exclude-module", "PySide6.QtSensors",
    "--exclude-module", "PySide6.QtBluetooth",
    "--exclude-module", "PySide6.QtTextToSpeech",
    "--exclude-module", "PySide6.QtHttpServer",
    "--exclude-module", "PySide6.QtSerialPort",
    "--exclude-module", "PySide6.QtSql",
    "--exclude-module", "PySide6.QtSvg",
    "--exclude-module", "PySide6.QtTest",
    "--exclude-module", "PySide6.QtXml",
    "--exclude-module", "PySide6.QtDBus",
    "--exclude-module", "PySide6.QtHelp",
    "--exclude-module", "PySide6.QtLocation",
    "--exclude-module", "PySide6.QtOpenGL",
    "--exclude-module", "PySide6.QtOpenGLWidgets",

    # ---- Excluded dev / test / unused libraries ----
    "--exclude-module", "black",
    "--exclude-module", "flake8",
    "--exclude-module", "pytest",
    "--exclude-module", "pytokens",
    "--exclude-module", "watchdog",
    "--exclude-module", "Pygments",
    "--exclude-module", "yaml",
    "--exclude-module", "pycodestyle",
    "--exclude-module", "pyflakes",
    "--exclude-module", "mccabe",
    "--exclude-module", "pluggy",
    "--exclude-module", "iniconfig",
    "--exclude-module", "packaging",
    "--exclude-module", "mypy_extensions",
    "--exclude-module", "pathspec",
    "--exclude-module", "click",

    $entryPoint
)

Write-Host ">>> Building $appName (one-directory) ..."
& $python @mainArgs
if ($LASTEXITCODE -ne 0) {
    throw "Main launcher build failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $mainExePath)) {
    throw "Build finished, but the executable was not found: $mainExePath"
}

# ============================================================================
#                      UPDATER BUILD (one-file)
# ============================================================================
# ---- AUDIT (June 2026) ----
#
# The updater entry point (updater_entry.py) and the code it calls
# (startup_screen.py -> UpdateApplyWorker) require only:
#   - PySide6.QtCore      (QThread, QTimer, Signal, QEventLoop)
#   - PySide6.QtGui       (QPainter, QFont, QColor, QPaintDevice)
#   - PySide6.QtWidgets   (QApplication, QWidget)
#   - psutil              (UpdateApplyWorker._wait_for_launcher_exit)
#   - stdlib: json, os, shutil, subprocess, sys, time, zipfile, pathlib
#
# The updater does NOT use:
#   - QtMultimedia, QtMultimediaWidgets, QtNetwork
#   - minecraft_launcher_lib
#   - requests (the main launcher downloads the ZIP; the updater only
#     applies it)
#   - dotenv, mutagen, pypresence, spotipy, yt_dlp, PIL
# ============================================================================

$updaterArgs = @(
    "-m", "PyInstaller",
    "--onefile",
    "--noconsole",
    "--noconfirm",
    "--clean",
    "--name", $updaterName,
    "--distpath", $updaterDistDir,
    "--workpath", "build\updater",
    "--icon", $iconPath,
    "--optimize", "2",

    # ---- Minimal PySide6 for updater UI ----
    "--hidden-import", "PySide6.QtCore",
    "--hidden-import", "PySide6.QtGui",
    "--hidden-import", "PySide6.QtWidgets",

    # ---- Exclude everything heavy ----
    "--exclude-module", "PySide6.QtMultimedia",
    "--exclude-module", "PySide6.QtMultimediaWidgets",
    "--exclude-module", "PySide6.QtNetwork",
    "--exclude-module", "PySide6.QtWebEngineCore",
    "--exclude-module", "PySide6.QtWebEngineWidgets",
    "--exclude-module", "PySide6.QtWebEngineQuick",
    "--exclude-module", "PySide6.QtDesigner",
    "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "PySide6.QtQuick3D",
    "--exclude-module", "PySide6.QtPdf",
    "--exclude-module", "PySide6.QtCharts",
    "--exclude-module", "PySide6.QtGraphs",
    "--exclude-module", "PySide6.QtSpatialAudio",
    "--exclude-module", "PySide6.QtSensors",
    "--exclude-module", "PySide6.QtBluetooth",
    "--exclude-module", "PySide6.QtTextToSpeech",
    "--exclude-module", "PySide6.QtHttpServer",
    "--exclude-module", "PySide6.QtSerialPort",
    "--exclude-module", "PySide6.QtSql",
    "--exclude-module", "PySide6.QtSvg",
    "--exclude-module", "PySide6.QtTest",
    "--exclude-module", "PySide6.QtXml",
    "--exclude-module", "PySide6.QtDBus",
    "--exclude-module", "PySide6.QtHelp",
    "--exclude-module", "PySide6.QtLocation",
    "--exclude-module", "PySide6.QtOpenGL",
    "--exclude-module", "PySide6.QtOpenGLWidgets",
    "--exclude-module", "minecraft_launcher_lib",
    "--exclude-module", "dotenv",
    "--exclude-module", "mutagen",
    "--exclude-module", "pypresence",
    "--exclude-module", "spotipy",
    "--exclude-module", "yt_dlp",
    "--exclude-module", "PIL",
    "--exclude-module", "Pygments",
    "--exclude-module", "pytokens",
    "--exclude-module", "watchdog",
    "--exclude-module", "yaml",
    "--exclude-module", "black",
    "--exclude-module", "flake8",
    "--exclude-module", "pytest",
    "--exclude-module", "requests",
    "--exclude-module", "certifi",
    "--exclude-module", "charset_normalizer",
    "--exclude-module", "idna",
    "--exclude-module", "urllib3",

    $updaterEntry
)

Write-Host ">>> Building $updaterName (one-file) ..."
& $python @updaterArgs
if ($LASTEXITCODE -ne 0) {
    throw "Updater build failed with exit code $LASTEXITCODE."
}

$builtUpdaterExe = Join-Path $updaterDistDir "$updaterName.exe"
if (-not (Test-Path -LiteralPath $builtUpdaterExe)) {
    throw "Updater build finished, but $builtUpdaterExe was not found."
}

# Copy the updater into the main distribution directory so it ships alongside
# the launcher.
Copy-Item -LiteralPath $builtUpdaterExe -Destination (Join-Path $mainDistDir "$updaterName.exe") -Force

# Clean up the temporary one-file build artifacts.
Remove-Item -LiteralPath $updaterDistDir -Recurse -Force -ErrorAction SilentlyContinue

# ============================================================================
# Cleanup
# ============================================================================
if (-not $KeepSpec) {
    Remove-Item -LiteralPath "$appName.spec" -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "$updaterName.spec" -Force -ErrorAction SilentlyContinue
    $dot_spec_dir = Join-Path $PSScriptRoot "__pycache__"
    if (Test-Path -LiteralPath $dot_spec_dir) {
        Remove-Item -LiteralPath $dot_spec_dir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "============================================"
Write-Host "  BUILD COMPLETE"
Write-Host "============================================"
Write-Host "  Launcher : $mainExePath"
$updaterFinalPath = Join-Path $mainDistDir "$updaterName.exe"
Write-Host "  Updater  : $updaterFinalPath"
Write-Host ""

# Show size
if (Test-Path -LiteralPath $mainExePath) {
    $launcherSize = (Get-Item -LiteralPath $mainExePath).Length
    $updaterSize = (Get-Item -LiteralPath $updaterFinalPath -ErrorAction SilentlyContinue).Length
    $dirSize = (Get-ChildItem -LiteralPath $mainDistDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
    Write-Host ("  Launcher exe        : {0:N1} MB" -f ($launcherSize / 1MB))
    if ($updaterSize) {
        Write-Host ("  Updater exe         : {0:N1} MB" -f ($updaterSize / 1MB))
    }
    Write-Host ("  Total distribution  : {0:N1} MB" -f ($dirSize / 1MB))
}
Write-Host ""