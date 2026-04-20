@echo off
REM Activate the virtual environment
call .venv\Scripts\activate.bat

REM Start the launcher
python app/main.py

REM Deactivate the virtual environment (optional, as the script ends)
deactivate