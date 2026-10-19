@echo off
chcp 65001 >nul
cd /d %~dp0

echo 检查远程仓库……
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo ❌ 还没有设置 GitHub 远程仓库。
    echo 请先在 README「发布到 GitHub」小节完成第 1、2 步，再运行此脚本。
    pause
    exit /b 1
)

git add -A
git commit -m "更新 %date% %time%" >nul
git push origin main
if errorlevel 1 ( echo ❌ 推送失败，请看上方报错 ) else ( echo ✅ 已推送！GitHub Actions 正在自动打包镜像，几分钟内完成。 )
pause
