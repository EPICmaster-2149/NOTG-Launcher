param(
    [switch]$SkipClean,
    [switch]$KeepSpec
)

$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$appName = "NOTG Launcher"
$entryPoint = "app/main.py"
$iconPath = "Minecraft-Launcher.ico"
$distExe = Join-Path $PSScriptRoot "dist\$appName\$appName.exe"
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
} else {
    $python = "python"
}

Write-Host "Using Python: $python"

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
    "--collect-all", "PySide6",
    "--collect-all", "minecraft_launcher_lib",
    "--collect-all", "pypresence",
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

if (-not $KeepSpec) {
    Remove-Item -LiteralPath "$appName.spec" -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Build complete:"
Write-Host $distExe
