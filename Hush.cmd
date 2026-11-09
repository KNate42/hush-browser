@echo off
start "" "%~dp0app\firefox.exe" -no-remote -profile "%~dp0profile" %*
