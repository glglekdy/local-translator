@echo off
rem Local Translator installer: installs Python and the app, then opens it.
rem The heavy AI parts are downloaded later from the app's Download page.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install.ps1" %*
if errorlevel 1 pause
