@echo off
REM ══════════════════════════════════════════════════════════════════
REM  LeagueMrfox V1.0  打包腳本 (PyInstaller + Eel)
REM  執行前請確認：pip install pyinstaller eel
REM ══════════════════════════════════════════════════════════════════

REM ── 使用 Python 3.11（有安裝 eel 的那個）──────────────────────────
set PYTHON="C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe"

REM ── 輸出資料夾 ────────────────────────────────────────────────────
set DIST_DIR=dist
set BUILD_DIR=build_tmp

echo [1/3] 清除舊的建置產物...
if exist "%DIST_DIR%"  rmdir /s /q "%DIST_DIR%"
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "LeagueMrfox.spec" del /q "LeagueMrfox.spec"

echo [2/3] 執行 PyInstaller 打包...
%PYTHON% -m PyInstaller ^
    --name "LeagueMrfox" ^
    --noconsole ^
    --onedir ^
    --add-data "web;web" ^
    --icon=app.ico ^
    --distpath "%DIST_DIR%" ^
    --workpath "%BUILD_DIR%" ^
    --clean ^
    main.py

REM 備注：若需要單一 .exe 請改用 --onefile
REM       但 Eel 在 --onefile 模式下需注意解壓路徑，建議優先使用 --onedir

echo [3/3] 完成！輸出位置：%DIST_DIR%\LeagueMrfox\LeagueMrfox.exe
pause
