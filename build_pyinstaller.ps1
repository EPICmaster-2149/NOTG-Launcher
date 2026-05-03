$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

pyinstaller `
    --onedir `
    --noconsole `
    --noconfirm `
    --name NOTG-Launcher `
    --add-data "assets;assets" `
    --add-data "app/ui;ui" `
    --icon Minecraft-Launcher.ico `
    --hidden-import PySide6.QtCore `
    --hidden-import PySide6.QtGui `
    --hidden-import PySide6.QtWidgets `
    --hidden-import PySide6.QtMultimedia `
    --hidden-import PySide6.QtMultimediaWidgets `
    --collect-all PySide6 `
    --collect-all minecraft_launcher_lib `
    app/main.py
