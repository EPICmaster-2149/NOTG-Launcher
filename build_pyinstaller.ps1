param(
    [switch]$SkipClean,
    [switch]$KeepSpec
)

$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$appName = "NOTG Launcher"
$updaterName = "NOTG Updater"
$entryPoint = "app/main.py"
$updaterEntryPoint = "app/updater_entry.py"
$iconPath = "Minecraft-Launcher.ico"
$distExe = Join-Path $PSScriptRoot "dist\$appName\$appName.exe"
$distUpdaterExe = Join-Path $PSScriptRoot "dist\$appName\$updaterName.exe"
$updaterBuildDist = Join-Path $PSScriptRoot "dist\_updater"
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
} else {
    $python = "python"
}

Write-Host "Using Python: $python"

$localSecretFiles = @(
    ".env",
    "curseforge_config.json",
    "curseforge-api-key.txt",
    "spotify_token_cache",
    ".spotify_token_cache"
)
foreach ($secretFile in $localSecretFiles) {
    if (Test-Path -LiteralPath $secretFile) {
        Write-Warning "Local secret file '$secretFile' exists and is intentionally excluded from the PyInstaller bundle."
    }
}

& $python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed for '$python'. Run: $python -m pip install -r requirements.txt"
}

if (-not $SkipClean) {
    Write-Host "Cleaning previous PyInstaller output..."
    Remove-Item -LiteralPath "build" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "dist" -Recurse -Force -ErrorAction SilentlyContinue
}

$arguments = @(
    "-m", "PyInstaller",
    "--onedir",
    "--noconsole",
    "--noconfirm",
    "--clean",
    "--name", $appName,
    "--add-data", "assets;assets",
    "--add-data", "app/ui;ui",
    "--icon", $iconPath,
    "--hidden-import", "PySide6.QtCore",
    "--hidden-import", "PySide6.QtGui",
    "--hidden-import", "PySide6.QtWidgets",
    "--hidden-import", "PySide6.QtMultimedia",
    "--hidden-import", "PySide6.QtMultimediaWidgets",
    "--hidden-import", "spotipy.oauth2",
    "--hidden-import", "dotenv",
    "--collect-data", "minecraft_launcher_lib",
    "--copy-metadata", "minecraft-launcher-lib",
    "--exclude-module", "PySide6.QtWebEngineCore",
    "--exclude-module", "PySide6.QtWebEngineWidgets",
    "--exclude-module", "PySide6.QtWebEngineQuick",
    "--exclude-module", "PySide6.QtDesigner",
    "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "PySide6.QtPdf",
    "--exclude-module", "PySide6.QtCharts",
    "--exclude-module", "PySide6.QtGraphs",
    $entryPoint
)

Write-Host "Building $appName..."
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $distExe)) {
    throw "Build finished, but the expected executable was not found: $distExe"
}

$updaterArguments = @(
    "-m", "PyInstaller",
    "--onefile",
    "--noconsole",
    "--noconfirm",
    "--clean",
    "--name", $updaterName,
    "--distpath", $updaterBuildDist,
    "--workpath", "build\updater",
    "--icon", $iconPath,
    "--hidden-import", "PySide6.QtCore",
    "--hidden-import", "PySide6.QtGui",
    "--hidden-import", "PySide6.QtWidgets",
    "--exclude-module", "PySide6.QtWebEngineCore",
    "--exclude-module", "PySide6.QtWebEngineWidgets",
    "--exclude-module", "PySide6.QtWebEngineQuick",
    "--exclude-module", "PySide6.QtDesigner",
    "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "PySide6.QtPdf",
    "--exclude-module", "PySide6.QtCharts",
    "--exclude-module", "PySide6.QtGraphs",
    $updaterEntryPoint
)

Write-Host "Building $updaterName..."
& $python @updaterArguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller updater build failed with exit code $LASTEXITCODE."
}

$builtUpdaterExe = Join-Path $updaterBuildDist "$updaterName.exe"
if (-not (Test-Path -LiteralPath $builtUpdaterExe)) {
    throw "Updater build finished, but the expected executable was not found: $builtUpdaterExe"
}

Copy-Item -LiteralPath $builtUpdaterExe -Destination $distUpdaterExe -Force
Remove-Item -LiteralPath $updaterBuildDist -Recurse -Force -ErrorAction SilentlyContinue

if (-not $KeepSpec) {
    Remove-Item -LiteralPath "$appName.spec" -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "$updaterName.spec" -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Build complete:"
Write-Host $distExe
Write-Host $distUpdaterExe
