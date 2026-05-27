@echo off
REM ══════════════════════════════════════════════════════════════════
REM  LeagueMrfox V1.0  打包腳本
REM  執行前請確認：pip install pyinstaller eel pywebview
REM  並將 app.ico 放在專案根目錄與 web/ 資料夾
REM ══════════════════════════════════════════════════════════════════

set PYTHON=python

echo [1/2] 清除舊的建置產物...
if exist dist         rmdir /s /q dist
if exist build        rmdir /s /q build
if exist LeagueMrfox.spec del /q LeagueMrfox.spec

echo [2/2] 執行打包...
%PYTHON% -m eel main.py web ^
    --onefile --noconsole --icon=app.ico --name="LeagueMrfox" ^
    --hidden-import webview ^
    --hidden-import webview.platforms.winforms ^
    --hidden-import clr

echo.
echo 完成！輸出位置：dist\LeagueMrfox.exe
pause
