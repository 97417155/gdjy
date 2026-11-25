@echo off
chcp 65001 >nul
cd /d %~dp0
echo 正在启动广东院经营分析智能问数系统...
python run.py --port 8848
pause
