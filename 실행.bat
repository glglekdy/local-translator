@echo off
cd /d "%~dp0"
rem Installed copy: <root>\app with <root>\venv next to it. Dev checkout: the venv under the user profile.
rem (Both are ASCII-only paths: a dependency cannot read files from Korean paths.)
set "PYW=%~dp0..\venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%USERPROFILE%\.venvs\local-translator\Scripts\pythonw.exe"
start "" "%PYW%" app.py
