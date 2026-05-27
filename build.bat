@echo off
REM ══════════════════════════════════════════════════════════════════
REM  LeagueMrfox V1.0  打包腳本
REM  執行前請確認：
REM    pip install pyinstaller eel
REM  並將 app.ico 放在專案根目錄
REM ══════════════════════════════════════════════════════════════════

REM ── 使用 Python 3.11（有安裝 eel 的那個）──────────────────────────
set PYTHON="C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe"

echo [1/2] 清除舊的建置產物...
if exist dist         rmdir /s /q dist
if exist build        rmdir /s /q build
if exist LeagueMrfox.spec del /q LeagueMrfox.spec

echo [2/2] 執行打包（eel 模式，單一 .exe，隱藏黑視窗）...
%PYTHON% -m eel main.py web --onefile --noconsole --icon=app.ico --name="LeagueMrfox"

echo.
echo 完成！輸出位置：dist\LeagueMrfox.exe
pause
