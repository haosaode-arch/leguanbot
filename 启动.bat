@echo off
chcp 65001 >nul
cd /d %~dp0
echo 检查依赖……
pip install -r requirements.txt --quiet --disable-pip-version-check
echo 启动机器人……
python bot.py
pause
