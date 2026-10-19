@echo off
chcp 65001 >nul
cd /d %~dp0

echo 检查远程仓库……
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo ❌ 还没有设置 GitHub 远程仓库，请先在 github.com 建仓库。
    pause
    exit /b 1
)

echo 备份上一版源代码（Git 中的 HEAD 版本）……
for /f %%i in ('git log -1 --format=%%h') do set OLD=%%i
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set TS=%%i
set BK=%~dp0源代码\历史备份\%OLD%_%TS%
mkdir "%BK%" 2>nul
git archive HEAD 源代码 | tar -x --strip-components=1 -C "%BK%"
if exist "%BK%\bot.py" ( echo ✅ 已备份上一版 v%OLD% → 源代码\历史备份\%OLD%_%TS%
) else ( echo ⚠️ 备份失败，跳过……继续推送 )
echo.

git add -A
git commit -m "备份上一版(%OLD%)并更新 %TS%" >nul 2>&1
git push origin main
if errorlevel 1 ( echo ❌ 推送失败，请看上方报错 ) else ( echo ✅ 已推送！等 Actions 构建完成后，服务器 pull 即可更新。 )
pause
